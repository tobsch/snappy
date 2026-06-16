# Hardware — 3D-printed enclosures

Parametric OpenSCAD enclosures for the decentralised multiroom build (one amp
box per Wondom GAB8, plus a Raspberry Pi 5 "brain box" near the amps). Each
folder holds the `.scad` source and the rendered `.stl` outputs (`-base` =
main body, `-lid` = top).

| Folder | Box | Footprint | Notes |
|--------|-----|-----------|-------|
| `gab8-amp-case/` | Wondom GAB8 amplifier | ~156 × 118 × 80 mm | Rear 2×2 4-pole speaker terminals (16 = 8 BTL ch), front vertical USB-C + power + control terminals, air-permeable speaker motif in the lid |
| `rpi5-brain-box/` | Raspberry Pi 5 + Active Cooler | 93.2 × 110.2 × 36 mm | Layout B (flat & wide): Pi in front, terminals hang from the lid into a rear bay, all Pi ports + side/lid cooler vents, 4× 4-pole GPIO→amp terminals |

## Render / regenerate STLs

OpenSCAD is installed on the Pi (`sudo apt install openscad xvfb`). Headless:

```bash
cd hardware/rpi5-brain-box
xvfb-run -a openscad -o rpi5-base.stl -D 'part="base"' rpi5-case.scad
xvfb-run -a openscad -o rpi5-lid.stl  -D 'part="lid"'  rpi5-case.scad
```

Same pattern for `gab8-amp-case` (`part="base"|"lid"`). Visual check: render a
PNG (`-o x.png --camera=... --imgsize=... --projection=perspective`) and view it.

All dimensions are parametric in the `EDIT` block at the top of each `.scad`.
Connector cutouts are taken from the physical panel terminals — verify body
depth and Pi port windows against your parts before printing.

See also: `docs/` for the design rationale and the brain-box / star-ground plan.
