"""
skills.py
=========
High-level composite skills that bundle multiple MCP tool calls into
single atomic operations for the AI command model.

Instead of the model calling 3-5 raw tools per action, it calls one skill.
Each skill internally chains the underlying mcp_* functions, applies
safety logic (battery checks, boundary validation), and returns a
consolidated result dict.

Consumed by mcp_server.py which registers each skill as an @mcp.tool().
"""

import json
import math

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
    BASE_CENTER,
)
from src.core.db import get_scanned_areas_summary


# ─────────────────────────────────────────────────────────────
# Utility
# ─────────────────────────────────────────────────────────────

def _haversine(lng1, lat1, lng2, lat2):
    """Distance in km between two GPS points."""
    lat1, lng1, lat2, lng2 = map(math.radians, [lat1, lng1, lat2, lng2])
    dlat = lat2 - lat1
    dlng = lng2 - lng1
    a = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlng / 2) ** 2
    return 6371 * 2 * math.asin(math.sqrt(a))


# ═══════════════════════════════════════════════════════════════
# SKILL 1: fleet_overview
# ═══════════════════════════════════════════════════════════════

def skill_fleet_overview() -> dict:
    """
    Full situational awareness in a single call.

    Combines:
      get_active_drones → get_all_drones_status → get_team_sector_status

    Returns a consolidated dict with:
      - drone_ids: list of active drone ID strings
      - fleet: full status of every drone (position, battery, status, ring role)
      - sector: current team sector progress (active sector, waypoints remaining)
      - fleet_summary: quick-glance counts (idle, moving, scanning, low_batt, charging)
    """
    drone_ids = mcp_get_active_drones()
    fleet = mcp_get_all_drones_status()
    sector = mcp_get_team_sector_status()

    # Build quick summary counts
    counts = {"idle": 0, "moving": 0, "scanning": 0, "low_batt": 0, "charging": 0, "rescuing": 0}
    for d in fleet:
        s = d.get("status", "idle")
        if s in counts:
            counts[s] += 1

    return {
        "drone_ids": drone_ids,
        "fleet": fleet,
        "sector": sector,
        "fleet_summary": counts,
        "total_drones": len(drone_ids),
    }


# ═══════════════════════════════════════════════════════════════
# SKILL 2: safe_navigate
# ═══════════════════════════════════════════════════════════════

def skill_safe_navigate(drone_id: str, x: float, y: float) -> dict:
    """
    Battery-safe drone navigation — prevents stranding in the field.

    Combines:
      calculate_battery_plan → move_drone_to OR recall_drone_to_base

    Flow:
      1. Run battery cost analysis for the proposed waypoint.
      2. If CONTINUE → execute move_drone_to(drone_id, x, y).
      3. If RETURN_AFTER_WP → move to waypoint but flag for immediate recall after scan.
      4. If RETURN_NOW → execute recall_drone_to_base(drone_id) instead.

    Returns the battery plan analysis plus the action taken.
    """
    plan = mcp_battery_plan(drone_id, x, y)
    recommendation = plan.get("recommendation", "CONTINUE")

    if recommendation == "RETURN_NOW":
        recall_result = mcp_recall_drone(drone_id)
        return {
            "action": "RECALLED",
            "reason": "Insufficient battery to reach waypoint safely",
            "battery_plan": plan,
            "result": recall_result,
        }
    elif recommendation == "RETURN_AFTER_WP":
        move_result = mcp_move_to(drone_id, x, y)
        return {
            "action": "MOVED_THEN_RECALL",
            "reason": "Can reach waypoint but must return to base after scan",
            "battery_plan": plan,
            "result": move_result,
            "recall_after_scan": True,
        }
    else:
        move_result = mcp_move_to(drone_id, x, y)
        return {
            "action": "MOVED",
            "reason": "Safe for waypoint and return trip",
            "battery_plan": plan,
            "result": move_result,
        }


# ═══════════════════════════════════════════════════════════════
# SKILL 3: scan_waypoint
# ═══════════════════════════════════════════════════════════════

def skill_scan_waypoint(drone_id: str, x: float, y: float) -> dict:
    """
    Full scan-at-waypoint cycle — navigate, scan, advance.

    Combines:
      safe_navigate(drone_id, x, y) → thermal_scan → advance_zone_waypoint

    Returns:
      - navigation: result from safe_navigate (includes battery plan)
      - scan: thermal scan results (survivors found, scan radius)
      - advance: zone waypoint advancement result
      - survivors_found: count of survivors detected in this scan
    """
    nav = skill_safe_navigate(drone_id, x, y)

    # If drone was recalled, skip scan
    if nav["action"] == "RECALLED":
        return {
            "navigation": nav,
            "scan": None,
            "advance": None,
            "survivors_found": 0,
            "status": "recalled_before_scan",
        }

    scan = mcp_thermal_scan(drone_id)
    advance = mcp_advance_zone_waypoint(drone_id)

    survivors_found = len(scan.get("survivors_found", []))

    return {
        "navigation": nav,
        "scan": scan,
        "advance": advance,
        "survivors_found": survivors_found,
        "status": "scan_complete",
    }


