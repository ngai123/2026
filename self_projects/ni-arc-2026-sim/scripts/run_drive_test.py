"""
run_drive_test.py — End-to-end demo: brain → HAL → SimHAL → MuJoCo → robot moves.

Opens the MuJoCo passive viewer and drives the robot forward 1 m, then stops.
Proves the HAL plumbing works.

Usage:
    .venv/bin/python scripts/run_drive_test.py [--distance 1.0] [--speed 0.5]
    .venv/bin/python scripts/run_drive_test.py --headless  (no viewer; logs to stdout)
"""
from __future__ import annotations

import argparse
import math
import subprocess
import sys
import time
from pathlib import Path

import mujoco
import mujoco.viewer


def bring_to_front_macos() -> None:
    """Bring the mjpython window to the foreground on macOS so the user
    doesn't have to hunt for it. Silent no-op on other platforms."""
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
        pass  # never let a UI cosmetic kill the run

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from brain.hal_sim import load_sim  # noqa: E402

WORLD = ROOT / "mjcf" / "world.xml"
ROBOT_SPEC = ROOT / "spec" / "robot_diff.yaml"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--distance", type=float, default=1.0, help="metres to drive forward")
    ap.add_argument("--speed", type=float, default=0.25, help="forward speed (m/s)")
    ap.add_argument("--time-scale", type=float, default=0.5,
                    help="sim/wall time ratio; 0.5 = slow-motion (half real-time), 1.0 = real-time")
    ap.add_argument("--headless", action="store_true", help="no viewer; log only")
    ap.add_argument("--control-rate", type=float, default=100.0, help="control loop Hz")
    ap.add_argument("--no-camera-follow", action="store_true",
                    help="disable camera tracking the robot")
    args = ap.parse_args()

    if not WORLD.exists():
        print(f"ERROR: {WORLD} not found. Run scripts/build_world.py --with-robot", file=sys.stderr)
        return 2

    control_dt = 1.0 / args.control_rate
    model, data, hal = load_sim(WORLD, ROBOT_SPEC, control_dt=control_dt)
    print(f"loaded: {model.nbody} bodies, control_dt={control_dt*1000:.1f}ms, "
          f"physics_dt={model.opt.timestep*1000:.1f}ms, "
          f"steps/tick={hal.steps_per_tick}")

    # Capture starting pose.
    x0, y0, yaw0 = hal.read_pose_odom()
    print(f"start pose: x={x0:+.3f} y={y0:+.3f} yaw={math.degrees(yaw0):+.1f}°")

    def control_step() -> bool:
        """One control tick. Return True if mission complete."""
        x, y, yaw = hal.read_pose_odom()
        # Distance travelled in the robot's start-frame forward direction.
        dx, dy = x - x0, y - y0
        travelled = dx * math.cos(yaw0) + dy * math.sin(yaw0)
        remaining = args.distance - travelled

        if remaining > 0.02:                      # 2 cm tolerance
            # Simple proportional ramp-down: slow down in the last 30 cm.
            v_cmd = args.speed * min(1.0, remaining / 0.30)
            hal.set_chassis_velocity(v_cmd, 0.0, 0.0)
            return False
        else:
            hal.set_chassis_velocity(0.0, 0.0, 0.0)
            return True

    # Run loop.
    log_every = max(1, int(1.0 / control_dt))    # log once per simulated second
    tick_count = 0
    mission_done_at: float | None = None
    settle_after_done = 1.0  # keep stepping for 1 s after stop to show settling
    auto_exit_after_done = 2.0   # close viewer this many wall-seconds after stop

    if args.headless:
        while True:
            done = control_step()
            hal.tick()
            tick_count += 1
            if tick_count % log_every == 0:
                x, y, yaw = hal.read_pose_odom()
                vx, vy, w = hal.read_chassis_velocity()
                print(f"  t={hal.now():5.2f}s  pose=({x:+.3f},{y:+.3f},"
                      f"{math.degrees(yaw):+5.1f}°)  v=({vx:+.3f},{w:+.3f})")
            if done and mission_done_at is None:
                mission_done_at = hal.now()
                print(f"REACHED target at t={mission_done_at:.2f}s "
                      f"(travelled {args.distance:.2f} m)")
            if mission_done_at is not None and hal.now() - mission_done_at > settle_after_done:
                break
    else:
        with mujoco.viewer.launch_passive(model, data) as viewer:
            # ---- Friendlier defaults ----------------------------------------
            # Close in on the robot, slight overhead angle, side-on view.
            viewer.cam.distance = 2.8
            viewer.cam.azimuth = 110.0
            viewer.cam.elevation = -18.0
            viewer.cam.lookat[:] = (x0, y0, 0.15)

            # Turn off all the overlay flags that clutter the screen.
            # mjVIS_* enums: only keep the basics (geoms, lighting).
            for flag in (
                mujoco.mjtVisFlag.mjVIS_PERTOBJ,
                mujoco.mjtVisFlag.mjVIS_CONSTRAINT,
                mujoco.mjtVisFlag.mjVIS_CONTACTPOINT,
                mujoco.mjtVisFlag.mjVIS_CONTACTFORCE,
                mujoco.mjtVisFlag.mjVIS_TRANSPARENT,
                mujoco.mjtVisFlag.mjVIS_INERTIA,
                mujoco.mjtVisFlag.mjVIS_JOINT,
                mujoco.mjtVisFlag.mjVIS_ACTUATOR,
            ):
                viewer.opt.flags[flag] = 0

            print(f"\n[viewer] time scale = {args.time_scale:.2f}× real-time")
            print(f"[viewer] speed       = {args.speed:.2f} m/s")
            print(f"[viewer] target dist = {args.distance:.2f} m")
            print(f"[viewer] camera follows robot. Drag mouse to orbit; Esc to close.\n")

            bring_to_front_macos()
            wall_t0 = time.time()
            done_wall_t: float | None = None
            while viewer.is_running():
                done = control_step()
                hal.tick()

                if not args.no_camera_follow:
                    x, y, _ = hal.read_pose_odom()
                    viewer.cam.lookat[0] = x
                    viewer.cam.lookat[1] = y

                viewer.sync()
                tick_count += 1

                if tick_count % log_every == 0:
                    x, y, _ = hal.read_pose_odom()
                    state = "stopped" if done else "driving"
                    print(f"  t={hal.now():5.2f}s  x={x:+.3f}  "
                          f"travelled={x-x0:+.3f}m  [{state}]")

                if done and mission_done_at is None:
                    mission_done_at = hal.now()
                    done_wall_t = time.time()
                    print(f"\n>>> REACHED target at sim t={mission_done_at:.2f}s "
                          f"(wall {time.time()-wall_t0:.1f}s) <<<\n")

                # Auto-close a bit after stop so user gets a clean log.
                if done_wall_t is not None and time.time() - done_wall_t > auto_exit_after_done:
                    break

                # Pacing: sleep so sim time tracks wall time at TIME_SCALE rate.
                wall_target = hal.now() / args.time_scale
                wall_actual = time.time() - wall_t0
                if wall_target > wall_actual:
                    time.sleep(wall_target - wall_actual)

    print("done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
