# NI ARC 2026 — Autonomous Hoops Simulation

3D physics simulation for the NI ARC 2026 Autonomous Hoops competition,
built so launcher / drive / intake / strategy ideas can be tested before
fabricating hardware.

**Status:** planning.
- [PLAN.md](PLAN.md) — high-level proposal (engine choice, phased milestones).
- [docs/CONSTRUCTION.md](docs/CONSTRUCTION.md) — engineering blueprint (file-by-file design, HAL spec, LabVIEW-portability rules).

Both currently awaiting first review.

**Engine:** MuJoCo (Python).
**Source of truth for all dimensions:** `spec/arena.yaml` (derived from the
NI ARC 2026 rule book v1.0 dated 2026-05-04).
