# Spotify Connect loud noise — post-start watchdog (re-applied; NOT a proven fix)

Status: **Watchdog re-implemented, rebuilt, deployed — but it is NOT confirmed to
fix the noise.** Corrected 2026-06-08 (see banner). The noise mechanism is open;
the watchdog guards a narrow case that has not fired in observation.

> **⚠️ CORRECTION 2026-06-08.** This doc originally claimed the noise was a
> "stale-dmix wedge" proven by `/proc/asound/.../sub0/status` showing `RUNNING`
> + `appl_ptr 0` + `hw_ptr advancing`. **That signature is wrong** — it is
> *normal shared-dmix playback*, not a wedge (confirmed: amp1 showed it while
> Wohnzimmer played cleanly; the "dead owner_pid" was a live audio-thread TID
> that `ps -p` doesn't list). So:
> - The live "wedge" reads in this doc were unreliable.
> - The watchdog targets a *real but narrow* code condition: a stream-start
>   delivering **zero PCM bytes**. In observation it fired **0×** over 13h with
>   180 context-loss events, and logs show PCM *does* flow (`first pcm chunk`) —
>   so the zero-PCM case is likely **not** the mechanism here. The watchdog is
>   cheap insurance, **not a demonstrated cure**.
> - What likely actually calmed things: the **container recreate** (fresh Connect
>   sessions) + dev's existing upstream guards (`SpotifyUnavailableLoopGuard`,
>   node-librespot 0.4.2), not this patch.
> - The genuinely-unfixed root cause is the **librespot context-loss churn**
>   (your open librespot PR #1713, which doesn't work yet). See also the volume
>   leak `docs/2026-06-08-spotify-connect-volume-default.md` — same root cause.

## Symptom

Wohnzimmer and Elternbad "failed" on **Spotify Connect** — the zone showed
playing but the speakers emitted **loud noise** (not music). Other sources
(AirPlay) were fine.

## What was actually happening

The classic **stale-dmix wedge**: lox sent the sendspin client a *stream-start
with no PCM behind it*, the client opened its ALSA device, and dmix looped the
stale prebuffer forever → audible garbage. Live proof at the time:

```
/proc/asound/amp1/pcm0p/sub0/status →
  state: RUNNING        # client opened the device
  appl_ptr: 0           # but no writer is feeding it
  hw_ptr: <advancing>   # dmix keeps reading → loops stale buffer = noise
```

The wedged substream's `owner_pid` pointed at the dead `sendspin@room_*`
process that left it RUNNING. Wohnzimmer = amp1 ch7/8; Elternbad = amp2 ch3/4.
amp1's dmix is shared by **backupkueche / esszimmer / kueche / wohnzimmer**, so
the wedge persisted on amp1 even after restarting one client.

The upstream trigger: the **librespot Spotify-Connect context-loss bug**
(`context is not available` / `reason=replace`), which is **still unfixed on the
`dev` image**. It produces empty/phantom stream-starts. Elternbad being hit too
is consistent with the account-wide nature of the churn (all Connect devices on
the one Spotify account).

The Spotify **refresh token was SET (134 chars)** during this incident — so this
was NOT the refresh-token-wipe bug
(`docs/2026-06-06-spotify-refresh-token.md`), it was purely the wedge.

## Root cause of the *regression*: a patch went missing

On **2026-06-07** lox-audioserver was migrated from the beta ghcr image (with
file-copy `/app/dist` patches) to a **locally-built `dev` image**
(`lox-audioserver:dev-local`, see `memory/project_upstream_bugs.md`). The dev
image is a clean build from upstream source — so **all the old file-copy patches
were dropped**. Verified: zero `[local-patch]` markers in the running container.

The dropped patch that mattered here was the **`sendspinOutput.js` post-start
watchdog** — the safety net that tore down a started-but-starved stream before
dmix could loop it. dev brought native equivalents of several other patches
(#273 format-align, #287 volume default, satellites, AirPlay) but **not** this
one, and **not** a context-loss fix. Result: trigger still present, mitigation
gone → loud noise returned.

A separate aggravator: an uncommitted `speaker_config.json` change had bumped
every room's `max_volume` from `0.25` → `1.0` (4× the ceiling), which would make
any wedge 4× louder. Reverted.

## The fix

Re-implemented the post-start watchdog against dev's **refactored**
`SendspinOutput` (per-client senders / satellites — the old compiled patch did
not apply). In `~/lox-src-dev/src/adapters/outputs/sendspin/sendspinOutput.ts`:

- new field `startWatchdogTimer` + `START_WATCHDOG_MS = 5000`
- local `sawFirstFrame`, set in `emitFrame` whenever a frame can reach the client
- after `startStream` arms the stream (`void consumeStream()`), set a 5s timer;
  if the stream token is still current and `sawFirstFrame` is false → log
  `Sendspin post-start watchdog: no PCM after stream start; tearing down`,
  `teardown()`, `scheduleRestart()`
- `teardown()` clears the timer

The window is safe: a healthy stream delivers frame #1 well under 5s (the lead
gate is a no-op for the first frame), so only a truly starved start trips it.

Markers: `// [local-patch]` (5 sites). Image rebuilt as
`BUILD_VERSION=4.0.0-dev-0fdc879-watchdog`, deployed via `docker compose up -d`.

## Verification (2026-06-08)

- `tsc` passed in the image build (exit 0).
- `docker exec lox-audioserver grep -c 'post-start watchdog' /app/dist/.../sendspinOutput.js` → ≥1
- Container healthy, port 7090 up, refresh token survived recreate (`SET 134`).
- All amps `closed`, no wedge.

## Durability

The dev image survives container recreate, but a `git pull` in `~/lox-src-dev`
drops the working-tree edit. Source of truth + re-apply instructions:
**`~/multiroom-tooling/lox-patches/dev-sendspin-poststart-watchdog.patch`** and
`lox-patches/README.md` (host-local; `lox-patches/` is gitignored). After any
pull: `git apply` the patch, rebuild, `docker compose up -d`.

## Manual recovery (if a wedge ever recurs before the watchdog catches it)

```bash
# identify the wedge + which dead client owns the amp1 substream
cat /proc/asound/amp1/pcm0p/sub0/status        # RUNNING / appl_ptr=0 / hw advancing
# stop the zone LOX-SIDE first (client restart alone re-wedges — lox re-issues the empty start)
curl -s localhost:7091/audio/<zoneId>/off
systemctl restart sendspin@room_<id>
```
Lox zone ids (2026-06-08): Esszimmer=4, Wohnzimmer=5, Backupküche=8, Küche=9,
Elternbad=3. amp1 is shared — if needed, recover all amp1 clients together.

## Still open (follow-up)

> **Correction 2026-06-08:** an earlier version of this list said to "re-apply the
> Spotify burst-recovery patch" on dev. That was wrong — burst-recovery is your
> issue **#252** (hourly audio-key storms), filed as **PR #257**, already fixed
> upstream in **node-librespot 0.4.2** which dev ships. It is NOT the churn
> behind this noise and should NOT be re-applied.

- **The real root cause: librespot context-loss churn** (`context is not
  available` / `reason=replace`). Your attempt is **librespot PR #1713** (OPEN,
  WIP) — per your own notes it does not yet fix the symptom. This is the only
  lever that would address both the noise AND the 100%-volume leak (#287).
- **Confirm the noise mechanism before patching further.** Don't trust `/proc`
  substream status (see banner). Catch it by ear with no source playing, and
  capture the raw container log (`context is not available`, `reason=replace`,
  `first pcm chunk`, `Sendspin output format mismatch`) around the event.
- **Watchdog:** leave it in (harmless insurance) but don't credit it until it
  actually fires (`grep 'post-start watchdog'` in the container log).
- ~~Wohnzimmer `max_volume` 1.0~~ — pre-existing; only relevant if the noise is
  truly a stale loop (now unconfirmed). Low priority.

## References

- `memory/project_upstream_bugs.md` — dev migration + watchdog re-apply note
- `docs/2026-06-06-spotify-refresh-token.md` — the related (but distinct) token bug
- `docs/2026-06-06-speaker-noise-investigation.md` — original amp1 wedge investigation
- `lox-patches/README.md` — re-apply procedure
</content>
