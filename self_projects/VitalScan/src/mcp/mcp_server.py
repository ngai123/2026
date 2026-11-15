"""
mcp_server.py
=============
FastMCP server that exposes Metro Manila rescue drone tools to the Command Agent.

Started automatically by main.py. Runs three things concurrently:
  1. Mesa simulation   — headless background thread (metro_manila_rescue.py)
  2. Live dashboard    — FastAPI + WebSocket on http://localhost:8765 (dashboard.py)
  3. MCP SSE server    — tool endpoint on http://localhost:8766 (this file)
"""

import sys
import threading
import time
import uvicorn
from mcp.server.fastmcp import FastMCP

from src.core.metro_manila_rescue import (
    mcp_get_active_drones,
    mcp_get_battery_status,
    mcp_battery_plan,
    mcp_get_drone_info,
    mcp_get_all_drones_status,
    mcp_move_to,
    mcp_override_drone_target,
    mcp_recall_drone,
    mcp_thermal_scan,
    mcp_cv_scan,
    mcp_get_mission_status,
    mcp_get_sector_info,
    mcp_get_mapping_status,
    mcp_get_known_survivors,
    mcp_get_arc_waypoints,
    mcp_advance_arc_waypoint,
    mcp_get_next_sweep_waypoint,
    mcp_get_zone_assignment,
    mcp_advance_zone_waypoint,
    mcp_get_team_waypoint,
    mcp_get_team_sector_status,
    mcp_advance_team_sector,
    run_simulation_headless,
    configure_and_start,
)
from src.core.db import get_scanned_areas_summary
from src.ui.dashboard import start_dashboard
from src.agents.skills import (
    skill_fleet_overview,
    skill_safe_navigate,
    skill_scan_waypoint,
    skill_verified_scan,
    skill_sweep_next,
    skill_battery_check_recall,
    skill_mission_intel,
    skill_rescue_dispatch,
    skill_sector_advance,
)

MCP_PORT    = 8766
SOLARA_PORT = 8765

mcp = FastMCP("MetroManilaRescue", json_response=True)


# ── Fleet Discovery ───────────────────────────────────────────────────────────

@mcp.tool()
def get_active_drones() -> list[str]:
    """
    Discover all active rescue drones on the MCP network.
    ALWAYS call this first — drone IDs are assigned dynamically and must not be hardcoded.
    Returns a list of drone ID strings (e.g. ["drone_1", "drone_2", ...]).
    """
    return mcp_get_active_drones()


# ── Battery & Status ──────────────────────────────────────────────────────────

@mcp.tool()
def get_battery_status(drone_id: str) -> dict:
    """
    Check battery level and operational status of a specific drone.
    Returns battery%, status, and a warning string if battery ≤ 20%.
    Always check battery before assigning a sector mission.
    """
    return mcp_get_battery_status(drone_id)


@mcp.tool()
def calculate_battery_plan(drone_id: str, next_wp_x: float, next_wp_y: float) -> dict:
    """
    Battery management planning tool — full round-trip cost analysis.

    Given the drone's current position and the NEXT waypoint it is about to fly to,
    calculates whether the drone has enough battery to:
      (a) Fly to the waypoint
      (b) Complete a thermal scan there
      (c) Return to base with a safe reserve (≥ 15%)

    Returns:
      current_battery_pct    — battery right now
      dist_to_wp_km          — distance to next waypoint
      dist_wp_to_base_km     — distance from waypoint back to base
      cost_to_wp_pct         — battery cost for WP flight
      cost_wp_to_base_pct    — battery cost for return leg
      battery_after_wp_pct   — battery on waypoint arrival
      battery_after_return_pct — battery on base arrival
      max_range_km           — max flyable distance before hitting reserve floor
      recommendation:
        CONTINUE        → safe for WP + return
        RETURN_AFTER_WP → reach WP but can't return safely; do scan then come back
        RETURN_NOW      → not enough battery to reach WP safely; return immediately

    Use this before every move_drone_to call to avoid stranding drones in the field.
    """
    return mcp_battery_plan(drone_id, next_wp_x, next_wp_y)


@mcp.tool()
def get_drone_info(drone_id: str) -> dict:
    """
    Get full situational data for a drone:
    - Current position (x, y)
    - Battery percentage
    - Operational status (idle/moving/scanning/rescuing/charging/low_batt)
    - Home base name and coordinates (for recall planning)
    - Current target coordinates (if any)
    - Number of survivors rescued so far
    - Estimated remaining range in grid cells
    """
    return mcp_get_drone_info(drone_id)


