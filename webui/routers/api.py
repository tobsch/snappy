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
            if zone_id not in zones:
                zones.append(zone_id)
        else:
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
    """Deploy configuration (generates ALSA config, restarts services)"""
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
    """Preview generated ALSA config without deploying"""
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

    return {
        "alsa_config": alsa_stdout.decode(),
    }


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
