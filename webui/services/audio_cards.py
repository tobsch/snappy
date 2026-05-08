"""Detect ALSA USB audio cards on the system.

Parses /proc/asound/cards and supplements with udev info from /sys/class/sound.
Used by the rack UI to show the actual model / USB path of each configured amp,
and to surface unconfigured USB amps as candidates for "+ Add Amp".
"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path
from typing import Iterable


CARDS_PROC = Path("/proc/asound/cards")
SYS_SOUND = Path("/sys/class/sound")

# Cards we never treat as amps — built-in HDMI/loopback/etc.
SKIP_DRIVERS = {"vc4-hdmi", "Loopback", "snd-aloop"}
SKIP_NAME_RE = re.compile(r"^(vc4hdmi|Loopback|HDA|HDMI|bcm2835)", re.IGNORECASE)


def _udev_path_for(card_index: int) -> str | None:
    sysdir = SYS_SOUND / f"card{card_index}"
    if not sysdir.exists():
        return None
    try:
        out = subprocess.run(
            ["udevadm", "info", "-q", "property", str(sysdir)],
            capture_output=True, text=True, timeout=2,
        )
    except Exception:
        return None
    for line in out.stdout.splitlines():
        if line.startswith("ID_PATH="):
            return line[len("ID_PATH="):].strip()
    return None


def _count_playback_subdevices(card_index: int) -> int:
    sysdir = SYS_SOUND / f"card{card_index}"
    if not sysdir.exists():
        return 0
    n = 0
    for pcm in sysdir.glob("pcm*p"):
        # subdevice count from /proc
        proc_pcm = Path(f"/proc/asound/card{card_index}") / pcm.name
        for sub in proc_pcm.glob("sub*"):
            n += 1
        if n == 0:
            n = 1  # at least one playback substream
    return n


def detect_cards() -> list[dict]:
    """Return a list of dicts describing every ALSA card.

    Each dict contains:
      index        — kernel card number
      id           — ALSA short id (e.g. 'amp1' after udev rename, or 'GAB8' default)
      driver       — e.g. 'USB-Audio', 'vc4-hdmi', 'Loopback'
      description  — human description from /proc/asound/cards line 1 (e.g. 'WONDOM GAB8')
      longname     — full description line 2 (vendor + model + USB topology)
      usb_path     — udev ID_PATH (or None for non-USB cards)
      is_usb_audio — convenience boolean
      is_skip      — built-in HDMI / loopback / etc.
    """
    if not CARDS_PROC.exists():
        return []

    text = CARDS_PROC.read_text()
    # Each card spans two lines: header line + longname line.
    cards: list[dict] = []
    lines = text.splitlines()
    i = 0
    header_re = re.compile(r"^\s*(\d+)\s+\[\s*(\S+)\s*\]:\s*(\S+)\s*-\s*(.*)$")
    while i < len(lines):
        m = header_re.match(lines[i])
        if not m:
            i += 1
            continue
        idx = int(m.group(1))
        cid = m.group(2)
        driver = m.group(3)
        desc = m.group(4).strip()
        longname = lines[i + 1].strip() if i + 1 < len(lines) else ""
        i += 2

        is_usb_audio = driver == "USB-Audio"
        is_skip = (driver in SKIP_DRIVERS) or bool(SKIP_NAME_RE.match(cid))

        cards.append({
            "index": idx,
            "id": cid,
            "driver": driver,
            "description": desc,
            "longname": longname,
            "usb_path": _udev_path_for(idx),
            "is_usb_audio": is_usb_audio,
            "is_skip": is_skip,
        })
    return cards


def annotate_configured_amps(cards: Iterable[dict], configured_amps: dict) -> list[dict]:
    """Tag cards as configured (matches an amp_id) or candidate (not yet)."""
    result = []
    for c in cards:
        d = dict(c)
        d["configured_as"] = c["id"] if c["id"] in configured_amps else None
        result.append(d)
    return result


def find_card_for_amp(cards: Iterable[dict], amp_id: str) -> dict | None:
    for c in cards:
        if c.get("id") == amp_id:
            return c
    return None