@mcp.tool()
def get_all_drones_status() -> list[dict]:
    """
    Get full status of every drone in the fleet simultaneously.
    Use this after get_active_drones() for fleet-wide situational awareness
    before planning sector assignments.
    """
    return mcp_get_all_drones_status()


# ── Movement ──────────────────────────────────────────────────────────────────

@mcp.tool()
def move_drone_to(drone_id: str, x: float, y: float) -> str:
    """
    Order a drone to navigate to grid coordinates (x, y).
    The drone moves step-by-step each simulation tick.

    Battery cost: ~3% per grid cell (Manhattan distance).
    Safety rule: keep ≥ 20% battery reserve.
    Formula: available_battery = current_battery - 20
             max_safe_range    = available_battery / 3 cells

    Use get_sector_info() to get sector center coordinates.
    Will REFUSE if battery ≤ 20% — recall first in that case.
    """
    return mcp_move_to(drone_id, x, y)


@mcp.tool()
def override_drone_target(drone_id: str, x: float, y: float) -> str:
    """
    SUPERVISOR ONLY: Force a drone to abandon its current action/route and
    immediately redirect to these new coordinates. Use this to prevent redundant scans.
    """
    return mcp_override_drone_target(drone_id, x, y)


@mcp.tool()
def recall_drone_to_base(drone_id: str) -> str:
    """
    Immediately recall a drone to its home base station for recharging.
    Use when battery ≤ 20% OR when reassigning the drone to a different sector.
    The drone will navigate directly to its base and begin charging automatically.
    """
    return mcp_recall_drone(drone_id)


# ── Thermal Scanning ──────────────────────────────────────────────────────────

@mcp.tool()
def thermal_scan(drone_id: str) -> dict:
    """
    Activate the drone's thermal imaging sensor to detect survivors.
    Scans the drone's current cell and surrounding cells within radius 2.
    Returns a list of detected survivors with location, critical status, and rescue state.
    Always call this after moving a drone to a sector.
    """
    return mcp_thermal_scan(drone_id)


@mcp.tool()
def computer_vision_scan(drone_id: str) -> dict:
    """
    Second-pass CV verification of thermal contacts. Required before the drone
    is allowed to leave a waypoint where a thermal hit was found.

    Strict rules:
      1. The drone must be STOPPED (no pending movement path).
      2. A thermal_scan must already have been performed at this position so
         there are detected contacts to analyse.
      3. Each contact must be CV-scanned TWICE (double-confirm) before the
         classification is trusted. Call this tool twice in sequence at the
         same position to fully confirm.

    Returns:
      analyses              — per-contact {confidence, pass_count, confirmed,
                              classification HUMAN|FALSE_POSITIVE, zone CRITICAL|NORMAL}
      all_confirmed         — True only when every contact has pass_count >= 2
      requires_another_pass — True if at least one contact needs a 2nd CV pass
      status                — no_contacts | needs_second_pass | confirmed
    """
    return mcp_cv_scan(drone_id)


# ── Mission Intelligence ──────────────────────────────────────────────────────

@mcp.tool()
def set_mission_paused(paused: bool) -> dict:
    """
    Pause or resume the simulation. 
    True = pause, False = resume.
    """
    from src.core.metro_manila_rescue import set_mission_paused as smp
    smp(paused)
    return {"status": "paused" if paused else "resumed"}


@mcp.tool()
def get_mission_status() -> dict:
    """
    Get overall mission progress:
    - Current simulation tick
    - Survivors rescued / total
    - Rescue percentage
    - Mission complete flag
    - Total distance flown and battery consumed
    - Last 5 rescue events
    Call periodically to monitor mission progress.
    """
    return mcp_get_mission_status()


@mcp.tool()
def get_mapping_status() -> dict:
    """
    Get the coverage percentage of Metro Manila mapped by drones.
    Returns the percentage mapped and a list of unmapped sector names.
    PHASE 1 is complete when mapped_percentage == 100%.
    """
    return mcp_get_mapping_status()


@mcp.tool()
def get_scanned_areas_db() -> str:
    """
    Query the persistent Central Database for explicitly summarized 
    coordinate bounds of regions already mapped by drones.
    Avoid scanning these areas again.
    """
    return get_scanned_areas_summary()


@mcp.tool()
def get_known_survivors() -> list[dict]:
    """
    Get coordinates of all survivors within the mapped sections that
    HAVE NOT yet been rescued.
    Use this during PHASE 2 to assign drones for rescue mathematically.
    """
    return mcp_get_known_survivors()


