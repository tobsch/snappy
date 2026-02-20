"""API routes - REST endpoints"""

from fastapi import APIRouter, Request, HTTPException
from pydantic import BaseModel

from services.config import ConfigService
from services.audio import AudioService

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


# === Zone endpoints ===

@router.get("/config/zones")
async def get_zones(request: Request):
    """Get all zones"""
    config_svc = get_config_service(request)
    return config_svc.get_zones()


class ZoneUpdate(BaseModel):
    name: str
    include_all: bool = False


@router.post("/config/zones/{zone_id}")
async def create_zone(request: Request, zone_id: str, data: ZoneUpdate):
    """Create a new zone"""
    config_svc = get_config_service(request)
    config_svc.create_zone(zone_id, data.model_dump())
    return {"status": "ok", "zone_id": zone_id}


@router.put("/config/zones/{zone_id}")
async def update_zone(request: Request, zone_id: str, data: ZoneUpdate):
    """Update a zone"""
    config_svc = get_config_service(request)
    if not config_svc.get_zone(zone_id):
        raise HTTPException(status_code=404, detail="Zone not found")
    config_svc.update_zone(zone_id, data.model_dump())
    return {"status": "ok", "zone_id": zone_id}


@router.delete("/config/zones/{zone_id}")
async def delete_zone(request: Request, zone_id: str):
    """Delete a zone"""
    config_svc = get_config_service(request)
    if not config_svc.delete_zone(zone_id):
        raise HTTPException(status_code=404, detail="Zone not found")
    return {"status": "ok"}


class ZoneRoomsUpdate(BaseModel):
    rooms: list[str]


@router.put("/zones/{zone_id}/rooms")
async def set_zone_rooms(request: Request, zone_id: str, data: ZoneRoomsUpdate):
    """Set which rooms belong to a zone"""
    config_svc = get_config_service(request)

    # Verify zone exists
    if not config_svc.get_zone(zone_id):
        raise HTTPException(status_code=404, detail="Zone not found")

    # Get all rooms and update their zones arrays
    all_rooms = config_svc.get_rooms()
    for room_id, room in all_rooms.items():
        zones = room.get('zones', [])
        if room_id in data.rooms:
            # Room should be in this zone
            if zone_id not in zones:
                zones.append(zone_id)
        else:
            # Room should NOT be in this zone
            if zone_id in zones:
                zones.remove(zone_id)
        room['zones'] = zones
        config_svc.update_room(room_id, room)

    return {"status": "ok", "zone_id": zone_id}


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


# === Stream endpoints ===

@router.get("/config/streams")
async def get_streams(request: Request):
    """Get all streams"""
    config_svc = get_config_service(request)
    return config_svc.get_streams()


class StreamCreate(BaseModel):
    type: str  # librespot, airplay, pipe, alsa, sendspin
    name: str
    bitrate: int | None = None  # for librespot
    port: int | None = None  # for airplay
    url: str | None = None  # for sendspin
    path: str | None = None  # for pipe
    input: str | None = None  # for alsa


@router.post("/config/streams/{stream_id}")
async def create_stream(request: Request, stream_id: str, data: StreamCreate):
    """Create a new stream"""
    config_svc = get_config_service(request)

    stream_config = {"type": data.type, "name": data.name}

    if data.type == "librespot":
        stream_config["bitrate"] = data.bitrate or 320
    elif data.type == "airplay":
        stream_config["port"] = data.port or 7000
    elif data.type == "sendspin":
        stream_config["url"] = data.url or "ws://192.168.0.235:7090/sendspin"
    elif data.type == "pipe":
        stream_config["path"] = data.path or f"/tmp/snapfifo_{stream_id}"
    elif data.type == "alsa":
        stream_config["input"] = data.input

    config_svc.update_stream(stream_id, stream_config)
    return {"status": "ok", "stream_id": stream_id}


@router.delete("/config/streams/{stream_id}")
async def delete_stream(request: Request, stream_id: str):
    """Delete a stream"""
    config_svc = get_config_service(request)
    if not config_svc.delete_stream(stream_id):
        raise HTTPException(status_code=404, detail="Stream not found")
    # Also remove from stream_targets
    targets = config_svc.get_stream_targets()
    if stream_id in targets:
        del config_svc.config['snapcast']['stream_targets'][stream_id]
        config_svc.save()
    return {"status": "ok"}


# === Stream targets ===

class StreamTargetCreate(BaseModel):
    zones: list[str] = []
    rooms: list[str] = []


