"""
build_robot.py — Generate mjcf/robot_diff.xml from spec/robot_diff.yaml.

Run:   .venv/bin/python scripts/build_robot.py
Output: mjcf/robot_diff.xml

Builds a parametric differential-drive robot with:
  - 2 drive wheels (differential, velocity-controlled)
  - 2 passive caster balls (front + back)
  - Intake roller (velocity-controlled)
  - Pitch-adjustable launcher arm with dual flywheels (position + velocity-controlled)
  - Camera placeholder geom (visual only)

This file does NOT modify scripts/build_world.py.
To integrate, call build_robot_body() and build_robot_actuators() from a
separate world-builder or test harness.

HAL method mapping (LabVIEW portability):
  wheel_left / wheel_right   → set_chassis_velocity(left_rad_s, right_rad_s)
  intake_roller               → intake_engage(duty)
  flywheel_left / flywheel_right → launcher_charge(left_rpm, right_rpm)
  pitch_arm                   → launcher_aim(pitch_deg)
  wheel joints qpos           → read_encoders() → (left_rad, right_rad)
  IMU (auto, MuJoCo)          → read_imu() → (yaw_rad, yaw_rate_rad_s)
  intake_beam (sim sensor)    → read_intake_beam() → bool
  camera placeholder          → read_camera_balls() → list[(bearing, dist, golden)]
"""
from __future__ import annotations

import math
import sys
from pathlib import Path
from xml.dom import minidom
from xml.etree.ElementTree import Element, SubElement, tostring

import yaml

ROOT = Path(__file__).resolve().parent.parent
SPEC_PATH = ROOT / "spec" / "robot_diff.yaml"
OUT_PATH = ROOT / "mjcf" / "robot_diff.xml"


# ---------------------------------------------------------------------------
# Formatting helpers (same style as build_world.py)
# ---------------------------------------------------------------------------
def fmt(v: float) -> str:
    return f"{v:.6g}"


def fmt3(x: float, y: float, z: float) -> str:
    return f"{fmt(x)} {fmt(y)} {fmt(z)}"


