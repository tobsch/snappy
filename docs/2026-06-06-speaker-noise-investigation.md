# Speaker noise investigation (radio static / hum / pop)

Status: **OPEN — investigation in progress.** Started 2026-06-06. This is a living
doc; append findings to the **Log** at the bottom.

Goal: eliminate persistent noise on the multiroom speakers. The **radio-like
static** is the unsolved one — it survived extensive EMI/hardware work.

---

## System

- 3× Wondom **GAB8** amplifiers (TI **TPA3244** class-D), USB audio in
- Raspberry **Pi 5**
- **Mean Well 24 V** PSU (Pi + amps unified onto it)
- **Schaffner FN2030** EMI filter on mains
- Speaker runs: **~20 m, unshielded, parallel to mains wiring in the walls**
- Amp power via **GPIO SHDN** (active-low) per amp, driven by `powermanager`
  (auto-SHDN on ALSA inactivity). Map: amp1=GPIO27, amp2=GPIO22, amp3=GPIO17.
  amp4 (C-Media USB, the line-in device) has **no GPIO → always on**.
- Audio path: lox-audioserver → sendspin client per room → ALSA `room_<x>`
  (dmix) → GAB8 channel.

## Symptoms (not one noise — at least three)

1. **Low-frequency hum**
2. **Radio-like interference / static** — *present with no audio playing*, and
   **appears in different rooms over time** ← the persistent, unsolved one
3. **Loud pop on power-up**
4. Secondary: **~50 W idle** draw (amps not settling into SHDN)

---

## Working hypothesis: 3 symptoms, 3 different root causes

Treating it all as "EMI" risks buying ferrites/shielding to fix something that
isn't EMI. Current mapping:

