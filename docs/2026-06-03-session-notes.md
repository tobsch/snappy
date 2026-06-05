# Session notes — 2026-06-03

End-to-end recap of what was broken, what was fixed, and what's still open.

## Resolved during this session

### 1. Test sounds in the webui were silent (or beeping instead of playing)

**Cause chain**:
- The webui's `play_chime` / `play_tts` / `play_room_stereo` invoke `aplay` directly, which bypasses sendspin's WebSocket. The external `powermanager.sh` only wakes amps when sendspin bytes flow → tests fired into powered-down amps → silence.
- When an amp *was* on, amp1 sometimes had a residual `RUNNING / appl_ptr=0` dmix loop from `sendspin` #233 → test produced the stale beep instead of the chime.

**Fix** — `webui/services/audio.py` (commit **9b2b048** "webui: auto-power amp for test sounds"):
- New `_ensure_amp_on(amp)` calls `ampctl on <amp>` best-effort before each test.
- 100 ms settle so the amp's mute-release completes before the first sample.
- `play_room_stereo` powers both amps in parallel (handles cross-device stereo).
- Belt-and-suspenders: also runs `amixer -c <amp> sset PCM 100%` to defeat the GAB8 hardware-mixer drift to 57%/−18 dB that bites after some power cycles (the udev rule misses certain reconnect paths).

### 2. amp3 test sounds were inaudible (the "beep works on amp1, not amp3" puzzle)

**Cause**: amp3's USB-Audio PCM master had drifted to **57 % (−18 dB)** while amp1/amp2 were at 100 %. The chime was reaching the amp correctly — just 18 dB quieter than intended. The amp-volume.service had set all three to 100% on boot but didn't re-fire when amp3 was power-cycled.

**Fix**: rolled into the `_ensure_amp_on` change above — every webui test now resets the target amp's PCM master to 100 % so this stops being a surprise.

### 3. Spotify Connect default volume on a zone always loud

**Investigation only** (no change applied):
- lox config has per-zone `volumes.default: 10`. It IS applied on play-start (`playerListeners.js:35-36, 98-101`).
- But on Spotify Connect activation, librespot fires a `volume` event reflecting the Spotify client's device-picker slider, which `spotifyInputService` forwards into the zone, clobbering the default. Hence "always loud".
- Spotify Connect doesn't reliably remember per-device volume in the picker, so "just set it once" isn't a real fix. The clean fix is a small lox patch (suppress the first volume event per session) — deferred at the user's request.

### 4. Global TEST VOL slider in the rack header (default 75 %)

`webui/templates/amplifiers.html` + `static/css/style.css` (commit **ec05ebd**):
- New slider in the rack-header controls between TEST CHIME/TTS toggle and AMPS toggle. Range 0-100, default 75.
- Persisted in `localStorage['testVolume']` so it survives reloads.
- Replaces the per-speaker live-volume gain that was previously piped into `/api/test/*` — all test calls (channel and room) now send this single value.

### 5. Per-amp GPIO is now configurable (UI + schema)

`ampctl`, `powermanager/powermanager.sh`, `speaker_config.json`, `webui/{services,routers,templates,static/css}` (commit **525073d**):
- New schema: `amplifiers.<id>.gpio` (int, optional) in `speaker_config.json`. Absent/null = "no SHDN line wired" → amp is treated as **always-on**: `ampctl status` returns `"on"`, on/off are no-ops, `powermanager.sh` skips it entirely.
- `ampctl` rewritten to read GPIO from `speaker_config.json` (was a hardcoded `AMP_GPIO` array). Now lives in-repo at `./ampctl` and is installed to `/usr/local/bin/ampctl`. JSON output format preserved for powermanager compatibility.
- `powermanager.sh` builds `CARDS` dynamically from `speaker_config.json`, filtering to amps with a configured `gpio`.
- WebUI: each amp module's faceplate shows `GPIO: <n>` (or `—`), double-click → modal to edit (0-63 or blank for always-on); saves via `PATCH /api/config/amps/<id>`. Add-Amp form gained an optional GPIO field.
- Existing amp1/2/3 mapping (27/22/17) was seeded into `speaker_config.json` so behavior is bit-for-bit unchanged.

### 6. Küche stopped playing → diagnosed two distinct issues

**a) librespot context-loss burst** (the recurring, well-known one):
- Log showed the classic `couldn't load context info because: context is not available` flood followed by `reason=replace`. Same pattern as PR #1713 (which didn't land cleanly in librespot — the binary patch was reverted earlier).
- Recovery: `docker restart lox-audioserver` (no permanent fix here).

