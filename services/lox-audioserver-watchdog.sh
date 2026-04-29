#!/usr/bin/env bash
# Watchdog for lox-audioserver librespot skip loop.
#
# Problem: librespot inside lox-audioserver can enter a broken state where
# it rapidly skips through tracks. This happens when:
# - Audio key requests fail (stale session)
# - Zone switching causes context loss across extensions
#
# Once in this state, librespot never recovers on its own.
#
# Detection: tail docker logs and count "playback session terminated by engine"
# with reason=replace. If we see 3+ replace events within 30 seconds,
# the skip loop is active — restart the container.
#
# Runs as a long-lived daemon that continuously tails the logs.

CONTAINER="lox-audioserver"
# Number of replace events in the window to trigger restart
THRESHOLD=3
# Time window in seconds
WINDOW=30
# Cooldown after restart before monitoring again (seconds)
RESTART_COOLDOWN=60

log() {
  echo "[lox-watchdog] $(date '+%Y-%m-%d %H:%M:%S') $*"
}

log "Starting lox-audioserver watchdog (threshold=${THRESHOLD} replaces in ${WINDOW}s)"

# Array of timestamps for recent replace events
declare -a replace_times=()

docker logs --follow --since 1s "$CONTAINER" 2>&1 | while IFS= read -r line; do
  # Match replace events (the skip indicator)
  if [[ "$line" == *"reason=replace"*"playback session terminated by engine"* ]]; then
    now=$(date +%s)
    replace_times+=("$now")

    # Prune events outside the window
    pruned=()
    for ts in "${replace_times[@]}"; do
      if (( now - ts <= WINDOW )); then
        pruned+=("$ts")
      fi
    done
    replace_times=("${pruned[@]}")

    count=${#replace_times[@]}
    log "Replace event detected (${count}/${THRESHOLD} in ${WINDOW}s window)"

    if (( count >= THRESHOLD )); then
      log "Skip loop detected! Restarting ${CONTAINER}..."
      docker restart "$CONTAINER"
      log "Container restarted. Cooling down for ${RESTART_COOLDOWN}s..."
      replace_times=()
      sleep "$RESTART_COOLDOWN"
      log "Cooldown complete, resuming monitoring"
      # Re-attach to the log stream after restart
      exec "$0"
    fi
  fi

  # Also catch audio key errors (the other skip trigger from #238)
  if [[ "$line" == *"error audio key"* ]]; then
    now=$(date +%s)
    replace_times+=("$now")

    pruned=()
    for ts in "${replace_times[@]}"; do
      if (( now - ts <= WINDOW )); then
        pruned+=("$ts")
      fi
    done
    replace_times=("${pruned[@]}")

    count=${#replace_times[@]}
    log "Audio key error detected (${count}/${THRESHOLD} in ${WINDOW}s window)"

    if (( count >= THRESHOLD )); then
      log "Audio key failure loop detected! Restarting ${CONTAINER}..."
      docker restart "$CONTAINER"
      log "Container restarted. Cooling down for ${RESTART_COOLDOWN}s..."
      replace_times=()
      sleep "$RESTART_COOLDOWN"
      log "Cooldown complete, resuming monitoring"
      exec "$0"
    fi
  fi
done
