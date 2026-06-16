"""API routes - REST endpoints"""

import copy

from fastapi import APIRouter, Request, HTTPException
from pydantic import BaseModel

from services.config import ConfigService
from services.audio import AudioService
from services.apply import apply_config, apply_inputs, amixer_set, linear_to_amixer_pct
from services.audio_cards import detect_cards, annotate_configured_amps, find_card_for_amp

router = APIRouter(tags=["api"])


def get_config_service(request: Request) -> ConfigService:
    return ConfigService(request.app.state.config_file)


def get_audio_service(request: Request) -> AudioService:
    return AudioService(request.app.state.project_dir)


# === Config endpoints ===

@router.get("/config")
async def get_config(request: Request):
    """Get full configuration"""
    config_svc = get_config_service(request)
    return config_svc.config


@router.get("/config/rooms")
async def get_rooms(request: Request):
    """Get all rooms"""
    config_svc = get_config_service(request)
    return config_svc.get_rooms()


class RoomUpdate(BaseModel):
    name: str
    left: str | None = None
    right: str | None = None
    sub: str | None = None
    mono: str | None = None      # single-speaker room: L+R get downmixed onto this channel
    zones: list[str] = []


@router.post("/config/rooms/{room_id}")
async def create_room(request: Request, room_id: str, data: RoomUpdate):
    """Create a new room"""
    config_svc = get_config_service(request)
    config_svc.create_room(room_id, data.model_dump())
    return {"status": "ok", "room_id": room_id}


@router.put("/config/rooms/{room_id}")
async def update_room(request: Request, room_id: str, data: RoomUpdate):
    """Update a room"""
    config_svc = get_config_service(request)
    if not config_svc.get_room(room_id):
        raise HTTPException(status_code=404, detail="Room not found")
    config_svc.update_room(room_id, data.model_dump())
    return {"status": "ok", "room_id": room_id}


@router.delete("/config/rooms/{room_id}")
async def delete_room(request: Request, room_id: str):
    """Delete a room"""
    config_svc = get_config_service(request)
    if not config_svc.delete_room(room_id):
        raise HTTPException(status_code=404, detail="Room not found")
    return {"status": "ok"}


# === Speaker endpoints ===

@router.get("/config/speakers")
async def get_speakers(request: Request):
    """Get all speakers"""
    config_svc = get_config_service(request)
    return config_svc.get_speakers()


class SpeakerUpdate(BaseModel):
    amplifier: str
    channel: int
    volume: int = 100
    latency: int = 0


@router.put("/config/speakers/{speaker_id}")
async def update_speaker(request: Request, speaker_id: str, data: SpeakerUpdate):
    """Update a speaker"""
    config_svc = get_config_service(request)
    config_svc.update_speaker(speaker_id, data.model_dump())
    return {"status": "ok", "speaker_id": speaker_id}


# === Amp discovery / management ===

@router.get("/system/audio-cards")
async def audio_cards(request: Request):
    """List all ALSA cards on the system.

    Each entry indicates whether it's already configured as an amp and whether
    it looks like a USB audio device that could be added.
    """
    config_svc = get_config_service(request)
    cards = detect_cards()
    annotated = annotate_configured_amps(cards, config_svc.get_amplifiers())
    return {"cards": annotated}


class AmpAdd(BaseModel):
    card: str | None = None     # ALSA short id (e.g. 'amp4'); defaults to amp_id
    channels: int = 8
    gpio: int | None = None     # SHDN GPIO line; None = amp is always-on (no GPIO control)


@router.post("/config/amps/{amp_id}")
async def add_amp(request: Request, amp_id: str, data: AmpAdd):
    """Register a new amplifier in the config.

    Does NOT write a udev rule — that's a system-level concern. If you want
    persistent ALSA naming for a freshly plugged-in amp, also add the matching
    rule to devconfig/99-wondom-gab8.rules and reload udev.
    """
    config_svc = get_config_service(request)
    if amp_id in config_svc.get_amplifiers():
        raise HTTPException(status_code=409, detail=f"Amp {amp_id!r} already exists")
    if not amp_id.replace("_", "").isalnum():
        raise HTTPException(status_code=400, detail="amp_id must be alphanumeric/underscore")
    entry: dict = {
        "card": data.card or amp_id,
        "channels": int(data.channels),
    }
    if data.gpio is not None:
        entry["gpio"] = int(data.gpio)
    config_svc.add_amplifier(amp_id, entry)
    return {"status": "ok", "amp_id": amp_id}


