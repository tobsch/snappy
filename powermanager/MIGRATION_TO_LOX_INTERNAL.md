# Migration: replace external power manager with lox-audioserver's internal one

**Status:** research / proposal — no changes applied yet.

## Goal

Retire the host-side `powermanager.service` (driven by `powermanager.sh` + `ampctl`) and let `lox-audioserver`'s built-in power manager drive the three Wondom GAB8 amplifiers' SHDN GPIO pins directly.

## What lox-audioserver provides

Source: `src/application/zones/services/powerManager.ts` and `sharedPowerGroupManager.ts`.

- **Per-zone `powerManager` config** with action types: `gpio` / `url` / `udp` / `crelay`.
  The GPIO action uses **`gpioset`** (libgpiod) and is configurable:
  - `pin` (GPIO line offset within chip)
  - `activeHigh` (true → ON writes 1)
  - `chip` (default `gpiochip0`)
  - `gpiosetPath` (default `gpioset`)
- **`SharedPowerGroupManager`** — multiple zones bind to one `powerGroupId`; the group's GPIO fires while *any* bound zone is active. This is exactly the shape we need for `amp1` (4 rooms).
- **Activation modes**: `activeModes: ['play']` (default) — power on when the zone's state is `play`.
- **Timers**: `onDelayMs`, `offDelayMs` (with `offDelayEnabled` toggle).
- **Bonus capability** we don't have today: `playbackPreDelayMs` — per-zone pre-delay before audio starts, so playback waits until the amp has woken (eliminates click/pop on first sample).

## Current setup vs. internal capability

| Aspect | Current external (`powermanager.sh` + `ampctl`) | lox internal |
|---|---|---|
| Detection | `bytes_received` from sendspin WebSocket (real PCM flow) | `zone.state.mode === 'play'` (lox internal state) |
| GPIO driver | `pinctrl` (RPi-native sysfs) | `gpioset` (libgpiod via `/dev/gpiochip0`) |
| Multi-room per amp | derived from `speaker_config.json` | native via `powerGroups` |
| Off-delay | 60 s hardcoded | per-zone, configurable |
| Pre-warm delay | none | `playbackPreDelayMs` per zone |
| Self-heal on external state change | yes (re-reads `ampctl status`) | n/a — lox is the only writer |

## Mapping: amps → GPIOs → lox zones

Derived from `speaker_config.json` + the running `lox-audioserver` config:

| Amp  | GPIO (BCM) | Lox zone(s) (id, display name) → `speaker_config.json` room |
|------|------------|------------------------------------------------------------|
| amp1 | 27         | Küche (9) → `kueche`, Wohnzimmer (5) → `wohnzimmer`, Esszimmer (4) → `esszimmer`, Backupküche (8) → `backupkueche` |
| amp2 | 22         | Elternbad (6) → `elternbad` |
| amp3 | 17         | **Elternschlafzimmer (7) → `schlafzimmer` (ch 1+2)**, **Außenbereich (10) → `vordach` (ch 3+4 or similar)** |
| —    | —          | Kinderzimmer Linda (1), Kinderzimmer Louise (2), Gästebad (11), Einliegerwohnung (12) — no speakers in `speaker_config.json`; leave `powerManager` unset |

- All three pins live on **`gpiochip0` (pinctrl-rp1)** on the RPi 5, so the default `chip: "gpiochip0"` works.
- The container already has **`gpioset` installed** at `/usr/bin/gpioset`.
- **No cross-device stereo zones** (every room maps to exactly one amp), which keeps the model clean — `powerGroupId` is one-per-zone in the schema.

## Gaps that block switching today

1. **No `/dev/gpiochip0` in the container.** Current devices are only `hidraw0/1/2` + `bus/usb`. `compose.yaml` needs the new device passthrough.
2. **Driver conflict.** The host `powermanager.service` is `active`/`enabled` and uses `pinctrl`; the container would use `gpioset` (line-request via ioctl). Both touch the same physical pins → must **stop + disable** the host service before enabling the internal manager (otherwise: last-writer-wins + possible `gpioset` line-claim failure).
3. **Detection robustness regression.** State-based is fine when lox state ≡ reality, but during the wedge/storm patterns we've been hunting (no PCM despite `state=play`), the amp would stay on unnecessarily. Not unsafe — just slightly less power-efficient than the bytes-based detector. Acceptable tradeoff.
4. **`compose.yaml` edit forces a container recreate.** That **wipes the PR #273 JS patch** (compiled `PlaybackCoordinator.js`); it must be re-applied (memory has the re-apply steps and the `local-fix (PR #273)` marker).
5. **Zone-name ↔ speaker_config room-id mapping resolved.** Lox display names diverge from `speaker_config.json` room ids — Elternschlafzimmer→`schlafzimmer`, Außenbereich→`vordach`. Both land on **amp3** (sharing it). The migration mapping (table above and config sketch below) accounts for this.

## Migration sketch (concrete shape; nothing applied yet)

### `~/lox-audioserver/compose.yaml`

```yaml
services:
  loxoneaudioserver:
    devices:
      - /dev/hidraw0:/dev/hidraw0
      - /dev/hidraw1:/dev/hidraw1
      - /dev/hidraw2:/dev/hidraw2
      - /dev/bus/usb:/dev/bus/usb
      - /dev/gpiochip0:/dev/gpiochip0   # NEW
```

