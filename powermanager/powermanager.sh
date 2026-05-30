#!/usr/bin/env bash

# GPIO SHDN control for Wondom GAB8 amplifiers
# Controls each amp independently via GPIO shutdown pins.
# ALSA/USB stays connected — only the amp output stage is toggled.
#
# Detection: samples each sendspin process's WebSocket bytes_received over a
# short window. Real PCM playback is ~288 KB/s; idle/keepalive is <1 KB/s.
# This avoids the dmix false-positive where /proc/asound/.../hw_ptr keeps
# advancing even when no audio is being written.
#
# Hardware state is re-read from `ampctl status` each iteration so that
# external state changes (manual ampctl, power glitches) self-heal.

SPEAKER_CONFIG="/home/tobias/multiroom-tooling/speaker_config.json"

# Build CARDS dynamically from speaker_config.json: only amps that have a
# `gpio` field configured. Amps without a gpio are wired straight to power
# (always-on) and don't need (or support) software toggling — leave them alone.
mapfile -t CARDS < <(python3 - "$SPEAKER_CONFIG" <<'PY' 2>/dev/null
import json, sys
try:
    c = json.load(open(sys.argv[1]))
except Exception:
    sys.exit(0)
for k, amp in sorted((c.get('amplifiers') or {}).items()):
    if isinstance(amp, dict) and isinstance(amp.get('gpio'), int):
        print(k)
PY
)
[[ ${#CARDS[@]} -gt 0 ]] || CARDS=("amp1" "amp2" "amp3")  # safe fallback if config unreadable

SAMPLE_WINDOW=2          # seconds between bytes_received samples
ACTIVE_THRESHOLD=50000   # >50KB/2s = real audio (active PCM is ~576KB/2s)
IDLE_TIMEOUT=60          # seconds of inactivity before shutting an amp down

declare -A last_active_ts

log() {
  echo "[powermanager] $(date '+%Y-%m-%d %H:%M:%S') $*"
}

# Build room → amps mapping from speaker_config.json.
# Echoes lines: "<room_id> <amp1> [amp2] ..."
load_room_amp_map() {
  python3 - "$SPEAKER_CONFIG" <<'PY'
import json, sys
c = json.load(open(sys.argv[1]))
for rid, room in c.get('rooms', {}).items():
    amps = set()
    for side in ('left', 'right', 'sub'):
        spk_id = room.get(side)
        if spk_id:
            spk = c.get('speakers', {}).get(spk_id, {})
            if spk.get('amplifier'):
                amps.add(spk['amplifier'])
    if amps:
        print(rid + ' ' + ' '.join(sorted(amps)))
PY
}

# Echo "<room_id> <pid>" for each running sendspin@room_*.service
list_sendspin_pids() {
  systemctl list-units --no-legend --state=running 'sendspin@*' 2>/dev/null \
    | awk '{print $1}' \
    | while read -r unit; do
        pid=$(systemctl show -p MainPID --value "$unit" 2>/dev/null)
        [[ -z "$pid" || "$pid" == "0" ]] && continue
        # unit is sendspin@room_xxx.service → room id is "xxx"
        rid=$(echo "$unit" | sed -E 's/^sendspin@room_(.*)\.service$/\1/')
        echo "$rid $pid"
      done
}

# Get bytes_received for a sendspin pid's WebSocket to localhost:7090
ws_bytes_received() {
  local pid=$1
  ss -tpi dst 127.0.0.1:7090 2>/dev/null \
    | grep -A1 "pid=$pid," \
    | grep -oP 'bytes_received:\K[0-9]+'
}

# Get current amp state via ampctl. Echoes "<amp> <on|off>" lines.
read_amp_states() {
  ampctl status 2>/dev/null \
    | python3 -c "import json,sys; d=json.load(sys.stdin); [print(k,v) for k,v in d.items()]" 2>/dev/null
}

amp_enable()  { ampctl on  "$1" >/dev/null 2>&1; }
amp_disable() { ampctl off "$1" >/dev/null 2>&1; }

# ---- main ----

log "Starting powermanager daemon (bytes-flow mode, cards: ${CARDS[*]})"

# Load room → amps map once at startup. Re-read on SIGHUP.
declare -A room_amps
trap 'log "SIGHUP: reloading room→amp map"; reload_map=1' HUP

reload_map=1
while true; do
  if (( reload_map )); then
    declare -A room_amps=()
    while read -r line; do
      rid=$(echo "$line" | awk '{print $1}')
      amps=$(echo "$line" | cut -d' ' -f2-)
      room_amps[$rid]="$amps"
    done < <(load_room_amp_map)
    log "Loaded room→amp map: ${#room_amps[@]} rooms"
    reload_map=0
  fi

  # Snapshot 1: bytes_received per running sendspin
  # `declare -A foo=()` clears the array; plain `declare -A foo` keeps stale entries.
  declare -A pid_room=()
  declare -A bytes1=()
  while read -r rid pid; do
    [[ -z "$rid" || -z "$pid" ]] && continue
    pid_room[$pid]=$rid
    b=$(ws_bytes_received "$pid")
    bytes1[$pid]=${b:-0}
  done < <(list_sendspin_pids)

  sleep "$SAMPLE_WINDOW"

  # Snapshot 2 + delta → which rooms have real audio flowing
  declare -A active_amps=()
  for pid in "${!bytes1[@]}"; do
    b2=$(ws_bytes_received "$pid")
    b2=${b2:-0}
    delta=$(( b2 - ${bytes1[$pid]} ))
    if (( delta > ACTIVE_THRESHOLD )); then
      rid=${pid_room[$pid]}
      for amp in ${room_amps[$rid]}; do
        active_amps[$amp]=1
      done
    fi
  done

  # Read actual hardware state (self-heals from external changes)
  declare -A amp_state=()
  while read -r amp state; do
    amp_state[$amp]=$state
  done < <(read_amp_states)

  now_ts=$(date +%s)
  for card in "${CARDS[@]}"; do
    is_active=${active_amps[$card]:-0}
    state=${amp_state[$card]:-unknown}

    if (( is_active )); then
      last_active_ts[$card]=$now_ts
      if [[ "$state" != "on" ]]; then
        log "$card: audio detected (state was '$state') - enabling"
        amp_enable "$card"
      fi
    else
      if [[ "$state" == "on" ]]; then
        local_last=${last_active_ts[$card]:-0}
        if (( local_last == 0 )); then
          # First seen idle this session — start the clock now so we don't
          # immediately disable an amp the user just turned on.
          last_active_ts[$card]=$now_ts
        elif (( now_ts - local_last >= IDLE_TIMEOUT )); then
          log "$card: no audio for ${IDLE_TIMEOUT}s - disabling"
          amp_disable "$card"
          last_active_ts[$card]=0
        fi
      fi
    fi
  done
done