class AmpUpdate(BaseModel):
    # Only fields the user might change are exposed here; channels is structural
    # (changing it requires speaker re-config / asound regen) so kept out for now.
    gpio: int | None = None     # null/omitted = clear (amp becomes always-on)


@router.patch("/config/amps/{amp_id}")
async def update_amp(request: Request, amp_id: str, data: AmpUpdate):
    """Update an existing amplifier's settings (currently: GPIO pin).

    Pass `gpio: null` (or omit) to clear the GPIO mapping — the amp is then
    treated as always-on (status: on; on/off no-op; powermanager skips it).
    """
    config_svc = get_config_service(request)
    partial = data.model_dump(exclude_unset=True)
    # Map omitted-but-meaningful semantics: if the client posted gpio:null
    # explicitly, model_dump includes it; if they POSTed an empty body we
    # don't touch anything.
    if not config_svc.update_amplifier(amp_id, partial):
        raise HTTPException(status_code=404, detail="Amp not found")
    return {"status": "ok", "amp_id": amp_id, "applied": partial}


@router.delete("/config/amps/{amp_id}")
async def delete_amp(request: Request, amp_id: str):
    """Remove an amplifier. Refuses if any speaker still references it."""
    config_svc = get_config_service(request)
    used_by = [s for s, sp in config_svc.get_speakers().items() if sp.get("amplifier") == amp_id]
    if used_by:
        raise HTTPException(
            status_code=409,
            detail=f"Amp {amp_id!r} still in use by speakers: {', '.join(used_by)}",
        )
    if not config_svc.delete_amplifier(amp_id):
        raise HTTPException(status_code=404, detail="Amp not found")
    return {"status": "ok"}


# === Inputs (USB capture → lox lineIn) ===

class InputAdd(BaseModel):
    card: str | None = None          # ALSA card id; defaults to input_id
    channels: int = 2                # native capture channel count
    sample_rate: int = 48000         # native capture rate (plug resamples to 44100)
    lox_input_id: str | None = None  # id sent in the TCP handshake; defaults to input_id
    name: str | None = None          # UI display name
    autostart: bool = True           # enable lineinpipe@<id> on apply


class InputUpdate(BaseModel):
    # card/channels are structural (capture format) — kept out; change those by
    # re-adding. Here we expose the fields a user tweaks day-to-day.
    name: str | None = None
    sample_rate: int | None = None
    lox_input_id: str | None = None
    autostart: bool | None = None


def _input_with_status(input_id: str, inp: dict, cards: list) -> dict:
    """Annotate a stored input with live card presence + capture channel count."""
    card_id = inp.get("card", input_id)
    card = find_card_for_amp(cards, card_id)
    return {
        "id": input_id,
        "card": card_id,
        "channels": inp.get("channels", 2),
        "sample_rate": inp.get("sample_rate", 48000),
        "lox_input_id": inp.get("lox_input_id", input_id),
        "name": inp.get("name", input_id),
        "autostart": inp.get("autostart", True),
        "online": card is not None,
        "capture_channels": (card or {}).get("capture_channels", 0),
    }


@router.get("/config/inputs")
async def list_inputs(request: Request):
    """List configured inputs, each annotated with whether its capture card is
    currently present and how many capture channels it advertises."""
    config_svc = get_config_service(request)
    cards = detect_cards()
    return {
        "inputs": {
            iid: _input_with_status(iid, inp, cards)
            for iid, inp in config_svc.get_inputs().items()
        }
    }