# ═══════════════════════════════════════════════════════════════
# SKILL: verified_scan — the canonical scan cycle drones must follow
# ═══════════════════════════════════════════════════════════════

def skill_verified_scan(drone_id: str, x: float, y: float) -> dict:
    """
    The CANONICAL per-waypoint cycle every drone must follow:

        move → thermal_scan → (stop) → cv_scan → cv_scan (double-confirm) → advance

    Flow:
      1. safe_navigate to (x, y).
      2. thermal_scan — fast IR sweep within the 100m green circle.
      3. If thermal found survivors:
           a. cv_scan pass 1 — lock boxes onto each contact.
           b. cv_scan pass 2 — double-confirm classification (HUMAN / zone).
         Only after both passes succeed does the drone advance.
      4. If thermal found nothing, advance immediately — no CV needed.

    Returns:
      navigation, thermal, cv_pass_1, cv_pass_2, advance,
      confirmed_survivors (list),
      status: moved_only | thermal_only | verified | needs_retry | recalled
    """
    nav = skill_safe_navigate(drone_id, x, y)
    if nav["action"] == "RECALLED":
        return {
            "status":     "recalled",
            "navigation": nav,
            "thermal":    None,
            "cv_pass_1":  None,
            "cv_pass_2":  None,
            "advance":    None,
            "confirmed_survivors": [],
        }

    thermal = mcp_thermal_scan(drone_id)
    survivors_in_range = thermal.get("survivors_in_range", [])

    # No contacts → skip CV, just advance to keep the sweep moving.
    if not survivors_in_range:
        advance = mcp_advance_zone_waypoint(drone_id)
        return {
            "status":     "thermal_only",
            "navigation": nav,
            "thermal":    thermal,
            "cv_pass_1":  None,
            "cv_pass_2":  None,
            "advance":    advance,
            "confirmed_survivors": [],
        }

    # Thermal hit — stop, run CV twice for double-confirm.
    cv1 = mcp_cv_scan(drone_id)
    cv2 = mcp_cv_scan(drone_id)

    confirmed = [a for a in cv2.get("analyses", []) if a.get("confirmed")]

    # If hold is still active, keep drone parked so FPV/CV confirmation can finish.
    if cv2.get("cv_hold_active"):
        return {
            "status":     "needs_retry",
            "navigation": nav,
            "thermal":    thermal,
            "cv_pass_1":  cv1,
            "cv_pass_2":  cv2,
            "advance":    None,
            "confirmed_survivors": confirmed,
            "message":    "CV hold still active — keep drone stationary and rerun verified_scan shortly.",
        }

    if cv2.get("all_confirmed"):
        advance = mcp_advance_zone_waypoint(drone_id)
        return {
            "status":     "verified",
            "navigation": nav,
            "thermal":    thermal,
            "cv_pass_1":  cv1,
            "cv_pass_2":  cv2,
            "advance":    advance,
            "confirmed_survivors": confirmed,
        }

    # Some contacts still unconfirmed — hold position, do not advance.
    return {
        "status":     "needs_retry",
        "navigation": nav,
        "thermal":    thermal,
        "cv_pass_1":  cv1,
        "cv_pass_2":  cv2,
        "advance":    None,
        "confirmed_survivors": confirmed,
        "message":    "CV double-confirm incomplete — remain at waypoint and re-run verified_scan.",
    }


# ═══════════════════════════════════════════════════════════════
# SKILL 4: sweep_next
# ═══════════════════════════════════════════════════════════════

def skill_sweep_next(drone_id: str) -> dict:
    """
    One-call "do the next step in the team sector sweep".

    Combines:
      get_team_waypoint → safe_navigate → thermal_scan → advance

    Flow:
      1. Get next team waypoint for this drone.
      2. If role_complete → attempt advance_team_sector.
      3. If all_sectors_complete → return mission done.
      4. Otherwise → safe_navigate + thermal_scan + advance.

    Returns full sweep step result including waypoint, scan, and sector status.
    """
    wp = mcp_get_team_waypoint(drone_id)
    wp_status = wp.get("status", "")

    if wp_status == "all_sectors_complete":
        return {
            "status": "mission_complete",
            "message": "All sectors have been fully swept",
            "waypoint": None,
            "scan": None,
        }

    if wp_status == "role_complete":
        advance = mcp_advance_team_sector()
        return {
            "status": "role_complete",
            "message": "Drone's slice done — team sector advance attempted",
            "advance_result": advance,
            "waypoint": None,
            "scan": None,
        }

    # Normal waypoint — navigate, scan, and continue
    x = wp.get("waypoint_x") or wp.get("x")
    y = wp.get("waypoint_y") or wp.get("y")

    if x is None or y is None:
        return {
            "status": "error",
            "message": "No valid waypoint coordinates returned",
            "waypoint": wp,
            "scan": None,
        }

    nav = skill_safe_navigate(drone_id, float(x), float(y))

    if nav["action"] == "RECALLED":
        return {
            "status": "recalled",
            "waypoint": wp,
            "navigation": nav,
            "scan": None,
        }

    scan = mcp_thermal_scan(drone_id)

    return {
        "status": "sweep_step_complete",
        "waypoint": wp,
        "navigation": nav,
        "scan": scan,
        "survivors_found": len(scan.get("survivors_found", [])),
    }


