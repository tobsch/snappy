/* ============================================================================
   Raspberry Pi 5 "brain-box" enclosure — parametric (OpenSCAD)
   LAYOUT B: flat & wide ("flach und breiter").
   ----------------------------------------------------------------------------
   Pi 5 board 85 x 56, PCB 1.4. Mounting holes Ø2.7, 58 x 49, 3.5 inset
   (from the official RPi 5 mechanical drawing, RP-008347-DS).
   Ports (verify against your board):
     BOTTOM edge ("S"): USB-C @11.2, micro-HDMI @25.8 & 39.2
     RIGHT  edge ("E"): Ethernet @10.2, USB-A stacks @29.1 & 47
   Cooler: official Active Cooler (~24 mm above PCB) sits over the Pi.

   The box footprint is EXTENDED ~46 mm past the GPIO (N) edge into a "bay".
   The 4x 4-pole panel terminals (GPIO -> Wondom SHDN/MUTE/SYNC/GND) hang from
   the lid INTO that empty bay (no Pi/cooler below) -> they cost no extra
   height. Box is only ~36 mm tall instead of stacking terminals over the
   cooler. The 40-pin GPIO header faces straight into the bay = short wiring.
   Venting: left (W) wall over the cooler + slots in the lid over the cooler.
   Render: set `part`, F6, export STL.
   ========================================================================== */

$fn = 48;

/* ----------------------------- EDIT: board ------------------------------- */
pi_w       = 85.0;     // X
pi_d       = 56.0;     // Y
pcb_th     = 1.4;
hole_d     = 2.7;      // Pi mounting hole (M2.5)
hole_ix    = 3.5;      // inset
hole_dx    = 58.0;     // hole spacing X
hole_dy    = 49.0;     // hole spacing Y

/* ----------------------------- EDIT: build ------------------------------- */
wall       = 1.6;
floor_th   = 1.6;
lid_th     = 2.0;
clear_xy   = 2.5;      // board edge -> inner wall

standoff_h  = 4.0;     // lift Pi off floor (bottom-side clearance)
standoff_od = 6.0;
pi_pilot    = 2.1;     // self-tap M2.5 into the standoff (board screws)

cooler_h    = 24.0;    // official Active Cooler height above PCB
cooler_gap  = 3.0;     // clearance cooler top -> lid underside

/* bay: rear footprint extension where the terminals hang from the lid */
bay_d      = 46.0;     // how far the box extends past the GPIO (N) edge
term_drop  = 18.0;     // small-connector body depth (hangs into the bay)

/* lid: held by 4 corner posts, M3 countersunk (like the amp box) */
post_od        = 7.0;
post_pilot     = 2.5;
post_len       = 10.0;
lid_screw_d    = 3.2;
lid_csk_d      = 6.0;
lid_lip        = 0.8;
lid_clear      = 0.3;

/* vents */
vent_w = 3.0; vent_gap = 3.0; vent_margin = 8.0;

/* SMALL 4-pole panel terminals (3.81 mm pitch) — from the datasheet image.
   Analogous to the big ones: cutout width = poles*pitch + 11. */
term_poles  = 4;
term_port_w = 4*3.81 + 11.2;    // 26.44  panel cutout width
term_port_h = 12.3;             //        panel cutout height
term_hole_d = 3.25;             //        mounting screw hole Ø
term_pitch  = 4*3.81 + 16.45;   // 31.69  screw-hole pitch

part = "all";          // "all" | "base" | "lid"

/* --------------------------- derived geometry ---------------------------- */
inner_w = pi_w + 2*clear_xy;                      // 90
inner_d = pi_d + 2*clear_xy + bay_d;              // 61 + 46 = 107
inner_h = standoff_h + pcb_th + cooler_h + cooler_gap;  // 32.4 (cooler dominates)
outer_w = inner_w + 2*wall;
outer_d = inner_d + 2*wall;
total_h = floor_th + inner_h + lid_th;            // ~36
bx = wall + clear_xy;  by = wall + clear_xy;      // Pi board origin in box coords
pcb_top = floor_th + standoff_h + pcb_th;         // z of the PCB top (ports sit here)
bay_y0  = by + pi_d;                              // bay starts at the GPIO (N) edge
echo(str("Pi5 box (layout B): ", outer_w, " x ", outer_d, " x ", total_h,
         " mm  (cavity ", inner_h, ", term hangs ", term_drop, ")"));

/* ports: ["face", pos_on_board, width, height, z_center_above_pcb, name]
     face S = bottom edge (y=0) | E = right edge (x=pi_w)
     >>> verify width/height/pos against your actual Pi 5 <<< */
ports = [
  ["S", 11.2, 11,  5, 2.5,  "USB-C"],
  ["S", 25.8,  8,  5, 2.5,  "HDMI0"],
  ["S", 39.2,  8,  5, 2.5,  "HDMI1"],
  ["E", 10.2, 17, 15, 7.0,  "Ethernet"],
  ["E", 29.1, 15, 17, 8.0,  "USB-A 3.0"],
  ["E", 47.0, 15, 17, 8.0,  "USB-A 2.0"],
];

