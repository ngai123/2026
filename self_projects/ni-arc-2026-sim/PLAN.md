# NI ARC 2026 Autonomous Hoops — Simulation Plan v0.1

**Status:** Draft for first review. No code yet. Author: Claude (Opus 4.7). Date: 2026-05-21.

---

## 1. What we're building

A 3D physics simulation of the NI ARC 2026 "Autonomous Hoops" competition field, accurate enough that:

- **Launcher tuning** (flywheel RPM, exit pitch/yaw) measured in sim transfers to the real robot within a small calibration delta.
- **Drive dynamics** (turn radius, acceleration, wheel slip on banner flooring) match reality close enough that path-planning logic written in sim works on hardware.
- **Strategy iteration** for AUTO and MANUAL phases can happen entirely in software before any hardware is built.

It is **not** (yet):
- A polished demo for judges.
- A software-in-the-loop harness for the real LabVIEW VI. (Deferred to v2.)
- A reinforcement-learning training environment.
- A multi-robot opponent-AI battle sim. (Stub opponent only.)

## 2. Engine choice (decided)

**MuJoCo** (Apache-2.0, `pip install mujoco`).

Rationale, ranked:
1. Best-in-class contact and friction physics for the launcher + foam ball + rim scenario.
2. Single-file MJCF scenes, Python in-process control loop — fast iteration, LLM-friendly authoring.
3. No CAD tooling required — the entire rulebook geometry is boxes, cylinders, spheres.
4. Cross-platform, lightweight install.

Webots was the runner-up. Reason it lost: weaker ODE-based contact model for high-spin thin contacts, and its main advantage (documented LabVIEW TCP/IP path) is only relevant for the deferred v2 SIL goal.

If we later need true LabVIEW SIL, we add a TCP bridge to MuJoCo (~200 lines Python) rather than switch engines.

## 3. Architecture

```
spec/                       ← single source of truth (YAML)
  arena.yaml                  rulebook dimensions, colors, ball counts
  robot.yaml                  parametric chassis + drivetrain + launcher + intake
  ball_physics.yaml           CoR, friction, density (calibrated from real samples)
  surface_physics.yaml        banner flooring friction parameters

scripts/
  build_mjcf.py               spec/*.yaml  →  mjcf/world.xml + robot.xml
  run_interactive.py          load world, keyboard-drive, log telemetry
  run_match.py                full match runner with referee + scoring
  calibrate_ball.py           drop test fitter: video → CoR/friction
  calibrate_drive.py          turn-radius fitter

mjcf/                       ← GENERATED — do not hand-edit
  world.xml
  robot.xml
  goal_red.xml / goal_blue.xml
  meshes/                     hollow goal-face boolean mesh (only "asset" needed)

oracle/                     ← physics oracle for launcher
  launcher_only.xml           goal + ball + idealized launcher
  sweep_rpm_angle.py          → aim_lookup.csv  (RPM, pitch) → (hit_zone, landing_xy)
  validate_aimy.py            sanity check against AIMY paper trajectories

experiments/                ← reusable scenarios, one per milestone
  m1_environment.py           load + render, latency probe
  m2_motor_response.py        velocity tracking
  m3_navigation.py            two 90° turns + stop at target
  m4_pickup_transport.py      intake reliability sweep
  m5_launch_accuracy.py       aim solver vs measured outcomes
  m6_full_auto.py             60 s autonomous run with scoring

brain/                      ← Python control logic; mirrors what we'd port to LabVIEW
  hal.py                      hardware abstraction (sim adapter today, myRIO adapter later)
  state_machine.py            AUTO and MANUAL phase logic
  perception.py               ball detection from camera feed
  aim_solver.py               consumes oracle/aim_lookup.csv

referee/
  rules.py                    scoring table from rulebook, penalty logic
  phase_clock.py              60 s AUTO + 180 s MANUAL + Golden release at t=210 s

docs/
  rulebook_extract.md         the canonical dimensions table (cross-check at every change)
  physics_calibration.md      how to measure real CoR / friction with a phone camera
  decisions.md                ADRs as we go

assets/reference/           ← rulebook PDF, AIMY paper, useful CAD diagrams
```

**Hard rule:** any number that comes from the rulebook lives only in `spec/arena.yaml`. Code reads it; the MJCF generator emits it; tests assert it. One source of truth.

## 4. Spec artifact (preview, not yet written)

`spec/arena.yaml` will encode every entry from the dimensional table the user provided. Sketch:

```yaml
field:
  size_m: [6.0, 6.0]
  flooring: banner_smooth
  perimeter_pipe_od_mm: 21
  line_width_mm: 25
zones:
  starting_red:  {color: "#FF9999", x: [-3.0, -2.93], y: [-1.0, 1.0]}
  starting_blue: {color: "#99CCFF", x: [ 2.93, 3.0], y: [-1.0, 1.0]}
  shared_ball:   {color: "#E2C884", x: [-1.0, 1.0], y: [-1.0, 1.0]}
  # near / mid / far zones per team...
balls:
  standard: {count: 36, diameter_m: 0.18, mass_kg: TBD_measure}
  golden:   {count: 10, diameter_m: 0.21, mass_kg: TBD_measure}
goal_structure:
  size_m: [2.0, 0.6, 1.5]
  material: plywood_15mm
  openings_diameter_m: 0.40
  low_row_bottom_m:  0.50
  high_row_bottom_m: 1.00
  opening_xs: [-0.6, 0.0, 0.6]
```

`spec/robot.yaml` will be parametric so you can swap geometry without re-authoring:

