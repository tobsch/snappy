/* ============================================================================
   GAB8 amplifier enclosure  —  parametric (OpenSCAD)
   ----------------------------------------------------------------------------
   Board: Wondom GAB8 (UMGAB8-01): 152.40 x 114.30, PCB 1.60,
   4x Ø3.80 holes 5.00 in from each edge. Heatsink 28.60 + 15 mm fan on top.

   Layout (this revision):
     REAR  (long edge "N")  : speaker terminal blocks  2EDGWC-5.08
     FRONT (long edge "S")  : USB-C feedthrough + power + control (SHDN/MUTE/SYNC/GND)
     LID                    : screwed down at 4 corner posts (box enlarged to fit)

   Render: open in OpenSCAD, set `part`, F5 preview, F6 + export STL.
   Check the console — it echoes whether the rear connectors actually fit.
   ========================================================================== */

$fn = 64;

/* ----------------------------- EDIT: board ------------------------------- */
board_w    = 152.40;
board_d    = 114.30;
pcb_th     = 1.60;
hole_d     = 3.80;
hole_inset = 5.00;
comp_h     = 33.0;     // tallest point ABOVE PCB (heatsink+15mm fan ~43) >>MEASURE<<

/* ----------------------------- EDIT: build ------------------------------- */
wall       = 1.6;      // 4 perimeters @0.4 — stable middle ground, still ~1/3 lighter than thick
floor_th   = 1.6;
lid_th     = 2.0;      // kept at 2.0: the M3 countersink (~1.4mm deep) needs the depth
clear_xy   = 6.0;      // board edge -> inner wall (front/sides)
rear_gap   = 20.0;     // EXTRA clearance behind the board at the REAR (for connector bodies)
total_h    = 80.0;     // overall OUTER height (floor + cavity + lid). airgap derives from it

standoff_h  = 6.0;
standoff_od = 7.0;
pilot_d     = 2.5;

/* lid: RECESSED (flush), held by 4 corner posts with M2.5 countersunk screws */
post_od        = 7.0;   // corner screw-post outer Ø
post_pilot     = 2.5;   // self-tap M3 pilot in the post
post_len       = 10.0;  // SHORT post hanging from the top (not full height) — saves filament
post_screw_len = 8.0;   // pilot depth from the top
lid_screw_d    = 3.2;   // M3 shaft clearance through the lid
lid_csk_d      = 6.0;   // M3 countersunk head Ø, 90deg
lid_lip        = 0.8;   // outer wall lip (wall 1.6 -> ledge 0.8)
lid_clear      = 0.3;   // gap around the recessed lid

/* lid vents */
vent_slot_w = 3.0; vent_rib_w = 3.0; vent_margin = 12.0;

/* lid speaker SYMBOL (engraved into the top, 1mm less filament there) */
lid_motif    = true;
motif_w      = 70;     // overall width of the loudspeaker icon
motif_depth  = 1.0;    // engraving depth (= 1mm less filament; < lid_th)
motif_vents  = true;   // make the symbol air-permeable (arcs cut through + cone perforated)

/* --------- derived geometry (BEFORE connectors: they depend on it) ------- */
inner_w = board_w + 2*clear_xy;
inner_d = board_d + 2*clear_xy + rear_gap;          // extra depth -> goes to the rear
inner_h = total_h - floor_th - lid_th;              // cavity height from target total
airgap  = inner_h - (standoff_h + pcb_th + comp_h); // implied clearance above comps
outer_w = inner_w + 2*wall;
outer_d = inner_d + 2*wall;
bx = wall + clear_xy;  by = wall + clear_xy;
echo(str("HEIGHT: total=", total_h, "mm  cavity=", inner_h, "mm  airgap above comps=", airgap,
         "mm", (airgap < 4) ? "  >>> TOO TIGHT (raise total_h or lower comp_h) <<<" : "  ok"));

/* ----------------- EDIT: connectors (all panel-mount) ------------------- */
conn_mid    = floor_th + inner_h/2;  // mid-height of the cavity
front_raise = 25.0;                  // raise FRONT connectors (USB/power/control)
rear_raise  = 17.0;                  // raise REAR terminal grid (capped: grid must fit the box)
front_zc    = conn_mid + front_raise;
rear_zc     = conn_mid + rear_raise;

// USB-C feedthrough (front), 17 mm screw pitch, port estimated
usb_enable = true;  usb_face = "S";  usb_along = outer_w*0.22;
usb_vertical = true;    // USB-C mounted VERTICAL (per file2): screws above/below
usb_screw_pitch = 17.0; usb_screw_d = 2.8; usb_port_w = 3.8; usb_port_h = 10.0;  // vertical: narrow x tall (~3x9.2 + room)

// REAR speaker terminals 2EDGWC-5.08, arranged as a grid (cols x rows)
term_enable    = true; term_face = "N";
term_cols      = 2;     // connectors across the rear (along the edge)
term_rows      = 2;     // connectors stacked vertically -> 2x2 = 4x 4-pole = 8 ch
term_poles     = 4;
term_row_pitch = 20.0;  // vertical centre-to-centre between rows
term_port_h    = 12.2;  // port height (from reference STL)
term_hole_d    = 3.05;  // screw hole Ø (from reference STL)

