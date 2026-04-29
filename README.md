# Multiroom Audio Tooling

# Opinionated multiroom speaker tooling

* Tools to identify and configure speakers connected to your USB amps.
* Generator for ALSA configuration for stereo room-based playback
* Sendspin service templates for lox-audioserver integration
* Per-amp GPIO power management based on audio activity
* Web interface for testing and configuration

## About This Project

I built a house with a custom multiroom audio system: a Raspberry Pi 5 connected to three Wondom GAB8 8-channel USB amplifiers, driving 24 speaker channels throughout the house.

The problem? After running speaker cables to every room and connecting them to the amplifiers, I had no idea which speaker was connected to which amplifier channel. Walking around the house with a laptop, playing test tones, and manually noting down "amp2 channel 5 = kitchen left" for 24 speakers is tedious and error-prone.

What started as a simple speaker identification tool grew from there: I needed ALSA configuration to combine mono channels into stereo room pairs (sometimes across different amplifiers), persistent USB device naming so configurations survive reboots, and automatic power management to switch off the amplifiers when idle.

This tooling handles all of that: interactive speaker identification with spoken announcements, automatic generation of ALSA configs, sendspin service management for lox-audioserver, and GPIO-based per-amp power management.

While originally built for Wondom GAB8 amplifiers, the tool is device-agnostic and works with any multi-channel USB audio device that exposes individual channels via ALSA.[^1]

[^1]: This project was developed with the assistance of [Claude](https://claude.ai), Anthropic's AI assistant, using [Claude Code](https://claude.ai/code).

## Requirements

- Python 3
- ALSA utilities (`aplay`, `speaker-test`)
- `espeak-ng` for TTS announcements during identification (`sudo apt install espeak-ng`)
- Multi-channel USB audio amplifiers with per-channel ALSA routing pre-configured (`amp1_ch1` through `amp*_ch8`)
- Docker for lox-audioserver
- `sendspin` for lox-audioserver audio playback (`pip install --user --break-system-packages sendspin`)
- `libportaudio2` for sendspin audio output
- `gpiod` for GPIO amplifier power control (`sudo apt install gpiod`)

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

### 3. Enable Sendspin Services

```bash
# Install service template
sudo cp services/sendspin@.service /etc/systemd/system/
sudo systemctl daemon-reload

# Enable for each room
sudo systemctl enable --now sendspin@room_kitchen sendspin@room_living ...
```

Check client status:

```bash
systemctl status 'sendspin@*'
```

### 4. Install Amplifier Power Manager (Optional)

The `powermanager/` folder contains a service that controls each amplifier independently via GPIO SHDN (shutdown) pins. This saves power when no audio is playing while keeping USB/ALSA connections alive.

**Requirements:**
- `gpiod` package for GPIO control
- `ampctl` CLI installed to `/usr/local/bin/` (see `ampctl` in repo)
- GPIO wiring from Pi header to GAB8 SHDN pins

**GPIO Pin Assignment:**

| Amp  | GPIO | Pi Pin |
|------|------|--------|
| amp1 | 27   | 13     |
| amp2 | 22   | 15     |
| amp3 | 17   | 11     |

**How it works:**
- Samples `hw_ptr` twice (0.2s apart) to detect actual audio flow per card
- Enables amp immediately when audio starts
- Disables amp after 60s of inactivity
- Each amp controlled independently (no all-or-nothing relay)

**Installation:**

```bash
# Install the script
sudo cp powermanager/powermanager.sh /usr/local/bin/
sudo chmod +x /usr/local/bin/powermanager.sh

# Install ampctl
sudo cp ampctl /usr/local/bin/
sudo chmod +x /usr/local/bin/ampctl

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

### 5. Test Playback

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

Rooms can belong to multiple zones (tag-based, not hierarchical). Zones are managed in lox-audioserver for streaming purposes. The special zone `alle` with `include_all: true` automatically includes all rooms.

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
| **Dashboard** | Overview of rooms, zones, amplifiers with quick test buttons |
| **Amplifiers** | Per-amp power control, view channel assignments, test individual channels (chime or TTS) |
| **Rooms** | Manage rooms, adjust per-speaker volume, test left/right/stereo |
| **Zones** | Create/delete zones, assign rooms to zones |
| **Sendspin** | View sendspin client status for each room |
| **Settings** | Global volume limit, deploy configuration, service status |

### API

REST API available at `/api/`. Key endpoints:

- `GET /api/config` - Full configuration
- `POST /api/test/channel` - Test amplifier channel (chime/TTS)
- `POST /api/test/room` - Test room playback
- `POST /api/deploy` - Deploy configuration
- `GET /api/system/powermanager` - Per-amp power state and audio activity
- `POST /api/system/amp` - Control individual amplifier power (GPIO)
- `GET /api/system/sendspin` - Sendspin client status for all rooms