### `~/lox-audioserver/data/config.json`

```jsonc
{
  "powerGroups": [
    {
      "id": "amp1",
      "name": "Amp 1 (Küche / Wohnzimmer / Esszimmer / Backupküche)",
      "powerManager": {
        "activeModes": ["play"],
        "offDelayEnabled": true,
        "offDelayMs": 60000,
        "gpio": { "enabled": true, "chip": "gpiochip0", "pin": 27, "activeHigh": true }
      }
    },
    {
      "id": "amp2",
      "name": "Amp 2 (Elternbad)",
      "powerManager": {
        "activeModes": ["play"],
        "offDelayEnabled": true,
        "offDelayMs": 60000,
        "gpio": { "enabled": true, "chip": "gpiochip0", "pin": 22, "activeHigh": true }
      }
    },
    {
      "id": "amp3",
      "name": "Amp 3 (Vordach / Außenbereich?)",
      "powerManager": {
        "activeModes": ["play"],
        "offDelayEnabled": true,
        "offDelayMs": 60000,
        "gpio": { "enabled": true, "chip": "gpiochip0", "pin": 17, "activeHigh": true }
      }
    }
  ],
  "zones": [
    { "id": 9,  /* Küche        */ "powerManager": { "powerGroupId": "amp1", "playbackPreDelayMs": 100 } },
    { "id": 5,  /* Wohnzimmer   */ "powerManager": { "powerGroupId": "amp1", "playbackPreDelayMs": 100 } },
    { "id": 4,  /* Esszimmer    */ "powerManager": { "powerGroupId": "amp1", "playbackPreDelayMs": 100 } },
    { "id": 8,  /* Backupküche  */ "powerManager": { "powerGroupId": "amp1", "playbackPreDelayMs": 100 } },
    { "id": 6,  /* Elternbad          */ "powerManager": { "powerGroupId": "amp2", "playbackPreDelayMs": 100 } },
    { "id": 7,  /* Elternschlafzimmer */ "powerManager": { "powerGroupId": "amp3", "playbackPreDelayMs": 100 } },
    { "id": 10, /* Außenbereich       */ "powerManager": { "powerGroupId": "amp3", "playbackPreDelayMs": 100 } }
    // zones 1, 2, 11, 12: no powerManager (no speakers in speaker_config)
  ]
}
```

## Order of operations (when executing)

1. Pre-set a known baseline: `ampctl off` on idle amps so the handover starts clean.
2. `sudo systemctl stop powermanager && sudo systemctl disable powermanager`.
3. Edit `compose.yaml` (add `/dev/gpiochip0` device passthrough).
4. Edit `data/config.json` (add `powerGroups`, set per-zone `powerManager.powerGroupId` + `playbackPreDelayMs`).
5. `cd ~/lox-audioserver && docker compose up -d` (recreate).
6. **Re-apply PR #273 patch** to the new compiled `PlaybackCoordinator.js` (uses `this.zoneAudioPrefs`; marker `local-fix (PR #273)`).
7. Verify: while playing in a Küche-group zone, `pinctrl get 27` (host) or `docker exec lox-audioserver gpioget gpiochip0 27` should report high; after ~60 s idle, low. Repeat for amp2/amp3.
8. Leave `/usr/local/bin/ampctl` in place as a manual override CLI for debugging; only `powermanager.service` is being retired.

## Rollback

1. Revert `compose.yaml` (remove `/dev/gpiochip0` line).
2. Revert `config.json` (remove `powerGroups` and per-zone `powerManager` blocks).
3. `docker compose up -d`.
4. Re-apply PR #273 patch.
5. `sudo systemctl enable --now powermanager`.

## Open items to confirm before executing

- **Zone-name ↔ speaker_config room-id mapping** confirmed: Elternschlafzimmer (lox zone 7) = `schlafzimmer` (room) → amp3 ch 1+2; Außenbereich (lox zone 10) = `vordach` (room) → amp3. Both share amp3.
- **Container capabilities for libgpiod.** `cap_add` already has `SYS_ADMIN` / `DAC_READ_SEARCH` / `SYS_NICE`. `gpioset` on `/dev/gpiochip0` typically needs just read/write on the device node; depending on kernel/policy may need `CAP_SYS_RAWIO` or membership in the `gpio` group. Worth a smoke test after passthrough is added:
  ```
  docker exec lox-audioserver gpioset gpiochip0 27=1
  ```
- **Pre-delay magnitude.** Set to **100 ms** per zone (enough for the GAB8 mute-release without an audible silence on play press).
- **Admin UI path.** `src/adapters/http/adminApi/adminApiHandler.ts` references `powerManager` config — there's likely a UI at `http://localhost:7090/` that can edit this without hand-editing JSON. Worth a check; may be the cleanest authoring path.
- **Storm/wedge behavior.** With state-based detection, if lox state stays at `play` during a no-PCM wedge, the amp stays on (no functional fault — just silence + wasted power). Bytes-based detection (current external) would catch that. Probably fine post node-librespot 0.4.2 + PR #273, but worth confirming during the first morning after switching.
