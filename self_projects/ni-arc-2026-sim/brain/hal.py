"""
hal.py — Abstract Hardware Abstraction Layer.

LABVIEW-PORTABLE.

This is the seam between control logic ("brain") and the world. Every method
below maps 1:1 to a LabVIEW myRIO Express VI (or a thin sub-VI wrapping one).
The brain code in brain/state_machine.py talks ONLY through this interface;
swap the SimHAL (MuJoCo-backed) for a future MyRIOHAL (real hardware) without
changing a line of brain code.

Design rules (enforced by code review, not the type system):
    - Only simple types cross this boundary: float, int, bool, fixed-size tuple.
    - No exceptions; errors surface as explicit return values or sentinel states.
    - Each method is one LabVIEW "case" in the brain VI; mirror it 1:1.

See docs/CONSTRUCTION.md §2 (HAL spec) and §7 (LabVIEW transferability rules).
"""
from __future__ import annotations

from abc import ABC, abstractmethod


class HAL(ABC):
    # ---- Lifecycle ------------------------------------------------------------
    @abstractmethod
    def tick(self) -> float:
        """Advance one control tick. Return dt (seconds) since previous tick.

        LabVIEW port: the body of the timed loop. dt is the loop interval.
        """

    @abstractmethod
    def now(self) -> float:
        """Seconds since the start of the match (or sim load)."""

    # ---- Drive ----------------------------------------------------------------
    @abstractmethod
    def set_chassis_velocity(self, vx_mps: float, vy_mps: float, omega_radps: float) -> None:
        """Commanded chassis velocity in CHASSIS frame.

        vx: forward (positive = forward of robot)
        vy: lateral (positive = left of robot); ignored by non-holonomic variants
        omega: yaw rate (positive = CCW, right-hand rule about +Z)

        LabVIEW port: a sub-VI that:
            1. Reads variant-specific drive kinematics from a typedef,
            2. Computes per-motor velocity commands,
            3. Writes PWM via the myRIO Motor Express VI.
        """

    @abstractmethod
    def read_chassis_velocity(self) -> tuple[float, float, float]:
        """Measured chassis velocity in CHASSIS frame: (vx, vy, omega)."""

    @abstractmethod
    def read_pose_odom(self) -> tuple[float, float, float]:
        """Best-effort pose estimate in WORLD frame: (x_m, y_m, yaw_rad).

        Source depends on adapter: encoders + IMU dead-reckoning on hardware;
        ground-truth qpos in sim (v1 cheat).
        """

    # ---- Intake ---------------------------------------------------------------
    @abstractmethod
    def intake_engage(self) -> None:
        """Start the intake mechanism (spin roller / open claw)."""

    @abstractmethod
    def intake_disengage(self) -> None:
        """Stop / retract the intake."""

    @abstractmethod
    def intake_has_ball(self) -> bool:
        """True if a ball is in the intake (beam break or sim sensor)."""

    # ---- Launcher -------------------------------------------------------------
    @abstractmethod
    def launcher_aim(self, pitch_deg: float, yaw_deg: float) -> None:
        """Aim the launcher. yaw is robot-relative; ignored by yaw-fixed variants."""

    @abstractmethod
    def launcher_charge(self, target_distance_m: float, target_height_m: float) -> None:
        """Prepare to fire at a target. Variant-specific: spin flywheels to RPM,
        or pressurise a pneumatic piston."""

    @abstractmethod
    def launcher_ready(self) -> bool:
        """True when the launcher state is stable and ready to fire."""

    @abstractmethod
    def launcher_fire(self) -> None:
        """Release one ball. No-op if no ball is loaded."""

    # ---- Sensors --------------------------------------------------------------
    @abstractmethod
    def read_imu(self) -> tuple[float, float]:
        """(yaw_rad, yaw_rate_rad_s) — absolute yaw + body-frame yaw rate."""

    @abstractmethod
    def read_intake_camera_balls(self) -> list[tuple[float, float, bool]]:
        """List of detected balls: (bearing_rad, distance_m, is_golden).

        bearing is robot-relative (0 = directly ahead, positive = left).
        Empty list if none in field of view. Will be implemented by a real
        vision pipeline in perception.py later; v1 SimHAL cheats by reading
        ball positions directly.
        """
