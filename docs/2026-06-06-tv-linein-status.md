# TV / Line-In → speakers — status (PARKED 2026-06-06)

Goal: get the TV audio (wired into the C-Media USB audio adapter = card **amp4**,
the device with a capture input) playing through the **Wohnzimmer** speakers.

**Current state: PARKED.** The capture side works; getting it to the speakers
does not work cleanly yet. Nothing is active or making noise.

## What's parked / safe state

- `lineinpipe@linein.service` — **stopped + disabled** (won't run, won't auto-start on boot).
- `speaker_config.json` → `inputs.linein` — retained, `autostart: false`.
- lox `data/config.json` → `inputs.lineIn.inputs[]` still has the `linein` entry
  (harmless while the bridge is off: selecting it in Loxone just shows "No
  Signal", no noise). Remove it later if you want it gone from the Loxone source
  list (needs a lox stop→edit→start).
- amp4 capture mixer ('Mic') was set to **0 dB** (was clipping at the maxed
  +30 dB). This resets to default on amp4 power-cycle — not yet persisted.

## What works

- **Capture**: TV signal is present and clean. Measured live on amp4 line-in:
  strong signal (was clipping at +30 dB gain → fixed to 0 dB, RMS ~2944, no clip).
- **Bridge + lox exposure**: `lineinpipe` streams PCM to lox's TCP ingest
  (`127.0.0.1:7080`) and heartbeats `/api/linein/<id>/bridge-status` so lox marks
  it connected. `GET :7090/api/linein` and Loxone `:7091/audio/cfg/getinputs`
  both return "USB Line-In". (See `CLAUDE.md` "Audio Inputs" + commit `93c9f7b`.)

## What does NOT work — and why

### Path A: line-in → lox → sendspin → speakers (the "proper" multiroom path)

Triggering `audio/5/linein/linein` (Wohnzimmer = zone 5) produced **a loud hum,
not TV audio**. Root cause from `sendspin@room_wohnzimmer` logs:

```
Audio format: pcm 48000Hz/24-bit/2ch
Stream STARTED: 8 chunks, 0.20 seconds buffered
Audio underflow detected; requesting re-anchor
Cleared audio queue after underflow
... (loops forever)
```

sendspin started, buffered 0.2 s, **immediately starved, and looped** — lox
wasn't feeding the live line-in steadily enough. Each underflow left amp1's dmix
substream `RUNNING / appl_ptr=0 / hw_ptr advancing` (the known stale-dmix
signature, see `memory/project_upstream_bugs.md`), so dmix looped a stale buffer
= the hum. A live line-in is the *hardest* case for the sendspin+dmix path (it's
continuous real-time, no buffer to draw ahead from) and hits the same fragility
that already affects Spotify here. Likely contributor: **double resample**
(card 48k → bridge 44.1k → lox → sendspin 48k).

Also: even if fixed, this path adds **latency** (capture → TCP → lox → sendspin →
ALSA → amp) → lip-sync lag, bad for TV.

### Path B: direct ALSA loop (chosen direction) — works, but needs a volume knob

`alsaloop -C plughw:amp4 -P room_wohnzimmer -r 48000 -c 2 -f S16_LE -t 50000 -S 4`

- **This WORKED** — TV audio came through the Wohnzimmer speakers, low latency,
  no underflow. `-S 4` (samplerate sync) handles the clock drift between the two
  independent USB clocks (amp4 capture vs amp1 playback).
- **Problem: too loud.** It plays through `room_wohnzimmer`, whose softvol
  (`vol_wohnzimmer_left/right`) was at **100% / -1.35 dB** and `global.max_volume`
  is **1.0** → full scale. The TV source is hot.
- **Coexistence**: `room_wohnzimmer` goes through **dmix** (software mixing), so
  it does NOT exclusively lock the speakers — lox/sendspin can still play; if both
  are active they **mix** (sum). In practice run the TV loop as a toggle.
- The Wohnzimmer room softvol is shared with lox playback, so the Loxone
  Wohnzimmer volume slider also attenuates the TV loop live. Open question: give
  the TV loop its **own** softvol (independent of music volume) vs. share the room
  softvol.

## To resume (Path B — the chosen direction)

1. Decide volume model: shared room softvol vs. a dedicated `tv_<room>` softvol
   (would add to `generate_alsa_config.py` so it survives asound regen).
2. Wrap the alsaloop command in a toggle service, e.g. `tv-wohnzimmer.service`
   (start when watching TV, stop otherwise). Tune `-t` (latency) vs xruns.
3. Persist the amp4 capture 0 dB gain (like playback `amp-volume.service`).
4. Decide whether to remove the lox `inputs.lineIn` entry + park/keep the
   `lineinpipe` bridge (Path A) since Path B bypasses lox entirely.

## Related

- Upstream bug **lox-audioserver#286** — admin UI "Failed to load line-in
  bridges" (`/admin/api/linein/*` routes unregistered in 4.0.0-beta.13). The
  offline/error shown on lox's admin Line-In page is this bug, not our config.
- Tooling-side inputs feature: commits `215f8e0` (feature) + `93c9f7b` (heartbeat).
- Original design notes: `docs/2026-06-05-inputs-plan.md`.
