# Speaker noise investigation (radio static / hum / pop)

Status: **RADIO-STATIC LIKELY SOLVED 2026-06-10 — root cause = Pi power supply
(non-isolated 24V→5V buck on the shared PSU) injecting noise via the USB ground.
Fix = clean/separate (or galvanically isolated) Pi 5V supply.** Pending 2-3 day
endurance confirmation. Hum/pop = separate hardware items. Living doc — newest
findings at the top of the **Log**.

Goal: eliminate persistent noise on the multiroom speakers. The **radio-like
static** was the unsolved one for a long time; the diagnostic chain (swap test →
USB test → ferrites useless → external Pi PSU = silent) pinned it to the Pi's
power/USB-ground path.

### Open TODO (2026-06-10, user plan — done by ~Sunday)
1. **2-3 day endurance test** — confirm the radio-static stays gone with the
   external/clean Pi supply.
2. **Fan controller** — replace the always-on housing fans with a controller that
   spins them up only when needed (e.g. temp threshold). Fans currently permanent;
   Pi now steady 38-43°C (was 85°C grilling).
3. **Re-cable + clean rebuild** — swap cables, tidy internal layout (keep USB away
   from speaker leads, short/twisted output pairs), permanent isolated 24→5V DC-DC
   for the Pi (or dedicated Pi supply).
4. Connect the three GAB8 **SYNC pins board-to-board** is moot — the control header
   pin 3 is **NC** on this board (see "Control header" note); nothing to do.

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
| **Radio static, amp powered, no playback** | **CONFIRMED amp-side (GAB8 / its USB input / shared power) — 2026-06-10 swap test.** NOT the cable/speaker | **No — and NOT cable shielding either; it's in the amp chain** |

> **Update 2026-06-10:** the radio-static is now confirmed **amp-side hardware** by
> a swap test (BT amp on the same Elternbad speaker+cable = silent). The earlier
> "software stale-dmix" suspicion for this symptom is **dropped** (that was the
> separate Spotify-Connect noise — see the (A)/(B) split below). Cable-as-antenna
> is **refuted**. Remaining question: GAB8 board vs its USB-audio input vs shared
> 24 V PSU/ground. See Log.

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

> **⚠️ RETRACTED 2026-06-08 — this test is WRONG.** The `RUNNING` + `appl_ptr 0`
> + `hw_ptr advancing` reading was treated below as the stale-dmix wedge
> fingerprint. It is **not**. On a *shared* dmix that exact signature is what
> **healthy playback** looks like:
> - there is only ONE hardware substream (`pcm0p/sub0`) for the whole dmix;
> - its `owner_pid` is the **audio thread's TID** of whichever client first
>   opened the dmix — often a high TID that `ps -p` won't list (looks "dead" but
>   isn't; check `/proc/<tid>` exists / `cat /proc/<tid>/status` → `Tgid`);
> - `appl_ptr 0` + `hw_ptr advancing` is the dmix master's normal state while
>   real audio plays.
>
> Confirmed live 2026-06-08: amp1 showed exactly this signature **while
> Wohnzimmer was playing music cleanly**. So the `/proc` substream status does
> **not** discriminate wedge from healthy playback, and earlier "it's wedged
> now" calls based on it were unreliable (and at least once interrupted real
> playback — Esszimmer).
>
> **The only reliable wedge test is your ears + source state:** do you hear
> garbage *while no zone is intentionally playing through that amp*? Cross-check
> whether any sendspin client on that amp has a live stream
> (`journalctl -u 'sendspin@room_*'`) and whether lox is sending a real source.
> A true detached stale-loop would corrupt the shared mix for *every* room on
> the amp — if one room plays cleanly, there is no active wedge.

~~When a room is actively doing the radio static, read that amp's stream status:~~

```bash
cat /proc/asound/<amp>/pcm0p/sub0/status   # NOT a reliable wedge test — see above
```

- ~~`RUNNING` + `appl_ptr 0` + `hw_ptr` advancing → SOFTWARE stale-dmix wedge~~
  → **also normal healthy playback. Do not use as a discriminator.**
- **`closed`** = the dmix has no clients attached at all (nothing playing on
  that amp). If the amp is powered and hissing with the dmix `closed` → genuinely
  **HARDWARE / EMI** — the existing playbook applies.

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