# ═══════════════════════════════════════════════════════════════
# SKILL 5: battery_check_recall
# ═══════════════════════════════════════════════════════════════

def skill_battery_check_recall(drone_id: str) -> dict:
    """
    Battery guard with automatic recall if critical.

    Combines:
      get_battery_status → (if low) recall_drone_to_base

    Returns battery status and whether a recall was triggered.
    """
    status = mcp_get_battery_status(drone_id)
    warning = status.get("warning")
    battery = status.get("battery", 100)

    if warning or battery <= 20:
        recall_result = mcp_recall_drone(drone_id)
        return {
            "battery": battery,
            "status": status.get("status"),
            "warning": warning,
            "action": "RECALLED",
            "recall_result": recall_result,
        }

    return {
        "battery": battery,
        "status": status.get("status"),
        "warning": None,
        "action": "OK",
    }


# ═══════════════════════════════════════════════════════════════
# SKILL 6: mission_intel
# ═══════════════════════════════════════════════════════════════

def skill_mission_intel() -> dict:
    """
    Full mission intelligence snapshot in a single call.

    Combines:
      get_mission_status → get_mapping_status → get_known_survivors → get_scanned_areas_db

    Returns consolidated intelligence:
      - mission: tick, rescued count, completion status
      - mapping: coverage percentage, unmapped sectors
      - survivors: list of known unrescued survivors
      - scanned_areas: summary of already-scanned regions
      - phase: "MAPPING" if coverage < 100%, else "RESCUE"
    """
    mission = mcp_get_mission_status()
    mapping = mcp_get_mapping_status()
    survivors = mcp_get_known_survivors()
    scanned = get_scanned_areas_summary()

    mapped_pct = mapping.get("mapped_percentage", 0)
    phase = "MAPPING" if mapped_pct < 100 else "RESCUE"

    unrescued_critical = [s for s in survivors if s.get("critical") and not s.get("rescued")]
    unrescued_stable = [s for s in survivors if not s.get("critical") and not s.get("rescued")]

    return {
        "mission": mission,
        "mapping": mapping,
        "survivors_unrescued": len(survivors),
        "survivors_critical": len(unrescued_critical),
        "survivors_stable": len(unrescued_stable),
        "survivor_list": survivors,
        "scanned_areas": scanned,
        "current_phase": phase,
    }


# ═══════════════════════════════════════════════════════════════
# SKILL 7: rescue_dispatch
# ═══════════════════════════════════════════════════════════════

def skill_rescue_dispatch(drone_id: str) -> dict:
    """
    End-to-end rescue dispatch — find nearest unrescued survivor and send drone.

    Combines:
      get_drone_info → get_known_survivors → (pick nearest critical first)
      → safe_navigate to survivor → thermal_scan

    Returns:
      - target_survivor: the survivor being dispatched to
      - navigation: safe_navigate result
      - scan: thermal scan result at survivor location
    """
    info = mcp_get_drone_info(drone_id)
    if info.get("error"):
        return {"status": "error", "message": info["error"]}

    drone_x = info.get("x", BASE_CENTER[0])
    drone_y = info.get("y", BASE_CENTER[1])

    survivors = mcp_get_known_survivors()
    if not survivors:
        return {
            "status": "no_survivors",
            "message": "No unrescued survivors known",
        }

    # Sort: critical first, then by distance
    def sort_key(s):
        dist = _haversine(drone_x, drone_y, s.get("x", 0), s.get("y", 0))
        priority = 0 if s.get("critical") else 1
        return (priority, dist)

    survivors.sort(key=sort_key)
    target = survivors[0]

    nav = skill_safe_navigate(drone_id, target["x"], target["y"])

    if nav["action"] == "RECALLED":
        return {
            "status": "recalled",
            "target_survivor": target,
            "navigation": nav,
            "scan": None,
        }

    scan = mcp_thermal_scan(drone_id)

    return {
        "status": "dispatched",
        "target_survivor": target,
        "navigation": nav,
        "scan": scan,
        "distance_km": _haversine(drone_x, drone_y, target["x"], target["y"]),
    }


# ═══════════════════════════════════════════════════════════════
# SKILL 8: sector_advance
# ═══════════════════════════════════════════════════════════════

def skill_sector_advance() -> dict:
    """
    Safe sector progression — checks readiness before advancing.

    Combines:
      get_team_sector_status → (check all drones done) → advance_team_sector

    Returns sector status and advance result.
    """
    sector = mcp_get_team_sector_status()
    remaining = sector.get("waypoints_remaining", 1)

    if remaining > 0:
        return {
            "status": "not_ready",
            "message": f"{remaining} waypoints remaining in current sector",
            "sector": sector,
            "advanced": False,
        }

    advance = mcp_advance_team_sector()
    return {
        "status": "advanced",
        "previous_sector": sector,
        "advance_result": advance,
        "advanced": True,
    }