@router.post("/config/inputs/{input_id}")
async def add_input(request: Request, input_id: str, data: InputAdd):
    """Register a new audio input and apply (regenerate ALSA + start bridge).

    Like amps, this does NOT write a udev rule — for persistent ALSA naming of
    the capture card, add a matching rule to devconfig/ and reload udev.
    """
    config_svc = get_config_service(request)
    project_dir = request.app.state.project_dir

    if input_id in config_svc.get_inputs():
        raise HTTPException(status_code=409, detail=f"Input {input_id!r} already exists")
    if not input_id.replace("_", "").isalnum():
        raise HTTPException(status_code=400, detail="input_id must be alphanumeric/underscore")

    old_config = copy.deepcopy(config_svc.config)
    entry = {
        "card": data.card or input_id,
        "channels": int(data.channels),
        "sample_rate": int(data.sample_rate),
        "lox_input_id": data.lox_input_id or input_id,
        "name": data.name or input_id,
        "autostart": bool(data.autostart),
    }
    config_svc.add_input(input_id, entry)
    new_config = copy.deepcopy(config_svc.config)

    try:
        result = await apply_inputs(project_dir, old_config, new_config)
    except RuntimeError as e:
        config_svc.save(old_config)  # roll back on apply failure
        raise HTTPException(status_code=500, detail=str(e))
    return {"status": "ok", "input_id": input_id, **result}


@router.patch("/config/inputs/{input_id}")
async def update_input(request: Request, input_id: str, data: InputUpdate):
    """Update an input's editable fields and re-apply if anything changed."""
    config_svc = get_config_service(request)
    project_dir = request.app.state.project_dir

    if input_id not in config_svc.get_inputs():
        raise HTTPException(status_code=404, detail="Input not found")

    partial = data.model_dump(exclude_unset=True)
    if not partial:
        return {"status": "ok", "input_id": input_id, "applied": {}}

    old_config = copy.deepcopy(config_svc.config)
    config_svc.update_input(input_id, partial)
    new_config = copy.deepcopy(config_svc.config)

    try:
        result = await apply_inputs(project_dir, old_config, new_config)
    except RuntimeError as e:
        config_svc.save(old_config)
        raise HTTPException(status_code=500, detail=str(e))
    return {"status": "ok", "input_id": input_id, "applied": partial, **result}


@router.delete("/config/inputs/{input_id}")
async def delete_input(request: Request, input_id: str):
    """Remove an input: stop+disable its bridge and regenerate ALSA."""
    config_svc = get_config_service(request)
    project_dir = request.app.state.project_dir

    if input_id not in config_svc.get_inputs():
        raise HTTPException(status_code=404, detail="Input not found")

    old_config = copy.deepcopy(config_svc.config)
    config_svc.delete_input(input_id)
    new_config = copy.deepcopy(config_svc.config)

    try:
        result = await apply_inputs(project_dir, old_config, new_config)
    except RuntimeError as e:
        config_svc.save(old_config)
        raise HTTPException(status_code=500, detail=str(e))
    return {"status": "ok", **result}


# === Live volume (runtime softvol via amixer) ===

class LiveVolumeRequest(BaseModel):
    amp: str            # amplifier id (e.g. 'amp1')
    channel: int        # 1-based channel number
    volume: int         # 0..100 linear


@router.post("/system/channel-volume")
async def set_channel_volume(request: Request, data: LiveVolumeRequest):
    """Set a per-speaker softvol live AND persist the value to JSON.

    Volume edits don't need an Apply: ALSA's per-speaker softvol picks up the
    new value immediately via amixer, and we save the integer to
    speaker_config.json so reloads / regens see the updated value. No ALSA
    regen, no sendspin restart — just instant + saved.
    """
    config_svc = get_config_service(request)

    # Find the speaker for (amp, channel)
    target = None
    spk_id_match = None
    for rid, room in config_svc.get_rooms().items():
        for side in ("left", "right", "sub", "mono"):
            spk_id = room.get(side)
            if not spk_id:
                continue
            spk = config_svc.get_speakers().get(spk_id)
            if not spk:
                continue
            if spk.get("amplifier") == data.amp and int(spk.get("channel", -1)) == int(data.channel):
                target = {"room": rid, "side": side, "card": data.amp}
                spk_id_match = spk_id
                break
        if target:
            break

    if not target:
        raise HTTPException(status_code=404, detail="No speaker assigned to that channel")

    # Honor the per-room max_volume ceiling (falls back to global) so a channel
    # fader can't exceed its room's configured maximum.
    room = config_svc.get_room(target["room"]) or {}
    max_vol = room.get("max_volume", config_svc.get_max_volume())
    pct = linear_to_amixer_pct(data.volume, max_vol)
    ctrl = f"vol_{target['room']}_{target['side']}"
    ok = await amixer_set(target["card"], ctrl, pct)
    if not ok:
        raise HTTPException(status_code=500, detail=f"amixer set failed for {ctrl}")

    # Persist to JSON so the value survives reloads / future regens
    if spk_id_match:
        config_svc.set_speaker_volume(spk_id_match, data.volume)

    return {"status": "ok", "control": ctrl, "amixer_pct": pct, "saved": bool(spk_id_match)}


