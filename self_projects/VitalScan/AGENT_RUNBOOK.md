# 🤖 VitalScan AI Agent Runbook

Welcome! If you are an AI assistant reading this, this document contains the condensed architectural state of the VitalScan codebase as of **v1.3.0**. Read this before making architectural assumptions or writing code.

---

## 1. Core Philosophy (Sense-Think-Act)
The system strictly separates **AI Logistics (LangGraph)** from the **Physics Engine (Mesa 3.0)**.
- **Drones cannot move themselves.** They must call MCP tools (e.g., `move_drone_to`, `thermal_scan`).
- The Python physics engine `src/core/metro_manila_rescue.py` handles the physical rules like OSRM routing, A* fallbacks, battery drain, and overrides.
- **Never attempt to implement physics, battery, or movement logic inside the AI Prompt.** Let the physics engine return error boundaries if an agent asks to do something impossible.

## 2. Recent Major Paradigm Shifts (Do Not Hallucinate Legacy Systems)
1. **The 3D FPV is GONE**: We previously used 5 separate Three.js FPV mini-map windows for the drones. **This has been removed.** The dashboard now uses a single unified **MapLibre native 3D vector tile OSM map**. Do not attempt to render Three.js instances for individual drones.
2. **Dynamic Overrides**: Drones can now be overridden by the physics engine under specific scenarios. If a drone hits an **Earthquake Zone** (`_quake_zones`), it automatically enters a `QUAKE_SURVEY` state and converges via A* regardless of the LLM's commands. Similarly, drones will randomly suffer a `MALFUNCTION` and RTB. Do not assume the LLM is always 100% in control of the position.
3. **Tactical Command Center**: The UI is now actionable. Operators can issue Force Recalls and smart filter logs. It is no longer just a passive log viewer. 

## 3. Technology Stack Pulse Check
- **Backend / Dashboard:** FastAPI + WebSockets + MapLibre GL JS + HTML5/CSS Vanilla. 
- **Agent Framework:** LangGraph ReAct Agents (`src/agents/drone_agents.py`). Multiple models supported (Gemini, Qwen3, gemma4).
- **Communication:** FastMCP (`src/mcp/mcp_server.py`) serving 26 exposed SSE tools.
- **Persistence:** SQLite (`rescue_mission.db`) saves the scan state so agents do not suffer context amnesia across long missions.

## 4. Key Global State Variables (Physics Engine)
If you are debugging state overrides in `metro_manila_rescue.py`, monitor:
- `_malfunction_triggered`: Boolean controlling if the simulation has injected a one-off hardware fault.
- `_quake_zones`: List of zones that trigger the collective convergence override.
- `DroneStatus` (Enum): Includes states like `MALFUNCTION`, `REPAIRING`, `QUAKE_SURVEY`, and `QUAKE_RTB`.

## 5. Next Steps
Cross-reference your task against `docs/ARCHITECTURE.md` and `docs/MCP_TOOLS.md` before altering the tool calling functions. Ensure you use A* or OSRM helper functions for all coordinate adjustments.
