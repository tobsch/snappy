#!/usr/bin/env bash
# ampctl - control Wondom GAB8 amplifier power via GPIO SHDN pins
#
# Usage:
#   ampctl status          Show status of all amps
#   ampctl status amp1     Show status of specific amp
#   ampctl on amp1         Enable amp1
#   ampctl off amp2        Disable amp2
#   ampctl on              Enable all amps
#   ampctl off             Disable all amps

declare -A AMP_GPIO=(
  [amp1]=27
  [amp2]=22
  [amp3]=17
)

ALL_AMPS=(amp1 amp2 amp3)

get_state() {
  local amp=$1
  local gpio=${AMP_GPIO[$amp]}
  local output
  output=$(pinctrl get "$gpio" 2>/dev/null)
  if [[ "$output" == *"| hi"* ]]; then
    echo "on"
  elif [[ "$output" == *"| lo"* ]]; then
    echo "off"
  else
    echo "unknown"
  fi
}

amp_on() {
  local amp=$1
  local gpio=${AMP_GPIO[$amp]}
  pinctrl set "$gpio" op dh 2>/dev/null
}

amp_off() {
  local amp=$1
  local gpio=${AMP_GPIO[$amp]}
  pinctrl set "$gpio" op dl 2>/dev/null
}

case "${1:-}" in
  status)
    if [[ -n "${2:-}" ]]; then
      # Single amp status
      amp="$2"
      [[ -n "${AMP_GPIO[$amp]:-}" ]] || { echo "Unknown amp: $amp" >&2; exit 1; }
      state=$(get_state "$amp")
      echo "$amp $state"
    else
      # All amps status (JSON for easy parsing)
      echo "{"
      first=true
      for amp in "${ALL_AMPS[@]}"; do
        state=$(get_state "$amp")
        $first || echo ","
        printf '  "%s": "%s"' "$amp" "$state"
        first=false
      done
      echo ""
      echo "}"
    fi
    ;;
  on)
    if [[ -n "${2:-}" ]]; then
      amp="$2"
      [[ -n "${AMP_GPIO[$amp]:-}" ]] || { echo "Unknown amp: $amp" >&2; exit 1; }
      amp_on "$amp"
      echo "$amp on"
    else
      for amp in "${ALL_AMPS[@]}"; do
        amp_on "$amp"
        echo "$amp on"
      done
    fi
    ;;
  off)
    if [[ -n "${2:-}" ]]; then
      amp="$2"
      [[ -n "${AMP_GPIO[$amp]:-}" ]] || { echo "Unknown amp: $amp" >&2; exit 1; }
      amp_off "$amp"
      echo "$amp off"
    else
      for amp in "${ALL_AMPS[@]}"; do
        amp_off "$amp"
        echo "$amp off"
      done
    fi
    ;;
  *)
    echo "Usage: ampctl {status|on|off} [amp1|amp2|amp3]" >&2
    exit 1
    ;;
esac
