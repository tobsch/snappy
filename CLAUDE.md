# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Multiroom Audio Tooling - identifies and configures speakers connected to multi-channel USB audio amplifiers and generates ALSA and Snapcast configuration for multiroom audio playback. Originally built for Wondom GAB8 amplifiers but works with any multi-channel USB audio device.

## Directory Structure

```
├── speaker_identify.py      # Interactive speaker identification via TTS
├── generate_alsa_config.py  # Generates ALSA PCM configuration
├── generate_snapserver_conf.py  # Generates Snapcast server config
├── deploy_config.py         # One-shot deployment (ALSA + Snapcast + API config)
├── speaker_config.json      # Speaker/room/zone configuration (v2.0)
├── devconfig/
│   ├── 99-wondom-gab8.rules # Example udev rules for persistent amp naming
│   └── 99-fernseher.rules   # udev rules for TV audio input
├── services/
│   ├── snapclient@.service  # Systemd template for per-room snapclients (local)
│   └── sendspin@.service    # Systemd template for per-room sendspin clients (remote)
└── powermanager/
    ├── powermanager.sh      # Auto relay control based on ALSA activity
    └── powermanager.service # Systemd service for power manager
```

## Commands

```bash
# Identify speakers interactively (plays TTS announcements, prompts for room/position/zones)
python3 speaker_identify.py
python3 speaker_identify.py --all        # Re-announce all channels including mapped ones

# Generate ALSA configuration from speaker_config.json
python3 generate_alsa_config.py > asound.conf

# Generate Snapcast server configuration
python3 generate_snapserver_conf.py > snapserver.conf

# Deploy everything in one go (ALSA config, Snapcast config, restart, configure groups)
python3 deploy_config.py

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
  "global": { "max_volume": 0.25 },
  "amplifiers": { "amp1": { "card": "amp1", "channels": 8 } },
  "inputs": { "fernseher": { "card": "fernseher", "channels": 1, "sampleformat": "48000:16:1", "name": "Fernseher" } },
  "speakers": { "room_left": { "amplifier": "amp1", "channel": 3, "volume": 100, "latency": 0 } },
  "rooms": { "room": { "name": "Room", "left": "room_left", "right": "room_right", "zones": ["zone1"] } },
  "zones": { "zone1": { "name": "Zone 1" }, "alle": { "name": "All", "include_all": true } },
  "snapcast": {
    "server": "localhost",
    "streams": {
      "spotify": { "type": "librespot", "name": "Spotify", "bitrate": 320 },
      "fernseher": { "type": "alsa", "input": "fernseher" }
    },
    "stream_targets": { "spotify": { "zones": ["alle"] } }
  }
}
```

### Global Settings

- `max_volume`: ALSA ttable coefficient (0.0-1.0) that limits maximum output volume. Default is 0.25 (25%, -12dB). Higher values = louder max volume.

### Inputs

Audio inputs (capture devices) for use as Snapcast stream sources:
- `card`: ALSA card name (should match udev-assigned name)
- `channels`: Number of input channels (1 for mono, 2 for stereo)
- `sampleformat`: Capture format (e.g., "48000:16:1" for 48kHz 16-bit mono)
- `name`: Display name in Snapcast

Reference inputs in streams with `"type": "alsa", "input": "input_id"`.

## Architecture

Three-stage workflow:
1. **speaker_identify.py** - Interactive CLI that plays TTS announcements (via espeak-ng) on each amplifier channel, prompts user for room name, left/right position, and zone assignments. Saves mappings to `speaker_config.json`. Progress is saved incrementally and can be resumed.
2. **generate_alsa_config.py** - Reads config, outputs ALSA config with base amplifier PCMs (`amp1`, `amp2`, etc.), room PCMs (`room_<name>`), and combined `all_rooms` device. Zones are handled by Snapcast, not ALSA.
3. **generate_snapserver_conf.py** - Reads config, outputs Snapcast server configuration with multiple stream sources (Spotify, AirPlay, pipe, etc.)

### Services

- **services/snapclient@.service** - Systemd template service for Snapcast clients connecting to the **local** snapserver. Instance name (`%i`) is the room ALSA device (e.g., `snapclient@room_kitchen.service`). Each room gets its own snapclient instance. Connects to `localhost:1704`.

- **services/sendspin@.service** - Systemd template service for Sendspin clients connecting to the **remote** Lox audioserver. Instance name (`%i`) is the room ALSA device (e.g., `sendspin@room_kitchen.service`). Each room gets its own sendspin instance. Connects to `ws://192.168.0.235:7090/sendspin`.

Both services run in parallel for each room, allowing audio from either the local snapserver or the remote Lox audioserver.

