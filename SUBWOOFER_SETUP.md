# Subwoofer Setup — Wohnzimmer

Dedicated subwoofer on a Raspberry Pi Nano (192.168.0.205), receiving audio via sendspin from lox-audioserver.

## Hardware

- **Device**: Raspberry Pi Nano
- **IP**: 192.168.0.205
- **Audio output**: USB DAC or onboard audio → subwoofer amplifier
- **Room**: Wohnzimmer

## Setup on the RPi Nano (192.168.0.205)

### 1. Install dependencies

```bash
ssh pi@192.168.0.205

sudo apt update
sudo apt install -y libportaudio2 python3-pip alsa-utils
pip install --user --break-system-packages sendspin aiosendspin
```

### 2. Identify the audio output device

```bash
# List available ALSA devices
aplay -l

# Test output (replace hw:0 with your device)
speaker-test -D hw:0 -c 2 -t sine -f 80
```

Note the card/device name for the sendspin config (e.g., `hw:0`, `plughw:0`, or a named device).

### 3. Create ALSA config for subwoofer filtering (optional)

To only pass low frequencies to the subwoofer, create `/etc/asound.conf`:

```
# Low-pass filter via ALSA LADSPA plugin (optional, requires swh-plugins)
# If not using ALSA filtering, use lox-audioserver's DSP or just send full-range audio

pcm.subwoofer {
    type plug
    slave.pcm "hw:0"
    slave.channels 2
}
```

If you want a proper low-pass filter, install `swh-plugins` and configure an LADSPA plugin chain. Alternatively, let the subwoofer amplifier handle crossover filtering.

### 4. Install sendspin service

Create `/etc/systemd/system/sendspin-subwoofer.service`:

```ini
[Unit]
Description=Sendspin client for Wohnzimmer subwoofer
After=network-online.target sound.target
Wants=network-online.target

[Service]
Type=simple
ExecStart=/home/pi/.local/bin/sendspin daemon \
    --url ws://192.168.0.203:7090/sendspin \
    --id subwoofer_wohnzimmer \
    --name subwoofer_wohnzimmer \
    --audio-device subwoofer
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

Adjust:
- `--url` — IP of the main audio server running lox-audioserver (192.168.0.203)
- `--audio-device` — the ALSA device name from step 2/3
- `--id` / `--name` — must be unique across all sendspin clients

### 5. Enable and start

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now sendspin-subwoofer.service

# Check status
journalctl -u sendspin-subwoofer -f
```

## Configure in lox-audioserver

The subwoofer sendspin client should appear in the lox-audioserver web UI (http://192.168.0.203:7090) once connected.

1. Open the lox-audioserver admin UI
2. Go to zone configuration for **Wohnzimmer**
3. Add `subwoofer_wohnzimmer` as an additional output for the zone
4. Set volume as needed (subwoofers typically need independent volume control)

## Testing

```bash
# From the RPi Nano — test direct ALSA output
speaker-test -D subwoofer -c 2 -t sine -f 60

# Check sendspin connection
journalctl -u sendspin-subwoofer -n 20

# Should see:
#   Connected to server 'Sendspin Server'
#   Handshake with server complete
#   Stream STARTED: ...
```

## Notes

- The subwoofer receives the **full stereo mix** from lox-audioserver, same as the main speakers. Crossover filtering (low-pass) should be handled by either:
  - The subwoofer amplifier's built-in crossover
  - An ALSA LADSPA plugin chain on the RPi
  - DSP settings in lox-audioserver (if supported)
- The subwoofer is on a separate network device, so it has independent latency. Adjust latency offset in lox-audioserver if needed to sync with the main Wohnzimmer speakers.
- The sendspin watchdog on the main server does NOT cover this device. If needed, install the watchdog on the RPi Nano as well.
