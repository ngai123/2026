# Construction Plan (Engineering Design) v0.1

Companion to [../PLAN.md](../PLAN.md). This document is the file-by-file design — function names, data types, control-flow, and LabVIEW-porting rules. Still no code; this is the blueprint we'd code from once you green-light it.

---

## 0. Two standing rules baked into every file

**R1 — Spec is canonical.** Nothing in `mjcf/`, `brain/`, `referee/` may hard-code a dimension, mass, or threshold. All such values live in `spec/*.yaml` and are loaded once at startup. If a number needs to change, you edit YAML, not Python.

**R2 — LabVIEW transferability.** Every line of code that touches "robot I/O" or "control logic" follows these constraints, because that code conceptually represents the future LabVIEW VI:

| Allowed | Not allowed in I/O + control code |
|---|---|
| `float`, `int`, `bool`, fixed-size `numpy.ndarray` | `dict`, custom objects with methods, generators |
| Plain `def` functions | Closures, decorators, `*args/**kwargs` |
| `if / for / while` loops | List comprehensions in hot path |
| Named, explicit state machine | Implicit "current state from boolean flags" |
| `time.monotonic()` for ticks | `asyncio`, `threading` (in control loop) |

Why: LabVIEW is a dataflow language; the patterns above translate to wires and structures. The "not allowed" patterns are Python sugar with no clean LabVIEW analog.

Each file that contains control or HAL code starts with a one-line comment:
```python
# LABVIEW-PORTABLE — see docs/labview_porting_guide.md
```
Each non-obvious function gets a `# LabVIEW port:` note describing the equivalent VI pattern.

---

## 1. Architecture in one picture

```
┌─────────────────────────────────────────────────────────────────────┐
│                            spec/*.yaml                              │
│                  (arena, robot, physics — owned by you)             │
└────────────────────────────────┬────────────────────────────────────┘
                                 │ loaded at startup
              ┌──────────────────┼──────────────────┐
              ▼                  ▼                  ▼
       ┌────────────┐    ┌────────────┐    ┌────────────┐
       │ build_mjcf │    │   referee  │    │    brain   │
       │  (one-off) │    │ (game rules│    │  (control  │
       │            │    │  + scoring)│    │   logic)   │
       └─────┬──────┘    └─────┬──────┘    └─────┬──────┘
             │ emits           │                 │ commands
             ▼                 │                 ▼
       ┌────────────┐          │           ┌────────────┐
       │ mjcf/*.xml │          │           │    HAL     │ ◄──── swap point
       │ (generated)│          │           │  abstract  │       (sim adapter
       └─────┬──────┘          │           └─────┬──────┘        today, myRIO
             │                 │                 │               adapter later)
             ▼                 ▼                 ▼
            ┌──────────────────────────────────────┐
            │             MuJoCo runtime           │
            │   physics + sensors + actuators      │
            └──────────────────────────────────────┘
                              │
                              ▼
                         viewer / logs / plots
```

---

## 2. The HAL — the most important file in the project

`brain/hal.py` is the seam between control logic and the world. Today it talks to MuJoCo. Tomorrow a `LabVIEWHAL` would talk to physical myRIO pins. The control logic doesn't change.

```python
# LABVIEW-PORTABLE — abstract HAL.
# Each method corresponds 1:1 to a myRIO Express VI in LabVIEW.

class HAL:
    # ---- Actuators (write side) ----
    def set_drive_pwm(self, left: float, right: float) -> None: ...
    def set_intake_pwm(self, duty: float) -> None: ...
    def set_flywheel_rpm(self, left_rpm: float, right_rpm: float) -> None: ...
    def set_launcher_pitch(self, deg: float) -> None: ...
    def set_launcher_yaw(self, deg: float) -> None: ...
    def trigger_ball_release(self) -> None: ...

    # ---- Sensors (read side, all return latest sample) ----
    def read_encoders(self) -> tuple[float, float]:     # rad, rad
    def read_imu(self) -> tuple[float, float]:          # yaw_rad, yaw_rate_rad_s
    def read_flywheel_rpm(self) -> tuple[float, float]:
    def read_launcher_angles(self) -> tuple[float, float]: # pitch_deg, yaw_deg
    def read_intake_beam(self) -> bool:                 # ball present?
    def read_camera_balls(self) -> list[tuple[float, float, float]]:
        # returns list of (bearing_deg, distance_m, is_golden) — perception output

    # ---- Lifecycle ----
    def tick(self) -> float:                            # returns dt since last tick
    def now(self) -> float:                             # seconds since match start
```

