# librespot context-loss self-heal (the real fix attempt for Spotify Connect churn)

> **SUPERSEDED as the noise cause (2026-06-10):** the recurring Küche noise was
> later traced to a **format-mismatch engine restart** (44.1k→48k `reason=replace`
> → starved stream → dmix loop), *not* this librespot context-loss. Candidate fix:
> **WIP draft PR lox-audioserver#289** (`fix/sendspin-connect-format-align`). This
> librespot self-heal stays deployed for separate observation but is **not** the
> fix for the beep. See `memory/project_upstream_bugs.md`.

Status: **BUILT + DEPLOYED to the running container 2026-06-10; awaiting live
validation.** This is a hypothesis-driven fix at a newly-identified seam. It has
NOT yet been proven on a real reproduction (the bar #1713 never cleared) — do
not mark it solved until the `re-hydrating from player_state` log is seen
firing and the `context is not available` storm stops in practice.

## The symptom (what the user actually hits)

On Spotify **Connect**, concentrated in one zone at a time (seen live in Küche,
zoneId 9, device `88AEDD68106A`): **noise, volume jumping around, and the wrong
song playing**. Live log during an episode (2026-06-10 07:26 CEST, ~19 s burst):
```
72×  couldn't load context info because: context is not available
48×  failed filling up next_track during stopping: Invalid state { context is not available }
 1×  reason=stop  source=spotify:track:… zoneId=9
 1×  reason=replace source=spotify-connect://88AEDD68106A zoneId=9
```
The `failed filling up next_track` is literally why the **wrong song** plays
(librespot can't resolve the queue → falls back to a stale track); the starved
stream is the **noise**; the churn throws the **volume**. All three are one bug.

## Root cause (traced in librespot source)

librespot source at `~/librespot-fix` (dev `33bf3a7`, core 0.8.0 — the exact
commit node-librespot 0.4.2 vendors). lox runs **one librespot Connect instance
per zone** (11 devices on one account).

The failure is in `connect/src/spirc.rs::handle_connection_id_update()` (the
dealer-reconnect path). On reconnect it fetches the cluster, then gates:
```rust
if !cluster.active_device_id.is_empty() || !same_session {
    info!("active device is <{}> …");
    return Ok(());          // ← early return, no context re-hydrate
}
```
It only re-resolves context (`handle_transfer`) when the device is *inactive and
idle*. In the failure case — **we reconnect as the still-active device but our
local context was wiped** (a prior dealer drop ran `handle_disconnect` →
`context_resolver.clear()`, or our session was recreated) — `active_device_id`
is our own id, so it **returns early and sits there active-but-contextless**.
The controller's next play/stop then drives `handle_stop()` →
`reset_playback_to_position(None)` → `context is not available` churn + stale
track.

**Why PR #1713 failed:** it stashed `context_uri` in `reset_context` before the
clear — but `context_uri` is already empty by then, so nothing to recover. Wrong
seam. The right seam is here: `cluster.player_state` **still carries the
`context_uri`** on reconnect (`state/transfer.rs:99`).

## The fix

`connect/src/spirc.rs`, inside the early-return branch of
`handle_connection_id_update`: if **we** are the active device, our local
context is empty, and the cluster's `player_state.context_uri` is non-empty,
re-hydrate via the existing `load_context_from_uri()` before returning. Minimal,
self-contained, only acts in the exact broken state. Patch:
`lox-patches/librespot-context-selfheal.patch` (34 lines, spirc.rs only).

> Scope note: this restores a *resolvable context* (kills the churn). It does NOT
> hand-restore exact track/position — the controller re-syncs that. If "wrong
> song" persists briefly after the heal fires, that's the follow-up (also set the
> current track from `cluster.player_state.track`).

## What was NOT changed, and why

- **lox JS (`spotifyInputService.ts`) left untouched.** dev already neutralizes
  the old "recreate engine on token rotation" trigger: `ensureNativeSession`
  compares a stable **credentials-hash** (`credHash` path, lines ~1214-1216)
  because `credentialsPayload` is populated from the account's stored
  `librespotCredentials`. So the JS amplifier the 2026-05 analysis worried about
  is already handled on dev; the remaining churn is genuine librespot
  dealer-drop context-loss → which this patch targets. Adding the old
  "no-cred branch → true" patch would be redundant and risky.
- **PR #1713 closed** 2026-06-10 with a comment explaining the wrong-seam
  diagnosis and that a fresh PR will target `handle_connection_id_update` once
  validated.

## Build + deploy (how it was done; how to redo)

Source: `~/librespot-fix` (patched). Build harness: `~/node-librespot-build`
(node-librespot **v0.4.2**, `b35c711`).
```bash
# 1. patched librespot → node-librespot's vendored path
rsync -a --exclude=.git --exclude=target ~/librespot-fix/ ~/node-librespot-build/librespot-dev/
# 2. build the napi binary (release; ~slow on the Pi)
cd ~/node-librespot-build && npm install && npm run build:native
#    -> dist/librespot_addon.node (ARM aarch64). Verify the patch is in it:
strings dist/librespot_addon.node | grep 're-hydrating from player_state'
# 3. deploy into the LINUX prebuild slot (NOT darwin-arm64 — container is linux):
BASE=/app/node_modules/@lox-audioserver/node-librespot/prebuilds/linux-arm64-gnu
sudo docker exec lox-audioserver sh -c "cp $BASE/librespot_addon.node $BASE/librespot_addon.node.orig"
sudo docker cp ~/node-librespot-build/dist/librespot_addon.node "lox-audioserver:$BASE/librespot_addon.node"
sudo docker restart lox-audioserver
```
Host copies for durability: `lox-patches/librespot_addon.node.context-selfheal`
+ `lox-patches/librespot-context-selfheal.patch`.

## Durability

This is a **file-copy into the running container — lost on image recreate /
`docker compose up --force-recreate`.** If it validates, bake it into the dev
image build (`~/lox-src-dev` Dockerfile pulls node-librespot; replace the
prebuilt binary or vendor the patched node-librespot). Rollback: the original is
at `…/linux-arm64-gnu/librespot_addon.node.orig` in the container.

## Test plan / how to validate

Monitor: `/tmp/selfheal-monitor.sh` → `/tmp/selfheal-test.log` (captures
context-loss / next_track / reason=replace / `re-hydrating` with timestamps).

Reproduce on Küche: play Spotify, then (a) let it idle so the dealer drops, then
play again; or (b) move the session between rooms and back. Expected on the next
episode:
- **PASS:** `re-hydrating from player_state` appears AND the `context is not
  available` / `failed filling up next_track` storm does not sustain; right song
  continues.
- **PARTIAL:** heal fires but brief wrong-track before app re-sync → add the
  track-restore follow-up.
- **FAIL:** churn recurs with no `re-hydrating` line → trigger path differs from
  the hypothesis; re-trace from the new log.

## Update 2026-06-10: verdict INCONCLUSIVE — patch kept, tracing at debug

Correction: I initially concluded the patch "didn't work" because
`re-hydrating from player_state` fired **0×** while two context-loss bursts
recurred (05:57 + 06:32 UTC) — and reverted to stock. **That was premature.**
Those bursts **self-recovered and the user reported no actual problem in that
window**, so the real audible failure case was never observed with the patch in
place. 0 fires during non-failures proves nothing. Re-deployed the patched
binary; the proper experiment is to **leave it running with debug on and wait
for a real, user-noticed issue**, then read the evidence:
- issue occurs **and** `re-hydrating` fired → patch engaged (helped or not?);
- issue occurs **and** no `re-hydrating` → condition mismatch, debug trace shows
  the true trigger (likely `context_uri` present but resolve returns "not
  available" — a different seam than the empty-context gate);
- long clean stretch → suggestive (not proof) the patch is preventing it.

Current state: **patched binary loaded** (`linux-arm64-gnu/librespot_addon.node`,
stock backed up in-container as `…/librespot_addon.node.stock`). **NOTE: a
`docker compose up --force-recreate` or image pull wipes the file-copied patch**
— only `docker restart` preserves it. Re-deploy from
`lox-patches/librespot_addon.node.context-selfheal` if the container is recreated.

**Debug-capture mode is ON (temporary)** to catch the real trigger live:
- `system.logging.consoleLevel` = `debug` in `~/lox-audioserver/data/config.json`
  (was `warn`).
- Docker log rotation added to `~/lox-audioserver/compose.yaml`
  (`json-file`, max-size 150m × 12 ≈ 1.8 GB) so debug can't fill the disk.
- Persistent filtered trace: systemd `lox-churn-trace.service`
  (`/usr/local/bin/lox-churn-trace.sh`) → `/var/log/lox-churn-trace.log`
  (re-attaches across container restarts; drops mDNS/frame spam).

When an episode happens: note the rough time, then read
`/var/log/lox-churn-trace.log` and grep the full debug in the docker json log
around that timestamp to find what *precedes* `couldn't load context info`.

**Revert when done** (don't leave debug running indefinitely):
```bash
sudo systemctl disable --now lox-churn-trace.service
sudo rm /etc/systemd/system/lox-churn-trace.service /usr/local/bin/lox-churn-trace.sh /var/log/lox-churn-trace.log
# config.json: set system.logging.consoleLevel back to "warn" (stop→edit→up -d)
# compose.yaml: optionally drop the logging: block (rotation is harmless to keep)
```

## References

- librespot source: `~/librespot-fix` (dev `33bf3a7`)
- closed PR: librespot-org/librespot#1713
- the symptom thread: `docs/2026-06-08-spotify-connect-noise-watchdog.md`,
  `docs/2026-06-08-spotify-connect-volume-default.md` (#287, same root cause)
- `memory/project_upstream_bugs.md`
</content>