@router.post("/config/stream_targets/{stream_id}")
async def set_stream_targets(request: Request, stream_id: str, data: StreamTargetCreate):
    """Set target zones/rooms for a stream"""
    config_svc = get_config_service(request)
    config_svc.update_stream_targets(stream_id, data.model_dump())
    return {"status": "ok", "stream_id": stream_id}


# === Zone stream toggles ===

@router.put("/zones/{zone_id}/streams/{stream_type}")
async def enable_zone_stream(request: Request, zone_id: str, stream_type: str):
    """Enable a stream type for a zone (creates stream with defaults)"""
    config_svc = get_config_service(request)

    # Map display type to internal type
    internal_type = 'librespot' if stream_type == 'spotify' else stream_type
    stream_id = f"{stream_type}_{zone_id}"

    # Get zone name for display name
    zone = config_svc.get_zone(zone_id)
    zone_name = zone.get('name', zone_id) if zone else zone_id

    # Create stream with sensible defaults
    if internal_type == 'librespot':
        stream_config = {
            "type": "librespot",
            "name": zone_name,
            "bitrate": 320,
        }
    elif internal_type == 'airplay':
        # Find next available port
        existing_ports = set()
        for s in config_svc.get_streams().values():
            if s.get('type') == 'airplay' and s.get('port'):
                existing_ports.add(s['port'])
        port = 7000
        while port in existing_ports:
            port += 1
        stream_config = {
            "type": "airplay",
            "name": zone_name,
            "port": port,
        }
    elif internal_type == 'sendspin':
        stream_config = {
            "type": "sendspin",
            "name": zone_name,
            "url": "ws://192.168.0.235:7090/sendspin",
        }
    else:
        raise HTTPException(status_code=400, detail=f"Unknown stream type: {stream_type}")

    # Save stream and target
    config_svc.update_stream(stream_id, stream_config)
    config_svc.update_stream_targets(stream_id, {"zones": [zone_id]})

    return {"status": "ok", "stream_id": stream_id}


@router.delete("/zones/{zone_id}/streams/{stream_type}")
async def disable_zone_stream(request: Request, zone_id: str, stream_type: str):
    """Disable a stream type for a zone (removes stream)"""
    config_svc = get_config_service(request)

    stream_id = f"{stream_type}_{zone_id}"

    # Delete stream
    config_svc.delete_stream(stream_id)

    # Also remove from stream_targets
    if 'snapcast' in config_svc.config and 'stream_targets' in config_svc.config['snapcast']:
        if stream_id in config_svc.config['snapcast']['stream_targets']:
            del config_svc.config['snapcast']['stream_targets'][stream_id]
            config_svc.save()

    return {"status": "ok"}


# === Global settings ===

class GlobalUpdate(BaseModel):
    max_volume: float


@router.put("/config/global")
async def update_global(request: Request, data: GlobalUpdate):
    """Update global settings"""
    config_svc = get_config_service(request)
    config_svc.update_global(data.model_dump())
    return {"status": "ok"}


# === Test endpoints ===

class ChannelTestRequest(BaseModel):
    amplifier: str
    channel: int
    type: str = "chime"  # "tts" or "chime"


@router.post("/test/channel")
async def test_channel(request: Request, data: ChannelTestRequest):
    """Play test sound on a channel"""
    audio_svc = get_audio_service(request)

    if data.type == "tts":
        success = await audio_svc.play_tts(data.amplifier, data.channel)
    else:
        success = await audio_svc.play_chime(data.amplifier, data.channel)

    if not success:
        raise HTTPException(status_code=500, detail="Playback failed")

    return {"status": "ok"}


class RoomTestRequest(BaseModel):
    room: str
    position: str = "stereo"  # "left", "right", or "stereo"


@router.post("/test/room")
async def test_room(request: Request, data: RoomTestRequest):
    """Play test sound on a room"""
    audio_svc = get_audio_service(request)
    success = await audio_svc.play_room_test(data.room, data.position)

    if not success:
        raise HTTPException(status_code=500, detail="Playback failed")

    return {"status": "ok"}


# === Deployment ===

@router.post("/deploy")
async def deploy(request: Request):
    """Deploy configuration (generates configs, restarts services)"""
    import asyncio

    project_dir = request.app.state.project_dir

    # Run deploy_config.py
    proc = await asyncio.create_subprocess_exec(
        'python3', str(project_dir / 'deploy_config.py'),
        cwd=str(project_dir),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
    )
    stdout, stderr = await proc.communicate()

    if proc.returncode != 0:
        raise HTTPException(
            status_code=500,
            detail=f"Deployment failed: {stderr.decode()}"
        )

    return {
        "status": "ok",
        "output": stdout.decode(),
    }