**Sim implementation** (`brain/hal_sim.py`) — wraps a `mujoco.MjData`, reads/writes via `data.qpos`, `data.qvel`, `data.ctrl`. Camera-balls is "cheated" by querying ball positions and adding Gaussian noise. ~150 LOC.

**Future LabVIEW implementation** (`brain/hal_myrio.py` — not built v1) — would speak UDP to a LabVIEW VI on the myRIO, or be entirely replaced when the brain is rewritten in LabVIEW. Either way, the *list of operations is the same*, which is the point.

**LabVIEW port note** — the methods above are the exact set of myRIO Express VIs the LabVIEW VI will need: PWM Out, Encoder, Accelerometer/Gyro, Analog In (for the beam-break), and TCP/UDP I/O for camera-detected balls (camera processing would either run on the host PC or on the myRIO's FPGA depending on chosen vision stack).

---

## 3. Control loop and state machine

`brain/state_machine.py` — single explicit state machine. No flags-as-state.

```python
# LABVIEW-PORTABLE
# Mirrors the LabVIEW "Standard State Machine" design pattern:
#   shift register holds current state enum → case structure dispatches → returns next state.

class State(IntEnum):
    INIT = 0
    AUTO_LEAVE_BASE = 1
    AUTO_LAUNCH_PRELOADED_1 = 2
    AUTO_LAUNCH_PRELOADED_2 = 3
    AUTO_PARK = 4
    AUTO_DONE = 5
    MANUAL_SEEK_BALL = 10
    MANUAL_PICKUP = 11
    MANUAL_AIM = 12
    MANUAL_FIRE = 13
    MANUAL_GOLDEN_RUSH = 14
    END = 99

def tick(state: State, hal: HAL, ctx: dict) -> State:
    # one big match/case (== LabVIEW case structure)
    # returns next state; no side-effects outside hal.* calls and ctx mutation
    ...
```

`ctx` is the "shift register data": a plain dict of named floats/ints. Constrained to those types because that's all LabVIEW cluster wires carry cleanly.

The top-level runner is dead simple:
```python
state = State.INIT
ctx = {...}
while not done:
    dt = hal.tick()
    state = tick(state, hal, ctx)
```

That's also the structure of the future LabVIEW VI: a while loop with a case structure inside. The translation is mechanical.

---

## 4. File-by-file inventory

| Path | Purpose | Key API | ~LOC | LabVIEW-relevant |
|---|---|---|---|---|
| `spec/arena.yaml` | Field, balls, goal, zones | static data | 80 | — |
| `spec/robot.yaml` | Robot geometry + sensors + actuator limits | static data | 50 | — |
| `spec/ball_physics.yaml` | CoR, friction (calibrated) | static data | 20 | — |
| `spec/surface_physics.yaml` | Banner-floor μ | static data | 10 | — |
| `scripts/build_mjcf.py` | Read spec → emit `mjcf/world.xml`, `mjcf/robot.xml`, `mjcf/goal.xml` | `main()` | 400 | no |
| `scripts/make_goal_mesh.py` | Generate triangulated mesh of plywood face with 6 holes (CSG handled offline) | `main()` | 120 | no |
| `scripts/run_interactive.py` | Load world, keyboard drive, log telemetry | `main()` | 100 | no |
| `scripts/run_match.py` | Headless full match: brain vs stub opponent, with referee | `main()` | 150 | no |
| `scripts/calibrate_ball.py` | Fit CoR/friction from drop-test video frames | `main()` | 200 | no |
| `mjcf/*.xml` | Generated — gitignored | — | gen | no |
| `mjcf/assets/goal_face.obj` | Pre-built mesh (one-time) | — | gen | no |
| `brain/hal.py` | Abstract HAL interface | `class HAL` | 80 | **yes — keep simple** |
| `brain/hal_sim.py` | MuJoCo-backed HAL | `class SimHAL(HAL)` | 200 | no (sim-only) |
| `brain/perception.py` | Pull simulated ball list, filter, return as polar | `update(hal) -> list` | 80 | yes (algorithm) |
| `brain/aim_solver.py` | Consume `oracle/aim_lookup.csv`, return (rpm, pitch, yaw) for target | `solve(distance, height, wind=0) -> tuple` | 100 | **yes — must port** |
| `brain/state_machine.py` | The big state machine + `tick()` | `tick(state, hal, ctx) -> State` | 350 | **yes — must port** |
| `brain/run_brain.py` | The loop above | `main()` | 50 | yes |
| `referee/rules.py` | Scoring table, penalty calc | `score_event(event) -> int` | 200 | no |
| `referee/phase_clock.py` | 60 s AUTO + 180 s MANUAL + Golden release at t=210 | `phase_at(t_sec) -> Phase` | 50 | no |
| `referee/match_loop.py` | Drives `run_brain` + scoring + opponent stub | `run_match(seed) -> MatchResult` | 200 | no |
| `oracle/launcher_only.xml` | Minimal MJCF: goal + ball + launcher | static | 80 | no |
| `oracle/sweep_rpm_angle.py` | Grid sweep → `aim_lookup.csv` | `main()` | 150 | no |
| `oracle/validate_aimy.py` | Compare against AIMY paper trajectories | `main()` | 100 | no |
| `experiments/m1..m6_*.py` | One scenario per rulebook milestone | `main()` | 100 ea | partial |
| `docs/labview_porting_guide.md` | Living doc: HAL → myRIO VI table, gotchas | prose | grows | **yes** |
| `docs/physics_calibration.md` | How to drop-test a real ball, fit μ | prose | grows | no |
| `docs/decisions.md` | ADRs | prose | grows | — |
| `tests/test_hal_contract.py` | Asserts SimHAL implements every method, returns correct types | pytest | 80 | yes |
| `tests/test_state_machine.py` | Deterministic state transitions on synthetic input | pytest | 200 | yes |
| `tests/test_referee_scoring.py` | Replay hand-scored match → assert total | pytest | 150 | no |
| `tests/test_aim_solver_roundtrip.py` | Solver(distance) → sim launch → ball lands at distance ±5% | pytest | 100 | yes |
| `pyproject.toml` / `requirements.txt` | mujoco, numpy, pyyaml, pytest, matplotlib, ffmpeg-python | — | 20 | no |
| `Makefile` | `make sim`, `make build`, `make test`, `make oracle` | — | 30 | no |
| `.gitignore` | mjcf/, .research/, *.csv outputs | — | 10 | — |

**Total v1 budget: ~4,000 LOC** (excluding generated MJCF and CSVs). Realistic for one student over ~3 weeks of focused work.

---

## 5. Data flow for one control tick

```
t = hal.now()
phase = phase_clock.phase_at(t)
balls = perception.update(hal)        # list[(bearing, distance, is_golden)]
state, ctx = state_machine.tick(state, hal, balls, phase, ctx)
hal.tick()                            # advance sim one physics step
```

Tick rate: 100 Hz default (10 ms). Configurable via `spec/robot.yaml` → `control_rate_hz`. Bounded at 500 Hz because that's the realistic upper limit for a myRIO LabVIEW control loop (the [NI knowledge article](https://knowledge.ni.com/KnowledgeArticleDetails?id=kA00Z0000019R13SAE) puts the practical ceiling around 1 kHz, and we leave headroom).

---

## 6. The launcher oracle — separate program, runs once

`oracle/sweep_rpm_angle.py` is **not** part of the control loop. It runs offline:

1. Load `oracle/launcher_only.xml` (goal + ball + idealized launcher).
2. For each (rpm ∈ {500..6000 step 100}, pitch_deg ∈ {15..70 step 1}):
   - Reset the world, set launcher state, eject ball with computed initial velocity + spin.
   - Step physics until ball lands or leaves field.
   - Record: landing (x, y), max height, whether it entered a goal opening, energy at impact.
3. Write `aim_lookup.csv`.

`brain/aim_solver.py` then loads that CSV at startup and serves `solve(distance, target_height) → (rpm, pitch_deg)` via 2D interpolation.

**LabVIEW port note:** the CSV is the deliverable to LabVIEW too. The LabVIEW VI loads it via "Read From Spreadsheet File", interpolates via the "Interpolate 2D Array" express VI. The solver logic ports in a half day.

---

## 7. LabVIEW transferability — concrete checklist

Each item is a design rule baked into the code from day one:

- [ ] No control-loop file imports anything outside: `numpy`, `time`, standard library, `brain.hal`.
- [ ] Every actuator command is a single scalar (or fixed-size tuple) — no streams of commands per tick.
- [ ] State enum values are explicit ints (so they map to LabVIEW typedef enums).
- [ ] `ctx` dict keys are documented in one place (`brain/ctx_schema.py`) listing name, type, units — this becomes the LabVIEW cluster definition.
- [ ] No exceptions in the control path — error states are explicit state values, not Python tracebacks.
- [ ] All units are SI in code (rad, m, s, rad/s); display conversion (deg, cm) happens only at logging/visualization boundary. LabVIEW prefers SI internally too.
- [ ] `docs/labview_porting_guide.md` gets a new row every time a brain function is added: `name | inputs (cluster) | outputs (cluster) | suggested VI pattern`.

When a hardware-savvy collaborator (or you, after some practice) sits down to port, they should be able to do it by mechanically following that guide, with no surprises.

---

## 8. Test strategy

- **Contract tests** ensure `SimHAL` implements every `HAL` method with the right signature and units. When `MyRIOHAL` is built later, the same tests run against it. If both pass, swapping is safe.
- **State-machine tests** feed synthetic sensor traces and assert transitions. Pure-Python, no MuJoCo dependency, runs in <1 s.
- **Referee scoring tests** replay a hand-scored match transcript and assert the total matches.
- **Oracle round-trip test** is the integration check: ask `aim_solver` for the launcher state to hit (distance=3 m, height=1.0 m), apply it in sim, assert the ball lands within 5% of target. If this fails, either the oracle or the physics is off.

Tests run in CI eventually; for now `make test` locally.

---

## 9. Build / dev workflow

```bash
make build       # python scripts/build_mjcf.py — regenerates mjcf/ from spec/
make sim         # python scripts/run_interactive.py — drive the robot with keyboard
make oracle      # python oracle/sweep_rpm_angle.py — regenerate aim_lookup.csv (slow, ~minutes)
make match       # python scripts/run_match.py — headless full match
make test        # pytest
make calibrate   # opens calibration helper for a drop-test video
```

Edit cycle: change `spec/arena.yaml` → `make build` → `make sim`. ~3 seconds.

---

## 10. What I'll execute in P0 once you green-light

Concrete first commits (P0, ~half day):

1. `pyproject.toml` + `requirements.txt` with pinned mujoco version.
2. `spec/arena.yaml` — **placeholder schema only**, values pulled from the rulebook but I'll flag every one for your confirmation.
3. `scripts/build_mjcf.py` — minimal version: empty 6 m × 6 m plane + perimeter rails, no goals/balls yet.
4. `scripts/run_interactive.py` — opens the MuJoCo viewer on the empty world.
5. `brain/hal.py` — abstract class only, no implementation.
6. `docs/labview_porting_guide.md` — empty table with column headers and the first row (HAL methods).
7. `Makefile`, `.gitignore`, `tests/` skeleton.

Acceptance: `make sim` opens the viewer and you see a flat field. That's it for P0.

After your sign-off on P0 I move to P1 (full geometry).

---

## 11. Decisions for you (carryover from PLAN.md §8 + new)

These now block coding (P0 doesn't, but P1 does for items 1-3):

1. **Robot type** — differential drive ✎ default. (Tell me if omni/mecanum instead.)
2. **Launcher type** — dual horizontal flywheel pair ✎ default.
3. **Sensor suite** — encoders + IMU + forward camera + intake beam ✎ default. **No GPS.**
4. **Python version** — 3.11 ✎ default.
5. **Repo init** — should I `git init` the project? It's currently not a git repo. Recommended yes.
6. **Where do you want me to put the running TODO list?** — `docs/decisions.md`, a `TODO.md`, or just the TaskCreate harness? (I'll default to `docs/decisions.md` for design ADRs and TaskCreate for live work.)

---

*End of construction plan v0.1. Review and tell me which sections to expand, simplify, or kill.*
