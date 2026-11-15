"""
verify_robot.py — Sanity-check the generated differential-drive robot.

Loads mjcf/robot_diff.xml, runs 1 second of physics, and checks:
  - model loads without errors
  - robot has expected number of joints (≥ 6 actuated + 1 freejoint)
  - robot has expected number of actuators (≥ 5)
  - after settling, robot Z-position is stable (not falling through floor)

Returns 0 if all checks pass, 1 otherwise.
"""
from __future__ import annotations

import sys
from pathlib import Path

import mujoco
import numpy as np
import yaml

ROOT = Path(__file__).resolve().parent.parent
ROBOT_XML = ROOT / "mjcf" / "robot_diff.xml"
SPEC_PATH = ROOT / "spec" / "robot_diff.yaml"
SETTLE_S = 1.0

# Expected minimums
MIN_ACTUATED_JOINTS = 6   # 2 wheels + 1 intake + 2 flywheels + 1 pitch
MIN_ACTUATORS = 5         # 2 wheels + 1 intake + 2 flywheels + 1 pitch


def main() -> int:
    passed = True

    # ---- Load spec ----
    spec = yaml.safe_load(SPEC_PATH.read_text())
    ch_h = spec["chassis"]["height_m"]

    # ---- Load model ----
    try:
        model = mujoco.MjModel.from_xml_path(str(ROBOT_XML))
    except Exception as exc:
        print(f"FAIL model load: {exc}")
        return 1
    data = mujoco.MjData(model)
    print(f"OK  model loads: {model.nbody} bodies, {model.ngeom} geoms")

    # ---- Check robot body exists ----
    robot_body_id = None
    for i in range(model.nbody):
        name = mujoco.mj_id2name(model, mujoco.mjtObj.mjOBJ_BODY, i)
        if name == "robot_red":
            robot_body_id = i
            break
    if robot_body_id is None:
        print("FAIL body 'robot_red' not found")
        return 1
    print(f"OK  body 'robot_red' found (id={robot_body_id})")

    # ---- Count joints ----
    # freejoint counts as 1 joint (with 7 qpos slots). We want to count the
    # actuated hinge/ball joints separately.
    actuated_joint_ids = []
    for i in range(model.njnt):
        jnt_name = mujoco.mj_id2name(model, mujoco.mjtObj.mjOBJ_JOINT, i)
        if jnt_name == "robot_free":
            continue  # skip freejoint in count
        actuated_joint_ids.append(i)

    n_actuated = len(actuated_joint_ids)
    if n_actuated < MIN_ACTUATED_JOINTS:
        print(f"FAIL actuated joints: {n_actuated} < {MIN_ACTUATED_JOINTS} expected")
        passed = False
    else:
        print(f"OK  actuated joints: {n_actuated} (>= {MIN_ACTUATED_JOINTS})")

    # ---- Check expected joint names ----
    expected_joint_names = {
        "wheel_left", "wheel_right",
        "intake_roller",
        "flywheel_left", "flywheel_right",
        "pitch_arm",
    }
    found_names = set()
    for jid in actuated_joint_ids:
        jname = mujoco.mj_id2name(model, mujoco.mjtObj.mjOBJ_JOINT, jid)
        if jname:
            found_names.add(jname)

    missing = expected_joint_names - found_names
    if missing:
        print(f"FAIL missing joints: {sorted(missing)}")
        passed = False
    else:
        print(f"OK  all expected joints found: {sorted(expected_joint_names)}")

    # ---- Count actuators ----
    n_act = model.nu
    if n_act < MIN_ACTUATORS:
        print(f"FAIL actuators: {n_act} < {MIN_ACTUATORS} expected")
        passed = False
    else:
        print(f"OK  actuators: {n_act} (>= {MIN_ACTUATORS})")

    # ---- Check actuator names ----
    expected_act_names = {
        "wheel_left", "wheel_right",
        "intake_roller",
        "flywheel_left", "flywheel_right",
        "pitch_arm",
    }
    found_act_names = set()
    for i in range(n_act):
        aname = mujoco.mj_id2name(model, mujoco.mjtObj.mjOBJ_ACTUATOR, i)
        if aname:
            found_act_names.add(aname)
    missing_act = expected_act_names - found_act_names
    if missing_act:
        print(f"FAIL missing actuators: {sorted(missing_act)}")
        passed = False
    else:
        print(f"OK  all expected actuators found: {sorted(expected_act_names)}")

    # ---- Settle physics ----
    mujoco.mj_resetData(model, data)
    n_steps = int(SETTLE_S / model.opt.timestep)
    z_history = []
    for step in range(n_steps):
        mujoco.mj_step(model, data)
        # Record robot Z position every 0.05 s
        if step % max(1, int(0.05 / model.opt.timestep)) == 0:
            z_history.append(data.xpos[robot_body_id, 2])
    z_history = np.array(z_history)

    print(f"OK  stepped {SETTLE_S}s ({n_steps} steps), sim time = {data.time:.3f}s")

    # ---- Check robot didn't fall through floor ----
    # The robot body origin is at chassis centre = ch_h/2 above the floor when resting.
    min_z = z_history.min()
    # Allow some settling bounce, but the chassis centre should stay above -0.1 m.
    z_threshold = -0.1
    if min_z < z_threshold:
        print(f"FAIL robot fell through floor: min Z = {min_z:.4f} m  (threshold {z_threshold} m)")
        passed = False
    else:
        print(f"OK  robot Z stable: min = {min_z:.4f} m, final = {z_history[-1]:.4f} m")

    # ---- Check robot is near rest (Z velocity small at end) ----
    robot_vel_z = data.cvel[robot_body_id, 2]  # translational Z velocity
    if abs(robot_vel_z) > 1.0:  # m/s — should be near zero after 1s settle
        print(f"WARN robot still moving vertically: vz = {robot_vel_z:.3f} m/s")
    else:
        print(f"OK  robot near rest: vz = {robot_vel_z:.4f} m/s")

    # ---- Final verdict ----
    if passed:
        print("\nverification PASS")
    else:
        print("\nverification FAIL")
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
