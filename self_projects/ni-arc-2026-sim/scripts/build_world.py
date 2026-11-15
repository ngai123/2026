"""
build_world.py — Generate mjcf/world.xml from spec/arena.yaml.

Run:   .venv/bin/python scripts/build_world.py [--with-robot]
Output: mjcf/world.xml

Generates the static arena (field, perimeter, goals, balls, zone decals).
With --with-robot, also places a differential-drive robot from spec/robot_diff.yaml
at the Red starting base.

v0.1 — square openings on goal faces (40 cm × 40 cm) as an approximation of the
       rulebook's 40 cm circular openings. To be replaced in v0.2 with a triangulated
       mesh having proper circular cutouts.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from xml.dom import minidom
from xml.etree.ElementTree import Element, SubElement, tostring

import yaml

ROOT = Path(__file__).resolve().parent.parent
SPEC_PATH = ROOT / "spec" / "arena.yaml"
ROBOT_SPEC_PATH = ROOT / "spec" / "robot_diff.yaml"
OUT_PATH = ROOT / "mjcf" / "world.xml"

# Import robot builders without re-executing build_robot.py's main.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_robot import build_robot_body, build_robot_actuators  # noqa: E402


# ---------------------------------------------------------------------------
# Colour helpers
# ---------------------------------------------------------------------------
def hex_to_rgba(hex_str: str, alpha: float = 1.0) -> str:
    h = hex_str.lstrip("#")
    r, g, b = (int(h[i : i + 2], 16) / 255.0 for i in (0, 2, 4))
    return f"{r:.3f} {g:.3f} {b:.3f} {alpha:.3f}"


def fmt(v: float) -> str:
    return f"{v:.6g}"


def fmt3(x: float, y: float, z: float) -> str:
    return f"{fmt(x)} {fmt(y)} {fmt(z)}"


# ---------------------------------------------------------------------------
# Geometry helpers
# ---------------------------------------------------------------------------
def add_box(
    parent: Element,
    name: str,
    pos_xyz: tuple[float, float, float],
    size_half_xyz: tuple[float, float, float],
    rgba: str,
    *,
    contype: int = 1,
    conaffinity: int = 1,
    euler_deg: tuple[float, float, float] | None = None,
) -> Element:
    """Add a static box geom (no body) — fixed to the world."""
    attrs = {
        "name": name,
        "type": "box",
        "pos": fmt3(*pos_xyz),
        "size": fmt3(*size_half_xyz),
        "rgba": rgba,
        "contype": str(contype),
        "conaffinity": str(conaffinity),
    }
    if euler_deg is not None:
        attrs["euler"] = fmt3(*euler_deg)
    return SubElement(parent, "geom", attrs)


def add_capsule(
    parent: Element,
    name: str,
    from_xyz: tuple[float, float, float],
    to_xyz: tuple[float, float, float],
    radius: float,
    rgba: str,
) -> Element:
    return SubElement(
        parent,
        "geom",
        {
            "name": name,
            "type": "capsule",
            "fromto": f"{fmt3(*from_xyz)} {fmt3(*to_xyz)}",
            "size": fmt(radius),
            "rgba": rgba,
            "contype": "1",
            "conaffinity": "1",
        },
    )


def add_ball_body(
    parent: Element,
    name: str,
    pos_xyz: tuple[float, float, float],
    radius: float,
    mass: float,
    rgba: str,
    friction_slide: float,
    restitution: float,
) -> Element:
    body = SubElement(parent, "body", {"name": name, "pos": fmt3(*pos_xyz)})
    SubElement(body, "freejoint", {"name": f"{name}_free"})
    SubElement(
        body,
        "geom",
        {
            "name": name,
            "type": "sphere",
            "size": fmt(radius),
            "mass": fmt(mass),
            "rgba": rgba,
            "friction": f"{fmt(friction_slide)} 0.005 0.0001",
            "solref": f"0.01 {fmt(1.0 - restitution)}",  # crude restitution mapping
            "contype": "1",
            "conaffinity": "1",
        },
    )
    return body


# ---------------------------------------------------------------------------
# Component builders
# ---------------------------------------------------------------------------
def build_floor(world: Element, spec: dict) -> None:
    fld = spec["field"]
    half_x = fld["size_xy_m"][0] / 2.0
    half_y = fld["size_xy_m"][1] / 2.0
    SubElement(
        world,
        "geom",
        {
            "name": "floor",
            "type": "plane",
            "pos": "0 0 0",
            "size": f"{fmt(half_x)} {fmt(half_y)} 0.1",
            "rgba": hex_to_rgba(fld["flooring_color"]),
            "friction": f"{fmt(spec['physics']['floor_friction_slide'])} 0.005 0.0001",
            "solref": f"0.01 {fmt(1.0 - spec['physics']['floor_restitution'])}",
        },
    )


def build_perimeter(world: Element, spec: dict) -> None:
    """Four PVC pipe capsules around the 6 m × 6 m boundary, ~5 cm above the floor."""
    fld = spec["field"]
    half_x = fld["size_xy_m"][0] / 2.0
    half_y = fld["size_xy_m"][1] / 2.0
    r = fld["perimeter_pipe_od_m"] / 2.0
    z = r  # rest the pipe on the floor (axis at radius height)
    rgba = "0.7 0.7 0.7 1.0"
    add_capsule(world, "pipe_north", (-half_x, half_y, z), (half_x, half_y, z), r, rgba)
    add_capsule(world, "pipe_south", (-half_x, -half_y, z), (half_x, -half_y, z), r, rgba)
    add_capsule(world, "pipe_east", (half_x, -half_y, z), (half_x, half_y, z), r, rgba)
    add_capsule(world, "pipe_west", (-half_x, -half_y, z), (-half_x, half_y, z), r, rgba)


def build_zone_decals(world: Element, spec: dict) -> None:
    """Thin flat coloured boxes layered on top of the floor.

    Layered z so each tier sits cleanly above the previous (avoids z-fighting):
      z=0.005  NEAR strips + shared ball zone
      z=0.010  starting zones (overlay on NEAR/MID)
      z=0.015  starting bases (overlay on starting zones)
    """
    z = 0.020
    thickness = 0.005
    zones = spec["zones"]

    def add_zone_rect(name: str, xrange, yrange, color_hex: str, alpha: float = 0.6) -> None:
        cx = (xrange[0] + xrange[1]) / 2.0
        cy = (yrange[0] + yrange[1]) / 2.0
        hx = (xrange[1] - xrange[0]) / 2.0
        hy = (yrange[1] - yrange[0]) / 2.0
        add_box(
            world,
            name,
            (cx, cy, z),
            (hx, hy, thickness),
            hex_to_rgba(color_hex, alpha),
            contype=0,
            conaffinity=0,  # purely visual
        )

    # Team-colored NEAR strips (opaque so they read at any camera angle).
    add_zone_rect(
        "zone_red_near", zones["red_near"]["x"], zones["red_near"]["y"],
        spec["teams"]["red"]["starting_zone_color"], alpha=1.0,
    )
    add_zone_rect(
        "zone_blue_near", zones["blue_near"]["x"], zones["blue_near"]["y"],
        spec["teams"]["blue"]["starting_zone_color"], alpha=1.0,
    )
    add_zone_rect(
        "zone_shared_ball", zones["shared_ball"]["x"], zones["shared_ball"]["y"],
        zones["shared_ball"]["color"], alpha=1.0,
    )
    # Starting zones — bump a tick above the NEAR strip so the colour reads as distinct.
    z_start = z + 0.005
    def add_lift(name, xr, yr, color, alpha):
        cx = (xr[0] + xr[1]) / 2.0
        cy = (yr[0] + yr[1]) / 2.0
        hx = (xr[1] - xr[0]) / 2.0
        hy = (yr[1] - yr[0]) / 2.0
        add_box(world, name, (cx, cy, z_start), (hx, hy, thickness),
                hex_to_rgba(color, alpha), contype=0, conaffinity=0)
    add_lift("zone_red_start", zones["red_starting"]["x"], zones["red_starting"]["y"],
             spec["teams"]["red"]["starting_zone_color"], 1.0)
    add_lift("zone_blue_start", zones["blue_starting"]["x"], zones["blue_starting"]["y"],
             spec["teams"]["blue"]["starting_zone_color"], 1.0)
    # Starting bases — yet another small lift, slightly darker.
    z_base = z + 0.010
    sb = spec["starting_bases"]
    def add_base(name, xr, yr, color):
        cx = (xr[0] + xr[1]) / 2.0
        cy = (yr[0] + yr[1]) / 2.0
        hx = (xr[1] - xr[0]) / 2.0
        hy = (yr[1] - yr[0]) / 2.0
        add_box(world, name, (cx, cy, z_base), (hx, hy, thickness),
                hex_to_rgba(color, 1.0), contype=0, conaffinity=0)
    add_base("base_red", sb["red"]["x"], sb["red"]["y"],
             spec["teams"]["red"]["starting_base_color"])
    add_base("base_blue", sb["blue"]["x"], sb["blue"]["y"],
             spec["teams"]["blue"]["starting_base_color"])


def build_goal(world: Element, spec: dict, team: str) -> None:
    """Build a goal structure for the given team ('red' or 'blue').

    v0.2: front face uses a triangulated mesh (`goal_face.obj`) generated by
    scripts/make_goal_face_mesh.py — gives proper circular cutouts matching
    the rulebook's 40 cm diameter openings.
    """
    g = spec["goal"]
    L, D, H = g["size_xyz_m"]            # length, depth, height
    t = g["wall_thickness_m"]
    rgba = hex_to_rgba(g["material_color"])

    cx, cy = g[f"{team}_goal_centre_xy"]
    yaw = g[f"{team}_goal_yaw_deg"]
    prefix = f"goal_{team}"

    body = SubElement(
        world,
        "body",
        {"name": prefix, "pos": fmt3(cx, cy, H / 2.0),
         "euler": fmt3(0.0, 0.0, yaw)},
    )

    # In the goal's local frame:
    #   X = along the 2-m length (left-right when facing the goal)
    #   Y = depth (front face at Y = -D/2, back face at Y = +D/2)
    #   Z = height (centre of structure at Z = 0; floor at Z = -H/2)

    # Back panel (full L × H, thickness t along Y).
    add_box(body, f"{prefix}_back",
            (0.0, +D / 2.0 - t / 2.0, 0.0),
            (L / 2.0, t / 2.0, H / 2.0), rgba)
    # Side panels (D depth × H height, thickness t along X). Length covers full D.
    add_box(body, f"{prefix}_side_left",
            (-L / 2.0 + t / 2.0, 0.0, 0.0),
            (t / 2.0, D / 2.0, H / 2.0), rgba)
    add_box(body, f"{prefix}_side_right",
            (+L / 2.0 - t / 2.0, 0.0, 0.0),
            (t / 2.0, D / 2.0, H / 2.0), rgba)
    # Top panel.
    add_box(body, f"{prefix}_top",
            (0.0, 0.0, +H / 2.0 - t / 2.0),
            (L / 2.0, D / 2.0, t / 2.0), rgba)

    # ---- Front face: triangulated mesh with 6 circular cutouts ----
    # Mesh native frame after make_goal_face_mesh.py:
    #   X ∈ [-L/2, +L/2]    (length, already correct)
    #   Y ∈ [-t, 0]         (thickness; we want centre at body-Y = -D/2 + t/2)
    #   Z ∈ [0, H]          (height; we want centre at body-Z = 0)
    # Place the mesh's origin so its centre aligns with the front-face plane.
    mesh_pos_y = -D / 2.0 + t / 2.0 - (-t / 2.0)   # = -D/2 + t
    mesh_pos_z = -H / 2.0
    SubElement(
        body,
        "geom",
        {
            "name": f"{prefix}_face",
            "type": "mesh",
            "mesh": "goal_face",
            "pos": fmt3(0.0, mesh_pos_y, mesh_pos_z),
            "rgba": rgba,
            "contype": "1",
            "conaffinity": "1",
        },
    )


def build_balls(world: Element, spec: dict) -> None:
    """Standard balls inside shared zone; preloaded balls at starting bases;
    golden balls just outside the field next to each team's starting base."""
    import math
    import random

    rng = random.Random(42)
    sb = spec["balls"]["standard"]
    g = spec["balls"]["golden"]
    r_std = sb["diameter_m"] / 2.0
    r_gold = g["diameter_m"] / 2.0

    # --- Standard balls in shared zone, lightly jittered grid ---
    z_x = spec["zones"]["shared_ball"]["x"]
    z_y = spec["zones"]["shared_ball"]["y"]
    n = sb["count_in_shared_zone"]
    cols = math.ceil(math.sqrt(n))
    rows = math.ceil(n / cols)
    cell_x = (z_x[1] - z_x[0]) / cols
    cell_y = (z_y[1] - z_y[0]) / rows
    placed = 0
    for i in range(rows):
        for j in range(cols):
            if placed >= n:
                break
            cx = z_x[0] + (j + 0.5) * cell_x + rng.uniform(-0.02, 0.02)
            cy = z_y[0] + (i + 0.5) * cell_y + rng.uniform(-0.02, 0.02)
            add_ball_body(
                world, f"ball_std_{placed:02d}",
                (cx, cy, r_std + 0.02), r_std, sb["mass_kg"],
                hex_to_rgba(sb["color"]),
                sb["friction_slide"], sb["restitution"],
            )
            placed += 1

    # --- Preloaded balls at each starting base (2 per team), stacked above ---
    bases = spec["starting_bases"]
    for team, base in bases.items():
        cx = (base["x"][0] + base["x"][1]) / 2.0
        cy = (base["y"][0] + base["y"][1]) / 2.0
        for k in range(sb["count_preloaded_per_team"]):
            add_ball_body(
                world, f"ball_pre_{team}_{k}",
                (cx + (k - 0.5) * 2 * r_std, cy, r_std + 0.05),
                r_std, sb["mass_kg"],
                hex_to_rgba(sb["color"]),
                sb["friction_slide"], sb["restitution"],
            )

    # --- Golden balls outside the field, near each starting base ---
    # Rulebook: 10 golden balls per team, released onto FIELD at t=210 s.
    # For static visualisation we place them just outside the field perimeter.
    half_x = spec["field"]["size_xy_m"][0] / 2.0
    for team, sign in (("red", -1), ("blue", +1)):
        x_outside = sign * (half_x + 0.30)
        for k in range(g["count_per_team"]):
            y = -1.0 + (k * 0.22)
            add_ball_body(
                world, f"ball_gold_{team}_{k:02d}",
                (x_outside, y, r_gold + 0.02),
                r_gold, g["mass_kg"],
                hex_to_rgba(g["color"]),
                g["friction_slide"], g["restitution"],
            )


