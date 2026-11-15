"""
hal_sim.py — MuJoCo-backed implementation of brain.hal.HAL.

Adapter for the differential-drive + roller-intake + dual-flywheel variant
defined by spec/robot_diff.yaml. When new variants are added, each gets its
own adapter class implementing the same HAL contract.

NOT LabVIEW-portable — this file is sim-only. The brain code that talks to
this class IS LabVIEW-portable; that's the whole point of the seam.
"""
from __future__ import annotations

import math
import time
from pathlib import Path

import mujoco
import numpy as np
import yaml

from .hal import HAL


# Convenience: get an actuator ctrl-slot index by actuator name.
def _act_id(model: mujoco.MjModel, name: str) -> int:
    aid = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_ACTUATOR, name)
    if aid < 0:
        raise ValueError(f"actuator '{name}' not found in model")
    return aid


def _joint_id(model: mujoco.MjModel, name: str) -> int:
    jid = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_JOINT, name)
    if jid < 0:
        raise ValueError(f"joint '{name}' not found in model")
    return jid


def _body_id(model: mujoco.MjModel, name: str) -> int:
    bid = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_BODY, name)
    if bid < 0:
        raise ValueError(f"body '{name}' not found in model")
    return bid


class SimHAL(HAL):
    """SimHAL for the diff-drive robot in spec/robot_diff.yaml.

    Args:
        model:       a loaded mujoco.MjModel containing the robot.
        data:        the matching mujoco.MjData.
        robot_spec:  parsed spec/robot_diff.yaml dict (for wheel geometry).
        control_dt:  control-loop interval in seconds (one tick = N physics
                     steps where N = control_dt / model.opt.timestep).
        sim_steps_per_tick: explicit override; if None, derived from control_dt.
    """

    def __init__(
        self,
        model: mujoco.MjModel,
        data: mujoco.MjData,
        robot_spec: dict,
        control_dt: float = 0.01,                 # 100 Hz default
        sim_steps_per_tick: int | None = None,
    ):
        self.model = model
        self.data = data
        self.spec = robot_spec
        self.control_dt = float(control_dt)
        if sim_steps_per_tick is None:
            self.steps_per_tick = max(1, int(round(control_dt / model.opt.timestep)))
        else:
            self.steps_per_tick = int(sim_steps_per_tick)
        self._t_start = self.data.time

        # ---- Cache ids for the diff-drive variant -----------------------------
        # Actuators
        self._aid_wheel_left  = _act_id(model, "wheel_left")
        self._aid_wheel_right = _act_id(model, "wheel_right")
        self._aid_intake      = _act_id(model, "intake_roller")
        self._aid_fw_left     = _act_id(model, "flywheel_left")
        self._aid_fw_right    = _act_id(model, "flywheel_right")
        self._aid_pitch       = _act_id(model, "pitch_arm")

        # Bodies (for pose readout)
        self._bid_robot = _body_id(model, "robot_red")

        # Robot freejoint (for v1 "cheat" odometry)
        self._fj_jid = _joint_id(model, "robot_free")
        # freejoint qpos layout: x, y, z, qw, qx, qy, qz (7 values)
        self._fj_qpos_adr = model.jnt_qposadr[self._fj_jid]
        self._fj_qvel_adr = model.jnt_dofadr[self._fj_jid]

        # Wheel hinge joints (for encoder readout)
        self._jid_wheel_left  = _joint_id(model, "wheel_left")
        self._jid_wheel_right = _joint_id(model, "wheel_right")

        # ---- Kinematic constants from spec -----------------------------------
        wh = robot_spec["drive"]["wheels"]
        self.wheel_radius = float(wh["radius_m"])
        self.wheelbase = float(wh["wheelbase_m"])
        self.wheel_ctrl_max = float(wh["ctrl_range"][1])

        # ---- Launcher / intake state caches ----------------------------------
        pa = robot_spec["launcher"]["pitch_arm"]
        # The pitch actuator's joint coord maps "−pitch_max_deg ... −pitch_min_deg"
        # (see build_robot.py § pitch arm). We keep the public API in degrees.
        self._pitch_min_deg = float(pa["pitch_min_deg"])
        self._pitch_max_deg = float(pa["pitch_max_deg"])

        self._intake_engaged = False
        self._launcher_ready_threshold_rpm_err = 50.0   # rad/s tolerance
        self._launcher_target_rpm = 0.0

    # ---- Lifecycle ------------------------------------------------------------
    def tick(self) -> float:
        for _ in range(self.steps_per_tick):
            mujoco.mj_step(self.model, self.data)
        return self.control_dt

    def now(self) -> float:
        return float(self.data.time - self._t_start)

    # ---- Drive ----------------------------------------------------------------
    def set_chassis_velocity(self, vx_mps: float, vy_mps: float, omega_radps: float) -> None:
        # Diff drive cannot strafe — silently ignore vy.
        half_wb = self.wheelbase / 2.0
        omega_l = (vx_mps - omega_radps * half_wb) / self.wheel_radius
        omega_r = (vx_mps + omega_radps * half_wb) / self.wheel_radius
        # Clamp to actuator range so the motor doesn't saturate silently.
        cap = self.wheel_ctrl_max
        self.data.ctrl[self._aid_wheel_left]  = max(-cap, min(cap, omega_l))
        self.data.ctrl[self._aid_wheel_right] = max(-cap, min(cap, omega_r))

    def read_chassis_velocity(self) -> tuple[float, float, float]:
        # Sim cheat: derive from freejoint linear + angular velocity, rotated
        # back into the chassis frame.
        # qvel for a freejoint is [vx_w, vy_w, vz_w, wx_w, wy_w, wz_w] (world frame).
        v_world = self.data.qvel[self._fj_qvel_adr : self._fj_qvel_adr + 3]
        w_world = self.data.qvel[self._fj_qvel_adr + 3 : self._fj_qvel_adr + 6]
        _, _, yaw = self.read_pose_odom()
        c, s = math.cos(-yaw), math.sin(-yaw)
        vx = c * v_world[0] - s * v_world[1]
        vy = s * v_world[0] + c * v_world[1]
        omega = w_world[2]
        return float(vx), float(vy), float(omega)

    def read_pose_odom(self) -> tuple[float, float, float]:
        # V1 sim cheat: use ground-truth qpos.
        # qpos for freejoint = [x, y, z, qw, qx, qy, qz].
        qpos = self.data.qpos[self._fj_qpos_adr : self._fj_qpos_adr + 7]
        x, y = float(qpos[0]), float(qpos[1])
        # Yaw from quaternion (Z-axis Euler component).
        qw, qx, qy, qz = qpos[3], qpos[4], qpos[5], qpos[6]
        siny_cosp = 2.0 * (qw * qz + qx * qy)
        cosy_cosp = 1.0 - 2.0 * (qy * qy + qz * qz)
        yaw = math.atan2(siny_cosp, cosy_cosp)
        return x, y, float(yaw)

    # ---- Intake ---------------------------------------------------------------
    def intake_engage(self) -> None:
        self._intake_engaged = True
        # Spin the roller at its max rev/s — pulls balls inward.
        ctrl_max = float(self.spec["intake"]["roller"]["ctrl_range"][1])
        self.data.ctrl[self._aid_intake] = ctrl_max

    def intake_disengage(self) -> None:
        self._intake_engaged = False
        self.data.ctrl[self._aid_intake] = 0.0

    def intake_has_ball(self) -> bool:
        # V1 sim cheat: count standard or golden balls whose centre is within
        # a small AABB in front of the intake roller.
        # TODO(v1.1): replace with a proper beam-break sensor or contact query.
        robot_x, robot_y, yaw = self.read_pose_odom()
        # Intake position: 0.3 m ahead of chassis centre, height ~0.05 m.
        ix = robot_x + math.cos(yaw) * 0.30
        iy = robot_y + math.sin(yaw) * 0.30
        for bid in range(self.model.nbody):
            name = mujoco.mj_id2name(self.model, mujoco.mjtObj.mjOBJ_BODY, bid)
            if not name or not name.startswith("ball_"):
                continue
            bx, by, bz = self.data.xpos[bid]
            if abs(bx - ix) < 0.15 and abs(by - iy) < 0.15 and bz < 0.20:
                return True
        return False

    # ---- Launcher -------------------------------------------------------------
    def launcher_aim(self, pitch_deg: float, yaw_deg: float) -> None:
        # Diff-drive variant has fixed yaw (the whole chassis turns to aim).
        # yaw_deg is silently ignored.
        # Pitch joint coord = -pitch_deg (see build_robot.py § pitch arm).
        clamped_deg = max(self._pitch_min_deg, min(self._pitch_max_deg, pitch_deg))
        self.data.ctrl[self._aid_pitch] = -math.radians(clamped_deg)

    def launcher_charge(self, target_distance_m: float, target_height_m: float) -> None:
        # Placeholder linear-ish RPM model: scale with horizontal distance.
        # Real model comes from oracle/sweep_rpm_angle.py later.
        # For v1, simple heuristic: 100 rad/s per metre of horizontal range.
        target_rpm = max(0.0, min(600.0, 100.0 * target_distance_m))
        self._launcher_target_rpm = target_rpm
        self.data.ctrl[self._aid_fw_left]  = target_rpm
        self.data.ctrl[self._aid_fw_right] = target_rpm

    def launcher_ready(self) -> bool:
        # Compare actual flywheel rates to target.
        ql = self.data.qvel[self.model.jnt_dofadr[_joint_id(self.model, "flywheel_left")]]
        qr = self.data.qvel[self.model.jnt_dofadr[_joint_id(self.model, "flywheel_right")]]
        err = max(abs(self._launcher_target_rpm - ql),
                  abs(self._launcher_target_rpm - qr))
        return err < self._launcher_ready_threshold_rpm_err

    def launcher_fire(self) -> None:
        # No-op until we wire the "ball ejection event" model in v1.1.
        # Will: find ball in intake, remove it, spawn projectile with velocity
        # derived from launcher state.
        pass

    # ---- Sensors --------------------------------------------------------------
    def read_imu(self) -> tuple[float, float]:
        _, _, yaw = self.read_pose_odom()
        wz = float(self.data.qvel[self._fj_qvel_adr + 5])
        return yaw, wz

    def read_intake_camera_balls(self) -> list[tuple[float, float, bool]]:
        # V1 sim cheat: enumerate all ball bodies, return those in a 120° FOV
        # ahead of the robot, within 3 m.
        rx, ry, yaw = self.read_pose_odom()
        out: list[tuple[float, float, bool]] = []
        for bid in range(self.model.nbody):
            name = mujoco.mj_id2name(self.model, mujoco.mjtObj.mjOBJ_BODY, bid)
            if not name or not name.startswith("ball_"):
                continue
            bx, by, _ = self.data.xpos[bid]
            dx, dy = bx - rx, by - ry
            dist = math.hypot(dx, dy)
            if dist > 3.0:
                continue
            bearing_world = math.atan2(dy, dx)
            bearing = bearing_world - yaw
            # Wrap to (-pi, pi).
            while bearing > math.pi:
                bearing -= 2 * math.pi
            while bearing < -math.pi:
                bearing += 2 * math.pi
            if abs(bearing) > math.radians(60):
                continue
            is_golden = name.startswith("ball_gold")
            out.append((float(bearing), float(dist), is_golden))
        return out


def load_sim(world_xml: Path, robot_spec_yaml: Path, control_dt: float = 0.01) -> tuple[mujoco.MjModel, mujoco.MjData, SimHAL]:
    """Convenience: load the world + robot spec and return a ready-to-use SimHAL."""
    model = mujoco.MjModel.from_xml_path(str(world_xml))
    data = mujoco.MjData(model)
    robot_spec = yaml.safe_load(robot_spec_yaml.read_text())
    return model, data, SimHAL(model, data, robot_spec, control_dt=control_dt)
