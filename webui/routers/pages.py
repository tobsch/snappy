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
        "amplifiers": config_svc.get_amplifiers(),
    })


@router.get("/amplifiers", response_class=HTMLResponse)
async def amplifiers(request: Request):
    """Amplifier channel view: drag-and-drop room→channel assignment."""
    config_svc = get_config_service(request)
    templates = request.app.state.templates

    amps = []
    for amp_id, amp in config_svc.get_amplifiers().items():
        amps.append({
            "id": amp_id,
            "card": amp.get("card", amp_id),
            "channels": amp.get("channels", 8),
        })

    return templates.TemplateResponse("amplifiers.html", {
        "request": request,
        "amps": amps,
        "speakers": config_svc.get_speakers(),
        "rooms": config_svc.get_rooms(),
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