> **⚠️ PARTIALLY RETRACTED + RE-SCOPED 2026-06-08.** Two DISTINCT noise sources
> were conflated here — keep them separate:
>
> - **(A) Connect noise** — only during **Spotify Connect** playback. Software,
>   in the Spotify path (proof that holds: **AirPlay on the same speakers is
>   clean**). Root cause = librespot context-loss churn. This is its OWN topic:
>   `docs/2026-06-08-spotify-connect-noise-watchdog.md` +
>   `docs/2026-06-08-spotify-connect-volume-default.md` (#287) + librespot PR
>   #1713. **Not** this doc's subject.
> - **(B) Permanent EM-noise** — the radio-static/hum present *regardless of
>   playback* (amp powered + stream `closed` + hissing). Genuine HARDWARE/EMI.
>   **This** is what this doc is about.
>
> This "amp1 radio static = software wedge" finding wrongly tried to explain (B)
> as (A). Also: the `RUNNING/appl=0/hw=advancing` "signature" is NOT a wedge
> indicator (it's normal shared-dmix playback — see "The decisive test"). The
> only Connect-side signal that still holds is the sendspin-log `Stream started
> ... but no audio chunks`, but even that doesn't prove a detached stale loop.
> Net: the permanent radio-static is hardware (B); the Connect noise is separate
> (A); the `/proc` discriminator is void.

Monitor caught amp1 stuck `RUNNING/appl=0/hw=advancing/pwr=on` with `*** WEDGE ***`
for minutes — ~~the #233 signature, live~~ (but see retraction: that /proc state
is also normal playback). Traced via sendspin logs to
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

> **ANSWERED + MITIGATED 2026-06-08** — see
> `docs/2026-06-08-spotify-connect-noise-watchdog.md`. The empty stream-start
> comes from the **librespot Spotify-Connect context-loss bug** (still unfixed
> on the dev image). The mitigation (the **post-start watchdog**) had been LOST
> in the 2026-06-07 dev-image migration; it was re-implemented for dev, rebuilt,
> and deployed. So the amp1-wedge software root cause now has its safety net back.

## Log

- **2026-06-10 — RADIO-STATIC SOLVED: it's the Pi power supply (via USB ground).**
  Decisive test: gave the Pi a **separate external 5V supply** (instead of the
  non-isolated 24V→5V buck on the shared Mean-Well) → **noise gone.** Power stayed
  clean (`throttled=0x0`, no under-voltage). Chain that led here: swap test
  (amp-side) → USB-unplugged (USB is the carrier) → 3× ferrites = **zero effect**
  (rules out common-mode → it's capacitive/ground) → external Pi PSU = silent.
  Root cause: the cheap buck + shared ground put switching/ground noise on Pi
  5V/GND → onto the **USB ground** → into the amps' audio = "radio static".
  **Permanent fix:** isolated 24→5V DC-DC (keeps single PSU) OR a dedicated clean
  Pi supply. Pending 2-3 day endurance confirmation (see TODO at top). Control
  header note (from official Sure/Wondom GAB8 manual): JST-PH 4-pin =
  **1 SHDN (active-low), 2 MUTE (active-low), 3 NC, 4 GND**; only SHDN→GPIO and
  GND→Pi-GND are wired; MUTE & NC stay open. SHDN GPIOs moved to **amp1=GPIO14/Pin8,
  amp2=GPIO15/Pin10, amp3=GPIO18/Pin12, common GND=Pin6** (GPIO14/15 are UART pins
  but safe here — Pi-5 console is on the separate ttyAMA10 debug port, not GPIO14/15).
  Verified by `ampctl` rotation test (each amp powers correctly). GND wires at the
  header are **yellow** (non-standard — labelled).
- **2026-06-10 — Lead suspect now: long / COILED class-D output cables.**
  Reasoning: a class-D output carries HF switching residual (~hundreds of kHz +
  harmonics); a **coiled** output lead is an efficient loop antenna for it →
  radiates → couples into the sensitive input/USB leads → amplified = the
  "radio static". Coiling also raises series inductance (can degrade the output
  filter). Fits all evidence (swap test = amp-side; photo = bundled/coiled;
  old "re-routing changed the noise"). **Actions: never coil excess output
  lead** — shorten, or lay in a loose zig-zag/serpentine (not a round coil);
  twist +/− tightly; keep short + away from USB/input. **Cheap tests:** (a) at
  ONE amp uncoil/shorten the output lead and listen for the hiss to drop; (b)
  the USB-unplugged test still discriminates input-coupling (→ separate/shield
  input) vs pure output radiation (→ uncoil/twist/filter).
- **2026-06-10 — Context: Raspberry Pi was thermally killed ("grilled").** Ran
  hot at **85 °C with active throttling** (`throttled` current-throttle bits set)
  inside the closed amp chassis with the class-D amps. SD/software survived on the
  replacement; all amps re-detected + udev re-mapped (see
  `devconfig/99-wondom-gab8.rules`, verified paths 2026-06-10). **Fix in
  progress:** 3 large fans on a step-down (buck), permanently on (power
  negligible ~6-9 W; watch the buck's own EMI near audio-input cables). Target
  < 60-65 °C so throttling — a possible co-cause of the sendspin audio
  timing/underrun glitches — is off the table. SHDN GPIOs: amp1=GPIO27/Pin13,
  amp2=GPIO22/Pin15, amp3=GPIO17/Pin11 (active-low) + common GND to a Pi GND pin.
- **2026-06-10 — Photo review of the GAB chassis → internal cabling/layout is the
  prime suspect.** Open-chassis photo shows the class-D amp boards with all wiring
  **bundled and routed over the boards/heatsinks/fans**: yellow/black power+output
  pairs, thick black cables, the USB-audio dongle (green LED) + USB leads, and
  white runs all cross each other and the amps. Coiled excess cable present. No
  separation of output / input / power; unshielded internal output leads to the
  green terminal blocks. Class-D output residual (~hundreds of kHz) radiates from
  the output stage + leads → couples along the bundle → carried down the (clean)
  in-wall cable to the speaker. Matches the old "cabling over amps/PSU" finding.
  **Actions (cheap→harder):** (1) separate + shorten speaker-output leads, route
  away from USB/power, tightly twist +/−, no coils; (2) move USB-audio cables off
  the amp outputs + clip-on ferrite per USB lead; (3) uncoil excess cable; (4) if
  still hissing, small LC/ferrite output filter on the speaker leads. The
  USB-unplugged test still discriminates USB-input noise vs output-stage radiation.
- **2026-06-10 — SWAP TEST: noise is amp-side, NOT the cable/speaker (big result).**
  Connected a **separate Bluetooth amp to the Elternbad speaker** (same speaker,
  same ~20 m in-wall cable that hissed when GAB8 amp2 was on) → **zero noise.**
  Only the amplifier changed → the persistent radio/hiss originates on the **GAB8
  amp side, not the in-wall cable or the speaker.** **Refutes the "long unshielded
  cable = antenna" hypothesis** — no in-wall rewiring needed. Caveat: the BT amp
  changed three things at once vs the GAB8 (amp board, **input** = BT vs
  USB-from-Pi, **power** = own supply vs shared Mean Well 24 V + GPIO SHDN), so
  "amp-side" = the GAB8 board **or its USB-audio input or its shared power/ground**
  — not yet isolated further. Next narrowing: (a) GAB8 on a separate/isolated PSU,
  (b) GAB8 fed from a different USB source / with a USB isolator, (c) listen with
  USB unplugged but amp powered. Whichever still hisses is the culprit layer.
- **2026-06-06 (later)** — Monitor caught a live amp1 WEDGE (Wohnzimmer phantom
  FLAC stream-start, no PCM). Cleared via `audio/5/off` + client restart →
  amp1 closed + SHDN off. Gästebad/amp3 noise confirmed HARDWARE (amp on, stream
  closed). Both root causes now evidenced.
- **2026-06-06** — Investigation opened. Live snapshot above: all streams
  closed, powermanager active, amp1/2/3 SHDN-off, amp4 always-on. No wedge at
  read time. Hypothesis recorded: radio-static likely software stale-dmix
  (room-hopping + amps-won't-SHDN tells); hum/pop likely hardware. Next:
  stand up the state-logger + lsusb check to catch an event.
