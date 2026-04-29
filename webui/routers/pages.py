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
    """Zone management page"""
    config_svc = get_config_service(request)
    templates = request.app.state.templates

    # Enrich zone data with member rooms
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

        zones_data.append({
            'id': zone_id,
            'name': zone.get('name', zone_id),
            'include_all': zone.get('include_all', False),
            'rooms': rooms_info,
        })

    return templates.TemplateResponse("zones.html", {
        "request": request,
        "zones": zones_data,
        "all_rooms": config_svc.get_rooms(),
    })


@router.get("/playback", response_class=HTMLResponse)
async def playback(request: Request):
    """Sendspin client status page"""
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
