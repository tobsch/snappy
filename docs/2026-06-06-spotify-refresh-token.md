# Spotify refresh-token keeps getting wiped (root cause of "plays but no sound")

Status: **recurring — fix is known, durable fix (what wipes it) is OPEN.**
First fixed 2026-05-24, recurred 2026-06-06.

## Symptom

- A Spotify zone shows "playing" in the Spotify app, but **no audio reaches the
  speakers** (the sendspin/ALSA stream stays `closed`, or starts and immediately
  tears down).
- lox logs, repeatedly:
  ```
  [Content|Spotify:<account>] no refresh token configured for spotify account
  [Content|Spotify:<account>] spotify api request skipped, no access token
  [Audio|Manager] reason=replace source=spotify-connect://<deviceId> zoneId=N playback session terminated by engine
  ```

## Root cause

The Spotify account in lox config has an **empty `refreshToken`** while
`librespotCredentials` (the auth-blob used by the connect host) is still
present. Result: the connect host can *start* a session, but lox can never
refresh the **Web-API access token**, so the session can't stabilize → it churns
(`reason=replace`) → no sustained PCM.

This is the upstream amplifier of the broader Spotify storms: empty refresh token
→ bad-auth drift → account-wide `audio_key` timeouts + `reason=replace` churn →
also leaves **starved sendspin streams** that wedge the shared dmix (the amp1
"radio static" — see `docs/2026-06-06-speaker-noise-investigation.md`).

## Detect

```bash
sudo docker exec lox-audioserver sh -c 'cat /app/data/config.json' \
  | python3 -c "import json,sys; \
    [print(a.get('name'), 'refreshToken:', ('EMPTY' if not a.get('refreshToken') else f\"SET ({len(a['refreshToken'])} chars)\"), \
    '| librespotCredentials:', bool(a.get('librespotCredentials'))) \
    for a in json.load(sys.stdin).get('content',{}).get('spotify',{}).get('accounts',[])]"
```
A healthy token is ~134 chars. `EMPTY` + `librespotCredentials: True` = this bug.

## Fix (manual — OAuth, can't be done headless)

Re-authenticate the Spotify account in the **lox admin UI** (`http://<host>:7090`
→ Spotify → the account → re-login). The OAuth round-trip repopulates
`refreshToken`. Verify with the detect command (should flip to `SET (134 chars)`),
then confirm:
```bash
# auth errors should stop; reason=replace storms should drop to ~0
sudo docker logs --since 60s lox-audioserver 2>&1 | grep -iE 'no refresh token|reason=replace'
# and Spotify should produce audio again:
sudo docker logs --since 60s lox-audioserver 2>&1 | grep -i 'first pcm chunk'
```

Verified 2026-06-06: after re-auth, token `SET (134 chars)`, auth errors gone,
`reason=replace` count 0/60s, `first pcm chunk` logged, playback recovered.

## OPEN — what keeps wiping it (the durable fix)

It's now been cleared **twice** (set 2026-05-24, empty again 2026-06-06). Something
between sessions zeroes `refreshToken`. Suspects, in order:
1. **Miniserver-reconnect config rebuild** — same class as the zone-volume
   overwrite (lox issue #219): the Miniserver pushes config and a rebuild path
   drops fields it doesn't carry. Check whether `refreshToken` survives a
   Miniserver reconnect.
2. **lox restart / image pull / `docker compose up`** rewriting `config.json`.
3. Token actually expiring/being invalidated and lox blanking it.

**Tested 2026-06-06: a plain `docker restart lox-audioserver` does NOT wipe the token** (SET 134 before and after) — so suspect #2 (lox restart) is ruled out; the wiper is the Miniserver-reconnect rebuild (#1) or an image pull/recreate (#3).

To pin it: snapshot `refreshToken` now, then check it after (a) a lox restart,
(b) a Miniserver reconnect, (c) overnight. Whichever blanks it is the culprit.
Until then, expect to re-auth periodically.

## Separate, deeper issue (NOT the token)

Even with the token fixed, the connect session can hit
`failed filling up next_track ... context is not available` →
`reason=replace` churn (the librespot **context-loss / pause-resume** bug — see
`memory/project_upstream_bugs.md`, librespot PR #1713 and the reverted JS
patches). Observed 2026-06-06 at ~99 `context is not available`/60s during
startup; it eventually caught and played. That's its own thread, not solved by
re-auth.

## 2026-06-06 isolation: AirPlay works, Spotify doesn't

After the re-auth, Spotify still couldn't sustain audio (started → `appl_ptr=0`
starved stream on amp1, both Esszimmer and Wohnzimmer = account-wide). **AirPlay
on the same speakers worked immediately.** That cleanly isolates the remaining
fault: lox → sendspin → ALSA → amp → speaker chain is **healthy**; the token is
fixed (`SET (134)`, survived sendspin client restarts); the only broken part is
**Spotify Connect**, stuck in the `context is not available` / `reason=replace`
churn (librespot context-loss). So: use AirPlay meanwhile; Spotify Connect needs
the deep librespot fix, not a token re-auth. Recovery for a starved Spotify
stream: `audio/<zoneId>/off` (port 7091) + `systemctl restart sendspin@room_<id>`.

## Not the token: the 2026-06-08 "loud noise" recurrence

On 2026-06-08 Wohnzimmer + Elternbad made loud noise on Spotify Connect **with
the refresh token SET (134 chars)** — so it was NOT this bug. It was the
stale-dmix wedge fed by the context-loss churn, made worse because the
**post-start watchdog mitigation had been dropped** in the 2026-06-07 dev-image
migration. Re-applied and resolved — see
`docs/2026-06-08-spotify-connect-noise-watchdog.md`. Keep the two distinct:
empty-token = "plays but silent"; missing-watchdog = "plays as loud noise".

## References

- `memory/project_upstream_bugs.md` — "Spotify account had EMPTY refreshToken",
  the context-loss saga, lox issue #252
- `docs/2026-06-06-speaker-noise-investigation.md` — the amp1 wedge this feeds
- `docs/2026-06-08-spotify-connect-noise-watchdog.md` — the missing-watchdog
  recurrence + fix
