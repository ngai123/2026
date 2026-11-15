"""
run_square_test.py — Drive the robot in a square: forward, turn 90°, repeat ×4.

Exercises both the vx (forward) and omega (yaw rate) channels of the HAL.
Demonstrates that the brain code is variant-agnostic — same code would drive
any robot whose HAL supports set_chassis_velocity.

Usage:
    .venv/bin/mjpython scripts/run_square_test.py --side 1.0 --speed 0.25
    .venv/bin/python   scripts/run_square_test.py --headless --side 1.0
"""
from __future__ import annotations

import argparse
import math
import subprocess
import sys
import time
from enum import IntEnum
from pathlib import Path

import mujoco
import mujoco.viewer

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from brain.hal_sim import load_sim  # noqa: E402

WORLD = ROOT / "mjcf" / "world.xml"
ROBOT_SPEC = ROOT / "spec" / "robot_diff.yaml"


def bring_to_front_macos() -> None:
    if sys.platform != "darwin":
        return
    try:
        subprocess.run(
            ["osascript", "-e",
             'tell application "System Events" to '
             'set frontmost of every process whose unix id is %d to true'
             % subprocess.os.getpid()],
            check=False, capture_output=True, timeout=2.0,
        )
    except Exception:
        pass


class State(IntEnum):
    """LABVIEW-PORTABLE — maps to a LabVIEW typedef enum + case structure."""
    DRIVE = 0
    TURN  = 1
    DONE  = 99