// FRONT control terminal (SHDN/MUTE/SYNC/GND) 2EDGWC-5.08, 4-pole
ctrl_enable = true; ctrl_face = "S"; ctrl_along = outer_w*0.78; ctrl_poles = 4;

// FRONT power — now 4-pole (same 2EDGWC). Parallel +/- pairs for current.
pwr_enable = true;  pwr_face = "S"; pwr_along = outer_w*0.50; pwr_poles = 4;

part = "all";          // "all" | "base" | "lid"

// fit check for the rear terminals
term_flange = term_poles*5.08 + 23.67;
echo(str("REAR: ", term_cols, "x", term_rows, " of ", term_poles, "-pole  flange=", term_flange,
         "mm  row=", term_cols*term_flange, "mm vs usable=", outer_w-2*(wall+post_od), "mm",
         (term_cols*term_flange > outer_w-2*(wall+post_od)) ? "  >>> ROW TOO WIDE <<<" : "  ok"));

/* ------------------------------- helpers --------------------------------- */
module rounded_box(w, d, h, r) {
  hull() for (x=[r, w-r]) for (y=[r, d-r]) translate([x, y, 0]) cylinder(h=h, r=r);
}
module board_holes()  { for (x=[hole_inset, board_w-hole_inset]) for (y=[hole_inset, board_d-hole_inset]) translate([bx+x, by+y]) children(); }
// posts inset by (post_od/2 - 1) so they OVERLAP the walls by ~1mm (avoids tangent -> non-manifold)
module corner_posts() { o=post_od/2-1.0; for (x=[wall+o, outer_w-wall-o]) for (y=[wall+o, outer_d-wall-o]) translate([x, y]) children(); }

// rounded rectangular window through a wall (r = h/2 -> oval, used for USB-C)
module panel_window(face, a, z, w, h, r=1.0) {
  if (face=="W" || face=="E") {
    x0 = (face=="W") ? -1 : outer_w-wall-1;
    hull() for (s1=[-1,1]) for (s2=[-1,1])
      translate([x0, a+s1*(w/2-r), z+s2*(h/2-r)]) rotate([0,90,0]) cylinder(h=wall+2, r=r);
  } else {
    y0 = (face=="S") ? -1 : outer_d-wall-1;
    hull() for (s1=[-1,1]) for (s2=[-1,1])
      translate([a+s1*(w/2-r), y0, z+s2*(h/2-r)]) rotate([-90,0,0]) cylinder(h=wall+2, r=r);
  }
}
module panel_hole(face, a, z, d) {
  if (face=="W" || face=="E")
    translate([(face=="W")?wall/2:outer_w-wall/2, a, z]) rotate([0,90,0]) cylinder(h=wall+4, d=d, center=true);
  else
    translate([a, (face=="S")?wall/2:outer_d-wall/2, z]) rotate([-90,0,0]) cylinder(h=wall+4, d=d, center=true);
}

// 2EDGWC-5.08 terminal: narrow contact port + 2 screw holes at the wide pitch
module terminal(face, a, z, poles) {
  pw = poles*5.08 + 11.18;    // port width  (31.5 for 4-pole, from reference STL)
  hs = poles*5.08 + 16.67;    // screw-hole pitch  (~37 for 4-pole)
  panel_window(face, a, z, pw, term_port_h, 1.0);
  panel_hole(face, a - hs/2, z, term_hole_d);
  panel_hole(face, a + hs/2, z, term_hole_d);
}
// USB-C feedthrough: oval port + 2 screws. Vertical = screws above/below; else sideways.
module usb_cut() {
  r = min(usb_port_w, usb_port_h)/2;   // round the short ends -> stadium
  panel_window(usb_face, usb_along, front_zc, usb_port_w, usb_port_h, r);
  if (usb_vertical) {
    panel_hole(usb_face, usb_along, front_zc - usb_screw_pitch/2, usb_screw_d);
    panel_hole(usb_face, usb_along, front_zc + usb_screw_pitch/2, usb_screw_d);
  } else {
    panel_hole(usb_face, usb_along - usb_screw_pitch/2, front_zc, usb_screw_d);
    panel_hole(usb_face, usb_along + usb_screw_pitch/2, front_zc, usb_screw_d);
  }
}