```yaml
chassis:     {l_m: 0.5, w_m: 0.45, h_m: 0.2, mass_kg: 8.0}
drivetrain:  {type: differential, wheel_radius_m: 0.075, wheel_base_m: 0.35}
intake:      {type: roller, width_m: 0.4, surface_friction: 1.4}
launcher:    {type: dual_flywheel, wheel_radius_m: 0.06, separation_m: 0.18,
              pitch_range_deg: [10, 70], yaw_range_deg: [-45, 45]}
sensors:     {encoders: 2, imu: true, fwd_camera: {res: [640,480]}, intake_beam: true}
```

**No GPS.** The real robot doesn't have one.

## 5. Phased plan with acceptance gates

| Phase | What's built | Time est. | Acceptance gate (you sign off) |
|---|---|---|---|
| **P0** | Project skeleton, deps locked, MuJoCo viewer opens an empty plane | 0.5 day | `python scripts/run_interactive.py` shows an empty floor |
| **P1** | `arena.yaml` + `build_mjcf.py` → field + perimeter + zones + 36 + 2×2 balls, goals with hollow openings | 2 days | Visual 1:1 vs rulebook diagram; balls settle inside the shared zone |
| **P2** | Robot template + keyboard drive | 2 days | You can drive it across the field in <10 s, no caster hopping |
| **P3** | Ball physics calibration | 1 day | Sim ball drop CoR matches measured real-ball drop (±10%) |
| **P4** | Surface friction calibration | 1 day | Sim turn radius matches measured chassis push-test (±15%) |
| **P5** | Launcher oracle | 2 days | `aim_lookup.csv` agrees with hand calculation (drag-aware) within 5% and with AIMY-style trajectories within 10% |
| **P6** | Intake roller pickup sweep | 2 days | Geometry sweep produces a "pickup zone" plot; reliable pickup at typical drive speed |
| **P7** | Referee + scoring | 1 day | Replay of a hand-scored match transcript produces the same total |
| **P8** | Stub opponent + full match runner | 1 day | A 240 s match runs end-to-end without crashes |
| **P9** | Milestone verification scenes (M1-M6 from rulebook) | rolling | Each scene's documented criterion passes |

Total to P8: **~12 working days**. P9 then runs in parallel with your hardware milestones.

## 6. What I'd defer until you ask

- **LabVIEW TCP bridge / true SIL.** Add when v1 is stable; the brain layer is already abstracted.
- **Domain randomization / RL training loop.** Only if you decide to use learning-based aiming.
- **Web visualization** (Three.js viewer for spectators). Cosmetic.
- **Opponent strategy AI.** Stub opponent (random or scripted) is enough until you've finalized your own strategy.

## 7. Risks and how I'll address them

1. **Sim-to-real ball physics gap.** Mitigation: measure real foam ball CoR with a phone-camera drop test in P3, refuse to trust any oracle output until calibration error is below threshold. Document in `docs/physics_calibration.md`.
2. **Banner-flooring friction unknown.** Mitigation: push-test on a real banner sample with a known mass and a fish scale; fit μ_k in P4.
3. **Goal hollow geometry in MuJoCo.** MuJoCo doesn't do CSG natively. Mitigation: pre-build the goal-face as a single triangulated mesh with the six circular holes punched, ship as the only mesh asset in the repo. Generate it once with a 50-line `scripts/make_goal_mesh.py`.
4. **Launcher dynamics fidelity.** Foam ball compression through flywheel pair is hard to simulate exactly. Mitigation: do the launch as a "ball ejection event" with computed initial velocity and spin from flywheel state — don't try to simulate the squeeze through the rollers in real-time. AIMY paper does this.
5. **Camera-based ball perception is heavy.** Mitigation: v1 uses a simulated ball-detection sensor (sim cheats by querying ball positions and adding noise). Replace with real vision pipeline only if needed.

## 8. Open decisions I'd like answered (but I can default and start)

These don't block P0-P2. If you don't reply, I'll use the defaults marked.

1. **Sensor suite v1**: `[encoders, IMU, forward camera, intake beam]` — *default proposed*.
2. **Robot type for v1**: differential drive — *default*. Holonomic/omni-wheel is doable later.
3. **Launcher type for v1**: dual horizontal flywheel pair (most common in FRC-style basketball bots) — *default*.
4. **Real-ball measurements**: do you have a real foam ball you can drop on the actual banner surface for me to fit physics against? If yes, share short phone videos when ready (P3 needs this). If not, I use AIMY paper defaults and warn you that simulated aim won't transfer without later calibration.
5. **Python version**: 3.11 — *default*.

## 9. What I need from you to move past P0

- ✅ or ✎ this plan (file layout, phased order, acceptance gates).
- Answer (or ignore) the five open decisions in §8.
- Confirm the project home: `/Volumes/SSD/SelfProject/ni-arc-2026-sim/` ← already created.

Once green-lit, I'll do P0 (skeleton + deps + first MuJoCo "hello world") in one shot, you verify it opens, then we proceed to P1.

## 10. How I'll use mimo to save your tokens

- Repo scraping (extracting parameters from `gcornella/Ball-Launcher-RL`, `nubot-nudt`, AIMY): mimo.
- Bulk generation of MJCF stubs and parameter sweeps: mimo.
- Test scaffolding and small utility scripts: mimo.
- Architectural decisions, debugging non-obvious physics behavior, anything that needs the whole conversation: me.

---

*End of plan v0.1. Review and tell me what to change.*
