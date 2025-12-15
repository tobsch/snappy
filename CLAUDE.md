# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Wondom Speaker Identification Tool - identifies and configures speakers connected to Wondom GAB8 USB audio devices and generates ALSA and Snapcast configuration for multiroom audio playback.

## Directory Structure

```
testtool/
├── speaker_identify.py      # Interactive speaker identification via TTS
├── generate_alsa_config.py  # Generates ALSA PCM configuration
├── generate_snapserver_conf.py  # Generates Snapcast server config
├── speaker_config.json      # Speaker/room/zone configuration (v2.0)
├── services/
│   └── snapclient@.service  # Systemd template for per-room snapclients
└── powermanager/
    ├── powermanager.sh      # Auto relay control based on ALSA activity
    └── powermanager.service # Systemd service for power manager
```

## Commands

```bash
# Identify speakers interactively (plays TTS announcements, prompts for room/position/zones)
python3 speaker_identify.py
python3 speaker_identify.py --all        # Re-announce all channels including mapped ones
python3 speaker_identify.py --announce-rooms  # Announce room names instead of amp/channel

# Generate ALSA configuration from speaker_config.json
python3 generate_alsa_config.py > wondom_rooms.conf

# Generate Snapcast server configuration
python3 generate_snapserver_conf.py > snapserver.conf

# Test playback to a room
aplay -D room_<roomname> test.wav

# Test playback to all rooms
aplay -D all_rooms test.wav
```

## Configuration File (v2.0)

The config file is stored at `speaker_config.json` (in this tool directory).

### Structure

```json
{
  "version": "2.0",
  "amplifiers": { "amp1": { "card": "GAB8", "channels": 8 } },
  "speakers": { "room_left": { "amplifier": "amp1", "channel": 3, "volume": 100, "latency": 0 } },
  "rooms": { "room": { "name": "Room", "left": "room_left", "right": "room_right", "zones": ["zone1"] } },
  "zones": { "zone1": { "name": "Zone 1" }, "alle": { "name": "All", "include_all": true } },
  "snapcast": {
    "server": "localhost",
    "streams": { "spotify": { "type": "librespot", "name": "Spotify", "bitrate": 320 } },
    "stream_targets": { "spotify": { "zones": ["alle"] } }
  }
}
```

## Architecture

Three-stage workflow:
1. **speaker_identify.py** - Interactive CLI that plays German TTS announcements (via espeak-ng) on each GAB8 channel, prompts user for room name, left/right position, and zone assignments. Saves mappings to `speaker_config.json`. Progress is saved incrementally and can be resumed.
2. **generate_alsa_config.py** - Reads config, outputs ALSA config with base amplifier PCMs (`amp1`, `amp2`, etc.), room PCMs (`room_<name>`), and combined `all_rooms` device. Zones are handled by Snapcast, not ALSA.
3. **generate_snapserver_conf.py** - Reads config, outputs Snapcast server configuration with multiple stream sources (Spotify, AirPlay, pipe, etc.)

### Services

- **services/snapclient@.service** - Systemd template service for Snapcast clients. Instance name (`%i`) is the room ALSA device (e.g., `snapclient@room_kitchen.service`). Each room gets its own snapclient instance.

- **powermanager/** - Automatic amplifier power control via USB relay:
  - Monitors ALSA card activity by checking `/proc/asound/cardX/pcm*/sub*/status`
  - Turns relay ON immediately when audio starts playing
  - Turns relay OFF after configurable idle timeout (default: 5 minutes)
  - Requires `crelay` tool for USB relay control

### Key Design Considerations

- Supports cross-device stereo pairs (left speaker on amp1, right on amp2) using ALSA multi plugin
- Channel indices: 1-based in config JSON, converted to 0-based for ALSA ttable
- Device naming convention: `amp1`/`amp2`/`amp3` map to `GAB8`/`GAB8_1`/`GAB8_2` ALSA cards
- Rooms can belong to multiple zones (tag-based, not hierarchical)
- Multiple Spotify/AirPlay streams supported (each appears as separate device)
- TTS announcements require pre-configured per-channel ALSA devices (`amp1_ch1` through `amp*_ch8`)

## Prerequisites

- Python 3
- ALSA utilities (`aplay`, `speaker-test`)
- `espeak-ng` for German TTS during speaker identification
- Wondom GAB8 USB audio devices with per-channel ALSA routing pre-configured
- Snapcast server and client (`snapserver`, `snapclient`) for multiroom streaming
- Optional: `librespot` for Spotify Connect
- Optional: `shairport-sync` compiled from source with `--with-airplay-2` for AirPlay 2 support
- Optional: `crelay` for automatic amplifier power management via USB relay