**b) Container then failed to restart entirely** with `ExitCode 128`:
```
error gathering device information while adding custom device
"/dev/hidraw1": no such file or directory
```
- Root cause: `compose.yaml` mapped `/dev/hidraw0/1/2` explicitly. Docker validates each `devices:` mapping at start, so **one amp's USB dropping out (`amp1` → `/dev/hidraw1` gone) crashed the whole container**.
- lox-audioserver doesn't actually use hidraw — `grep -r hidraw /app/dist /app/node_modules` returned nothing. The mappings were dead weight.

**Fix** (host-local — `~/lox-audioserver/compose.yaml`, not in this repo):
```yaml
devices:
  # /dev/bus/usb is all lox-audioserver needs (USB Audio Class for the GAB8s).
  # We used to pass /dev/hidraw0/1/2 too, but the app doesn't use hidraw at all
  # and Docker refuses to start the container if any mapped device is missing —
  # so a single amp disconnect (USB drop / power glitch) would crash the whole
  # container. Removing them makes the container resilient to amps coming and
  # going; lox-audioserver picks up the present amps via the USB bus.
  - /dev/bus/usb:/dev/bus/usb
```
- Container now starts regardless of how many amps are physically present.
- `amp1` was reconnected physically during the session; Küche resumed playing once it came back.

### 7. PR #273 (upstream lox-audioserver) commit message fix

Commitlint CI was failing because the commit subject started with `WIP:` (not a valid conventional-commit type). Reworded the commit on the fork branch to `fix(audio): align engine output format on the input/connect play path`, kept it on the fork's beta base so the push didn't drag in upstream workflow files (which had required the `workflow` gh-scope previously). Push went through cleanly without scope changes; CI commitlint check now passes.

---

## Container patches that get wiped on every `docker compose up -d`

Two patches live only in the running container's compiled JS and **must be re-applied after every image pull / recreate**:

1. **PR #273 marker** in `/app/dist/application/zones/PlaybackCoordinator.js` — the `playInputSource` output-format alignment using `this.zoneAudioPrefs`. Re-application script and exact diff are in the session memory (`project_upstream_bugs.md`).
2. (Previously, the librespot binary patch — but that was reverted after retest; container now runs stock librespot.)

The `~/lox-audioserver/compose.yaml` hidraw-removal **does** survive recreates (it's the compose file itself).

---

## Open / pending

- **Spotify refresh token is empty again** — Spotify revoked it (`refresh token revoked` error before the morning storm); now logs spam `no refresh token configured for spotify account`. Re-auth the account in the admin UI at http://localhost:7090/ — same flow as the 2026-05-24 fix. Until then, Web-API calls fail and the morning per-account dealer storms come back sooner.
- **PR #1713 (librespot, context-recovery on resume)** — still open / draft. The clean fix `1430e2a` (stash `context_uri` in `reset_context`, take-once in `handle_activate`) does not resolve the real-world symptom (the context_uri is often already empty at reset time). PR is published with a thorough review reply documenting why.
- **PR #273 (lox-audioserver, output-format alignment)** — still open / draft (`fix/sendspin-output-format-align`, commit 4ad5e11 on fork). Maintainer rudyberends has reviewed and confirmed the diagnosis. The branch is on the fork's stale beta base (audioManager arg); the corrected `zoneAudioPrefs` version requires rebasing onto current beta, which needs the `workflow` gh-scope — deferred.
- **Migration plan: external `powermanager` → lox internal `PowerManager`** (`powermanager/MIGRATION_TO_LOX_INTERNAL.md`, commit 98ba5cd) is documented and ready. Not executed yet — would require `compose.yaml` device passthrough for `/dev/gpiochip0`, plus a `powerGroups` block + per-zone `powerManager.powerGroupId` in `config.json`.
- **Schlafzimmer rewired to amp2** — physical change mentioned by the user. `speaker_config.json` still has `schlafzimmer_left/right → amp3 ch 1/2`; needs an update to point at amp2 with the new channels (not yet known). Easiest via the webui Rooms editor.
- **CLAUDE.md amp-mapping table is stale** — it claims amp2 = Wohnzimmer/Esszimmer, but `speaker_config.json` has those (plus Küche and Backupküche) on amp1. Worth a cleanup pass.

---

## Commits made this session (multiroom-tooling repo)

```
525073d  Make amp GPIO configurable in speaker_config.json + webui (UI editor)
ec05ebd  webui: global TEST VOL slider (default 75%)
9b2b048  webui: auto-power amp for test sounds
98ba5cd  Add migration plan for lox-audioserver internal power manager
```

Plus the host-local edit to `~/lox-audioserver/compose.yaml` (removed `/dev/hidrawN` mappings) — not in any git repo.