/* ------------------------------- base ------------------------------------ */
module standoffs() {
  translate([0,0,floor_th]) board_holes()
    difference() { cylinder(h=standoff_h, d=standoff_od); translate([0,0,-0.1]) cylinder(h=standoff_h+0.2, d=pilot_d); }
}
// SHORT posts hanging from the top, with a 45deg cone underside so they print without support
module lid_posts() {
  zt = floor_th + inner_h;        // post top = lid seat
  zb = zt - post_len;             // post bottom
  corner_posts()
    difference() {
      union() {
        translate([0,0,zb]) cylinder(h=post_len, d=post_od);
        translate([0,0,zb-post_od*1.5]) cylinder(h=post_od*1.5+0.01, d1=0, d2=post_od);  // ~19deg from vert -> support-free
      }
      translate([0,0,zt-post_screw_len]) cylinder(h=post_screw_len+0.1, d=post_pilot);
    }
}
module shell() {
  difference() {
    rounded_box(outer_w, outer_d, total_h, 3);                                // full outer height
    translate([wall, wall, floor_th]) cube([inner_w, inner_d, inner_h+0.1]);  // board cavity (to z=floor_th+inner_h)
    // recess pocket for the flush lid (top lid_th), leaving the outer lip + a ledge
    translate([lid_lip, lid_lip, floor_th+inner_h]) cube([outer_w-2*lid_lip, outer_d-2*lid_lip, lid_th+1]);
  }
}
module base() {
  difference() {
    union() { shell(); standoffs(); lid_posts(); }
    if (usb_enable)  usb_cut();
    if (term_enable) for (c=[0:term_cols-1]) for (r=[0:term_rows-1])
      terminal(term_face, outer_w*(c+0.5)/term_cols, rear_zc + (r-(term_rows-1)/2)*term_row_pitch, term_poles);
    if (ctrl_enable) terminal(ctrl_face, ctrl_along, front_zc, ctrl_poles);
    if (pwr_enable)  terminal(pwr_face,  pwr_along,  front_zc, pwr_poles);
  }
}

/* -------------------------------- lid ------------------------------------ */
module vent_slots() {
  pitch = vent_slot_w + vent_rib_w;
  n = floor((outer_d - 2*vent_margin) / pitch);
  difference() {
    union() for (i=[0:n-1])
      translate([vent_margin, vent_margin + i*pitch, -0.1]) cube([outer_w - 2*vent_margin, vent_slot_w, lid_th+0.2]);
    if (lid_motif) translate([outer_w/2, outer_d/2, -1]) cylinder(h=lid_th+2, d=motif_w+10, $fn=90);  // clear slots around the symbol
  }
}
// loudspeaker symbol (2D, centred): magnet/body + cone + 3 sound-wave arcs
module spk_icon_2d(w) {
  union() {
    translate([-w*0.45, -w*0.12]) square([w*0.12, w*0.24]);                              // magnet/body
    polygon([[-w*0.33,-w*0.12],[-w*0.33,w*0.12],[-w*0.14,w*0.27],[-w*0.14,-w*0.27]]);    // cone
    for (i=[1:3]) {
      R=w*(0.05+i*0.11); t=w*0.028;
      intersection() {
        difference() { circle(R+t/2,$fn=96); circle(R-t/2,$fn=96); }
        polygon([[-w*0.1,0],[w,w],[w,-w]]);                                              // right-opening wedge
      }
    }
  }
}
// air-permeable parts: arcs cut THROUGH + cone perforated like a membrane
module spk_vents_2d(w) {
  for (i=[1:3]) {                                   // the 3 sound-wave arcs (through)
    R=w*(0.05+i*0.11); t=w*0.028;
    intersection() {
      difference() { circle(R+t/2,$fn=96); circle(R-t/2,$fn=96); }
      polygon([[-w*0.1,0],[w,w],[w,-w]]);
    }
  }
  intersection() {                                  // cone perforation (membrane look)
    polygon([[-w*0.33,-w*0.12],[-w*0.33,w*0.12],[-w*0.14,w*0.27],[-w*0.14,-w*0.27]]);
    for (gx=[-w*0.34 : w*0.055 : 0]) for (gy=[-w*0.28 : w*0.055 : w*0.28])
      translate([gx,gy]) circle(d=w*0.032, $fn=16);
  }
}
// engrave the symbol 1mm relief, and (optionally) cut the air-permeable parts through
module lid_speaker() {
  translate([outer_w/2, outer_d/2, lid_th-motif_depth]) linear_extrude(motif_depth+1) spk_icon_2d(motif_w);
  if (motif_vents) translate([outer_w/2, outer_d/2, -1]) linear_extrude(lid_th+2) spk_vents_2d(motif_w);
}
// recessed lid: inset plate dropping into the rebate, M3 countersunk holes
module lid() {
  lo  = lid_lip + lid_clear;            // inset from the outer edge
  csk = (lid_csk_d - lid_screw_d)/2;    // 90deg countersink depth
  difference() {
    translate([lo, lo, 0]) rounded_box(outer_w-2*lo, outer_d-2*lo, lid_th, 3);
    vent_slots();
    if (lid_motif) lid_speaker();
    corner_posts() {
      translate([0,0,-0.1]) cylinder(h=lid_th+0.2, d=lid_screw_d);                       // through
      translate([0,0,lid_th-csk]) cylinder(h=csk+0.1, d1=lid_screw_d, d2=lid_csk_d);     // countersink (top)
    }
  }
}

/* ------------------------------ assemble --------------------------------- */
if (part=="base" || part=="all") base();
if (part=="lid") lid();
else if (part=="all") translate([0, 0, floor_th+inner_h+18]) lid();  // exploded above its recess
