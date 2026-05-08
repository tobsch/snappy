"""API routes - REST endpoints"""

import copy

from fastapi import APIRouter, Request, HTTPException
from pydantic import BaseModel

from services.config import ConfigService
from services.audio import AudioService
from services.apply import apply_config
from services.audio_cards import detect_cards, annotate_configured_amps

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
    config_svc.add_amplifier(amp_id, {
        "card": data.card or amp_id,
        "channels": int(data.channels),
    })
    return {"status": "ok", "amp_id": amp_id}


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
    position: str = "stereo"           # "left", "right", or "stereo"
    type: str = "chime"                # "tts" or "chime"
    volume_left: int | None = None     # live slider preview
    volume_right: int | None = None


@router.post("/test/room")
async def test_room(request: Request, data: RoomTestRequest):
    """Play test sound on a room — fans out to per-channel devices so each
    side gets its own live slider gain."""
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
        for side in ("left", "right", "sub"):
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
