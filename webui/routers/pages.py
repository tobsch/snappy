"""Page routes — single-page rack UI."""

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from services.config import ConfigService
from services.audio_cards import detect_cards, find_card_for_amp

router = APIRouter(tags=["pages"])


def get_config_service(request: Request) -> ConfigService:
    return ConfigService(request.app.state.config_file)


@router.get("/", response_class=HTMLResponse)
async def rack(request: Request):
    """The whole UI: a single rack with status, patch panel, and amp modules."""
    config_svc = get_config_service(request)
    templates = request.app.state.templates

    cards = detect_cards()
    amps = []
    for amp_id, amp in config_svc.get_amplifiers().items():
        # Match the physical card by its ALSA short id (amp.card), which is what
        # /proc/asound enumerates — not the config key. They only coincide once a
        # udev rule renames the card to the amp_id; an un-renamed amp enumerates
        # under its generic name (e.g. "Device") and must be matched on that.
        card = find_card_for_amp(cards, amp.get("card", amp_id))
        amps.append({
            "id": amp_id,
            "card": amp.get("card", amp_id),
            "channels": amp.get("channels", 8),
            "gpio": amp.get("gpio"),            # int or None (None = always-on)
            "model": (card or {}).get("description") or amp.get("card", amp_id),
            "usb_path": (card or {}).get("usb_path"),
            "online": card is not None,
        })

    inputs = []
    for input_id, inp in config_svc.get_inputs().items():
        card = find_card_for_amp(cards, inp.get("card", input_id))
        inputs.append({
            "id": input_id,
            "card": inp.get("card", input_id),
            "name": inp.get("name", input_id),
            "channels": inp.get("channels", 2),
            "sample_rate": inp.get("sample_rate", 48000),
            "lox_input_id": inp.get("lox_input_id", input_id),
            "autostart": inp.get("autostart", True),
            "online": card is not None,
            "capture_channels": (card or {}).get("capture_channels", 0),
        })

    return templates.TemplateResponse("amplifiers.html", {
        "request": request,
        "amps": amps,
        "inputs": inputs,
        "speakers": config_svc.get_speakers(),
        "rooms": config_svc.get_rooms(),
        "max_volume": config_svc.get_max_volume(),
    })
