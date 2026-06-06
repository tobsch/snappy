#!/usr/bin/env bash
# noise-monitor.sh — sample each amp's playback-stream + power state to catch the
# stale-dmix wedge that produces "radio static with no audio" and keeps amps
# from powering down.
#
# Wedge signature: state=RUNNING + appl_ptr=0 (no writer) + hw_ptr advancing
# (dmix looping a stale buffer). A normally-playing stream has appl_ptr>0.
#
# Logs to stdout → systemd journal. Read with:
#   journalctl -u noise-monitor -f                 # live
#   journalctl -u noise-monitor --since "10 min ago"  # around a noise event
#
# To correlate: when you HEAR the noise, note the time, then look for the amp
# carrying that room with a *** WEDGE *** flag (software) — or, if every amp is
# closed/idle at that time, the noise is hardware/EMI.
#
# See docs/2026-06-06-speaker-noise-investigation.md.
set -u

AMPS=(amp1 amp2 amp3 amp4)
INTERVAL="${NOISE_MONITOR_INTERVAL:-5}"     # seconds between samples
HEARTBEAT="${NOISE_MONITOR_HEARTBEAT:-60}"  # force a log line at least this often

declare -A prev_hw
last_line=""
last_beat=0

ts() { date '+%Y-%m-%d %H:%M:%S'; }

field() { printf '%s\n' "$1" | sed -n "s/^[[:space:]]*$2[[:space:]]*:[[:space:]]*//p" | head -1; }

echo "$(ts)  noise-monitor started (interval=${INTERVAL}s heartbeat=${HEARTBEAT}s)"

while true; do
  pstates=$(ampctl status 2>/dev/null)
  tokens=()
  wedge=""
  for a in "${AMPS[@]}"; do
    f="/proc/asound/$a/pcm0p/sub0/status"
    state="nodev"; appl=""; hw=""
    if [ -e "$f" ]; then
      content=$(cat "$f" 2>/dev/null)
      state=$(field "$content" state); [ -z "$state" ] && state="closed"
      appl=$(field "$content" appl_ptr)
      hw=$(field "$content" hw_ptr)
    fi
    pwr=$(printf '%s' "$pstates" | sed -n "s/.*\"$a\"[[:space:]]*:[[:space:]]*\"\([^\"]*\)\".*/\1/p")
    [ -z "$pwr" ] && pwr="?"

    adv="."
    if [ -n "$hw" ] && [ -n "${prev_hw[$a]:-}" ] && [ "$hw" != "${prev_hw[$a]}" ]; then adv="+"; fi
    [ -n "$hw" ] && prev_hw[$a]="$hw"

    if [ "$state" = "RUNNING" ] && [ "$appl" = "0" ]; then
      wedge="$wedge $a"
    fi

    if [ "$state" = "closed" ] || [ "$state" = "nodev" ]; then
      tokens+=("$a:$state/pwr=$pwr")
    else
      tokens+=("$a:$state/appl=$appl/hw=${hw}${adv}/pwr=$pwr")
    fi
  done

  line="${tokens[*]}"
  now=$(date +%s)
  flag=""
  [ -n "$wedge" ] && flag="   *** WEDGE:${wedge} (radio-static suspect) ***"

  if [ "$line" != "$last_line" ] || [ -n "$wedge" ] || [ $((now - last_beat)) -ge "$HEARTBEAT" ]; then
    echo "$(ts)  ${line}${flag}"
    last_line="$line"
    last_beat=$now
  fi

  sleep "$INTERVAL"
done
