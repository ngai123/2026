"""
make_goal_face_mesh.py — Build a triangulated mesh of the goal front face with
six circular openings cut out. Save as mjcf/assets/goal_face.obj.

The mesh is the FRONT PANEL only (length × height plate, thickness along its
normal). It is positioned in build_world.py so it sits flush with the front of
the goal cavity.

Mesh frame after generation:
  +X = along goal length (2.0 m)
  +Y = thickness direction (15 mm)   ← will be remapped via euler in MJCF
  +Z = along goal height (1.5 m)
The polygon is built in the (X, Z) plane and extruded along Y.

Run:   .venv/bin/python scripts/make_goal_face_mesh.py
Output: mjcf/assets/goal_face.obj
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import trimesh
import yaml
from shapely.geometry import Polygon, Point

ROOT = Path(__file__).resolve().parent.parent
SPEC = ROOT / "spec" / "arena.yaml"
OUT = ROOT / "mjcf" / "assets" / "goal_face.obj"

CIRCLE_SEGMENTS = 64   # higher = smoother circular openings


def main() -> int:
    spec = yaml.safe_load(SPEC.read_text())
    g = spec["goal"]
    L = g["size_xyz_m"][0]                # 2.0 m
    H = g["size_xyz_m"][2]                # 1.5 m
    t = g["wall_thickness_m"]             # 0.015 m
    r = g["opening_diameter_m"] / 2.0     # 0.20 m
    low_z_bot = g["low_row_bottom_m"]     # 0.50 m (from floor)
    high_z_bot = g["high_row_bottom_m"]   # 1.00 m
    xs = g["opening_xs_m"]                # [-0.6, 0.0, 0.6]

    # Outer rectangle in (X, Z) plane, X∈[-L/2, +L/2], Z∈[0, H].
    outer = Polygon([
        (-L / 2.0, 0.0),
        (+L / 2.0, 0.0),
        (+L / 2.0, H),
        (-L / 2.0, H),
    ])

    # Six circular holes (low row + high row).
    holes = []
    for z_bot in (low_z_bot, high_z_bot):
        z_centre = z_bot + r  # circle centre = bottom + radius
        for x_centre in xs:
            holes.append(Point(x_centre, z_centre).buffer(r, quad_segs=CIRCLE_SEGMENTS // 4))

    # Subtract holes from outer.
    face_poly = outer
    for h in holes:
        face_poly = face_poly.difference(h)

    # Extrude along Y (mesh thickness direction).
    mesh = trimesh.creation.extrude_polygon(face_poly, height=t)

    # extrude_polygon extrudes a 2D polygon (in XY plane) along Z by `height`.
    # We need our face to live in the XZ plane and be thick along Y.
    # Currently mesh: 2D poly was in (X, Z) values but trimesh treats poly coords
    # as (X, Y), extrudes along Z. So mesh has:
    #   X = goal-length (correct)
    #   Y = goal-height (we wanted Z)
    #   Z = thickness   (we wanted Y)
    # Swap Y and Z to fix: rotate -90° about X axis.
    R = trimesh.transformations.rotation_matrix(np.pi / 2.0, [1, 0, 0])
    mesh.apply_transform(R)
    # After rotation: X still length, Y now thickness, Z now height.
    # But the rotation flipped sign of Z (now goes from -H to 0).
    # Shift up so Z ∈ [0, H] again.
    mins = mesh.bounds[0]
    mesh.apply_translation([0.0, 0.0, -mins[2]])

    # Sanity check.
    b = mesh.bounds
    print(f"mesh bounds (m): X={b[0][0]:+.3f}..{b[1][0]:+.3f}  "
          f"Y={b[0][1]:+.3f}..{b[1][1]:+.3f}  "
          f"Z={b[0][2]:+.3f}..{b[1][2]:+.3f}")
    print(f"mesh: {len(mesh.vertices)} verts, {len(mesh.faces)} faces, "
          f"watertight={mesh.is_watertight}, volume={mesh.volume:.5f} m³")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    mesh.export(OUT)
    print(f"wrote {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