# === Per-room max volume (ceiling) ===

class RoomMaxVolume(BaseModel):
    max_volume: float | None = None   # 0..1, or null to inherit global


@router.post("/config/rooms/{room_id}/max-volume")
async def set_room_max_volume(request: Request, room_id: str, data: RoomMaxVolume):
    """Set (or clear) a room's max_volume ceiling and re-seed its softvols live.

    Pure runtime: max_volume is applied at the softvol-seeding layer, so this
    re-seeds via amixer — no ALSA regen and no sendspin restart.
    """
    config_svc = get_config_service(request)
    if room_id not in config_svc.get_rooms():
        raise HTTPException(status_code=404, detail="Room not found")

    config_svc.set_room_max_volume(room_id, data.max_volume)
    from services.apply import seed_room_softvols
    seeded = await seed_room_softvols(config_svc.config, room_id)
    effective = config_svc.get_room(room_id).get("max_volume", config_svc.get_max_volume())
    return {
        "status": "ok",
        "room_id": room_id,
        "max_volume": data.max_volume,
        "effective": effective,
        "seeded": seeded,
    }


# === Test endpoints ===

class ChannelTestRequest(BaseModel):
    amplifier: str
    channel: int
    type: str = "chime"            # "tts" or "chime"
    volume: int | None = None      # 0..100 to live-preview slider; None = full


@router.post("/test/channel")
async def test_channel(request: Request, data: ChannelTestRequest):
    """Play test sound on a channel; honors slider volume if provided."""
    audio_svc = get_audio_service(request)

    if data.type == "tts":
        success = await audio_svc.play_tts(data.amplifier, data.channel, data.volume)
    else:
        success = await audio_svc.play_chime(data.amplifier, data.channel, data.volume)

    if not success:
        raise HTTPException(status_code=500, detail="Playback failed")

    return {"status": "ok"}


class RoomTestRequest(BaseModel):
    room: str
    position: str = "stereo"           # "left", "right", "stereo", or "mono"
    type: str = "chime"                # "tts" or "chime"
    volume_left: int | None = None     # live slider preview
    volume_right: int | None = None


@router.post("/test/room")
async def test_room(request: Request, data: RoomTestRequest):
    """Play test sound on a room — fans out to per-channel devices so each
    side gets its own live slider gain. Mono rooms play once on the single
    channel."""
    audio_svc = get_audio_service(request)
    config_svc = get_config_service(request)

    room = config_svc.get_room(data.room)
    if not room:
        raise HTTPException(status_code=404, detail="Room not found")

    def lookup(side: str):
        spk_id = room.get(side)
        if not spk_id:
            return None, None
        spk = config_svc.get_speaker(spk_id)
        if not spk:
            return None, None
        return spk.get("amplifier"), spk.get("channel")

    # Mono rooms are identified by the `mono` field. The "left side" slot in
    # play_room_stereo carries the single mono channel; the right side is left
    # unwired so no second device is opened.
    if room.get("mono"):
        mono_amp, mono_ch = lookup("mono")
        success = await audio_svc.play_room_stereo(
            mono_amp, mono_ch, data.volume_left,
            None, None, None,
            sound=data.type,
            text=room.get("name", data.room),
        )
        if not success:
            raise HTTPException(status_code=500, detail="Playback failed")
        return {"status": "ok"}

    left_amp, left_ch = (None, None)
    right_amp, right_ch = (None, None)
    if data.position in ("stereo", "left"):
        left_amp, left_ch = lookup("left")
    if data.position in ("stereo", "right"):
        right_amp, right_ch = lookup("right")

    text = f"{room.get('name', data.room)}"
    success = await audio_svc.play_room_stereo(
        left_amp, left_ch, data.volume_left,
        right_amp, right_ch, data.volume_right,
        sound=data.type,
        text=text,
    )

    if not success:
        raise HTTPException(status_code=500, detail="Playback failed")

    return {"status": "ok"}


