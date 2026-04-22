# GPIO Power Control for Amplifiers

## Goal

Replace the USB relay (crelay) with direct GPIO control of the Wondom GAB8 amplifier SHDN (shutdown) pins. This eliminates the problems caused by USB power cycling:

- ALSA device disconnection and state resets
- Sendspin streams becoming stale (RUNNING with appl_ptr=0 indefinitely)
- Need for cooldown timers after power-off to avoid false activity detection
- Dependency on crelay and USB relay hardware

With GPIO SHDN control, the USB audio connection stays alive. Only the amplifier output stage is enabled/disabled.

## GPIO Pin Assignment

Using the left side of the Raspberry Pi 5 40-pin header, pins 9–15:

| Amp  | GND Pin | SHDN Pin | GPIO |
|------|---------|----------|------|
| amp1 | 6       | 13       | 27   |
| amp2 | 14      | 15       | 22   |
| amp3 | 9       | 11       | 17   |

## Wiring

### SHDN (Shutdown)
Connect each GPIO pin to the SHDN pin on the corresponding GAB8 amplifier board. Each amp gets its own GND pin from the Pi header.

### SYNC (PWM Synchronization)
Connect the SYNC pins of all three GAB8 boards together (daisy-chain: amp1 SYNC → amp2 SYNC → amp3 SYNC). This synchronizes PWM switching frequencies across boards and prevents audible beating/interference from unsynchronized Class-D switching.

**TODO:** Confirm SHDN pin logic level on the GAB8 (active-low or active-high) before implementing.

## Implementation Plan

1. Update `powermanager.sh` to use `gpioset` instead of `crelay`
2. Remove the `RELAY_OFF_COOLDOWN` workaround (no longer needed since USB stays connected)
3. Remove the `is_sendspin_active()` workaround (ALSA state will be reliable)
4. Simplify `is_any_card_active()` — can rely on standard ALSA status checks
5. Update the web UI relay control API to use GPIO
6. Update lox-audioserver relay configuration (or bypass it for GPIO)
7. Add udev rules or systemd service to set initial GPIO state at boot

## Dependencies

- `gpiod` package (already installed)
- `libgpiod` / `python3-libgpiod` (already installed)
- Physical wiring from Pi GPIO header to GAB8 SHDN pins