def wrap_angle(a: float) -> float:
    while a > math.pi:
        a -= 2 * math.pi
    while a < -math.pi:
        a += 2 * math.pi
    return a


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--side", type=float, default=1.0, help="square side length (m)")
    ap.add_argument("--speed", type=float, default=0.25, help="forward speed (m/s)")
    ap.add_argument("--turn-rate", type=float, default=0.6,
                    help="yaw rate during 90° turns (rad/s)")
    ap.add_argument("--time-scale", type=float, default=0.5,
                    help="sim/wall time ratio (0.5 = slow-motion)")
    ap.add_argument("--headless", action="store_true")
    ap.add_argument("--control-rate", type=float, default=100.0)
    args = ap.parse_args()

    if not WORLD.exists():
        print(f"ERROR: {WORLD} not found. Run scripts/build_world.py --with-robot",
              file=sys.stderr)
        return 2

    control_dt = 1.0 / args.control_rate
    model, data, hal = load_sim(WORLD, ROBOT_SPEC, control_dt=control_dt)
    print(f"loaded: {model.nbody} bodies  control_dt={control_dt*1000:.1f}ms")

    # ---- Mission plan: 4 legs (drive + turn left). ---------------------------
    # Each leg = drive args.side metres, then turn +90° CCW.
    legs_remaining = 4
    state = State.DRIVE

    # Per-segment captures (updated on entering each state).
    x_start = y_start = yaw_start = 0.0
    yaw_target = 0.0

    def enter_drive() -> None:
        nonlocal x_start, y_start, yaw_start
        x_start, y_start, yaw_start = hal.read_pose_odom()
        print(f"  leg {5-legs_remaining}/4  DRIVE forward {args.side:.2f}m")

    def enter_turn() -> None:
        nonlocal yaw_start, yaw_target
        _, _, yaw_start = hal.read_pose_odom()
        yaw_target = yaw_start + math.pi / 2.0  # +90° CCW
        print(f"  leg {5-legs_remaining}/4  TURN  +90°")

    # Initialise state.
    enter_drive()

    def control_step() -> None:
        nonlocal state, legs_remaining
        x, y, yaw = hal.read_pose_odom()

        if state == State.DRIVE:
            travelled = ((x - x_start) * math.cos(yaw_start) +
                         (y - y_start) * math.sin(yaw_start))
            remaining = args.side - travelled
            if remaining > 0.02:
                v_cmd = args.speed * min(1.0, remaining / 0.25)
                hal.set_chassis_velocity(v_cmd, 0.0, 0.0)
            else:
                hal.set_chassis_velocity(0.0, 0.0, 0.0)
                state = State.TURN
                enter_turn()

        elif state == State.TURN:
            yaw_err = wrap_angle(yaw_target - yaw)
            if abs(yaw_err) > math.radians(2.0):       # 2° tolerance
                omega = args.turn_rate * max(0.2, min(1.0, abs(yaw_err) / math.radians(20.0)))
                hal.set_chassis_velocity(0.0, 0.0, math.copysign(omega, yaw_err))
            else:
                hal.set_chassis_velocity(0.0, 0.0, 0.0)
                legs_remaining -= 1
                if legs_remaining > 0:
                    state = State.DRIVE
                    enter_drive()
                else:
                    state = State.DONE
                    print("\n>>> Square complete <<<\n")

        elif state == State.DONE:
            hal.set_chassis_velocity(0.0, 0.0, 0.0)

    log_every = max(1, int(0.5 / control_dt))   # log every 0.5 sim-seconds
    tick_count = 0
    done_wall_t: float | None = None
    auto_exit_after_done = 3.0

    if args.headless:
        while True:
            control_step()
            hal.tick()
            tick_count += 1
            if tick_count % log_every == 0:
                x, y, yaw = hal.read_pose_odom()
                print(f"  t={hal.now():5.2f}s  pose=({x:+.3f},{y:+.3f},"
                      f"{math.degrees(yaw):+6.1f}°)  [{state.name}]")
            if state == State.DONE:
                if done_wall_t is None:
                    done_wall_t = time.time()
                if time.time() - done_wall_t > 0.5:
                    break
        print("done.")
        return 0

    with mujoco.viewer.launch_passive(model, data) as viewer:
        viewer.cam.distance = 2.5
        viewer.cam.azimuth = 110.0
        viewer.cam.elevation = -28.0
        viewer.cam.lookat[:] = (x_start, y_start, 0.15)
        for flag in (
            mujoco.mjtVisFlag.mjVIS_PERTOBJ, mujoco.mjtVisFlag.mjVIS_CONSTRAINT,
            mujoco.mjtVisFlag.mjVIS_CONTACTPOINT, mujoco.mjtVisFlag.mjVIS_CONTACTFORCE,
            mujoco.mjtVisFlag.mjVIS_TRANSPARENT, mujoco.mjtVisFlag.mjVIS_INERTIA,
            mujoco.mjtVisFlag.mjVIS_JOINT, mujoco.mjtVisFlag.mjVIS_ACTUATOR,
        ):
            viewer.opt.flags[flag] = 0

        print(f"\n[viewer] time scale = {args.time_scale:.2f}× real-time")
        print(f"[viewer] speed       = {args.speed:.2f} m/s")
        print(f"[viewer] turn rate   = {args.turn_rate:.2f} rad/s")
        print(f"[viewer] square side = {args.side:.2f} m\n")

        bring_to_front_macos()
        wall_t0 = time.time()

        while viewer.is_running():
            control_step()
            hal.tick()

            x, y, _ = hal.read_pose_odom()
            viewer.cam.lookat[0] = x
            viewer.cam.lookat[1] = y
            viewer.sync()
            tick_count += 1

            if tick_count % log_every == 0:
                x, y, yaw = hal.read_pose_odom()
                print(f"  t={hal.now():5.2f}s  pose=({x:+.3f},{y:+.3f},"
                      f"{math.degrees(yaw):+6.1f}°)  [{state.name}]")

            if state == State.DONE and done_wall_t is None:
                done_wall_t = time.time()
            if done_wall_t is not None and time.time() - done_wall_t > auto_exit_after_done:
                break

            wall_target = hal.now() / args.time_scale
            wall_actual = time.time() - wall_t0
            if wall_target > wall_actual:
                time.sleep(wall_target - wall_actual)

    print("done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