# === Bulk config write + apply ===

class ApplyRequest(BaseModel):
    """New full config for speakers/rooms (other top-level keys preserved as-is)."""
    speakers: dict[str, dict]
    rooms: dict[str, dict]
    max_volume: float | None = None  # 0..1; if provided, replaces global.max_volume


@router.post("/config/apply")
async def config_apply(request: Request, data: ApplyRequest):
    """Atomically write new speakers+rooms config and run the apply pipeline.

    Steps: write speaker_config.json, regenerate /etc/asound.conf, restart
    sendspin services for rooms whose effective channel mapping changed.
    """
    config_svc = get_config_service(request)
    project_dir = request.app.state.project_dir

    old_config = copy.deepcopy(config_svc.config)

    # Validate: every speaker referenced by a room must exist; no two speakers
    # may share an (amp, channel); no two rooms may share a speaker.
    speakers = data.speakers
    rooms = data.rooms

    # (amp, channel) uniqueness
    seen_channels: dict[tuple[str, int], str] = {}
    for spk_id, spk in speakers.items():
        amp = spk.get("amplifier")
        ch = spk.get("channel")
        if not amp or ch is None:
            raise HTTPException(status_code=400, detail=f"Speaker {spk_id!r} missing amplifier/channel")
        key = (amp, int(ch))
        if key in seen_channels:
            raise HTTPException(
                status_code=400,
                detail=f"Channel {amp}/{ch} used by both {seen_channels[key]!r} and {spk_id!r}",
            )
        seen_channels[key] = spk_id

    # Speaker-room consistency
    speaker_used_by: dict[str, str] = {}
    for room_id, room in rooms.items():
        for side in ("left", "right", "sub", "mono"):
            spk_id = room.get(side)
            if not spk_id:
                continue
            if spk_id not in speakers:
                raise HTTPException(
                    status_code=400,
                    detail=f"Room {room_id!r} references unknown speaker {spk_id!r}",
                )
            if spk_id in speaker_used_by:
                raise HTTPException(
                    status_code=400,
                    detail=f"Speaker {spk_id!r} used by both {speaker_used_by[spk_id]!r} and {room_id!r}",
                )
            speaker_used_by[spk_id] = room_id

    # Build new config: copy old + replace speakers/rooms (+ optional global)
    new_config = copy.deepcopy(old_config)
    new_config["speakers"] = speakers
    new_config["rooms"] = rooms
    if data.max_volume is not None:
        v = max(0.0, min(1.0, float(data.max_volume)))
        new_config.setdefault("global", {})["max_volume"] = v

    # Persist to disk (creates a .bak)
    config_svc.save(new_config)

    # Run apply pipeline
    try:
        result = await apply_config(project_dir, old_config, new_config)
    except RuntimeError as e:
        # Roll back on apply failure
        config_svc.save(old_config)
        raise HTTPException(status_code=500, detail=str(e))

    return {"status": "ok", **result}


# === System ===

@router.get("/system/services")
async def get_services(request: Request):
    """Get status of system services"""
    import asyncio

    services = ['powermanager']

    # Get sendspin services for each room
    config_svc = get_config_service(request)
    for room_id in config_svc.get_rooms().keys():
        services.append(f'sendspin@room_{room_id}')

    results = {}
    for service in services:
        proc = await asyncio.create_subprocess_exec(
            'systemctl', 'is-active', service,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL
        )
        stdout, _ = await proc.communicate()
        results[service] = stdout.decode().strip()

    return results


class AmpControlRequest(BaseModel):
    amp: str   # "amp1", "amp2", "amp3"
    state: str  # "on" or "off"


@router.post("/system/amp")
async def control_amp(request: Request, data: AmpControlRequest):
    """Control individual amplifier via ampctl"""
    import asyncio

    proc = await asyncio.create_subprocess_exec(
        'ampctl', data.state, data.amp,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
    )
    _, stderr = await proc.communicate()

    if proc.returncode != 0:
        raise HTTPException(status_code=500, detail=f"ampctl failed: {stderr.decode()}")

    return {"status": "ok", "amp": data.amp, "state": data.state}


