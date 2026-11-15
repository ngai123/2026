# VitalScan — Domain Context

Glossary, invariants, and boundaries for the autonomous SAR drone swarm. The terms "agent", "tool", and "memory" mean specific things here — read this before editing.

## Glossary

### Drones & formation
- **Rescue Drone (R1–R5)** — Five autonomous field drones. Scan for survivors, manage battery, report findings. Runtime IDs `drone_21` … `drone_25`.
- **Command Drone (CMD)** — Single formation leader. Flies arc waypoints, monitors ring-swaps, reports fleet health. Does NOT scan.
- **3-2-1 Arc Formation** — Radial concentric rings centred at Batasan Complex (120.980°E, 14.590°N): OUTER (1.5 km, R1/R2/R3), MIDDLE (1.0 km, R4/R5), INNER (0.5 km, recycled drones).

### Mission modes
- **Team Sector Sweep** — All 5 drones converge on one pie-slice (72° each) at a time. R1/R2/R3 → OUTER, R4/R5 → MIDDLE.
- **Boustrophedon Sweep** — Lawnmower pattern. 100% area coverage guarantee.
- **Arc Formation Navigation** — Radial fan-sweep expanding outward in concentric rings.

### AI & control
- **ReAct Agent** — LangGraph Reasoning+Acting loop per drone. Picks tools (`get_battery → move → scan`), streams decisions. Backed by Gemini 2.5 / Qwen3 / local LLM.
- **MCP** — Model Context Protocol. 26 SSE tools (`move_drone_to`, `thermal_scan`, `advance_arc_waypoint`, …) bridge AI to the physics engine.
- **Scan Memory** — SQLite (`rescue_mission.db`) persists scanned areas, survivors, events. Survives restarts; agents query before moving to avoid re-scans.

### System events
- **Earthquake Protocol** — Seismic zones (1.1 km from base, 0.245 km radius) trigger convergence: all drones pause → `QUAKE_SURVEY` → A* to zone centre → `QUAKE_RTB`.
- **Malfunction** — Fault on the 10th thermal scan. Drone enters `MALFUNCTION`, auto-recalls to base for `REPAIRING`.
- **Battery Swap** — When an OUTER drone hits ≤ 50%, the physics engine (not AI) auto-recalls it and promotes the nearest MIDDLE drone to OUTER.

### Dashboard & routing
- **X-Ray Console** — Tactical UI. Streams drone reasoning tokens live; shows positions, survivors, sector coverage, battery. Supports force-recall overrides.
- **OSRM Routing** — Tier-1: real street geometry via `router.project-osrm.org`. 3s timeout.
- **A\* Fallback** — Tier-2: 15×15 virtual grid over Manila bounds, Haversine heuristic. Activates on OSRM timeout.

## Invariants

1. **All positions are real GPS** (longitude, latitude) bounded 14.550°–14.630°N, 120.950°–121.010°E. Distance via Haversine (R=6371 km). Bearing: 0° = North, clockwise.
2. **Fixed ports:** MCP SSE on `8766`, FastAPI dashboard on `8765`. Main sim runs headless in a background thread spawned by `main.py`.
3. **Agent lifecycle:** every drone loops `read state via MCP → plan → execute → sleep 6s`. CMD skips `thermal_scan`, uses `get_all_drones_status`.
4. **Scan persistence:** every `thermal_scan()` writes to `scanned_areas` (x, y, radius, tick). Agents must consult `get_scanned_areas_db()` before moving.
5. **Battery:** drain = 2.4% per km (Haversine). Start 70–100%. Auto-recall at ≤ 50%. Charge 20% / tick at base. Movement blocked below 20% (except `override_drone_target`).
6. **Formation ring promotion** is a physics engine concern, never an AI decision. AI cannot mutate drone position directly — only via MCP.

## Boundaries

**Inside:** 5 rescue + 1 command drone in continuous GPS space (Mesa 3.0), 600 survivors with injury flags, OSRM/A* routing, battery/charge/ring-swap, earthquake & malfunction, thermal scanning (100 m radius), three navigation strategies.

**External:** Gemini 2.5 / Qwen3 LLMs (cloud or local), OSRM public router, FastAPI + MapLibre dashboard, SQLite for mission log.

**AI/physics separation:** the physics engine in `metro_manila_rescue.py` owns all movement, battery, collision, and scan outcomes. AI agents reason and decide but mutate state *only* through MCP tools — they cannot hallucinate positions or scans.

**Domain context:** Search & Rescue response to a Mw 7.4 West Valley Fault earthquake in Metro Manila — "Operation BAYANIHAN".