# ---------------------------------------------------------------------------
# Top-level MJCF assembly
# ---------------------------------------------------------------------------
def build_mjcf(spec: dict, robot_spec: dict | None = None) -> str:
    mujoco = Element("mujoco", {"model": "ni_arc_2026_arena"})

    SubElement(mujoco, "compiler", {
        "angle": "degree", "coordinate": "local",
        "meshdir": "assets",   # mesh files live in mjcf/assets/
    })

    SubElement(
        mujoco,
        "option",
        {
            "timestep": fmt(spec["physics"]["timestep_s"]),
            "gravity": fmt3(*spec["physics"]["gravity_mps2"]),
            "integrator": spec["physics"]["integrator"],
        },
    )

    visual = SubElement(mujoco, "visual")
    SubElement(visual, "headlight", {"diffuse": "0.6 0.6 0.6", "ambient": "0.4 0.4 0.4"})
    SubElement(visual, "global", {"offwidth": "1280", "offheight": "720"})

    asset = SubElement(mujoco, "asset")
    SubElement(asset, "texture", {
        "type": "skybox", "builtin": "gradient",
        "rgb1": "0.6 0.8 1.0", "rgb2": "0.2 0.3 0.5",
        "width": "256", "height": "256",
    })
    # Triangulated mesh of the goal front panel with six circular cutouts.
    # Generated by scripts/make_goal_face_mesh.py from spec/arena.yaml.
    SubElement(asset, "mesh", {
        "name": "goal_face",
        "file": "goal_face.obj",   # resolved against compiler.meshdir = "assets"
    })

    world = SubElement(mujoco, "worldbody")

    # Lighting
    SubElement(world, "light", {
        "directional": "true", "pos": "0 0 6",
        "dir": "0 0 -1", "diffuse": "0.8 0.8 0.8",
    })

    # Fixed cameras for deterministic offscreen rendering.
    # MJCF camera convention: camera looks down its local -Z axis; +Y is "up" on screen.
    # xyaxes = (X_world_xyz, Y_world_xyz) — where Y is the on-screen "up".
    SubElement(world, "camera", {
        "name": "cam_top",
        "pos": "0 0 9",
        "xyaxes": "1 0 0  0 1 0",  # +X right, +Y up on screen
        "fovy": "45",
    })
    # Iso SW: camera at (-6,-6,6), looking at origin. View dir = (1,1,-1)/√3.
    # Camera Z (back) = -view = (-1,-1,1). Choose camera Y (up) approx world +Z:
    #   project world Z onto plane perp to view dir → (1,1,2)/√6.
    # Camera X (right) = cross(Y, Z) = (3,-3,0)/√18 → (1,-1,0).
    SubElement(world, "camera", {
        "name": "cam_iso_sw",
        "pos": "-6 -6 6",
        "xyaxes": "1 -1 0  1 1 2",
        "fovy": "45",
    })
    # Looking AT the blue goal (at +Y) from the centre, roughly eye level.
    # Camera at (0,1,1) looking toward +Y, so view dir = (0,1,0).
    # Camera Y (screen up) = world +Z = (0,0,1). Camera X (screen right) = cross(Y,Z_cam):
    #   Z_cam = -view = (0,-1,0). X = cross((0,0,1),(0,-1,0)) = (1,0,0).
    SubElement(world, "camera", {
        "name": "cam_blue_goal",
        "pos": "0 1.0 1.0",
        "xyaxes": "1 0 0  0 0 1",
        "fovy": "55",
    })
    # Same for red goal (at -Y), camera south of centre looking -Y.
    SubElement(world, "camera", {
        "name": "cam_red_goal",
        "pos": "0 -1.0 1.0",
        "xyaxes": "-1 0 0  0 0 1",
        "fovy": "55",
    })

    build_floor(world, spec)
    build_zone_decals(world, spec)
    build_perimeter(world, spec)
    build_goal(world, spec, "red")
    build_goal(world, spec, "blue")
    build_balls(world, spec)

    if robot_spec is not None:
        # Place robot at the centre of the Red starting base, facing +X (toward field centre).
        # Red starting base bounds: x∈[-3.0,-2.3], y∈[-0.35,0.35].
        rb = spec["starting_bases"]["red"]
        cx = (rb["x"][0] + rb["x"][1]) / 2.0
        cy = (rb["y"][0] + rb["y"][1]) / 2.0
        # Robot's +X = forward. Yaw=0 → forward points to world +X (toward field centre
        # from the Red base on the left side).
        build_robot_body(world, robot_spec, pose_xyz=(cx, cy, 0.0), yaw_deg=0.0)
        build_robot_actuators(mujoco, robot_spec)

    raw = tostring(mujoco, encoding="unicode")
    pretty = minidom.parseString(raw).toprettyxml(indent="  ")
    return pretty


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--with-robot", action="store_true",
                    help="include diff-drive robot at the Red starting base")
    args = ap.parse_args()

    if not SPEC_PATH.exists():
        print(f"ERROR: spec not found: {SPEC_PATH}", file=sys.stderr)
        return 2
    spec = yaml.safe_load(SPEC_PATH.read_text())
    robot_spec = None
    if args.with_robot:
        if not ROBOT_SPEC_PATH.exists():
            print(f"ERROR: robot spec not found: {ROBOT_SPEC_PATH}", file=sys.stderr)
            return 2
        robot_spec = yaml.safe_load(ROBOT_SPEC_PATH.read_text())
    xml = build_mjcf(spec, robot_spec)
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(xml)
    print(f"wrote {OUT_PATH}  ({len(xml):,} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
