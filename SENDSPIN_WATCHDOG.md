# Sendspin Stale Stream Watchdog

## Problem

Sendspin (via PortAudio's mmap mode) can leave ALSA streams in `RUNNING` state indefinitely after audio stops. The `appl_ptr` stays at 0 and `hw_ptr` advances forever, making the stream appear active to ALSA while no audio is actually playing. This prevents new audio from playing until the sendspin service is restarted.

Standard ALSA detection metrics don't work here:
- `avail_max` / `avail` — grows continuously because `appl_ptr` stays at 0 (PortAudio mmap quirk)
- `hw_ptr` movement — advances at sample rate regardless of whether audio is playing
- `delay` — massively negative in both active and stale states

## Solution

The watchdog runs every 5 minutes via a systemd timer and uses two detection methods:

### 1. Disconnect after play (log-based)

If `"Disconnected from server"` is logged after the last `"Stream STARTED"`, the stream is definitively stale — audio was playing, then the server went away, but PortAudio kept the ALSA stream open.

### 2. WebSocket byte flow (network-based)

Takes two readings of `bytes_received` on the sendspin WebSocket connection (to `localhost:7090`) 2 seconds apart using `ss -tpi`. Active PCM audio at 48kHz/24-bit/stereo produces ~288 KB/s (~576 KB in 2 seconds). If the delta is below 50 KB, no audio is flowing and the stream is stale.

This approach is reliable because it checks actual data on the wire, not ALSA state.

## What was tried and didn't work

- **`avail_max < 500K` threshold** — PortAudio mmap keeps `appl_ptr=0`, so `avail` and `avail_max` grow at sample rate even during active playback
- **Log-idle heuristic (30-minute silence)** — Long uninterrupted playback can go 30+ minutes without any sendspin log entries (no volume changes, no sync corrections), causing false positives that killed active sessions
- **`hw_ptr` comparison between checks** — Advances at 48kHz in both active and stale states

## Files

- `services/sendspin-watchdog.sh` — The watchdog script
- `services/sendspin-watchdog.service` — Systemd oneshot service
- `services/sendspin-watchdog.timer` — Systemd timer (every 5 minutes)

## Installation

```bash
sudo cp services/sendspin-watchdog.sh /usr/local/bin/sendspin-watchdog.sh
sudo chmod +x /usr/local/bin/sendspin-watchdog.sh
sudo cp services/sendspin-watchdog.service /etc/systemd/system/
sudo cp services/sendspin-watchdog.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now sendspin-watchdog.timer
```

## Checking status

```bash
# Timer status and next run
systemctl status sendspin-watchdog.timer

# Recent watchdog runs
journalctl -u sendspin-watchdog.service -n 20

# Manual test run
sudo /usr/local/bin/sendspin-watchdog.sh
```
