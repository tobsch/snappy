"""Page routes - serves HTML pages"""

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from services.config import ConfigService
from services.audio_cards import detect_cards, find_card_for_amp

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

    cards = detect_cards()
    amps = []
    for amp_id, amp in config_svc.get_amplifiers().items():
        card = find_card_for_amp(cards, amp_id)
        amps.append({
            "id": amp_id,
            "card": amp.get("card", amp_id),
            "channels": amp.get("channels", 8),
            "model": (card or {}).get("description") or amp.get("card", amp_id),
            "usb_path": (card or {}).get("usb_path"),
            "online": card is not None,
        })

    return templates.TemplateResponse("amplifiers.html", {
        "request": request,
        "amps": amps,
        "speakers": config_svc.get_speakers(),
        "rooms": config_svc.get_rooms(),
        "max_volume": config_svc.get_max_volume(),
    })


@router.get("/playback", response_class=HTMLResponse)
async def playback(request: Request):
    """Sendspin client status page"""
    templates = request.app.state.templates

    return templates.TemplateResponse("playback.html", {
        "request": request,
    })


