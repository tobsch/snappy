# Spotify Connect starts at 100% volume (OBSERVING)

Status: **OPEN — observing.** Mechanism understood; root cause shared with the
loud-noise wedge. No fix applied yet (user wants to watch it first).

## Symptom

Starting **Spotify Connect** on a zone (e.g. Elternbad) blasts the room at
**~100%** instead of the configured default, even though the maintainer added a
fix for exactly this (#287).

## Not a config problem

Per-zone volumes in lox `config.json` (2026-06-08) are correct:

| zone | volumes.default | maxVolume |
|---|---|---|
| all 11 zones (incl. Elternbad, Wohnzimmer) | **10** | 100 |

So the configured default is 10, not 100. The 100% is coming from Spotify, not
from config.

## How the #287 fix is supposed to work

In `~/lox-src-dev/src/adapters/inputs/spotify/spotifyInputService.ts` (present
and compiled in the running container — `grep -c suppressConnectVolumeUntil
/app/dist/adapters/inputs/spotify/spotifyInputService.js` → 3):

1. On Connect activation, librespot fires a `volume` event = the Spotify app's
   **picker-slider** value, often **100%** on a fresh phone session.
2. `startControllerPlayback()` arms a window:
   `suppressConnectVolumeUntil = Date.now() + connectActivationVolumeSuppressMs`
   with **`connectActivationVolumeSuppressMs = 1500`** (1.5s).
3. The `volume` handler checks `if (Date.now() < suppressConnectVolumeUntil)` →
   **swallows** the event (debug-logs, no `updateVolume`). So the Spotify 100%
   is ignored during activation.
4. Meanwhile the play-start path `onPlayerStarted()`
   (`src/application/zones/playback/playerListeners.ts`) applies the zone default
   — **but only on a "fresh start"**:
   ```
   const isFreshStart = !ctx.alert && (ctx.state.mode === 'stop' || hadPendingReset);
   const volume = isFreshStart ? getZoneDefaultVolume(ctx.config)
                               : clampVolumeForZone(ctx.config, ctx.state.volume);
   ```
5. After 1.5s, real slider moves from the phone propagate normally.

## Why it still leaks to 100% here

Same root cause as the noise wedge: the **unfixed librespot Spotify-Connect
context-loss churn** (`context is not available` → `failed filling up next_track`
→ `reason=replace`, seen live in the raw container log for zoneId 5). It breaks
both halves of the fix:

- **Volume event lands outside the 1.5s window.** The churn delays the Connect
  handshake and *re-fires* the volume event on every `reason=replace`. Any event
  arriving after 1500ms is no longer suppressed → `updateVolume(zoneId, 100)`
  clobbers `state.volume`.
- **The restart is not a clean "fresh start."** `reason=replace` is a *replace*,
  not a `stop`. So `onPlayerStarted` on the replaced session sees
  `isFreshStart === false` → it does **not** re-apply `volumes.default`, it keeps
  `ctx.state.volume` = the leaked 100%.

So the 100%-blast and the loud-noise wedge are the **same disease**: Connect
context-loss churn. #287 is sound but its fixed 1.5s window is too fragile under
churn.

## Candidate fixes (not yet applied)

1. **Strengthen the suppression** (smallest): suppress connect-volume *until the
   first stable `playing` state* instead of a fixed 1.5s, and **re-arm on each
   `reason=replace`/re-activation**. Local patch in `spotifyInputService.ts`,
   same delivery path as the watchdog (patch in `lox-patches/`, rebuild dev img).
2. **Re-apply default on connect re-activation** — treat a Spotify reactivation
   as a fresh start in `onPlayerStarted` so the default re-applies after a replace.
3. **Fix the churn** (root cause) — port burst-recovery / a context-loss
   mitigation; also fixes the noise.

## What to observe

- Does it blast 100% on a *clean* start (no churn) or only when the
  `reason=replace` storm is active? (Tells us if it's purely the window-timing
  or also the fresh-start gate.)
- Capture the raw log around a 100% start:
  ```bash
  CID=$(sudo docker inspect lox-audioserver --format '{{.Id}}')
  sudo grep -aiE 'volume|reason=replace|context is not available|started' \
    /var/lib/docker/containers/$CID/$CID-json.log | tail -40
  ```
  (Suppression logs at `debug` — bump `consoleLevel` to `debug` temporarily to
  see `suppressing connect activation volume` vs a late `updateVolume`.)
- Which zones / does it correlate with the zones that also wedge (amp1 family)?

## References

- `docs/2026-06-08-spotify-connect-noise-watchdog.md` — the shared root cause
  (context-loss churn) and the post-start watchdog
- `memory/project_upstream_bugs.md` — #287 (`f161c7a2`, 1.5s window), context-loss saga
</content>