def hex_to_rgba(hex_str: str, alpha: float = 1.0) -> str:
    h = hex_str.lstrip("#")
    r, g, b = (int(h[i : i + 2], 16) / 255.0 for i in (0, 2, 4))
    return f"{r:.3f} {g:.3f} {b:.3f} {alpha:.3f}"


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
    mass: float | None = None,
) -> Element:
    """Add a box geom to a body."""
    attrs: dict[str, str] = {
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
    if mass is not None:
        attrs["mass"] = fmt(mass)
    return SubElement(parent, "geom", attrs)


def add_cylinder(
    parent: Element,
    name: str,
    fromto: tuple[float, float, float, float, float, float],
    radius: float,
    rgba: str,
    *,
    mass: float | None = None,
    contype: int = 1,
    conaffinity: int = 1,
) -> Element:
    """Add a cylinder geom via fromto + size."""
    attrs: dict[str, str] = {
        "name": name,
        "type": "cylinder",
        "fromto": f"{fmt(fromto[0])} {fmt(fromto[1])} {fmt(fromto[2])} "
                  f"{fmt(fromto[3])} {fmt(fromto[4])} {fmt(fromto[5])}",
        "size": fmt(radius),
        "rgba": rgba,
        "contype": str(contype),
        "conaffinity": str(conaffinity),
    }
    if mass is not None:
        attrs["mass"] = fmt(mass)
    return SubElement(parent, "geom", attrs)


# ---------------------------------------------------------------------------
# Robot builder
# ---------------------------------------------------------------------------
def build_robot_body(
    world_elem: Element,
    robot_spec: dict,
    pose_xyz: tuple[float, float, float] = (0.0, 0.0, 0.0),
    yaw_deg: float = 0.0,
) -> None:
    """Add <body name="robot_red"> with all child geoms/joints to a <worldbody>.

    Args:
        world_elem: The <worldbody> Element to append the robot to.
        robot_spec: Parsed robot_diff.yaml dict.
        pose_xyz:   World position (x, y, z) of the robot origin (chassis bottom-centre).
        yaw_deg:    Initial yaw rotation (degrees) around Z axis.
    """
    r = robot_spec
    ch = r["chassis"]
    drv = r["drive"]
    wh = drv["wheels"]
    cs = drv["casters"]
    intk = r["intake"]["roller"]
    lnchr = r["launcher"]
    fw = lnchr["flywheels"]
    pa = lnchr["pitch_arm"]
    cam = r["camera_placeholder"]

    # ---- Derived dimensions ----
    ch_l, ch_w, ch_h = ch["length_m"], ch["width_m"], ch["height_m"]
    ch_mass = ch["mass_kg"]
    ch_rgba = hex_to_rgba(ch["color"])

    wh_r = wh["radius_m"]
    wh_hw = wh["hub_width_m"]
    wb = wh["wheelbase_m"]

    cs_r = cs["radius_m"]
    cs_front_x = cs["front_offset_m"]
    cs_back_x = cs["back_offset_m"]

    # Ground clearance — chassis bottom sits this high above floor.
    gc = ch.get("ground_clearance_m", 0.0)
    # World z of chassis centre = ch_h/2 + ground_clearance.
    # To convert "height-above-floor" → chassis-local Z, subtract chassis-centre world z.
    chassis_centre_world_z = ch_h / 2.0 + gc

    # Intake placement in chassis-local frame:
    #   X = +ch_l/2 + front_offset (ahead of chassis face)
    #   Z = height_above_floor − chassis_centre_world_z
    intk_x = ch_l / 2.0 + intk["front_offset_m"]
    intk_z = intk["height_above_floor_m"] - chassis_centre_world_z

    # Pitch arm hinge in chassis-local frame:
    #   X = -ch_l/2 (back face)
    #   Z = hinge_z − chassis_centre_world_z
    pa_x = -ch_l / 2.0
    pa_z = pa["hinge_z_m"] - chassis_centre_world_z

    # Pitch arm default angle (from spec pitch_default_deg, mapped to joint coords)
    pa_default_deg = pa["pitch_default_deg"]
    # In joint frame: arm at -X horizontal when joint=0; positive joint angle → arm tilts
    # upward.   For 10..70 deg from horizontal → joint range = [-(70°), -(10°)].
    pa_joint_min_rad = -math.radians(pa["pitch_max_deg"])
    pa_joint_max_rad = -math.radians(pa["pitch_min_deg"])
    pa_default_rad = -math.radians(pa_default_deg)

    # ---- Root body with freejoint ----
    # Chassis centre in world: raise by ch_h/2 + ground_clearance so the chassis
    # bottom sits at pose_xyz.z + ground_clearance (i.e., floats above floor).
    cx, cy, cz = pose_xyz[0], pose_xyz[1], pose_xyz[2] + chassis_centre_world_z
    robot_body = SubElement(
        world_elem,
        "body",
        {
            "name": "robot_red",
            "pos": fmt3(cx, cy, cz),
            "euler": fmt3(0.0, 0.0, yaw_deg),
        },
    )
    SubElement(robot_body, "freejoint", {"name": "robot_free"})

    # ---- Materials (for visual distinction) ----
    asset = None  # materials are defined at top-level if needed; we use inline rgba.

    # ---- Chassis box ----
    add_box(
        robot_body,
        "chassis_box",
        (0.0, 0.0, 0.0),
        (ch_l / 2.0, ch_w / 2.0, ch_h / 2.0),
        ch_rgba,
    )

    # ---- Drive wheels (left + right) ----
    wheel_rgba = hex_to_rgba(wh["color"])
    for side, sign_y in [("left", +1.0), ("right", -1.0)]:
        w_name = f"wheel_{side}"
        wy = sign_y * wb / 2.0
        # Wheel centre is at world z = wh_r (so wheel bottom touches floor).
        # In chassis-local frame: subtract chassis_centre_world_z.
        wz = wh_r - chassis_centre_world_z
        wheel_body = SubElement(
            robot_body,
            "body",
            {"name": w_name, "pos": fmt3(0.0, wy, wz)},
        )
        SubElement(
            wheel_body,
            "joint",
            {
                "name": w_name,
                "type": "hinge",
                "axis": "0 1 0",
                "limited": "false",
                "damping": "0.01",
            },
        )
        # Cylinder: fromto along Y axis, half-width = hub_width/2
        hw_half = wh_hw / 2.0
        add_cylinder(
            wheel_body,
            f"{w_name}_geom",
            (0.0, -hw_half, 0.0, 0.0, +hw_half, 0.0),
            wh_r,
            wheel_rgba,
            mass=wh["mass_kg"],
        )

    # ---- Caster balls (front + back) ----
    caster_rgba = hex_to_rgba(cs["color"])
    for c_name, cx_off in [("caster_front", cs_front_x), ("caster_back", cs_back_x)]:
        # Caster sphere centre at world z = cs_r (touches floor).
        cz_off = cs_r - chassis_centre_world_z
        caster_body = SubElement(
            robot_body,
            "body",
            {"name": c_name, "pos": fmt3(cx_off, 0.0, cz_off)},
        )
        SubElement(
            caster_body,
            "joint",
            {
                "name": f"{c_name}_j",
                "type": "ball",
                "damping": "0.0001",
                "limited": "false",
            },
        )
        SubElement(
            caster_body,
            "geom",
            {
                "name": f"{c_name}_geom",
                "type": "sphere",
                "size": fmt(cs_r),
                "mass": fmt(cs["mass_kg"]),
                "rgba": caster_rgba,
                "contype": "1",
                "conaffinity": "1",
            },
        )

    # ---- Intake roller ----
    int_rgba = hex_to_rgba(intk["color"])
    int_body = SubElement(
        robot_body,
        "body",
        {"name": "intake_roller", "pos": fmt3(intk_x, 0.0, intk_z)},
    )
    SubElement(
        int_body,
        "joint",
        {
            "name": "intake_roller",
            "type": "hinge",
            "axis": "0 1 0",
            "limited": "false",
            "damping": "0.01",
        },
    )
    # Roller cylinder along Y axis
    r_half = intk["length_m"] / 2.0
    fric = intk["friction"]
    SubElement(
        int_body,
        "geom",
        {
            "name": "intake_roller_geom",
            "type": "cylinder",
            "fromto": f"0 {fmt(-r_half)} 0  0 {fmt(+r_half)} 0",
            "size": fmt(intk["radius_m"]),
            "mass": fmt(intk["mass_kg"]),
            "rgba": int_rgba,
            "friction": f"{fmt(fric[0])} {fmt(fric[1])} {fmt(fric[2])}",
            "contype": "1",
            "conaffinity": "1",
        },
    )

    # ---- Launcher pitch arm ----
    pa_rgba = hex_to_rgba(pa["color"])
    pa_al = pa["arm_length_m"]
    # Default orientation: arm extends backward at -pa_default_deg from horizontal.
    arm_body = SubElement(
        robot_body,
        "body",
        {
            "name": "pitch_arm",
            "pos": fmt3(pa_x, 0.0, pa_z),
            "euler": fmt3(0.0, pa_default_deg, 0.0),   # initial visual orientation
        },
    )
    SubElement(
        arm_body,
        "joint",
        {
            "name": "pitch_arm",
            "type": "hinge",
            "axis": "0 1 0",
            "limited": "true",
            "range": f"{fmt(pa_joint_min_rad)} {fmt(pa_joint_max_rad)}",
            "damping": "0.1",
        },
    )
    # Arm geom: thin box extending from hinge to flywheel centre.
    add_box(
        arm_body,
        "pitch_arm_geom",
        (-pa_al / 2.0, 0.0, 0.0),
        (pa_al / 2.0, 0.015, 0.015),  # 3 cm × 3 cm cross-section
        pa_rgba,
        mass=pa["mass_kg"],
    )

    # ---- Flywheel pair (mounted at end of pitch arm) ----
    fw_rgba = hex_to_rgba(fw["color"])
    fw_sep = fw["separation_m"]
    fw_hw = fw["hub_width_m"]
    for side, sign_y in [("left", +1.0), ("right", -1.0)]:
        fw_name = f"flywheel_{side}"
        fy = sign_y * fw_sep / 2.0
        # Mounted at the distal end of the arm (X = -arm_length)
        fw_body = SubElement(
            arm_body,
            "body",
            {
                "name": fw_name,
                "pos": fmt3(-pa_al, fy, 0.0),
            },
        )
        SubElement(
            fw_body,
            "joint",
            {
                "name": fw_name,
                "type": "hinge",
                "axis": "0 1 0",   # spin around Y axis (horizontal, perpendicular to ball path)
                "limited": "false",
                "damping": "0.001",
            },
        )
        # Flywheel cylinder along Y axis (same as spin axis — disc in XZ plane).
        fw_hw_half = fw_hw / 2.0
        add_cylinder(
            fw_body,
            f"{fw_name}_geom",
            (0.0, -fw_hw_half, 0.0, 0.0, +fw_hw_half, 0.0),
            fw["radius_m"],
            fw_rgba,
            mass=fw["mass_kg"],
        )

    # ---- Camera placeholder (visual-only, on top of chassis, toward front) ----
    cam_off = cam["offset_xyz_m"]
    cam_half = [s / 2.0 for s in cam["size_xyz_m"]]
    add_box(
        robot_body,
        "camera_placeholder",
        tuple(cam_off),
        tuple(cam_half),
        hex_to_rgba(cam["color"]),
        contype=0,
        conaffinity=0,   # no collision — purely visual marker
    )


def build_robot_actuators(mujoco_elem: Element, robot_spec: dict) -> None:
    """Add <actuator> elements for all robot motors.

    Args:
        mujoco_elem: The top-level <mujoco> Element (actuator is a direct child).
        robot_spec:  Parsed robot_diff.yaml dict.
    """
    r = robot_spec
    wh = r["drive"]["wheels"]
    intk = r["intake"]["roller"]
    fw = r["launcher"]["flywheels"]
    pa = r["launcher"]["pitch_arm"]

    act = SubElement(mujoco_elem, "actuator")

    # Drive wheels — velocity-controlled
    for side in ("left", "right"):
        SubElement(
            act,
            "velocity",
            {
                "name": f"wheel_{side}",
                "joint": f"wheel_{side}",
                "kv": fmt(wh["max_torque"]),
                "ctrlrange": f"{fmt(wh['ctrl_range'][0])} {fmt(wh['ctrl_range'][1])}",
            },
        )

    # Intake roller — velocity-controlled
    SubElement(
        act,
        "velocity",
        {
            "name": "intake_roller",
            "joint": "intake_roller",
            "kv": fmt(intk["max_torque"]),
            "ctrlrange": f"{fmt(intk['ctrl_range'][0])} {fmt(intk['ctrl_range'][1])}",
        },
    )

    # Flywheels — velocity-controlled (one per wheel)
    for side in ("left", "right"):
        SubElement(
            act,
            "velocity",
            {
                "name": f"flywheel_{side}",
                "joint": f"flywheel_{side}",
                "kv": fmt(fw["max_torque"]),
                "ctrlrange": f"{fmt(fw['ctrl_range'][0])} {fmt(fw['ctrl_range'][1])}",
            },
        )

    # Pitch arm — position-controlled
    pa_kp = pa["kp"]
    pa_min = -math.radians(pa["pitch_max_deg"])
    pa_max = -math.radians(pa["pitch_min_deg"])
    SubElement(
        act,
        "position",
        {
            "name": "pitch_arm",
            "joint": "pitch_arm",
            "kp": fmt(pa_kp),
            "ctrlrange": f"{fmt(pa_min)} {fmt(pa_max)}",
        },
    )


# ---------------------------------------------------------------------------
# Full standalone MJCF (for testing)
# ---------------------------------------------------------------------------
def build_standalone_mjcf(spec: dict) -> str:
    """Build a minimal MJCF with just the robot on a floor (for testing)."""
    mujoco = Element("mujoco", {"model": "robot_diff"})

    SubElement(mujoco, "compiler", {"angle": "degree", "coordinate": "local"})
    SubElement(
        mujoco,
        "option",
        {"timestep": "0.005", "gravity": "0 0 -9.81", "integrator": "implicitfast"},
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

    world = SubElement(mujoco, "worldbody")

    # Lighting
    SubElement(world, "light", {
        "directional": "true", "pos": "0 0 6",
        "dir": "0 0 -1", "diffuse": "0.8 0.8 0.8",
    })

    # Floor
    SubElement(
        world,
        "geom",
        {
            "name": "floor",
            "type": "plane",
            "pos": "0 0 0",
            "size": "3 3 0.1",
            "rgba": "0.9 0.9 0.85 1.0",
            "friction": "0.9 0.005 0.0001",
        },
    )

    # Robot
    build_robot_body(world, spec, pose_xyz=(0.0, 0.0, 0.0), yaw_deg=0.0)
    build_robot_actuators(mujoco_elem=mujoco, robot_spec=spec)

    raw = tostring(mujoco, encoding="unicode")
    pretty = minidom.parseString(raw).toprettyxml(indent="  ")
    return pretty


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------
def main() -> int:
    if not SPEC_PATH.exists():
        print(f"ERROR: spec not found: {SPEC_PATH}", file=sys.stderr)
        return 2
    spec = yaml.safe_load(SPEC_PATH.read_text())

    xml = build_standalone_mjcf(spec)
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(xml)
    print(f"wrote {OUT_PATH}  ({len(xml):,} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