- **powermanager/** - Automatic amplifier power control via USB relay:
  - Monitors ALSA card activity by checking `/proc/asound/cardX/pcm*/sub*/status`
  - Turns relay ON immediately when audio starts playing
  - Turns relay OFF after configurable idle timeout (default: 5 minutes)
  - Requires `crelay` tool for USB relay control

### deploy_config.py

One-shot deployment script that:
1. Generates and installs ALSA config to `/etc/asound.conf`
2. Generates and installs Snapcast config to `/etc/snapserver.conf`
3. Installs service templates (snapclient@.service, sendspin@.service)
4. Restarts snapserver
5. Enables and restarts snapclient and sendspin services for all rooms
6. Waits for snapclients to connect (30s timeout)
7. Configures Snapcast groups via JSON-RPC API (port 1705)

The script uses `stream_targets` from `speaker_config.json` to assign rooms to streams based on zone membership. Requires sudo access.

### Key Design Considerations

- Supports cross-device stereo pairs (left speaker on amp1, right on amp2) using ALSA multi plugin
- Channel indices: 1-based in config JSON, converted to 0-based for ALSA ttable
- **Persistent device naming**: Example udev rules in `devconfig/` show how to rename USB audio devices to `amp1`/`amp2`/`amp3` based on USB port path. Users must adapt these for their specific devices. The names are bound to USB ports, not physical units - label your cables/ports.
- **ALSA device naming to avoid prefix collisions**: Cross-device rooms create individual speaker devices named `speaker_{room}_left` and `speaker_{room}_right` (not `room_{room}_left`) to avoid prefix-matching issues with sendspin. Sendspin uses `startswith()` for device matching, so `room_esszimmer` would incorrectly match `room_esszimmer_left`. Using `speaker_` prefix prevents this.
- Rooms can belong to multiple zones (tag-based, not hierarchical)
- Multiple Spotify/AirPlay streams supported (each appears as separate device)
- TTS announcements require pre-configured per-channel ALSA devices (`amp1_ch1` through `amp*_ch8`)

## Prerequisites

- Python 3
- ALSA utilities (`aplay`, `speaker-test`)
- `espeak-ng` for TTS during speaker identification
- Multi-channel USB audio amplifiers with per-channel ALSA routing pre-configured
- Snapcast server and client (`snapserver`, `snapclient`) for multiroom streaming
- `sendspin` for Lox audioserver integration (`pip install sendspin` + `apt install libportaudio2`)
- Optional: `librespot` for Spotify Connect
- Optional: `shairport-sync` compiled from source with `--with-airplay-2` for AirPlay 2 support
- Optional: `crelay` for automatic amplifier power management via USB relay

## Troubleshooting

### No audio playing / audio too quiet
1. **Check if amplifiers are powered on** - The powermanager controls a USB relay that powers the amplifiers. If the relay is off, no audio will play even if everything else is working. Check with `crelay` or look at relay status.
2. **Check amplifier mixer levels** - Each amp has its own PCM volume: `amixer -c amp1 sget PCM`. Set to 100% with `amixer -c amp1 sset PCM 100%` and save with `sudo alsactl store`.
3. Check snapclient logs: `journalctl -u 'snapclient@room_*' -f`
4. Test direct ALSA playback: `speaker-test -D room_<name>_raw -c 2 -t sine`
5. Check Snapcast group assignments and stream status

### Snapclient configuration
The snapclient service uses `--sampleformat 48000:16:*` because:
- Many USB amplifiers (including Wondom GAB8) operate at 48kHz
- Spotify streams at 44.1kHz and needs resampling to 48kHz
- The `*` for channels is required by snapclient (must match source)

Do NOT add `buffer_time` parameter - it's interpreted as milliseconds and causes massive buffer issues (e.g., `buffer_time=80000` = 80 seconds, not 80ms).

### Librespot cache corruption
If Spotify streams show "playing" status but snapclients report "No chunks available" or you see these errors in `journalctl -u snapserver`:
```
(librespot_core::audio_key) Audio key response timeout
(librespot_playback::player) Unable to load key, continuing without decryption
(librespot_playback::player) Unable to read audio file: Symphonia Decoder Error: end of stream
```

The librespot cache is likely corrupted. Fix by clearing the cache for the affected stream:
```bash
# For spotify_wohnen stream:
sudo rm -rf /var/cache/snapserver/librespot-spotify_wohnen/*

# For spotify_kueche stream:
sudo rm -rf /var/cache/snapserver/librespot-spotify_kueche/*

# Then restart snapserver
sudo systemctl restart snapserver
```

After restart, you'll need to re-select the Spotify device in your Spotify app and reassign stream targets (run `deploy_config.py` or use the JSON-RPC API).

### Sendspin issues
Check sendspin logs: `journalctl -u 'sendspin@room_*' -f`

If sendspin fails to start with "PortAudio library not found":
```bash
sudo apt-get install libportaudio2
```

If sendspin can't connect to the Lox audioserver:
1. Verify the server is reachable: `nc -zv 192.168.0.235 7090`
2. Check the WebSocket URL in `services/sendspin@.service`
3. Restart the service: `sudo systemctl restart sendspin@room_<name>.service`

**Sendspin device matching**: Sendspin uses prefix matching (`startswith()`) for audio device selection. This is why cross-device speaker devices use `speaker_` prefix instead of `room_` - to avoid `room_esszimmer` matching `room_esszimmer_left`. With correct ALSA naming, parallel startup works reliably.

### Powermanager not turning off amps

If amplifiers stay powered on even when no audio is playing, check for stale ALSA streams:

```bash
cat /proc/asound/amp1/pcm0p/sub0/status
```

A stale stream (e.g., from sendspin keeping the device open after audio ends) shows:
- `state: RUNNING` but no actual audio
- `avail_max` in the millions (e.g., 138,000,000+)
- `delay` massively negative (e.g., -138,000,000)

Real audio playback shows:
- `avail_max` around 40,000-65,000 (normal buffer size)
- `delay` small or moderately negative

The powermanager uses `avail_max < 1,000,000` as the threshold to distinguish real audio from stale streams. This threshold equals ~20 seconds of staleness at 48kHz sample rate.