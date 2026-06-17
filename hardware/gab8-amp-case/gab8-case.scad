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

/* lid vent style: "particles" (scattered halftone speaker) | "bloom" (rings) */
lid_style      = "particles";
lid_bubbles    = true;   // master enable for either lid vent style

/* --- "bloom": concentric rings of holes growing from the driver outward --- */
bub_cx_frac    = 0.50;   // focal point (driver) X as fraction of lid width
bub_cy_frac    = 0.50;   // focal point Y as fraction of lid depth
bub_ring_pitch = 10.0;   // radial spacing between bubble rings
bub_d_min      = 2.6;    // hole Ø at the centre
bub_d_max      = 7.0;    // hole Ø at the rim (clamped)
bub_d_gain     = 0.052;  // Ø growth per mm of radius
bub_arc_gap    = 3.6;    // min web between holes along a ring
bub_edge_marg  = 9.0;    // keep holes this far in from the lid edge
bub_post_keep  = 8.0;    // keep-out radius around each corner screw

/* --- "particles": diffuse scattered bubbles; big ones inside the speaker
   silhouette form it as a halftone, fine ones fade out into a particle cloud --- */
par_seed       = 11;     // RNG seed (change for a different scatter)
par_pitch      = 6.5;    // jittered-grid cell size (base spacing)
par_jit        = 1.5;    // max random offset from the cell centre (wilder = larger)
par_bg_min     = 1.4;    // background particle Ø range (the diffuse cloud)
par_bg_max     = 2.6;
par_bg_keep    = 0.52;   // base fraction of background particles kept
par_fade       = 70.0;   // distance over which the cloud thins out (diffuse)
par_spk_min    = 3.0;    // speaker-fill particle Ø range (the halftone core)
par_spk_max    = 5.0;
par_spk_w      = 120;    // overall width of the speaker silhouette on the lid
par_spk_halo   = 2.2;    // clear the diffuse cloud this far around the icon

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
// 2D rounded rectangle spanning (0,0)..(w,d)
module rrect2d(w,d,r){ hull() for(x=[r,w-r]) for(y=[r,d-r]) translate([x,y]) circle(r=r,$fn=48); }

// where bubbles are ALLOWED: lid plate inset by the edge margin, minus a
// keep-out disc around each corner screw post
module bubble_allowed_2d() {
  lo=lid_lip+lid_clear; m=bub_edge_marg; o=post_od/2-1.0;
  difference() {
    translate([lo+m, lo+m]) rrect2d(outer_w-2*(lo+m), outer_d-2*(lo+m), 4);
    for (x=[wall+o, outer_w-wall-o]) for (y=[wall+o, outer_d-wall-o])
      translate([x,y]) circle(r=bub_post_keep, $fn=40);
  }
}
// concentric rings of holes growing outward from the focal point (overshoots
// the plate; clipped by bubble_allowed_2d). Alternate rings staggered.
module bubble_field_2d() {
  cx=outer_w*bub_cx_frac; cy=outer_d*bub_cy_frac;
  rmax = max(cx,outer_w-cx) + max(cy,outer_d-cy);
  nr = ceil(rmax/bub_ring_pitch);
  circle(d=bub_d_min, $fn=24);                                   // driver hub
  for (k=[1:nr]) {
    r = k*bub_ring_pitch;
    d = min(bub_d_max, bub_d_min + r*bub_d_gain);
    n = max(6, floor(2*PI*r/(d+bub_arc_gap)));
    off = (k%2)*0.5;                                             // brick stagger
    for (i=[0:n-1]) { a=360*(i+off)/n;
      translate([cx+r*cos(a), cy+r*sin(a)]) circle(d=d, $fn=max(18,floor(d*6))); }
  }
}
// clip field to the allowed region, then OPEN (erode+dilate) to drop the thin
// edge slivers left by clipping -> only clean holes remain
module bubble_holes_2d() {
  offset(r=0.7) offset(r=-0.7) intersection() { bubble_field_2d(); bubble_allowed_2d(); }
}

// filled loudspeaker silhouette (body + cone + 3 thick sound arcs), width w
module spk_solid_2d(w) {
  union() {
    translate([-w*0.42,-w*0.13]) square([w*0.13, w*0.26]);                                 // magnet body
    polygon([[-w*0.30,-w*0.13],[-w*0.30,w*0.13],[-w*0.10,w*0.30],[-w*0.10,-w*0.30]]);       // cone
    for (i=[1:3]) { R=w*(0.06+i*0.13); t=w*0.055;
      intersection() { difference(){ circle(R+t/2,$fn=80); circle(R-t/2,$fn=80); }
                       polygon([[-w*0.05,0],[w,w],[w,-w]]); } }                              // sound arcs
  }
}
// jittered-grid particle field. kind="bg": diffuse cloud, density fades with
// distance from centre; kind="spk": dense larger bubbles (clipped to the icon)
module particle_grid_2d(kind) {
  cx=outer_w/2; cy=outer_d/2;
  nx=ceil(outer_w/par_pitch); ny=ceil(outer_d/par_pitch);
  R=rands(0,1,nx*ny*4, par_seed);
  for (iy=[0:ny-1]) for (ix=[0:nx-1]) {
    b=(iy*nx+ix)*4;
    px=(ix+0.5)*par_pitch + (R[b]-0.5)*2*par_jit;
    py=(iy+0.5)*par_pitch + (R[b+1]-0.5)*2*par_jit;
    if (kind=="spk") {
      translate([px,py]) circle(d=par_spk_min+(par_spk_max-par_spk_min)*R[b+3], $fn=22);
    } else {
      keep = par_bg_keep * (1 - 0.65*min(1, norm([px-cx,py-cy])/par_fade));   // fade out
      if (R[b+2] < keep)
        translate([px,py]) circle(d=par_bg_min+(par_bg_max-par_bg_min)*R[b+3], $fn=16);
    }
  }
}
module particle_holes_2d() {
  offset(r=0.5) offset(r=-0.5)                                     // open: drop edge/clip slivers
  intersection() {
    union() {
      difference() {                                              // diffuse cloud, but cleared out of the icon (halo)
        particle_grid_2d("bg");
        translate([outer_w/2, outer_d/2]) offset(r=par_spk_halo) spk_solid_2d(par_spk_w);
      }
      intersection() {                                            // icon filled by the clean halftone
        particle_grid_2d("spk");
        translate([outer_w/2, outer_d/2]) spk_solid_2d(par_spk_w);
      }
    }
    bubble_allowed_2d();
  }
}
module lid_bubble_cut() {
  translate([0,0,-1]) linear_extrude(lid_th+2)
    if (lid_style=="particles") particle_holes_2d(); else bubble_holes_2d();
}

// recessed lid: inset plate dropping into the rebate, M3 countersunk holes
module lid() {
  lo  = lid_lip + lid_clear;            // inset from the outer edge
  csk = (lid_csk_d - lid_screw_d)/2;    // 90deg countersink depth
  difference() {
    translate([lo, lo, 0]) rounded_box(outer_w-2*lo, outer_d-2*lo, lid_th, 3);
    if (lid_bubbles) lid_bubble_cut();
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