| Symptom | Most likely cause | EMI fixes help? |
|---|---|---|
| Low hum | Ground loop / mains coupling (hardware) | **Yes** |
| Power-up pop | SHDN/mute vs. rail timing (sequencing) | Partly — SHDN GPIOs are software-controlled, so we can mute-before-power |
| **Radio static, no input, migrates between rooms over time** | **Suspect: software stale-dmix loop (#233 family) on this system** | **No — ferrites can't touch it** |

### Why the radio-static is suspected to be SOFTWARE, not EMI

The `#233`-family bug on this exact system: a sendspin client wedges, leaving
its ALSA playback stream stuck `state: RUNNING` with `appl_ptr = 0` while
`hw_ptr` keeps advancing → **dmix loops a stale buffer → garbled noise**, with
no real audio playing. See `memory/project_upstream_bugs.md` and the
troubleshooting note in `CLAUDE.md` ("Loud noise or distortion from speakers").

Two tells that point at software over EMI:

- **"Migrates between rooms over time"** — each room's sendspin client can wedge
  independently and intermittently. EMI on fixed cabling is more constant /
  correlated with mains activity, not room-hopping over hours.
- **"~50 W idle, amps won't SHDN"** — a wedged stream keeps `hw_ptr` advancing,
  so `powermanager` thinks audio is flowing and **never SHDN's that amp**. EMI
  cannot keep an amp powered. A software wedge produces *both* the noise and the
  stuck-on power. This single observation is the strongest discriminator.

### Third, separate failure mode: USB DAC firmware

The amps' USB audio interface enumerating as **"SAVITECH Corp. Bravo HD FW
Update"** is a distinct fault: a USB DAC dropping into bootloader/FW-update mode
stops being an audio device and can output garbage. Unrelated to both EMI and
dmix. Check with `lsusb` when noise occurs.

---

## What's already been done (hardware/EMI — from prior debugging)

- **Power:** replaced Pi PSU; unified Pi + amp supplies; added Schaffner FN2030
  EMI filter; checked grounding / PE continuity.
- **USB/firmware:** found devices in "SAVITECH Bravo HD FW Update" mode;
  looked into firmware recovery / bootloader behavior.
- **Internal wiring:** found open solder joints / exposed contacts; internal
  cabling originally routed *over* the amps and PSU; **re-routing/fixing cables
  to the chassis changed the noise significantly** (→ real HF/layout coupling).
- **Speaker cables:** confirmed ~20 m, unshielded, parallel to mains → antenna
  behavior suspected.

Prior conclusions (hardware lens): long cables as antennas, class-D sensitivity,
poor internal layout, EMI/HF pickup. Less likely: USB ground loops, the Pi
itself, mains EMI alone, defective boards.

Recommended hardware actions still on the table: clean internal layout, pair
+/− conductors, eliminate exposed contacts, ferrites near amp outputs, per-amp
SHDN, better connectors, output filtering if needed.

---

## Live state snapshot — 2026-06-06 (read-only, no noise produced)

- All four amps' playback streams: **`closed`** (no wedge at this instant)
- `powermanager`: **active**; correctly SHDN'd **amp1/2/3 = off** (idle),
  **amp4 = on** (always-on, no GPIO)
- 11 sendspin clients connected, all **idle** (streams closed)

→ Clean right now, consistent with an **intermittent** wedge ("over time"),
not constant EMI. Need to catch it in the act.

---

## The decisive test (do this BEFORE more hardware spend)

When a room is actively doing the radio static, read that amp's stream status:

```bash
cat /proc/asound/<amp>/pcm0p/sub0/status   # e.g. amp1
```

- **`RUNNING` + `appl_ptr 0` + `hw_ptr` advancing** → **SOFTWARE** stale-dmix
  wedge. Recovery: `sudo systemctl restart sendspin@room_<id>` (restart all
  clients sharing that amp's dmix). No ferrite will ever fix this.
- **`closed`** but amp powered and hissing → genuinely **HARDWARE / EMI** —
  the existing playbook applies.

### Planned instrumentation

- [ ] Lightweight **state-logger**: sample every amp's `pcm0p/sub0/status`
  (state/appl_ptr/hw_ptr) + `ampctl status` every few seconds to a logfile, so
  the next noise event is captured with proof instead of guesswork.
- [ ] `lsusb` watch for any device in **Savitech/Bravo FW-update** mode.
- [ ] Correlate noise timestamps with `journalctl -u 'sendspin@room_*'` (look
  for stream-end / reconnect / underflow around the noise).
- [ ] Power-up **pop**: review SHDN GPIO sequencing — assert SHDN (mute) before
  rails, release after stable; check `powermanager` + boot ordering.

---

## Open questions

- Does the radio static occur when the amp's USB input is **physically
  unplugged** (pure hardware) or only while a stream is present (software)?
- Is it ever heard on amp1/2/3 **while powermanager reports them off**? (If yes
  → hardware; an SHDN'd amp shouldn't make digital noise.)
- Does restarting the offending room's `sendspin@` clear the static
  immediately? (If yes → software, decisively.)

## References

- `CLAUDE.md` → Troubleshooting → "Loud noise or distortion from speakers"
- `memory/project_upstream_bugs.md` → sendspin #233 stale-dmix loop, watchdog notes
- `docs/2026-06-06-tv-linein-status.md` → the line-in route hit the same
  stale-dmix underflow (related symptom)

---

## Findings — confirmed 2026-06-06

The monitor caught **both** problems live, partitioning them cleanly:

### Gästebad / amp3 noise = HARDWARE (EMI)
Repro: powering amp3 on → noise in Gästebad (mono, amp3 ch3). Monitor showed
`amp3:closed/pwr=on` — **amp powered, stream closed, no digital signal**, yet
noise. So it's the amp3 output / the ~20 m Gästebad speaker cable making noise
with no input → genuine EMI/hardware. The ferrite/shielding/cable-routing
playbook is the right fix for this one. Software mitigation: keep amp3 SHDN'd
when Gästebad isn't playing (powermanager already does this), so it's only
audible during actual playback.

### amp1 "radio static" = SOFTWARE stale-dmix wedge (root cause found)
Monitor caught amp1 stuck `RUNNING/appl=0/hw=advancing/pwr=on` with `*** WEDGE ***`
for minutes — the #233 signature, live. Traced via sendspin logs to
**room_wohnzimmer**: `Stream started with codec flac (48000/24/2)` but **no audio
chunks** — lox issued a stream-start to Wohnzimmer with no PCM behind it (a
phantom stream, likely a stuck source from earlier testing). sendspin opened
ALSA `RUNNING`, dmix looped the stale buffer = noise, and the advancing `hw_ptr`
kept powermanager from SHDN-ing amp1 (→ the "amps won't idle / 50 W" symptom).

**This is the discriminator proven:** EMI cannot keep an amp powered; a phantom
stream does both the noise and the stuck-on power.

Recovery that worked: `audio/5/off` (stop Wohnzimmer in lox via :7091) **then**
`systemctl restart sendspin@room_wohnzimmer`. Restarting the client *alone* did
NOT clear it — lox re-issued the empty stream-start on reconnect, re-wedging.
You must stop the zone at the lox side first. After: amp1 `closed`, SHDN off,
monitor clean.

### Open: why did lox push an empty FLAC stream-start to Wohnzimmer?
Likely a stuck source/session (Wohnzimmer has a history of Spotify audio-key
storms — see `memory/project_upstream_bugs.md`). The lox-side "stream-start
without PCM" wedge + the post-start byte watchdog mitigation are the relevant
threads. Needs follow-up: catch which source leaves Wohnzimmer in this state.

## Log

- **2026-06-06 (later)** — Monitor caught a live amp1 WEDGE (Wohnzimmer phantom
  FLAC stream-start, no PCM). Cleared via `audio/5/off` + client restart →
  amp1 closed + SHDN off. Gästebad/amp3 noise confirmed HARDWARE (amp on, stream
  closed). Both root causes now evidenced.
- **2026-06-06** — Investigation opened. Live snapshot above: all streams
  closed, powermanager active, amp1/2/3 SHDN-off, amp4 always-on. No wedge at
  read time. Hypothesis recorded: radio-static likely software stale-dmix
  (room-hopping + amps-won't-SHDN tells); hum/pop likely hardware. Next:
  stand up the state-logger + lsusb check to catch an event.