@mcp.tool()
def get_sector_info() -> dict:
    """
    Get Metro Manila search sector definitions.
    Returns a dict of sector names → center coordinates (x, y).
    Use these coordinates with move_drone_to() for systematic coverage.
    Sectors span all major districts: Manila, Pasay, Makati, Taguig, Pasig,
    Marikina, Quezon City, Caloocan, Navotas-Malabon.
    """
    return mcp_get_sector_info()


@mcp.tool()
def get_arc_waypoints(drone_id: str) -> dict:
    """Get arc waypoint list for formation drone navigation."""
    return mcp_get_arc_waypoints(drone_id)


@mcp.tool()
def advance_arc_waypoint(drone_id: str) -> dict:
    """Advance command drone to next arc waypoint in formation sweep."""
    return mcp_advance_arc_waypoint(drone_id)


@mcp.tool()
def get_next_sweep_waypoint(drone_id: str) -> dict:
    """Get the next waypoint from the boustrophedon sweep path for a drone.
    Uses a robot-vacuum coverage algorithm to guarantee full area scanning.
    Returns the next coordinate the drone should move to, or 'complete' if done."""
    return mcp_get_next_sweep_waypoint(drone_id)


@mcp.tool()
def get_zone_assignment(drone_id: str) -> dict:
    """
    Zone-Ring Assignment: returns the current ring zone (OUTER / MIDDLE / INNER)
    and the next waypoint the Command Agent should dispatch this drone to.
    Zones are searched outside-in (OUTER first, then MIDDLE, then INNER).
    OUTER = 1.3–2.0 km from base, MIDDLE = 0.6–1.3 km, INNER = 0.0–0.6 km.
    Always call this instead of get_next_sweep_waypoint for zone-aware navigation.
    """
    return mcp_get_zone_assignment(drone_id)


@mcp.tool()
def advance_zone_waypoint(drone_id: str) -> dict:
    """
    Advance the drone to the next waypoint within its current zone ring.
    Call after the drone completes its thermal scan at the current position.
    When all waypoints in a zone are done, the next get_zone_assignment call
    automatically promotes the drone to the inner ring.
    """
    return mcp_advance_zone_waypoint(drone_id)


# ── Team Sector Tools (all 5 drones sweep one sector together) ─────────────────

@mcp.tool()
def get_team_waypoint(drone_id: str) -> dict:
    """
    TEAM SECTOR SWEEP — pop the next pre-assigned waypoint from this drone's personal queue.
    3-2-1 distribution: R1/R2/R3 → OUTER ring, R4/R5 → MIDDLE ring, INNER shared.
    Returns status='next_waypoint' with x/y/ring/sector info.
    Returns status='role_complete' when this drone's slice is done (call advance_team_sector).
    Returns status='all_sectors_complete' when mission is done.
    """
    return mcp_get_team_waypoint(drone_id)


@mcp.tool()
def get_team_sector_status() -> dict:
    """
    Get current team sector status: which sector is active, how many waypoints dispatched/remaining,
    sector color, angle range, and overall progress (sector 1/5, 2/5, etc.).
    Use this for situational awareness before assigning waypoints.
    """
    return mcp_get_team_sector_status()


@mcp.tool()
def advance_team_sector() -> dict:
    """
    Advance all 5 drones to the next team sector.
    Call when get_team_waypoint returns status='role_complete'.
    Returns 'not_ready' if teammates are still sweeping; 'advanced' when the whole team is done.
    """
    return mcp_advance_team_sector()


# ── Composite Skills (high-level operations) ─────────────────────────────────

@mcp.tool()
def fleet_overview() -> dict:
    """
    SKILL: Full fleet situational awareness in a single call.
    Returns all active drone IDs, full status of every drone (position, battery,
    ring role), current team sector progress, and a fleet summary with counts
    of idle/moving/scanning/charging/low_batt drones.
    Call this FIRST at the start of every decision cycle.
    """
    return skill_fleet_overview()


@mcp.tool()
def safe_navigate(drone_id: str, x: float, y: float) -> dict:
    """
    SKILL: Battery-safe drone navigation — prevents stranding.
    Runs battery cost analysis for the proposed waypoint, then either:
      - Moves the drone if battery is sufficient (action=MOVED)
      - Moves but flags for recall after scan (action=MOVED_THEN_RECALL)
      - Recalls the drone to base instead (action=RECALLED)
    Always use this instead of raw move_drone_to.
    """
    return skill_safe_navigate(drone_id, x, y)