@router.get("/system/powermanager")
async def get_powermanager_status(request: Request):
    """Get per-amp power status via ampctl and ALSA activity"""
    import asyncio
    import json as jsonlib

    amps = {}

    # Get all amp states in one call
    proc = await asyncio.create_subprocess_exec(
        'ampctl', 'status',
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL
    )
    stdout, _ = await proc.communicate()
    try:
        states = jsonlib.loads(stdout.decode())
    except Exception:
        states = {}

    for amp in ["amp1", "amp2", "amp3"]:
        amp_info = {"state": states.get(amp, "unknown"), "audio_active": False}

        # Check ALSA activity
        try:
            status_file = f'/proc/asound/{amp}/pcm0p/sub0/status'
            proc = await asyncio.create_subprocess_exec(
                'cat', status_file,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL
            )
            stdout, _ = await proc.communicate()
            if 'state: RUNNING' in stdout.decode():
                amp_info["audio_active"] = True
        except Exception:
            pass

        amps[amp] = amp_info

    return {"amps": amps}


# === Sendspin status ===

@router.get("/system/sendspin")
async def get_sendspin_status(request: Request):
    """Get sendspin client status for all rooms"""
    import asyncio

    config_svc = get_config_service(request)
    clients = {}

    for room_id in config_svc.get_rooms().keys():
        service = f'sendspin@room_{room_id}'
        proc = await asyncio.create_subprocess_exec(
            'systemctl', 'is-active', service,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL
        )
        stdout, _ = await proc.communicate()
        status = stdout.decode().strip()

        clients[room_id] = {
            "service": service,
            "active": status == "active",
            "status": status,
        }

    return {"clients": clients}


# === Input runtime status ===

