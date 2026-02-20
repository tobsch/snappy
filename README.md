# Multiroom Audio Tooling

# Opinionated multiroom speaker tooling

* Tools to identify and configure speakers connected to your USB amps.
* Generator for ALSA configuration for stereo room-based playback
* Generator for Snapcast server configuration for multiroom streaming & matching clients
* Power manager to turn on and off amps via Relays

## About This Project

I built a house with a custom multiroom audio system: a Raspberry Pi 5 connected to three Wondom GAB8 8-channel USB amplifiers, driving 24 speaker channels throughout the house.

The problem? After running speaker cables to every room and connecting them to the amplifiers, I had no idea which speaker was connected to which amplifier channel. Walking around the house with a laptop, playing test tones, and manually noting down "amp2 channel 5 = kitchen left" for 24 speakers is tedious and error-prone.

What started as a simple speaker identification tool grew from there: I needed ALSA configuration to combine mono channels into stereo room pairs (sometimes across different amplifiers), Snapcast configuration for multiroom streaming with per-room Spotify and AirPlay endpoints, persistent USB device naming so configurations survive reboots, and automatic power management to switch off the amplifiers when idle.

This tooling handles all of that: interactive speaker identification with spoken announcements, automatic generation of ALSA and Snapcast configs, one-shot deployment, and relay-based power management.

While originally built for Wondom GAB8 amplifiers, the tool is device-agnostic and works with any multi-channel USB audio device that exposes individual channels via ALSA.[^1]