@router.get("/deploy/preview")
async def preview_deploy(request: Request):
    """Preview generated configs without deploying"""
    import asyncio

    project_dir = request.app.state.project_dir

    # Generate ALSA config
    alsa_proc = await asyncio.create_subprocess_exec(
        'python3', str(project_dir / 'generate_alsa_config.py'),
        cwd=str(project_dir),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
    )
    alsa_stdout, _ = await alsa_proc.communicate()

    # Generate Snapcast config
    snap_proc = await asyncio.create_subprocess_exec(
        'python3', str(project_dir / 'generate_snapserver_conf.py'),
        cwd=str(project_dir),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
    )
    snap_stdout, _ = await snap_proc.communicate()

    return {
        "alsa_config": alsa_stdout.decode(),
        "snapserver_config": snap_stdout.decode(),
    }


# === System ===

@router.get("/system/services")
async def get_services(request: Request):
    """Get status of system services"""
    import asyncio

    services = ['snapserver', 'powermanager']

    # Get snapclient and sendspin services
    config_svc = get_config_service(request)
    for room_id in config_svc.get_rooms().keys():
        services.append(f'snapclient@room_{room_id}')
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


class RelayRequest(BaseModel):
    state: str  # "on" or "off"


@router.post("/system/relay")
async def control_relay(request: Request, data: RelayRequest):
    """Control USB relay (on/off)"""
    import asyncio

    # Relay logic is inverted: relay ON = amps OFF
    cmd_state = "off" if data.state == "on" else "on"

    proc = await asyncio.create_subprocess_exec(
        'crelay', '1', cmd_state,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
    )
    stdout, stderr = await proc.communicate()

    if proc.returncode != 0:
        raise HTTPException(status_code=500, detail=f"Relay control failed: {stderr.decode()}")

    return {"status": "ok", "relay_state": data.state}


@router.get("/system/powermanager")
async def get_powermanager_status(request: Request):
    """Get powermanager status (relay state and audio activity)"""
    import asyncio
    import re

    result = {
        "relay_state": "unknown",
        "audio_active": False,
        "active_cards": []
    }

    # Get relay state
    try:
        proc = await asyncio.create_subprocess_exec(
            'crelay', '1',
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, _ = await proc.communicate()
        output = stdout.decode().strip()
        # crelay output: "Relay 1 is OFF" or "Relay 1 is ON"
        # Inverted logic: relay OFF = amps ON
        if 'OFF' in output.upper():
            result["relay_state"] = "on"  # amps are on
        elif 'ON' in output.upper():
            result["relay_state"] = "off"  # amps are off
    except Exception:
        pass

    # Check ALSA activity
    config_svc = get_config_service(request)
    cards = list(config_svc.get_amplifiers().keys())

    for card in cards:
        try:
            # Check /proc/asound/<card>/pcm0p/sub0/status
            proc = await asyncio.create_subprocess_exec(
                'cat', f'/proc/asound/{card}/pcm0p/sub0/status',
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL
            )
            stdout, _ = await proc.communicate()
            status = stdout.decode()

            if 'state: RUNNING' in status:
                # Check if owner process is alive
                pid_match = re.search(r'owner_pid\s*:\s*(\d+)', status)
                if pid_match:
                    pid = pid_match.group(1)
                    # Check if process exists
                    pid_check = await asyncio.create_subprocess_exec(
                        'cat', f'/proc/{pid}/comm',
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.DEVNULL
                    )
                    pid_stdout, _ = await pid_check.communicate()
                    if pid_check.returncode == 0:
                        # Process exists - stream is active
                        result["active_cards"].append(card)
                        result["audio_active"] = True
        except Exception:
            pass

    return result


# === Snapcast ===

from services.snapcast import SnapcastClient


@router.get("/snapcast/status")
async def snapcast_status():
    """Get Snapcast server status"""
    try:
        client = SnapcastClient()
        status = await client.get_status()
        return status
    except Exception as e:
        return {"error": str(e)}


class GroupStreamRequest(BaseModel):
    group_id: str
    stream_id: str


@router.post("/snapcast/group/stream")
async def set_group_stream(data: GroupStreamRequest):
    """Set stream for a group"""
    try:
        client = SnapcastClient()
        await client.set_group_stream(data.group_id, data.stream_id)
        return {"status": "ok"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


class GroupVolumeRequest(BaseModel):
    client_id: str
    volume: int


@router.post("/snapcast/client/volume")
async def set_client_volume(data: GroupVolumeRequest):
    """Set volume for a client"""
    try:
        client = SnapcastClient()
        await client.set_client_volume(data.client_id, data.volume)
        return {"status": "ok"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
