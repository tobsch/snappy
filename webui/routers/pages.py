"""Page routes - serves HTML pages"""

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from services.config import ConfigService

router = APIRouter(tags=["pages"])


def get_config_service(request: Request) -> ConfigService:
    return ConfigService(request.app.state.config_file)


@router.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    """Main dashboard page"""
    config_svc = get_config_service(request)
    templates = request.app.state.templates

    return templates.TemplateResponse("dashboard.html", {
        "request": request,
        "rooms": config_svc.get_rooms(),
        "zones": config_svc.get_zones(),
        "streams": config_svc.get_streams(),
        "amplifiers": config_svc.get_amplifiers(),
    })


@router.get("/amplifiers", response_class=HTMLResponse)
async def amplifiers(request: Request):
    """Amplifier channel view with test buttons"""
    config_svc = get_config_service(request)
    templates = request.app.state.templates

    # Build channel grid data
    amps_data = []
    for amp_id, amp in config_svc.get_amplifiers().items():
        channels = []
        for ch in range(1, amp.get('channels', 8) + 1):
            assignment = config_svc.get_channel_assignment(amp_id, ch)
            channels.append({
                'number': ch,
                'assignment': assignment,
            })
        amps_data.append({
            'id': amp_id,
            'card': amp.get('card', amp_id),
            'channels': channels,
        })

    return templates.TemplateResponse("amplifiers.html", {
        "request": request,
        "amplifiers": amps_data,
    })


@router.get("/rooms", response_class=HTMLResponse)
async def rooms(request: Request):
    """Room management page"""
    config_svc = get_config_service(request)
    templates = request.app.state.templates

    # Enrich room data with speaker info
    rooms_data = []
    for room_id, room in config_svc.get_rooms().items():
        left_speaker = config_svc.get_speaker(room.get('left')) if room.get('left') else None
        right_speaker = config_svc.get_speaker(room.get('right')) if room.get('right') else None

        rooms_data.append({
            'id': room_id,
            'name': room.get('name', room_id),
            'zones': room.get('zones', []),
            'left': {
                'id': room.get('left'),
                'speaker': left_speaker,
            } if left_speaker else None,
            'right': {
                'id': room.get('right'),
                'speaker': right_speaker,
            } if right_speaker else None,
        })

    return templates.TemplateResponse("rooms.html", {
        "request": request,
        "rooms": rooms_data,
        "zones": config_svc.get_zones(),
    })


@router.get("/zones", response_class=HTMLResponse)
async def zones(request: Request):
    """Zone & Stream management page"""
    config_svc = get_config_service(request)
    templates = request.app.state.templates

    # Get all streams and their targets
    all_streams = config_svc.get_streams()
    stream_targets = config_svc.get_stream_targets()

    # Build set of enabled stream types per zone
    zone_stream_types = {}
    for stream_id, targets in stream_targets.items():
        stream = all_streams.get(stream_id, {})
        stream_type = stream.get('type', 'unknown')
        # Map librespot -> spotify for display
        if stream_type == 'librespot':
            stream_type = 'spotify'
        for zone_id in targets.get('zones', []):
            if zone_id not in zone_stream_types:
                zone_stream_types[zone_id] = set()
            zone_stream_types[zone_id].add(stream_type)

    # Enrich zone data with member rooms and stream flags
    zones_data = []
    for zone_id, zone in config_svc.get_zones().items():
        member_rooms = config_svc.get_rooms_in_zone(zone_id)
        rooms_info = []
        for room_id in member_rooms:
            room = config_svc.get_room(room_id)
            if room:
                rooms_info.append({
                    'id': room_id,
                    'name': room.get('name', room_id),
                })

        enabled_types = zone_stream_types.get(zone_id, set())
        zones_data.append({
            'id': zone_id,
            'name': zone.get('name', zone_id),
            'include_all': zone.get('include_all', False),
            'rooms': rooms_info,
            'has_spotify': 'spotify' in enabled_types,
            'has_airplay': 'airplay' in enabled_types,
            'has_sendspin': 'sendspin' in enabled_types,
        })

    return templates.TemplateResponse("zones.html", {
        "request": request,
        "zones": zones_data,
        "all_rooms": config_svc.get_rooms(),
    })


@router.get("/streams", response_class=HTMLResponse)
async def streams(request: Request):
    """Stream configuration page"""
    config_svc = get_config_service(request)
    templates = request.app.state.templates

    # Enrich stream data with targets
    streams_data = []
    stream_targets = config_svc.get_stream_targets()

    for stream_id, stream in config_svc.get_streams().items():
        targets = stream_targets.get(stream_id, {})
        streams_data.append({
            'id': stream_id,
            'name': stream.get('name', stream_id),
            'type': stream.get('type', 'unknown'),
            'config': stream,
            'target_zones': targets.get('zones', []),
            'target_rooms': targets.get('rooms', []),
        })

    return templates.TemplateResponse("streams.html", {
        "request": request,
        "streams": streams_data,
        "zones": config_svc.get_zones(),
        "rooms": config_svc.get_rooms(),
    })


@router.get("/playback", response_class=HTMLResponse)
async def playback(request: Request):
    """Playback control page (Snapcast)"""
    templates = request.app.state.templates

    return templates.TemplateResponse("playback.html", {
        "request": request,
    })


@router.get("/settings", response_class=HTMLResponse)
async def settings(request: Request):
    """Settings page"""
    config_svc = get_config_service(request)
    templates = request.app.state.templates

    return templates.TemplateResponse("settings.html", {
        "request": request,
        "max_volume": config_svc.get_max_volume(),
        "global_config": config_svc.get_global(),
    })
