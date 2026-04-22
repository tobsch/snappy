# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Multiroom Audio Tooling - provides the **ALSA configuration layer** for multi-channel USB audio amplifiers. This tooling identifies speakers, maps them to rooms, and generates ALSA PCM devices that audio servers can use for playback.

**Primary use case**: Configuration layer for [lox-audioserver](https://github.com/lox-audioserver/lox-audioserver), which handles multiroom audio streaming, Spotify/AirPlay integration, and Loxone home automation. The sendspin clients connect to lox-audioserver and play audio through the ALSA devices configured by this tooling.

**Legacy/Optional**: Snapcast support is retained for standalone multiroom setups without Loxone integration.

Originally built for Wondom GAB8 amplifiers but works with any multi-channel USB audio device.

## Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                         Loxone Miniserver                           │
│                    (Home automation control)                        │
└─────────────────────────────────────────────────────────────────────┘
                                   │
                                   ▼
┌─────────────────────────────────────────────────────────────────────┐
│                        lox-audioserver                              │
│              (Docker container on this machine)                     │
│  - Bridges Loxone ↔ Audio                                           │
│  - Spotify Connect, AirPlay, TuneIn                                 │
│  - Zone/room management                                             │
│  - Relay control for amplifier power (via crelay)                   │
│  - Sendspin server (ws://localhost:7090/sendspin)                   │
└─────────────────────────────────────────────────────────────────────┘
                                   │
                    WebSocket connections
                                   │
                                   ▼
┌─────────────────────────────────────────────────────────────────────┐
│                    sendspin clients (per room)                      │
│         sendspin@room_kitchen, sendspin@room_living, etc.           │
│              Receives audio stream, plays to ALSA device            │
└─────────────────────────────────────────────────────────────────────┘
                                   │
                          ALSA PCM devices
                                   │
                                   ▼
┌─────────────────────────────────────────────────────────────────────┐
│              ALSA Configuration (this tooling provides)             │
│  - room_<name> devices (stereo, routed to correct amp channels)     │
│  - Per-speaker volume control via ttable                            │
│  - Cross-device stereo pairs supported                              │
└─────────────────────────────────────────────────────────────────────┘
                                   │
                                   ▼
┌─────────────────────────────────────────────────────────────────────┐
│                   USB Audio Amplifiers                              │
│               (Wondom GAB8 or similar, amp1/amp2/amp3)              │
│                    Directly connected speakers                      │
└─────────────────────────────────────────────────────────────────────┘
```

### What This Tooling Provides

1. **Speaker identification** (`speaker_identify.py`) - Interactive CLI to map amplifier channels to rooms
2. **ALSA configuration** (`generate_alsa_config.py`) - Generates `/etc/asound.conf` with room PCM devices
3. **Sendspin service templates** (`services/sendspin@.service`) - Systemd services for each room
4. **Web UI** (`webui/`) - Browser interface for testing speakers and managing configuration
5. **udev rules** (`devconfig/`) - Persistent naming for USB amplifiers

### What lox-audioserver Provides

- Multiroom audio streaming (Spotify, AirPlay, TuneIn, line-in)
- Loxone home automation integration
- Zone and group management
- Volume control per zone
- Relay control for amplifier power (replaces powermanager)
- Web admin interface at http://localhost:7090

## Directory Structure

```
├── speaker_identify.py      # Interactive speaker identification via TTS
├── generate_alsa_config.py  # Generates ALSA PCM configuration
├── speaker_config.json      # Speaker/room/zone configuration (v2.0)
├── devconfig/
│   ├── 99-wondom-gab8.rules # udev rules for persistent amp naming
│   ├── 99-amp-volume.rules  # udev rules to restore ALSA mixer on reconnect
│   └── 99-fernseher.rules   # udev rules for TV audio input
├── services/
│   ├── sendspin@.service    # Systemd template for sendspin clients (PRIMARY)
│   ├── amp-volume.service   # Sets ALSA mixer levels to 100% at boot
│   └── snapclient@.service  # Systemd template for snapclients (LEGACY)
├── powermanager/            # LEGACY - being replaced by lox-audioserver
│   ├── powermanager.sh      # Auto relay control based on ALSA activity
│   └── powermanager.service # Systemd service for power manager
├── lox-audioserver/         # Docker setup (not in git, local only)
│   ├── compose.yaml         # Docker compose for lox-audioserver
│   └── data/                # lox-audioserver configuration and data
└── webui/
    ├── app.py               # FastAPI application entry point
    ├── requirements.txt     # Python dependencies
    ├── webui.service        # Systemd service for web interface
    ├── routers/
    │   ├── api.py           # REST API endpoints
    │   └── pages.py         # HTML page routes
    ├── services/
    │   ├── config.py        # Configuration file CRUD operations
    │   ├── audio.py         # TTS and chime playback
    │   └── snapcast.py      # Snapcast JSON-RPC client (legacy)
    ├── templates/           # Jinja2 HTML templates
    └── static/
        ├── css/style.css    # Styling
        ├── js/app.js        # Toast notifications
        └── sounds/          # Test chime sound

# Legacy (Snapcast-based, optional)
├── generate_snapserver_conf.py  # Generates Snapcast server config
└── deploy_config.py             # One-shot deployment for Snapcast setup
```

## Quick Start (lox-audioserver Setup)

### 1. Configure ALSA devices

```bash
# Identify speakers (plays TTS on each channel, prompts for room assignment)
python3 speaker_identify.py

# Generate and install ALSA config
python3 generate_alsa_config.py | sudo tee /etc/asound.conf
```

### 2. Start lox-audioserver

```bash
cd ~/lox-audioserver
sudo docker compose up -d

# Access admin UI at http://localhost:7090
```

### 3. Enable sendspin services

```bash
# Install service template
sudo cp services/sendspin@.service /etc/systemd/system/
sudo systemctl daemon-reload

# Enable for each room
sudo systemctl enable --now sendspin@room_kitchen sendspin@room_living ...
```

### 4. Test playback

```bash
# Direct ALSA test
aplay -D room_kitchen test.wav

# Or trigger playback via Loxone / lox-audioserver web UI
```

## lox-audioserver Configuration

The lox-audioserver runs as a Docker container with:

```yaml
# ~/lox-audioserver/compose.yaml
services:
  loxoneaudioserver:
    container_name: lox-audioserver
    image: ghcr.io/lox-audioserver/lox-audioserver:beta-latest
    restart: unless-stopped
    network_mode: host
    cap_add:
      - SYS_ADMIN
      - DAC_READ_SEARCH
      - SYS_NICE
    security_opt:
      - apparmor=unconfined
    volumes:
      - ./data:/app/data
    devices:
      - /dev/hidraw0:/dev/hidraw0
      - /dev/hidraw1:/dev/hidraw1
      - /dev/hidraw2:/dev/hidraw2
      - /dev/hidraw3:/dev/hidraw3
      - /dev/bus/usb:/dev/bus/usb  # For crelay USB relay control
```

Key ports (all on host network):
- **7090** - Admin web UI and sendspin WebSocket server
- **1704** - Built-in Snapcast-compatible streaming (conflicts with standalone snapserver)

### Relay Control

lox-audioserver has crelay built-in for amplifier power control. The USB relay device is passed through to the container. Configure relay behavior in the lox-audioserver web UI.

Note: The relay uses inverted logic (NC wiring) - relay ON = amplifiers OFF. Consider rewiring to NO terminals for intuitive control.

## Configuration File (v2.0)

The config file `speaker_config.json` defines the ALSA layer:

```json
{
  "version": "2.0",
  "global": { "max_volume": 0.25 },
  "amplifiers": { "amp1": { "card": "amp1", "channels": 8 } },
  "speakers": {
    "kitchen_left": { "amplifier": "amp1", "channel": 3, "volume": 100 },
    "kitchen_right": { "amplifier": "amp1", "channel": 4, "volume": 100 }
  },
  "rooms": {
    "kitchen": { "name": "Kitchen", "left": "kitchen_left", "right": "kitchen_right" }
  },
  "zones": { ... }  // Used by legacy Snapcast setup
}
```

The zones and Snapcast-related config are ignored when using lox-audioserver (zones are managed in lox-audioserver instead).

## Web Interface

The web UI at http://localhost:8080 provides:

- **Dashboard** - Overview of rooms and amplifiers
- **Amplifiers** - Test individual channels (chime or TTS)
- **Rooms** - Test left/right/stereo, adjust per-speaker volume
- **Settings** - Relay control, service status, deploy configuration

Note: Playback and Zones pages are Snapcast-specific (legacy).

## Commands

```bash
# Speaker identification
python3 speaker_identify.py
python3 speaker_identify.py --all  # Re-announce all channels

# Generate ALSA config
python3 generate_alsa_config.py > asound.conf
sudo cp asound.conf /etc/asound.conf

# Test room playback
aplay -D room_kitchen test.wav

# Sendspin management
sudo systemctl status 'sendspin@*'
journalctl -u 'sendspin@room_kitchen' -f

# lox-audioserver management
sudo docker logs lox-audioserver -f
sudo docker restart lox-audioserver

# Relay control (from host)
crelay -i          # Show relay status
crelay 1 on        # Relay on (amps OFF with NC wiring)
crelay 1 off       # Relay off (amps ON with NC wiring)
```

## Key Design Considerations

- **ALSA device naming**: Room devices use `room_<name>` prefix. Cross-device stereo pairs use `speaker_<room>_left/right` to avoid sendspin's prefix matching issues.
- **Persistent device naming**: udev rules in `devconfig/` rename USB amps to `amp1`/`amp2`/`amp3` based on USB port path.
- **ALSA mixer persistence**: udev rule `99-amp-volume.rules` restores mixer levels when amps reconnect after power cycle.
- **Volume control**: `max_volume` in config limits ALSA ttable coefficient. Per-speaker volume is percentage of max.
- **Cross-device stereo**: Left speaker on amp1, right on amp2 - handled by ALSA multi plugin.

### Current Amp-to-USB Mapping (as of 2026-04)

| Amp   | USB Path                              | Primary Rooms |
|-------|---------------------------------------|---------------|
| amp1  | platform-xhci-hcd.1-usb-0:2:1.1       | Küche         |
| amp2  | platform-xhci-hcd.0-usb-0:1:1.1       | Wohnzimmer, Esszimmer |
| amp3  | platform-xhci-hcd.0-usb-0:2:1.1       | Backupküche, others |

To identify which amp is which, play a test tone on a specific channel:
```bash
speaker-test -D plughw:amp1 -c 8 -t sine -s 5  # Channel 5 on amp1
```

## Prerequisites

- Python 3
- ALSA utilities (`aplay`, `speaker-test`, `amixer`, `alsactl`)
- `espeak-ng` for TTS during speaker identification
- Multi-channel USB audio amplifiers
- Docker for lox-audioserver
- `sendspin` (`pip install --user --break-system-packages sendspin`)
  - Current version: 5.9.0 (as of 2026-04)
  - Upgrade: `pip install --user --break-system-packages --upgrade sendspin aiosendspin`
- `libportaudio2` for sendspin audio output
- `crelay` for USB relay control (optional, can use lox-audioserver's built-in)

## Troubleshooting

### No audio playing

1. Check sendspin connection: `journalctl -u 'sendspin@room_*' -f`
2. Check lox-audioserver: `sudo docker logs lox-audioserver`
3. Test direct ALSA: `speaker-test -D room_kitchen -c 2 -t sine`
4. Check ALSA mixer levels: `amixer -c amp1 sget PCM` (should be 100%)
5. Check relay/amplifier power: `crelay -i`

### Sendspin connection errors

```
WARNING:sendspin.daemon.daemon:Connection error (ClientConnectorError)
```

- Verify lox-audioserver is running: `sudo docker ps | grep lox`
- Check port 7090 is listening: `ss -tlnp | grep 7090`
- Restart lox-audioserver: `sudo docker restart lox-audioserver`

### Loud noise or distortion from speakers

This usually happens after lox-audioserver restarts while sendspin is playing:
```bash
# Restart the affected sendspin service to clear corrupted audio state
sudo systemctl restart sendspin@room_kueche
```

### ALSA mixer resets after power cycle

The `amp-volume.service` sets mixer levels to 100% at boot. If levels reset:
```bash
# Check service status
sudo systemctl status amp-volume.service

# Manually set mixer levels
amixer -c amp1 sset PCM 100%
amixer -c amp2 sset PCM 100%
amixer -c amp3 sset PCM 100%
```

Note: Do NOT use `alsactl restore` as it may restore old/incorrect levels.

### Amplifiers not detected or wrong names

If amps show up with wrong names after reconnection:
```bash
# Check current ALSA cards
cat /proc/asound/cards

# Verify udev rules
cat /etc/udev/rules.d/99-wondom-gab8.rules

# Test which amp is which by playing on specific channel
speaker-test -D plughw:amp1 -c 8 -t sine -s 5  # Plays on channel 5
```

### Identifying USB paths for udev rules

When amps are reconnected to different USB ports:
```bash
# Find USB path for each GAB8 amp
for card in /sys/class/sound/card*; do
  name=$(cat "$card/id" 2>/dev/null)
  if [[ "$name" == GAB8* ]]; then
    path=$(udevadm info -q property "$card" | grep ID_PATH= | cut -d= -f2)
    echo "$name: $path"
  fi
done
```

## Known Issues & Workarounds

### lox-audioserver resets zone volumes to 10% (or 30%)

**Issue**: When Loxone Miniserver connects to lox-audioserver, all zone volumes reset to default (10% in older versions, 30% in newer).

**Root cause**: In `loxoneConfigService.js`, the `extractZonesFromPayload()` function completely replaces all zones with freshly built ones using `defaultVolumes()`:
```javascript
cfg.zones = buildZoneConfigs(descriptors);  // Replaces all zones!
```

This happens on every Miniserver connection, not just startup. Editing `config.json` directly doesn't help because it gets overwritten.

**Status**: Reported as GitHub issue #219. The fix requires lox-audioserver to MERGE existing zone settings instead of replacing them.

**Workaround**: Currently none that persists. Volume must be set via Loxone or the lox-audioserver web UI after each reconnection.

### ALSA mixer levels reset to ~57% after amp power cycle

**Issue**: When amplifiers power off and back on, ALSA mixer levels reset to a default (~57%).

**Solution**: Created `amp-volume.service` that runs at boot with a delay:
```bash
# Install the service
sudo cp services/amp-volume.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable amp-volume.service
```

**Important**: Do NOT use `alsactl restore` in udev rules - it can restore incorrect levels.

### speaker_config.json volume settings

Volume values in `speaker_config.json` are percentages (0-100) of the `global.max_volume` setting:
- `max_volume: 0.25` means 25% of full scale is the maximum
- Speaker `volume: 100` means 100% of that max (so 25% actual)
- Speaker `volume: 50` means 50% of that max (so 12.5% actual)

For full volume output, set speaker volumes to 100 and adjust `max_volume` as needed.

## Legacy: Snapcast Setup

For standalone multiroom without Loxone, Snapcast can still be used:

```bash
# Generate Snapcast config
python3 generate_snapserver_conf.py > snapserver.conf
sudo cp snapserver.conf /etc/snapserver.conf

# Enable services (uses port 1714 to avoid lox-audioserver conflict)
sudo systemctl enable --now snapserver
sudo systemctl enable --now snapclient@room_kitchen ...

# Re-enable with:
sudo systemctl enable --now snapserver 'snapclient@room_*'
```

Note: If running alongside lox-audioserver, snapserver uses port 1714 (configured in `/etc/snapserver.conf` under `[stream]` section).