[^1]: This project was developed with the assistance of [Claude](https://claude.ai), Anthropic's AI assistant, using [Claude Code](https://claude.ai/code).

## Requirements

- Python 3
- ALSA utilities (`aplay`, `speaker-test`)
- `espeak-ng` for TTS announcements during identification (`sudo apt install espeak-ng`)
- Multi-channel USB audio amplifiers with per-channel ALSA routing pre-configured (`amp1_ch1` through `amp*_ch8`)
- Snapcast server and client (`snapserver`, `snapclient`) for multiroom streaming
- Optional: `librespot` for Spotify Connect
- Optional: `crelay` for automatic amplifier power management via USB relay

### AirPlay 2 Support

For AirPlay 2 support, `shairport-sync` must be compiled from source with AirPlay 2 enabled (not available in standard packages):

```bash
# Install dependencies
sudo apt install build-essential git autoconf automake libtool \
    libpopt-dev libconfig-dev libasound2-dev avahi-daemon libavahi-client-dev \
    libssl-dev libsoxr-dev libplist-dev libsodium-dev libavutil-dev \
    libavcodec-dev libavformat-dev uuid-dev libgcrypt-dev xxd

# Clone and build
git clone https://github.com/mikebrady/shairport-sync.git
cd shairport-sync
autoreconf -fi
./configure --sysconfdir=/etc --with-alsa --with-soxr --with-avahi \
    --with-ssl=openssl --with-metadata --with-airplay-2 --with-stdout
make
sudo make install
```

## Persistent Device Naming (udev)

By default, USB audio devices get names based on enumeration order, which can change between reboots or when devices are reconnected. This project includes example udev rules to assign persistent names (`amp1`, `amp2`, `amp3`) based on USB port path.

### Customizing for Your Setup

The included `devconfig/99-wondom-gab8.rules` is an example for Wondom GAB8 amplifiers on a Raspberry Pi 5. You'll need to adapt it for your specific devices.

1. Find your device's current ALSA ID and USB path:

```bash
# List current ALSA cards
cat /proc/asound/cards

# Get the USB path for a specific card (replace controlC2 with your card)
udevadm info -q all /dev/snd/controlC2 | grep -E "^E: (ID_PATH|ID_MODEL)="
```

2. Create udev rules matching your devices. Example structure:

```bash
# Match by device model/ID and USB path, assign persistent name
SUBSYSTEM=="sound", ATTR{id}=="YourDeviceID*", ENV{ID_PATH}=="your-usb-path", ATTR{id}="amp1"
```

3. Install and activate:

```bash
sudo cp devconfig/your-rules-file.rules /etc/udev/rules.d/
sudo udevadm control --reload-rules && sudo udevadm trigger

# Verify the new names
cat /proc/asound/cards
```

**Important:** The names are bound to USB ports, not to physical amplifier units. If you move an amplifier to a different USB port, you'll need to update the udev rules to match. Label your USB ports or cables to keep track.

## Usage

### 1. Identify Speakers

```bash
python3 speaker_identify.py
```

The tool will:
- Detect all configured amplifiers from `speaker_config.json`
- Play a TTS announcement on each channel (e.g., "Verstärker 1, Kanal 3")
- Prompt you for the room name, position (left/right), and zone assignments
- Save progress incrementally (can be resumed if interrupted)

Commands during identification:
- Enter a room name (e.g., `living room`, `kitchen`)
- Press Enter or type `skip` - Skip unused channels
- `quit` - Save progress and exit

CLI options:
- `--announce-rooms` / `-r` - Announce existing room names instead of amplifier/channel
- `--all` / `-a` - Re-announce all channels, including those already mapped

### 2. Generate ALSA Configuration

```bash
python3 generate_alsa_config.py > asound.conf
```

Review the generated config, then install:

```bash
sudo cp asound.conf /etc/asound.conf
```

### 3. Generate Snapcast Configuration

```bash
python3 generate_snapserver_conf.py > snapserver.conf
sudo cp snapserver.conf /etc/snapserver.conf
sudo systemctl restart snapserver
```

### 4. Install Snapcast Client Services

Install the systemd template service for snapcast clients:

```bash
sudo cp services/snapclient@.service /etc/systemd/system/
sudo systemctl daemon-reload
```

Enable and start a client for each room:

```bash
# Enable clients for all configured rooms
for room in $(python3 -c "import json; print(' '.join(json.load(open('speaker_config.json'))['rooms'].keys()))"); do
    sudo systemctl enable --now snapclient@room_${room}.service
done

# Or enable individual rooms manually
sudo systemctl enable --now snapclient@room_living_room.service
sudo systemctl enable --now snapclient@room_kitchen.service
```

Check client status:

```bash
systemctl status 'snapclient@*'
```

### 5. Install Amplifier Power Manager (Optional)

The `powermanager/` folder contains a service that automatically switches the amplifier on/off via a USB relay based on ALSA activity. This saves power when no audio is playing.

**Requirements:**
- USB relay controlled via `crelay` (e.g., Conrad/Sainsmart USB relay board)
- Install crelay: https://github.com/ondrej1024/crelay

**How it works:**
- Monitors `/proc/asound/cardX/pcm*/sub*/status` for RUNNING state
- Turns relay ON immediately when audio starts
- Turns relay OFF after 5 minutes (300s) of inactivity
- Polls every 50ms for responsive switching

**Installation:**

```bash
# Install the script
sudo cp powermanager/powermanager.sh /usr/local/bin/
sudo chmod +x /usr/local/bin/powermanager.sh

# Edit the script to match your setup
sudo nano /usr/local/bin/powermanager.sh
# - CARDS: ALSA card numbers to monitor (check with: cat /proc/asound/cards)
# - RELAY_ON_CMD / RELAY_OFF_CMD: commands for your relay
# - IDLE_TIMEOUT: seconds before power off (default: 300)

# Install and enable the service
sudo cp powermanager/powermanager.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now powermanager.service
```

Check status and logs:

```bash
systemctl status powermanager
journalctl -u powermanager -f
```

### 6. Test Playback

```bash
aplay -D room_living_room test.wav
aplay -D room_kitchen test.wav
aplay -D all_rooms test.wav  # Play to all speakers
```

## Configuration Format (v2.0)

Speaker mappings are stored in `speaker_config.json`:

```json
{
  "version": "2.0",
  "amplifiers": {
    "amp1": { "card": "amp1", "channels": 8 },
    "amp2": { "card": "amp2", "channels": 8 }
  },
  "speakers": {
    "living_room_left": { "amplifier": "amp1", "channel": 1, "volume": 100, "latency": 0 },
    "living_room_right": { "amplifier": "amp1", "channel": 2, "volume": 100, "latency": 0 },
    "kitchen_left": { "amplifier": "amp2", "channel": 3, "volume": 100, "latency": 0 },
    "kitchen_right": { "amplifier": "amp2", "channel": 4, "volume": 100, "latency": 0 }
  },
  "rooms": {
    "living_room": {
      "name": "Living Room",
      "left": "living_room_left",
      "right": "living_room_right",
      "zones": ["eg", "main"]
    },
    "kitchen": {
      "name": "Kitchen",
      "left": "kitchen_left",
      "right": "kitchen_right",
      "zones": ["eg"]
    }
  },
  "zones": {
    "eg": { "name": "Erdgeschoss" },
    "main": { "name": "Main Rooms" },
    "alle": { "name": "Überall", "include_all": true }
  },
  "snapcast": {
    "server": "localhost",
    "streams": {
      "spotify": { "type": "librespot", "name": "Spotify", "bitrate": 320 },
      "airplay": { "type": "airplay", "name": "AirPlay", "port": 7000 },
      "default": { "type": "pipe", "path": "/tmp/snapfifo", "sampleformat": "48000:16:2" }
    },
    "stream_targets": {
      "spotify": { "zones": ["alle"] },
      "airplay": { "zones": ["eg"] }
    }
  }
}
```

## Generated ALSA Devices

| Device | Description |
|--------|-------------|
| `amp1`, `amp2`, ... | Base amplifier PCM (hw access) |
| `room_<name>` | Stereo output for a specific room |
| `all_rooms` | Combined stereo output to all configured speakers |

## Cross-Device Stereo

The tool handles stereo pairs split across different amplifiers. For example, if your kitchen left speaker is on `amp2` and right speaker is on `amp3`, the generator creates a multi-device ALSA configuration that combines them into a single stereo `room_kitchen` device.

## Zones

Rooms can belong to multiple zones (tag-based, not hierarchical). Zones are used by Snapcast to group rooms for streaming - they are not managed by ALSA. The special zone `alle` with `include_all: true` automatically includes all rooms.

## Web Interface

A browser-based interface for managing the multiroom audio system. Built with FastAPI, HTMX, and Jinja2.

### Setup

```bash
cd webui
python3 -m venv venv
./venv/bin/pip install -r requirements.txt
```

### Running

**Development (with auto-reload):**
```bash
cd webui
./venv/bin/uvicorn app:app --host 0.0.0.0 --port 8080 --reload
```

**Production (systemd):**
```bash
sudo cp webui/webui.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now webui
```

Access at `http://<hostname>:8080`

### Features

| Page | Description |
|------|-------------|
| **Dashboard** | Overview of rooms, zones, streams, amplifiers with quick test buttons |
| **Amplifiers** | View all amplifier channels, see room assignments, test individual channels (chime or TTS) |
| **Rooms** | Manage rooms, adjust per-speaker volume, test left/right/stereo |
| **Zones & Streams** | Create/delete zones, assign rooms to zones, toggle Spotify/AirPlay per zone |
| **Playback** | View Snapcast status (streams, groups, connected clients) |
| **Settings** | Global volume limit, amplifier power control (relay), deploy configuration, service status |

### API

REST API available at `/api/`. Key endpoints:

- `GET /api/config` - Full configuration
- `POST /api/test/channel` - Test amplifier channel (chime/TTS)
- `POST /api/test/room` - Test room playback
- `POST /api/deploy` - Deploy configuration
- `GET /api/system/powermanager` - Relay state and audio activity
- `POST /api/system/relay` - Control amplifier power
- `GET /api/snapcast/status` - Snapcast server status
