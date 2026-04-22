#!/usr/bin/env bash
# Watchdog for stale sendspin ALSA streams.
#
# Problem: sendspin (via PortAudio) can leave ALSA streams in RUNNING state
# indefinitely after audio stops, with appl_ptr stuck at 0 and hw_ptr
# advancing forever. This prevents new audio from playing until the
# service is restarted.
#
# Detection strategy:
# 1. Find RUNNING ALSA streams owned by sendspin threads
# 2. Find the owning systemd service
# 3. Check if "Disconnected from server" occurred AFTER the last "Stream STARTED"
#    This is the only reliable stale indicator — stream was opened, then server went away.
#
# We do NOT use log-idle heuristics (e.g. "no logs for 30 min = stale") because
# long uninterrupted playback can go 30+ minutes without any log entries, causing
# false positives that kill active sessions.

CARDS=("amp1" "amp2" "amp3")

log() {
  echo "[sendspin-watchdog] $(date '+%Y-%m-%d %H:%M:%S') $*"
}

check_service_stale() {
  local pid=$1
  # Find the systemd service for this PID
  local service
  service=$(systemctl list-units --type=service --state=running 'sendspin@*' --no-legend 2>/dev/null \
    | awk '{print $1}' \
    | while read -r svc; do
        svc_pid=$(systemctl show -p MainPID --value "$svc" 2>/dev/null)
        if [[ "$svc_pid" == "$pid" ]]; then
          echo "$svc"
          break
        fi
      done)

  if [[ -z "$service" ]]; then
    log "WARNING: Could not find systemd service for PID $pid"
    return 1
  fi

  # Check if there's been a disconnect/connection error AFTER the last Stream STARTED.
  # This is a definitive stale indicator: stream opened, then server went away.
  local last_started last_disconnect
  last_started=$(journalctl -u "$service" --no-pager -g "Stream STARTED" -n 1 --output=short-unix 2>/dev/null \
    | head -1 | awk '{print int($1)}')
  last_disconnect=$(journalctl -u "$service" --no-pager -g "Disconnected from server" -n 1 --output=short-unix 2>/dev/null \
    | head -1 | awk '{print int($1)}')

  if [[ -n "$last_started" ]] && [[ -n "$last_disconnect" ]] && (( last_disconnect > last_started )); then
    log "Stale stream for $service (disconnected after last Stream STARTED) - restarting"
    systemctl restart "$service"
    return 0
  fi

  # Check if audio is actually flowing on the WebSocket to lox-audioserver.
  # Active playback: ~288 KB/s received (48kHz * 24-bit * 2ch PCM)
  # Idle/stale: near zero bytes received
  if ! is_audio_flowing "$pid"; then
    log "Stale stream for $service (no audio data flowing on WebSocket) - restarting"
    systemctl restart "$service"
    return 0
  fi

  return 0
}

# Check if audio data is flowing on the sendspin WebSocket connection.
# Takes two readings of bytes_received 2 seconds apart.
# Active PCM: ~288 KB/s = ~576 KB in 2 seconds
# Threshold: 50 KB in 2 seconds (generous margin for compressed formats)
is_audio_flowing() {
  local pid=$1
  local bytes1 bytes2 delta

  bytes1=$(ss -tpi dst 127.0.0.1:7090 2>/dev/null \
    | grep -A1 "pid=$pid," \
    | grep -oP 'bytes_received:\K[0-9]+')

  [[ -n "$bytes1" ]] || return 1  # No connection found

  sleep 2

  bytes2=$(ss -tpi dst 127.0.0.1:7090 2>/dev/null \
    | grep -A1 "pid=$pid," \
    | grep -oP 'bytes_received:\K[0-9]+')

  [[ -n "$bytes2" ]] || return 1

  delta=$(( bytes2 - bytes1 ))

  if (( delta > 50000 )); then
    return 0  # Audio is flowing
  fi

  return 1  # No meaningful data received
}

check_stale_streams() {
  local card status_file status content owner_pid tgid
  declare -A checked_pids

  for card in "${CARDS[@]}"; do
    for status_file in /proc/asound/${card}/pcm*/sub*/status; do
      [ -e "$status_file" ] || continue
      read -r status < "$status_file" 2>/dev/null || continue
      [[ "$status" == "state: RUNNING" ]] || continue

      content=$(cat "$status_file" 2>/dev/null) || continue
      owner_pid=$(awk '/owner_pid/{print $3}' <<< "$content")
      [[ -n "$owner_pid" ]] || continue

      # Check if owner is a sendspin process
      local proc_name
      proc_name=$(cat "/proc/$owner_pid/comm" 2>/dev/null) || continue
      [[ "$proc_name" == "sendspin" ]] || continue

      # Get the main thread PID (Tgid) since owner_pid may be a thread
      tgid=$(awk '/^Tgid:/{print $2}' "/proc/$owner_pid/status" 2>/dev/null)
      [[ -n "$tgid" ]] || tgid="$owner_pid"

      # Skip if we already checked this main PID
      [[ -n "${checked_pids[$tgid]}" ]] && continue
      checked_pids[$tgid]=1

      check_service_stale "$tgid"
    done
  done
}

check_stale_streams
