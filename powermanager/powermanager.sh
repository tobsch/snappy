#!/usr/bin/env bash

# ALSA cards to monitor for activity (using persistent udev names)
CARDS=("amp1" "amp2" "amp3")

# Relay commands (inverted: relay off = amp on, relay on = amp off)
RELAY_ON_CMD="crelay 1 off"
RELAY_OFF_CMD="crelay 1 on"

# Check interval in seconds
SLEEP_INTERVAL=0.1

# Idle timeout in seconds before turning off
IDLE_TIMEOUT=60

# Cooldown period after turning relay off (seconds)
# Prevents false re-activation when USB amp power-cycles reset ALSA state
RELAY_OFF_COOLDOWN=5

relay_on=false
last_active_ts=0
relay_off_ts=0

log() {
  echo "[powermanager] $(date '+%Y-%m-%d %H:%M:%S') $*"
}

is_any_card_active() {
  local status content owner_pid avail_max
  for card in "${CARDS[@]}"; do
    for status_file in /proc/asound/${card}/pcm*/sub*/status; do
      [ -e "$status_file" ] || continue
      # Quick check: read first line only - "closed" or "state: RUNNING"
      read -r status < "$status_file" 2>/dev/null || continue
      [[ "$status" == "state: RUNNING" ]] || continue

      # Stream is running - read full status once for all checks
      content=$(cat "$status_file" 2>/dev/null) || continue
      owner_pid=$(awk '/owner_pid/{print $3}' <<< "$content")

      # Check if owner process is alive
      [[ -n "$owner_pid" ]] && kill -0 "$owner_pid" 2>/dev/null || continue

      # Check for orphaned streams: appl_ptr=0 means app never wrote to current position
      # This catches PID-recycled cases where a different process now has the same PID
      appl_ptr=$(awk '/appl_ptr/{print $3}' <<< "$content")
      [[ "$appl_ptr" == "0" ]] && continue

      # Check avail_max for stale streams
      # Truly stale streams (hours) reach hundreds of millions or billions
      # Threshold of 100M (~35 min at 48kHz) allows normal playback
      avail_max=$(awk '/avail_max/{print $3}' <<< "$content")
      if [[ -z "$avail_max" ]] || (( avail_max < 100000000 )); then
        return 0  # Active or recently active
      fi
    done
  done
  return 1
}

log "Starting powermanager daemon (cards: ${CARDS[*]})"

# Initialize relay state based on current activity
if is_any_card_active; then
  log "Audio active at startup - ensuring relay ON"
  $RELAY_ON_CMD && relay_on=true
  last_active_ts=$(date +%s)
else
  log "No audio at startup - turning relay OFF"
  if $RELAY_OFF_CMD; then
    relay_on=false
    relay_off_ts=$(date +%s)
  fi
fi

while true; do
  now_ts=$(date +%s)

  # Skip activity check during cooldown period after relay off
  # (USB amp power-cycle can reset ALSA state, causing false activity detection)
  if [ "$relay_on" = false ] && (( now_ts - relay_off_ts < RELAY_OFF_COOLDOWN )); then
    sleep "$SLEEP_INTERVAL"
    continue
  fi

  if is_any_card_active; then
    last_active_ts=$now_ts
    if [ "$relay_on" = false ]; then
      log "Audio activity detected - turning relay ON"
      if $RELAY_ON_CMD; then
        relay_on=true
      else
        log "Failed to turn relay ON - will retry"
      fi
    fi
  else
    if [ "$relay_on" = true ]; then
      if (( now_ts - last_active_ts >= IDLE_TIMEOUT )); then
        log "No audio for ${IDLE_TIMEOUT}s - turning relay OFF"
        if $RELAY_OFF_CMD; then
          relay_on=false
          relay_off_ts=$now_ts
        else
          log "Failed to turn relay OFF - will retry"
        fi
      fi
    fi
  fi

  sleep "$SLEEP_INTERVAL"
done
