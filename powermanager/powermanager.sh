#!/usr/bin/env bash

# GPIO SHDN control for Wondom GAB8 amplifiers
# Controls each amp independently via GPIO shutdown pins.
# ALSA/USB stays connected — only the amp output stage is toggled.
#
# Detection: samples hw_ptr twice (0.2s apart) to check if audio is
# actually flowing, same principle as the sendspin watchdog.

CARDS=("amp1" "amp2" "amp3")

# Idle timeout per amp before shutting down (seconds)
IDLE_TIMEOUT=60

# Track state per amp
declare -A amp_on
declare -A last_active_ts

log() {
  echo "[powermanager] $(date '+%Y-%m-%d %H:%M:%S') $*"
}

amp_enable() {
  ampctl on "$1" >/dev/null
}

amp_disable() {
  ampctl off "$1" >/dev/null
}

# Check if audio is flowing on a specific card by sampling hw_ptr twice
is_card_active() {
  local card=$1
  local status_file status hw_ptr1 hw_ptr2

  for status_file in /proc/asound/${card}/pcm*/sub*/status; do
    [ -e "$status_file" ] || continue
    read -r status < "$status_file" 2>/dev/null || continue
    [[ "$status" == "state: RUNNING" ]] || continue

    # Sample hw_ptr twice to detect audio flow
    hw_ptr1=$(awk '/hw_ptr/{print $3}' "$status_file" 2>/dev/null)
    [[ -n "$hw_ptr1" ]] || continue

    sleep 0.2

    hw_ptr2=$(awk '/hw_ptr/{print $3}' "$status_file" 2>/dev/null)
    [[ -n "$hw_ptr2" ]] || continue

    if (( hw_ptr2 > hw_ptr1 )); then
      return 0  # Audio is flowing
    fi
  done

  return 1  # No audio on this card
}

log "Starting powermanager daemon (GPIO mode, cards: ${CARDS[*]})"

# Initialize: check each amp and set state
for card in "${CARDS[@]}"; do
  if is_card_active "$card"; then
    log "$card: audio active at startup - enabling"
    amp_enable "$card"
    amp_on[$card]=true
    last_active_ts[$card]=$(date +%s)
  else
    log "$card: no audio at startup - disabling"
    amp_disable "$card"
    amp_on[$card]=false
  fi
done

while true; do
  now_ts=$(date +%s)

  for card in "${CARDS[@]}"; do
    if is_card_active "$card"; then
      last_active_ts[$card]=$now_ts

      if [[ "${amp_on[$card]}" != "true" ]]; then
        log "$card: audio detected - enabling"
        amp_enable "$card"
        amp_on[$card]=true
      fi
    else
      if [[ "${amp_on[$card]}" == "true" ]]; then
        local_last=${last_active_ts[$card]:-0}
        if (( now_ts - local_last >= IDLE_TIMEOUT )); then
          log "$card: no audio for ${IDLE_TIMEOUT}s - disabling"
          amp_disable "$card"
          amp_on[$card]=false
        fi
      fi
    fi
  done

  sleep 1
done
