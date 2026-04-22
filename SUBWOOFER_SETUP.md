# Subwoofer Setup — Wohnzimmer

Dedicated subwoofer on a Raspberry Pi Zero 2W (192.168.0.205, hostname `sub`), receiving audio via sendspin from lox-audioserver.

## Hardware

- **Device**: Raspberry Pi Zero 2W
- **Hostname**: sub
- **IP**: 192.168.0.205
- **DAC**: HiFiBerry DAC+ Zero (I2S via GPIO, PCM5102A)
- **Audio output**: HiFiBerry → subwoofer amplifier
- **Room**: Wohnzimmer
- **SSH access**: `ssh tobias@192.168.0.205`

## Setup (completed)

### 1. HiFiBerry DAC overlay

Added to `/boot/firmware/config.txt`:

```
dtoverlay=hifiberry-dac
```

Reboot required after adding.

### 2. ALSA configuration

`/etc/asound.conf` on the RPi Zero:

```
pcm.!default {
    type plug
    slave.pcm "hw:sndrpihifiberry"
}

ctl.!default {
    type hw
    card sndrpihifiberry
}

pcm.subwoofer {
    type plug
    slave.pcm "hw:sndrpihifiberry"
}
```

### 3. Dependencies

```bash
sudo apt install -y libportaudio2 alsa-utils python3-pip
pip install --user --break-system-packages sendspin aiosendspin
```

Installed sendspin version: 7.0.0

### 4. Sendspin service

`/etc/systemd/system/sendspin-subwoofer.service`:

```ini
[Unit]
Description=Sendspin client for Wohnzimmer subwoofer
After=network-online.target sound.target
Wants=network-online.target

[Service]
Type=simple
User=tobias
Environment=PYTHONPATH=/home/tobias/.local/lib/python3.13/site-packages
ExecStart=/home/tobias/.local/bin/sendspin daemon \
    --url ws://192.168.0.203:7090/sendspin \
    --id subwoofer_wohnzimmer \
    --name subwoofer_wohnzimmer \
    --audio-device default
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

**Note**: Uses `--audio-device default` (not `subwoofer`) because PortAudio/sounddevice cannot open named ALSA devices. The ALSA config routes `default` to the HiFiBerry.

**Note**: Requires `PYTHONPATH` because sendspin is installed with `--user` but systemd runs in a clean environment.

### 5. Enable and start

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now sendspin-subwoofer.service
journalctl -u sendspin-subwoofer -f
```

## lox-audioserver Integration

**Status**: Pending — see [lox-audioserver#237](https://github.com/lox-audioserver/lox-audioserver/issues/237)

Each zone only supports a single sendspin output. The subwoofer needs either:
- A dedicated zone linked to Wohnzimmer via groups
- Multiple outputs per zone (not currently supported)

The `subwoofer_wohnzimmer` client connects and is visible in lox-audioserver, but cannot be assigned to the Wohnzimmer zone alongside `room_wohnzimmer`.

## Testing

```bash
# From the RPi Zero — test direct ALSA output
speaker-test -D default -c 2 -t sine -f 60

# Check sendspin connection
journalctl -u sendspin-subwoofer -n 20

# Should see:
#   Connected to server 'Sendspin Server'
#   Handshake with server complete
```

## Troubleshooting

### sendspin: "No module named 'sendspin'"
The service needs `PYTHONPATH` set (see service file above). sendspin is installed in user-local site-packages.

### sendspin: "No output device matching 'subwoofer'"
PortAudio cannot see named ALSA devices. Use `--audio-device default` instead and configure the ALSA default to point to the HiFiBerry.

### HiFiBerry not detected
Check that `dtoverlay=hifiberry-dac` is in `/boot/firmware/config.txt` and reboot. Verify with `aplay -l` — should show `snd_rpi_hifiberry_dac`.

## Notes

- The subwoofer receives the **full stereo mix** from lox-audioserver, same as the main speakers. Crossover filtering (low-pass) should be handled by the subwoofer amplifier's built-in crossover.
- The subwoofer is on a separate network device, so it has independent latency. Adjust latency offset in lox-audioserver if needed to sync with the main Wohnzimmer speakers.
- The sendspin watchdog on the main server does NOT cover this device.
