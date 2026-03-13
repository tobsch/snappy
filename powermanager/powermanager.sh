#!/usr/bin/env bash

# ALSA cards to monitor for activity (using persistent udev names)
CARDS=("amp1" "amp2" "amp3")

# Relay commands (inverted: relay off = amp on, relay on = amp off)
RELAY_ON_CMD="crelay 1 off"
RELAY_OFF_CMD="crelay 1 on"

# Check interval in seconds
SLEEP_INTERVAL=0.1

# Idle timeout in seconds before turning off
# Set high because sendspin keeps ALSA streams RUNNING even when idle
IDLE_TIMEOUT=600

# Cooldown period after turning relay off (seconds)
# Prevents false re-activation when USB amp power-cycles reset ALSA state
# USB amps take ~20-30 seconds to fully reset and clients to reconnect
RELAY_OFF_COOLDOWN=45

relay_on=false
last_active_ts=0
relay_off_ts=0

log() {
  echo "[powermanager] $(date '+%Y-%m-%d %H:%M:%S') $*"
}

# Check if any Snapcast stream is playing
is_snapcast_playing() {
  # Query Snapcast JSON-RPC API for stream status
  local response
  response=$(curl -s --max-time 1 -X POST -H "Content-Type: application/json" \
    -d '{"id":1,"jsonrpc":"2.0","method":"Server.GetStatus"}' \
    http://localhost:1705 2>/dev/null) || return 1

  # Check if any stream has status "playing"
  echo "$response" | grep -q '"status":"playing"'
}

# Check if any sendspin client is receiving audio
# Sendspin bypasses Snapcast, so we need to check ALSA activity from sendspin processes
# Note: sendspin's avail_max grows unboundedly even during playback (PortAudio quirk),
# so we can't use the avail_max threshold. Just check if sendspin owns a RUNNING stream.
is_sendspin_active() {
  local card status content owner_pid proc_name
  for card in "${CARDS[@]}"; do
    for status_file in /proc/asound/${card}/pcm*/sub*/status; do
      [ -e "$status_file" ] || continue
      read -r status < "$status_file" 2>/dev/null || continue
      [[ "$status" == "state: RUNNING" ]] || continue

      content=$(cat "$status_file" 2>/dev/null) || continue
      owner_pid=$(awk '/owner_pid/{print $3}' <<< "$content")
      [[ -n "$owner_pid" ]] || continue

      # Check if it's a sendspin process
      proc_name=$(cat "/proc/$owner_pid/comm" 2>/dev/null) || continue
      [[ "$proc_name" == "sendspin" ]] || continue

      # Sendspin owns a RUNNING stream - consider active
      return 0
    done
  done
  return 1
}

# Check if a process actually has an ALSA device open
# This catches PID recycling: process alive but doesn't own the stream
process_has_alsa_open() {
  local pid=$1 card=$2
  local card_num
  # Get card number from /proc/asound/card symlink
  card_num=$(readlink "/proc/asound/$card" 2>/dev/null | grep -o '[0-9]*')
  [[ -z "$card_num" ]] && return 1
  # Check if process has /dev/snd/pcm* for this card open
  ls -l "/proc/$pid/fd" 2>/dev/null | grep -q "/dev/snd/pcmC${card_num}"
}

# Store previous hw_ptr values to detect movement
declare -A prev_hw_ptr

is_any_card_active() {
  local status content owner_pid hw_ptr card key
  local found_active=false

  for card in "${CARDS[@]}"; do
    for status_file in /proc/asound/${card}/pcm*/sub*/status; do
      [ -e "$status_file" ] || continue
      read -r status < "$status_file" 2>/dev/null || continue
      [[ "$status" == "state: RUNNING" ]] || continue

      content=$(cat "$status_file" 2>/dev/null) || continue
      owner_pid=$(awk '/owner_pid/{print $3}' <<< "$content")

      # Check if owner process is alive
      [[ -n "$owner_pid" ]] && kill -0 "$owner_pid" 2>/dev/null || continue

      # Verify process actually has this ALSA device open
      process_has_alsa_open "$owner_pid" "$card" || continue

      # Get current hw_ptr
      hw_ptr=$(awk '/hw_ptr/{print $3}' <<< "$content")
      [[ -n "$hw_ptr" ]] || continue

      key="${card}_${status_file}"

      # Compare with previous hw_ptr - if changed, audio is flowing
      if [[ -n "${prev_hw_ptr[$key]}" ]] && [[ "$hw_ptr" != "${prev_hw_ptr[$key]}" ]]; then
        found_active=true
      fi

      # Store current hw_ptr for next check
      prev_hw_ptr[$key]="$hw_ptr"
    done
  done

  $found_active && return 0

  # Fallback: check Snapcast (works reliably)
  is_snapcast_playing && return 0

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