@router.get("/system/inputs")
async def get_input_status(request: Request):
    """Per-input runtime status: is the lineinpipe bridge active, and is the
    capture device actually running (PCM state RUNNING)?"""
    import asyncio

    config_svc = get_config_service(request)
    inputs = {}

    for input_id, inp in config_svc.get_inputs().items():
        unit = f"lineinpipe@{input_id}.service"
        proc = await asyncio.create_subprocess_exec(
            'systemctl', 'is-active', unit,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        stdout, _ = await proc.communicate()
        status = stdout.decode().strip()

        capturing = False
        card = inp.get("card", input_id)
        try:
            status_file = f'/proc/asound/{card}/pcm0c/sub0/status'
            proc = await asyncio.create_subprocess_exec(
                'cat', status_file,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
            )
            out, _ = await proc.communicate()
            if 'state: RUNNING' in out.decode():
                capturing = True
        except Exception:
            pass

        inputs[input_id] = {
            "service": unit,
            "active": status == "active",
            "status": status,
            "capturing": capturing,
        }

    return {"inputs": inputs}


# === Input test (capture a few seconds → play into a room) ===

class InputTestRequest(BaseModel):
    room: str | None = None   # room id to play into; None → all_rooms
    seconds: int = 3


@router.post("/test/input/{input_id}")
async def test_input(request: Request, input_id: str, data: InputTestRequest):
    """Capture a short sample from the input and play it into a room so the user
    can confirm the line-in is live. Routes input_<id> → room_<room>/all_rooms."""
    import asyncio

    config_svc = get_config_service(request)
    if input_id not in config_svc.get_inputs():
        raise HTTPException(status_code=404, detail="Input not found")

    target = f"room_{data.room}" if data.room else "all_rooms"
    if data.room and data.room not in config_svc.get_rooms():
        raise HTTPException(status_code=404, detail="Room not found")

    seconds = max(1, min(10, int(data.seconds)))
    # arecord from the input PCM → aplay to the room PCM. Both 44100/2ch raw.
    cmd = (
        f"arecord -D input_{input_id} -f S16_LE -c 2 -r 44100 -d {seconds} -t raw - 2>/dev/null | "
        f"aplay -D {target} -f S16_LE -c 2 -r 44100 -t raw - 2>/dev/null"
    )
    proc = await asyncio.create_subprocess_shell(cmd)
    try:
        await asyncio.wait_for(proc.wait(), timeout=seconds + 5)
    except asyncio.TimeoutError:
        proc.kill()
        raise HTTPException(status_code=500, detail="Test capture/playback timed out")

    if proc.returncode != 0:
        raise HTTPException(status_code=500, detail="Capture or playback failed")
    return {"status": "ok", "input": input_id, "target": target, "seconds": seconds}


# ----------------------------------------------------------------------------
# System tab: live host metrics + lox-audioserver status/control
# ----------------------------------------------------------------------------

def _read_file(path: str) -> str:
    try:
        with open(path) as f:
            return f.read()
    except Exception:
        return ""


def _cpu_times():
    """(total, idle) jiffies from /proc/stat first line, or None."""
    line = _read_file("/proc/stat").splitlines()
    if not line:
        return None
    parts = line[0].split()[1:]
    try:
        vals = [int(x) for x in parts]
    except ValueError:
        return None
    idle = vals[3] + (vals[4] if len(vals) > 4 else 0)  # idle + iowait
    return sum(vals), idle


@router.get("/system/metrics")
async def system_metrics(request: Request):
    """Live host metrics for the System tab (temp, CPU%, memory, load, throttle)."""
    import asyncio

    # CPU temperature
    temp_c = None
    raw = _read_file("/sys/class/thermal/thermal_zone0/temp").strip()
    if raw.isdigit():
        temp_c = round(int(raw) / 1000.0, 1)

    # CPU usage % over a short window
    cpu_percent = None
    a = _cpu_times()
    await asyncio.sleep(0.2)
    b = _cpu_times()
    if a and b:
        dt, di = b[0] - a[0], b[1] - a[1]
        if dt > 0:
            cpu_percent = round((1 - di / dt) * 100, 1)

    # Memory (MB)
    mem = {}
    for ln in _read_file("/proc/meminfo").splitlines():
        k, _, v = ln.partition(":")
        mem[k.strip()] = v.strip()

    def _kb(key):
        try:
            return int(mem.get(key, "0").split()[0])
        except Exception:
            return 0

    mem_total = _kb("MemTotal")
    mem_used = mem_total - _kb("MemAvailable")

    load = _read_file("/proc/loadavg").split()[:3]
    up = _read_file("/proc/uptime").split()
    uptime_s = int(float(up[0])) if up else None

    # Pi throttle flags
    throttled = None
    try:
        proc = await asyncio.create_subprocess_exec(
            "vcgencmd", "get_throttled",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
        )
        out, _ = await proc.communicate()
        throttled = (out.decode().strip().split("=")[-1] or None)
    except Exception:
        pass

    return {
        "temp_c": temp_c,
        "cpu_percent": cpu_percent,
        "mem_used_mb": round(mem_used / 1024.0, 1),
        "mem_total_mb": round(mem_total / 1024.0, 1),
        "load": load,
        "uptime_s": uptime_s,
        "throttled": throttled,
    }


@router.get("/system/lox")
async def lox_status(request: Request):
    """lox-audioserver Docker container status."""
    import asyncio
    import json as jsonlib

    proc = await asyncio.create_subprocess_exec(
        "docker", "inspect", "lox-audioserver",
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    out, err = await proc.communicate()
    if proc.returncode != 0:
        return {"status": "absent", "running": False,
                "error": err.decode().strip()[:200]}
    try:
        data = jsonlib.loads(out.decode())[0]
    except Exception:
        return {"status": "unknown", "running": False}
    state = data.get("State", {}) or {}
    health = state.get("Health") or {}
    return {
        "status": state.get("Status"),
        "running": bool(state.get("Running")),
        "started": state.get("StartedAt"),
        "image": (data.get("Config", {}) or {}).get("Image"),
        "health": health.get("Status") or "none",
    }


@router.post("/system/lox/restart")
async def lox_restart(request: Request):
    """Restart the lox-audioserver container."""
    import asyncio

    proc = await asyncio.create_subprocess_exec(
        "docker", "restart", "lox-audioserver",
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    _, err = await proc.communicate()
    if proc.returncode != 0:
        raise HTTPException(status_code=500,
                            detail=f"docker restart failed: {err.decode().strip()[:300]}")
    return {"status": "ok", "restarted": "lox-audioserver"}
