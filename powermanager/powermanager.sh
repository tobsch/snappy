#!/usr/bin/env bash

# ALSA cards to monitor for activity (using persistent udev names)
CARDS=("amp1" "amp2" "amp3")

# Relay commands (inverted: relay off = amp on, relay on = amp off)
RELAY_ON_CMD="crelay 1 off"
RELAY_OFF_CMD="crelay 1 on"

# Check interval in seconds (e.g., 0.05 = 50 milliseconds)
SLEEP_INTERVAL=0.05

# Idle timeout in seconds before turning off
IDLE_TIMEOUT=60

relay_on=false
last_active_ts=0

log() {
  echo "[powermanager] $(date '+%Y-%m-%d %H:%M:%S') $*"
}

is_any_card_active() {
  for card in "${CARDS[@]}"; do
    for status_file in /proc/asound/${card}/pcm*/sub*/status; do
      [ -e "$status_file" ] || continue
      if grep -q "RUNNING" "$status_file" 2>/dev/null; then
        # Check avail_max - stale streams accumulate millions, real audio stays ~40k
        # Threshold of 1M samples = ~20 seconds of staleness at 48kHz
        avail_max=$(grep "avail_max" "$status_file" 2>/dev/null | awk '{print $3}')
        if [[ -n "$avail_max" ]] && (( avail_max < 1000000 )); then
          return 0
        fi
      fi
    done
  done
  return 1
}

log "Starting powermanager daemon (cards: ${CARDS[*]})"

while true; do
  now_ts=$(date +%s)

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
        else
          log "Failed to turn relay OFF - will retry"
        fi
      fi
    fi
  fi

  sleep "$SLEEP_INTERVAL"
done
