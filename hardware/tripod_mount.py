"""Printable L-bracket: Wuji adapter flange -> camera tripod (1/4"-20 screw).

  pip install trimesh manifold3d
  python hardware/tripod_mount.py            # writes hardware/tripod_mount.stl

Flange side (from Wuji's drawing assets/wuji-description/hand2/hand2_2/attachment/...adapter-flange...pdf):
four slots 6.2 x 14.2 mm on a 49 mm circle, at 45 degrees. Four M6 screws go through the slots (heads on the hand
side, in the slots' counterbores) into M6 nuts held in hex pockets on the back of the bracket. The window in the
middle clears the flange's centre opening and its four small screws.
Tripod side: one 1/4"-20 nut in a hex pocket in the foot; the tripod's screw comes from below.

Axes: x = toward the piano (the hand's axis), y = sideways, z = up. All numbers in mm.
The hand's axis ends up AXIS_H above the tripod plate. Height above the keys = tripod column, pitch = tripod head."""
import os
import numpy as np, trimesh
from trimesh.creation import box, cylinder

T_PLATE, T_FOOT = 10.0, 12.0          # thickness of the upright plate and of the foot
W = 68.0                              # width (y)
AXIS_H = 44.0                         # flange centre above the bottom of the foot
BOLT_R = 27.0                         # M6 holes on a 54 mm circle (the slots allow 41 to 57 mm)
M6_D, M6_NUT_AF, M6_NUT_H = 6.6, 10.4, 4.5        # clearance hole, nut pocket across flats (10 + 0.4), pocket depth
QTR_D, QTR_NUT_AF = 6.8, 11.6                      # 1/4"-20: clearance hole, nut pocket (7/16" = 11.1 + 0.5)
UNDER_NUT = 3.0                                   # plastic left under the tripod nut: short tripod screws (6 mm) still reach it
QTR_NUT_H = T_FOOT - UNDER_NUT
WIN_Y, WIN_Z = 26.0, 44.0             # centre window
FOOT_L = 62.0                         # foot length behind the plate
TRIPOD_X = -30.0                      # tripod screw position (x), measured from the plate's back face
GUSSET_T, GUSSET_L = 6.0, 46.0

def place(mesh, xyz): mesh.apply_translation(xyz); return mesh
def cyl_x(d, h, sections=64):         # cylinder along x, starting at x = 0
    c = cylinder(radius=d / 2, height=h, sections=sections); c.apply_transform(trimesh.transformations.rotation_matrix(np.pi / 2, [0, 1, 0])); return place(c, [h / 2, 0, 0])
def hex_x(af, h):                     # hexagonal prism along x, starting at x = 0
    c = cylinder(radius=af / np.sqrt(3), height=h, sections=6); c.apply_transform(trimesh.transformations.rotation_matrix(np.pi / 2, [0, 1, 0])); return place(c, [h / 2, 0, 0])

H = AXIS_H + BOLT_R / np.sqrt(2) + M6_D / 2 + 9.0                      # plate height
plate = place(box([T_PLATE, W, H]), [T_PLATE / 2, 0, H / 2])
foot = place(box([FOOT_L + T_PLATE, W, T_FOOT]), [(T_PLATE - FOOT_L) / 2, 0, T_FOOT / 2])
parts = [plate, foot]
for s in (-1, 1):                     # two triangular ribs along the sides
    tri = trimesh.creation.extrude_polygon(__import__("shapely.geometry", fromlist=["Polygon"]).Polygon([(0, 0), (-GUSSET_L, 0), (0, GUSSET_L)]), GUSSET_T)
    tri.apply_transform(np.array([[1, 0, 0, 0], [0, 0, 1, 0], [0, 1, 0, 0], [0, 0, 0, 1.0]]))      # polygon (x, z), extruded along y
    parts.append(place(tri, [0, s * (W / 2 - GUSSET_T / 2) - GUSSET_T / 2, T_FOOT]))
body = trimesh.boolean.union(parts, engine="manifold")

cuts = [place(box([T_PLATE + 2, WIN_Y, WIN_Z]), [T_PLATE / 2, 0, AXIS_H])]
b = BOLT_R / np.sqrt(2)
for sy in (-1, 1):
    for sz in (-1, 1):
        cuts.append(place(cyl_x(M6_D, T_PLATE + 2), [-1, sy * b, AXIS_H + sz * b]))
        cuts.append(place(hex_x(M6_NUT_AF, M6_NUT_H + 1), [-1, sy * b, AXIS_H + sz * b]))            # pocket on the back face
cuts.append(place(cylinder(radius=QTR_D / 2, height=T_FOOT + 2, sections=64), [TRIPOD_X, 0, T_FOOT / 2]))
cuts.append(place(cylinder(radius=QTR_NUT_AF / np.sqrt(3), height=QTR_NUT_H + 1, sections=6), [TRIPOD_X, 0, T_FOOT - QTR_NUT_H / 2 + 0.5]))
part = trimesh.boolean.difference([body] + cuts, engine="manifold")

out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tripod_mount.stl"); part.export(out)
e = part.extents
print(f"{out}: {e[0]:.0f} x {e[1]:.0f} x {e[2]:.0f} mm, watertight {part.is_watertight}, {part.volume / 1000:.0f} cm3 solid "
      f"(about {part.volume / 1000 * 1.24 * 0.55:.0f} g of PLA at 40 % infill), hand axis {AXIS_H:.0f} mm above the tripod plate")
