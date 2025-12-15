#!/usr/bin/env bash

# ALSA cards to monitor for activity
CARDS=("2" "3")

# Relay commands
RELAY_ON_CMD="crelay 2 on"
RELAY_OFF_CMD="crelay 2 off"

# Check interval in seconds (e.g., 0.05 = 50 milliseconds)
SLEEP_INTERVAL=0.05

# Idle timeout in seconds before turning off
# 5 minutes = 300 seconds
IDLE_TIMEOUT=300

relay_on=false
last_active_ts=0

log() {
  echo "[powermanager] $(date '+%Y-%m-%d %H:%M:%S') $*"
}

is_any_card_active() {
  for card in "${CARDS[@]}"; do
    for status_file in /proc/asound/card${card}/pcm*/sub*/status; do
      [ -e "$status_file" ] || continue
      if grep -q "RUNNING" "$status_file" 2>/dev/null; then
        return 0
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
      $RELAY_ON_CMD
      relay_on=true
    fi
  else
    if [ "$relay_on" = true ]; then
      if (( now_ts - last_active_ts >= IDLE_TIMEOUT )); then
        log "No audio for ${IDLE_TIMEOUT}s - turning relay OFF"
        $RELAY_OFF_CMD
        relay_on=false
      fi
    fi
  fi

  sleep "$SLEEP_INTERVAL"
done
