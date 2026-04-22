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
# 3. Check if there has been ANY sendspin log activity in the last IDLE_THRESHOLD seconds
#    (active playback produces periodic logs: volume changes, sync corrections, etc.)
# 4. If the service has been completely silent AND has a stale ALSA stream, restart it
#
# This avoids false positives on long playback sessions, which produce periodic log entries.

IDLE_THRESHOLD=1800  # 30 minutes of zero log activity before considering stale
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

  local now
  now=$(date +%s)

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

  # Check for ANY log activity in the last IDLE_THRESHOLD seconds.
  # Active playback produces periodic entries (volume, sync, format changes).
  # A completely silent service with a RUNNING ALSA stream is stale.
  local last_any
  last_any=$(journalctl -u "$service" --no-pager -n 1 --output=short-unix 2>/dev/null \
    | tail -1 | awk '{print int($1)}')

  if [[ -z "$last_any" ]]; then
    log "Stale stream for $service (no log entries at all) - restarting"
    systemctl restart "$service"
    return 0
  fi

  local idle_secs=$(( now - last_any ))

  if (( idle_secs >= IDLE_THRESHOLD )); then
    log "Stale stream for $service (no log activity for ${idle_secs}s) - restarting"
    systemctl restart "$service"
    return 0
  fi

  return 0
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