@mcp.tool()
def scan_waypoint(drone_id: str, x: float, y: float) -> dict:
    """
    SKILL: Full scan-at-waypoint cycle — navigate + scan + advance.
    Safely navigates the drone to (x, y), runs a thermal scan for survivors,
    then advances the zone waypoint cursor.
    Returns navigation result, scan result, and count of survivors found.
    Use this for systematic sector coverage.
    """
    return skill_scan_waypoint(drone_id, x, y)


@mcp.tool()
def verified_scan(drone_id: str, x: float, y: float) -> dict:
    """
    SKILL (PREFERRED): The strict per-waypoint cycle every drone must follow:
        move → thermal_scan → (stop) → cv_scan → cv_scan (double-confirm) → advance

    - If the thermal scan is empty, the drone advances immediately (no CV needed).
    - If the thermal scan finds contacts, TWO computer_vision_scan passes run
      before advancing, so every contact is locked and double-confirmed.
    - If double-confirm fails, the drone HOLDS at the waypoint (does not advance)
      and the tool returns status="needs_retry" — re-run verified_scan to retry.

    Returns: navigation, thermal, cv_pass_1, cv_pass_2, advance,
             confirmed_survivors, and status
             (verified | thermal_only | needs_retry | recalled).
    Use this instead of scan_waypoint whenever contacts are expected.
    """
    return skill_verified_scan(drone_id, x, y)


@mcp.tool()
def sweep_next(drone_id: str) -> dict:
    """
    SKILL: Execute the next step in the team sector sweep.
    Gets the next team waypoint for the drone, navigates safely, scans,
    and advances. Handles role_complete and all_sectors_complete automatically.
    Returns: status (sweep_step_complete | role_complete | mission_complete | recalled),
    waypoint data, scan results, and survivors found count.
    """
    return skill_sweep_next(drone_id)


@mcp.tool()
def battery_check_recall(drone_id: str) -> dict:
    """
    SKILL: Battery guard with automatic recall.
    Checks battery level — if critical (≤20% or warning present),
    automatically recalls the drone to base.
    Returns battery level, status, and whether recall was triggered (action=OK or RECALLED).
    """
    return skill_battery_check_recall(drone_id)


@mcp.tool()
def mission_intel() -> dict:
    """
    SKILL: Full mission intelligence snapshot.
    Combines mission status, mapping coverage, known survivors, and scanned areas
    into a single intelligence report.
    Returns: mission progress, mapping percentage, current phase (MAPPING or RESCUE),
    counts of unrescued critical and stable survivors, and scanned area summary.
    """
    return skill_mission_intel()


@mcp.tool()
def rescue_dispatch(drone_id: str) -> dict:
    """
    SKILL: End-to-end rescue dispatch.
    Finds the nearest unrescued survivor (critical first), safely navigates
    the drone to that location, and performs a thermal scan.
    Use this during PHASE 2 (RESCUE) when all sectors are mapped.
    Returns target survivor, navigation result, and scan result.
    """
    return skill_rescue_dispatch(drone_id)


@mcp.tool()
def sector_advance() -> dict:
    """
    SKILL: Safe sector progression.
    Checks if all drones have finished their waypoints in the current sector.
    If ready, advances the team to the next sector.
    If not ready, returns remaining waypoint count.
    """
    return skill_sector_advance()


# ── Entry Point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    # 1. Start Mesa simulation in a background thread
    threading.Thread(
        target=run_simulation_headless,
        kwargs={"step_interval": 0.35},
        daemon=True,
        name="SimulationThread",
    ).start()

    # 2. Start the live dashboard in a background thread
    threading.Thread(
        target=start_dashboard,
        kwargs={"port": SOLARA_PORT},
        daemon=True,
        name="DashboardThread",
    ).start()

    time.sleep(0.5)
    print(f"[SYSTEM] Startup sequence complete.", file=sys.stderr, flush=True)
    print(f"[VIZ] Dashboard  → http://localhost:{SOLARA_PORT}", file=sys.stderr, flush=True)
    print(f"[MCP] MCP server → http://localhost:{MCP_PORT} (SSE)", file=sys.stderr, flush=True)

    # 3. Block serving MCP requests via SSE
    import os
    mcp.settings.port = int(os.environ.get("MCP_PORT", MCP_PORT))
    mcp.settings.host = "0.0.0.0"
    print(f"[SYSTEM] Starting FastMCP SSE server on port {mcp.settings.port}...", file=sys.stderr, flush=True)
    mcp.run(transport="sse")