/* ------------------------------- helpers --------------------------------- */
module rounded_box(w,d,h,r){ hull() for(x=[r,w-r]) for(y=[r,d-r]) translate([x,y,0]) cylinder(h=h,r=r); }
module pi_holes(){ for(x=[hole_ix, hole_ix+hole_dx]) for(y=[hole_ix, hole_ix+hole_dy]) translate([bx+x, by+y]) children(); }
module corner_posts(){ o=post_od/2-1; for(x=[wall+o, outer_w-wall-o]) for(y=[wall+o, outer_d-wall-o]) translate([x,y]) children(); }

// rectangular cut through a wall at (along, z), size w x h
module wall_cut(face, along, z, w, h) {
  if (face=="S") translate([bx+along-w/2, -1, z-h/2]) cube([w, wall+2, h]);
  if (face=="N") translate([bx+along-w/2, outer_d-wall-1, z-h/2]) cube([w, wall+2, h]);
  if (face=="W") translate([-1, by+along-w/2, z-h/2]) cube([wall+2, w, h]);
  if (face=="E") translate([outer_w-wall-1, by+along-w/2, z-h/2]) cube([wall+2, w, h]);
}
module port_cuts() { for (p=ports) wall_cut(p[0], p[1], pcb_top + p[4], p[2], p[3]); }

// left (W) wall vertical vent slots, in the cooler z-band, over the Pi region
module side_vents() {
  zc0 = floor_th + standoff_h;
  zc1 = floor_th + standoff_h + cooler_h;
  y0 = vent_margin; y1 = bay_y0 - vent_margin;     // only along the Pi region
  n = floor((y1 - y0)/(vent_w+vent_gap));
  for (i=[0:n-1]) translate([-1, y0 + i*(vent_w+vent_gap), zc0]) cube([wall+2, vent_w, zc1-zc0]);
}

// lid exhaust slots directly over the cooler (front half of the lid)
module lid_vents() {
  vy0 = by + 12; vy1 = by + pi_d - 6;
  n = floor((vy1 - vy0)/(vent_w+vent_gap));
  for (j=[0:n-1]) translate([bx+18, vy0 + j*(vent_w+vent_gap), -1]) cube([49, vent_w, lid_th+2]);
}

/* ------------------------------- base ------------------------------------ */
module standoffs(){ translate([0,0,floor_th]) pi_holes() difference(){ cylinder(h=standoff_h,d=standoff_od); translate([0,0,-0.1]) cylinder(h=standoff_h+0.2,d=pi_pilot);} }
module lid_posts(){
  zt=floor_th+inner_h; zb=zt-post_len;
  corner_posts() difference(){
    union(){ translate([0,0,zb]) cylinder(h=post_len,d=post_od);
             translate([0,0,zb-post_od*1.5]) cylinder(h=post_od*1.5+0.01,d1=0,d2=post_od); }   // steep printable taper
    translate([0,0,zt-8]) cylinder(h=8.1,d=post_pilot);
  }
}
module shell(){
  difference(){
    rounded_box(outer_w,outer_d,total_h,3);
    translate([wall,wall,floor_th]) cube([inner_w,inner_d,inner_h+0.1]);
    translate([lid_lip,lid_lip,floor_th+inner_h]) cube([outer_w-2*lid_lip,outer_d-2*lid_lip,lid_th+1]);  // lid recess
  }
}
module base(){
  difference(){
    union(){ shell(); standoffs(); lid_posts(); }
    port_cuts();
    side_vents();
  }
}

/* -------------------------------- lid ------------------------------------ */
// 4-pole terminal cut (panel window + 2 screw holes), screws along X (+/- pitch/2)
module lid_terminal(cx, cy) {
  translate([cx-term_port_w/2, cy-term_port_h/2, -1]) cube([term_port_w, term_port_h, lid_th+2]);
  for (dx=[-term_pitch/2, term_pitch/2]) translate([cx+dx, cy, -1]) cylinder(h=lid_th+2, d=term_hole_d);
}
module lid(){
  lo=lid_lip+lid_clear; csk=(lid_csk_d-lid_screw_d)/2;
  // 2x2 grid of terminals in the REAR BAY half of the lid
  cxc = wall + inner_w/2;
  gx  = [cxc - 21, cxc + 21];                  // two columns (screw extents ~±17.5)
  gy  = [bay_y0 + 14, bay_y0 + 32];            // two rows inside the bay
  difference(){
    translate([lo,lo,0]) rounded_box(outer_w-2*lo,outer_d-2*lo,lid_th,3);
    for(x=gx) for(y=gy) lid_terminal(x,y);
    lid_vents();
    corner_posts(){ translate([0,0,-0.1]) cylinder(h=lid_th+0.2,d=lid_screw_d);
                    translate([0,0,lid_th-csk]) cylinder(h=csk+0.1,d1=lid_screw_d,d2=lid_csk_d); }
  }
}

/* ------------------------------ assemble --------------------------------- */
if(part=="base"||part=="all") base();
if(part=="lid") lid();
else if(part=="all") translate([0,0,floor_th+inner_h+18]) lid();
