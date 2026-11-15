<div align="center">

# 📋 Changelog
### Metro Manila Search & Rescue Swarm

All notable changes to this project are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

</div>

---

## [v1.3.0] — 2026-04-23

### Added
- **Tactical Command Center** — Replaced the X-Ray console with actionable overrides including Force Recall, smart filtering, and a Critical Anomalies Feed.
- **3D MapLibre Urban Visualization** — Replaced the disjointed 3D FPV UI with a unified high-performance OSM building extrusion map with cinematic lighting.
- **Earthquake Zone Protocol** — If drones enter an active fault zone, the fleet collectively suspends search to conduct a 360-degree seismic survey via A* convergence, then returns to prior grid coordinates.
- **Drone Malfunction Simulation** — Implemented hardware faults (triggering at the 10th thermal scan) that enforce emergency RTB, disabling sweeps until full base repair is completed.
- **Procedural Convergence Effects** — Added a cinematic GPU-based fire/smoke particle system that dynamically reacts inside the 3D MapLibre scene upon disaster focus.
- **Gemma 4 Support** — Added `gemma4:e4b` to model selection matrix.

---

## [v1.2.0] — 2026-03-20

### Added
- **Team Sector Sweep** — all 5 drones cover one 72° pie-slice sector at a time before advancing (`get_team_waypoint`, `get_team_sector_status`, `advance_team_sector`)
- **3-2-1 Arc Formation** — drones fly concentric arc rings (0.5 / 1.0 / 1.5 km) from Batasan Complex Hub with automatic ring-swap on low battery
- **Zone-Ring navigation** — OUTER → MIDDLE → INNER search order prioritising earthquake perimeter first (`get_zone_assignment`, `advance_zone_waypoint`)
- **X-Ray AI Console** — 6-phase transparent AI pipeline streamed live to dashboard (model load → prompt → state → reasoning → tool calls → decision)
- **OSRM street routing** — drones now follow real road geometry via `router.project-osrm.org` with A\* fallback
- **Sector boundary enforcement** — drone tool wrappers block cross-sector movement at the LangChain tool level before any MCP call
- **Streaming token pipeline** — `StreamingCallback` + `asyncio.Queue` + `aiohttp` worker streams LLM tokens word-by-word to dashboard
- **Docker support** — `Dockerfile` with `PORT=7860` for Hugging Face Spaces deployment
- **Auto-placement defaults** — if no survivors/drones placed, simulation generates 600 survivors across a 2 km radius automatically
- **5 rescue drones + 1 CMD drone** — upgraded from 3 to 5 rescue drones with a dedicated formation command drone

### Changed
- Simulation now uses **real GPS coordinates** (longitude/latitude) for all agent positions instead of abstract grid indices
- Battery drain model updated to **0.5% per km** (Haversine distance) instead of per-cell cost
- MCP server port changed to **8766**, dashboard to **8765**
- `--model` CLI flag renamed to **`--models`** (plural) to support comma-separated model lists
- `DroneAgent` pathfinding upgraded from direct vector to **A\* on 15×15 virtual grid** with OSRM primary path

### Fixed
- Commander AI no longer starts before drones are placed on dashboard — now polls `get_active_drones()` until fleet is ready
- `_current_model` global reference now explicitly re-assigned in `run_simulation_headless()` after model creation
- Removed duplicate `_custom_survivors` variable declaration in `metro_manila_rescue.py`
- Added warning log when `get_active_drones()` returns an empty fleet

---

## [v1.1.0] — 2026-03-16

### Added
- **LangGraph ReAct agents** — replaced scripted drone logic with autonomous LLM decision-making via `create_react_agent`
- **FastMCP server** — exposed 16 drone control tools over SSE protocol on port 8766
- **SQLite persistence** — `rescue_mission.db` stores scan history, survivor records, and mission log across restarts
- **Live FastAPI dashboard** — WebSocket-powered map showing real-time drone positions and survivor status
- **Command Agent** — dedicated `command_agent.py` overseer that detects and prevents redundant sector scanning via `override_drone_target`
- **Boustrophedon sweep** — lawnmower-pattern coverage guaranteeing 100% area scan
- **Multi-model support** — Gemini 2.5 Flash, Gemini 2.0 Flash, Qwen3, Llama3, Phi3
- **Ollama integration** — local LLM support via `langchain-ollama`
- **Google Gemini integration** — cloud LLM support via `langchain-google-genai`
- **Async concurrency** — all drones run as parallel `asyncio` tasks with semaphore limits

### Changed
- Upgraded from synchronous scripted loop to fully async `asyncio` event loop
- Dashboard upgraded from static HTML to FastAPI + WebSocket live update architecture

### Fixed
- Race condition where simulation thread accessed `_current_model` before it was initialised

---

## [v1.0.0] — 2026-03-10

### Added
- **Mesa 3.0 simulation** — agent-based model with `DroneAgent` and `SurvivorAgent` classes
- **Initial drone physics** — movement, battery drain, charging, thermal scanning
- **Base stations** — Roxas Blvd Hub, Intramuros Base, UST Field Station
- **8 Manila search sectors** — Intramuros, Ermita, Malate, Binondo, Tondo, Sampaloc, Santa Cruz, Paco
- **SQLite schema** — `mission_log`, `scanned_areas`, `survivors` tables
- **`main.py` entry point** — subprocess-based launch of MCP server + dashboard + drone swarm
- **`requirements.txt`** — pinned dependency versions
- **`pyproject.toml`** — project metadata

---

> **Links:** [README](../README.md) · [SETUP](SETUP.md) · [ARCHITECTURE](ARCHITECTURE.md)
