"""
metro_manila_rescue.py
======================
Metro Manila Disaster Rescue Simulation — Mesa 3.0

25x25 grid representing Metro Manila during a typhoon/flooding scenario.
Drones are fully command-driven: they ONLY move when the AI agent issues
an explicit move_drone_to() or recall_drone_to_base() order via MCP.
They do NOT pick their own targets.

Used by:
  mcp_server.py  — imports MCP tool functions + run_simulation_headless()
  dashboard.py   — imports _current_model, DroneAgent, SurvivorAgent
"""

import mesa
import random
import sys
import threading
import time
import json
import math
from enum import Enum
from src.core.db import record_scan, record_survivor, log_event


# ─────────────────────────────────────────────────────────────
# 1. CONSTANTS & METRICS
# ─────────────────────────────────────────────────────────────

# Geographical bounds (Lng, Lat) for CITY OF MANILA tightly
GEO_BOUNDS = {"swLat": 14.550, "swLng": 120.950, "neLat": 14.630, "neLng": 121.010}

# NDRRMC drone charging hubs
BASE_STATIONS = {
    "Roxas Blvd Hub": (120.978, 14.575),  
    "Intramuros Base": (120.975, 14.589),
    "UST Field Station": (120.989, 14.610),
}

# City of Manila logical search sectors with center coordinates.
MANILA_CITY_SECTORS = {
    "Intramuros":  (120.975, 14.589),
    "Ermita":      (120.982, 14.578),
    "Malate":      (120.988, 14.570),
    "Binondo":     (120.974, 14.600),
    "Tondo":       (120.963, 14.616),
    "Sampaloc":    (120.994, 14.608),
    "Santa Cruz":  (120.982, 14.610),
    "Paco":        (120.993, 14.582),
}

# Simulation constants
NUM_DRONES     = 5
NUM_SURVIVORS  = 600
DISASTER_CELLS = 30

LOW_BATTERY    = 50   # % threshold — outer drones swap + return to base below this
BATTERY_DRAIN  = 2.4  # % per km moved (fast drain → clear RTB/replacement cycle for demo)
CHARGE_RATE    = 20   # % per tick while at base
VISION_RADIUS  = 0.1  # km radius around the drone checked during thermal scan (100m = blue circle on map)
SPEED_PER_TICK = 0.05 # km per tick moved

# ─────────────────────────────────────────────────────────────
# ARC FORMATION SWARM: 3-2-1 pattern with fan-shaped search
# ─────────────────────────────────────────────────────────────
BASE_CENTER = (120.980, 14.590)  # Center of arc rings

# Arc rings in km from base (inner to outer): 3-2-1 formation depth
ARC_RINGS_KM = [0.5, 1.0, 1.5]

# Four quadrants covering 360° (fan-shaped search)
QUADRANTS = {
    "Q_NE": (0, 90),      # Northeast
    "Q_NW": (270, 360),   # Northwest (or -90 to 0)
    "Q_SW": (180, 270),   # Southwest
    "Q_SE": (90, 180),    # Southeast
}

# Formation slots: R1-R5 (rescue drones), CMD (command drone)
FORMATION_SLOTS = ["R1", "R2", "R3", "R4", "R5", "CMD"]

# ─────────────────────────────────────────────────────────────
# TEAM SECTORS — 5 equal pie-slices, all 5 drones sweep one sector at a time.
# Compass bearing convention: 0 = North, 90 = East, CW (matches _offset_geo).
# ─────────────────────────────────────────────────────────────
TEAM_SECTORS = [
    {"id": "S1", "angle_start":   0, "angle_end":  72, "color": "#FF6600", "name": "Alpha",   "sweep": "arc"},
    {"id": "S2", "angle_start":  72, "angle_end": 144, "color": "#FF2222", "name": "Bravo",   "sweep": "fan"},
    {"id": "S3", "angle_start": 144, "angle_end": 216, "color": "#2244FF", "name": "Charlie", "sweep": "arc"},
    {"id": "S4", "angle_start": 216, "angle_end": 288, "color": "#22BB22", "name": "Delta",   "sweep": "fan"},
    {"id": "S5", "angle_start": 288, "angle_end": 360, "color": "#BB22BB", "name": "Echo",    "sweep": "arc"},
]

# Approximate km-per-degree for Manila latitude
_KM_PER_LAT = 111.0
_KM_PER_LNG = 111.0 * math.cos(math.radians(BASE_CENTER[1]))

# Shared global set by MetroManilaRescueModel.__init__; read by dashboard.py
_current_model = None

# Pause/resume control — cleared (paused) by default until user clicks START
_pause_event = threading.Event()

# Setup gate — blocks simulation thread until user places survivors and clicks START
_setup_event = threading.Event()

# Custom survivor positions set via the dashboard placement map
_custom_survivors: list | None = None

# Custom drone spawn positions set via the dashboard placement map
_custom_drones: list | None = None

# ── Team-sector shared state (all 5 drones work one sector at a time) ──────────
_team_lock           = threading.Lock()
_current_team_sector: int  = 0      # index into TEAM_SECTORS
_team_sector_all_wps: dict = {}     # sector_id → {ring: [(lng, lat, ring), ...]}
_team_sector_complete: bool = False  # True once all 5 sectors are exhausted
# Per-drone pre-assigned waypoint queues (strict 3-2-1 ring distribution)
_drone_sector_wps:  dict = {}  # drone_id → [(lng, lat, ring), ...]
_drone_sector_idx:  dict = {}  # drone_id → next waypoint index

# One-shot malfunction flag — triggers on the 10th thermal scan
_malfunction_triggered: bool = False
_thermal_scan_count:    int  = 0   # increments every mcp_thermal_scan call

# ── Earthquake zone response ──────────────────────────────────────────────────
# Zones match the frontend QUAKE_ZONES (bearing from BASE_CENTER, 1.1 km, r=0.245 km)
# Computed lazily after _offset_geo is defined.
_QUAKE_ZONE_BEARINGS   = [36, 108, 180]   # bisectors of S1, S2, S3 sectors
_QUAKE_ZONE_RADIUS_KM  = 0.245
_QUAKE_ZONE_DIST_KM    = 1.1
_quake_zones: list     = []   # [{lng, lat, radius_km}, …] — filled at model init
_quake_responded:  bool = False  # only one zone triggers the collective response
_quake_zone_active: dict | None = None  # the zone currently being surveyed


def set_mission_paused(paused: bool) -> None:
    """True → pause simulation; False → resume/start."""
    if paused:
        _pause_event.clear()
    else:
        _pause_event.set()


def _generate_default_placements() -> tuple[list, list, list]:
    """Generate defaults: 1 base, 5 drones, NUM_SURVIVORS survivors spread across the 2km scan circle."""
    base_lng, base_lat = BASE_CENTER

    bases = [{"x": base_lng, "y": base_lat}]

    # 5 rescue drones clustered at base (≈45m radius)
    drones = []
    for i in range(5):
        angle = (i / 5) * 2 * math.pi
        dx = 0.0004 * math.cos(angle)
        dy = 0.0004 * math.sin(angle)
        drones.append({"x": base_lng + dx, "y": base_lat + dy})

    # Survivors uniform-random inside 2km circle (same logic as _place_survivors fallback)
    survivors = []
    for _ in range(NUM_SURVIVORS):
        r_km  = math.sqrt(random.random()) * 2.0
        theta = random.random() * 2 * math.pi
        sx = base_lng + (r_km / _KM_PER_LNG) * math.cos(theta)
        sy = base_lat + (r_km / _KM_PER_LAT) * math.sin(theta)
        sx = max(GEO_BOUNDS["swLng"], min(GEO_BOUNDS["neLng"], sx))
        sy = max(GEO_BOUNDS["swLat"], min(GEO_BOUNDS["neLat"], sy))
        survivors.append({
            "x": sx, "y": sy,
            "critical": random.random() < 0.25,
        })

    return survivors, drones, bases


def configure_and_start(survivors: list = None, drones: list = None, bases: list = None) -> None:
    """
    Store survivor/drone positions and start simulation.
    If none provided, uses auto-generated defaults.
    """
    global _custom_survivors, _custom_drones, BASE_STATIONS

    # Auto-generate defaults if nothing provided
    if not survivors and not drones and not bases:
        print(f"[START] No placements provided — auto-generating defaults...", file=sys.stderr, flush=True)
        survivors, drones, bases = _generate_default_placements()

    print(f"[START] configure_and_start() called with {len(survivors or [])} survivors, {len(drones or [])} drones, {len(bases or [])} bases", file=sys.stderr, flush=True)

    if bases:
        BASE_STATIONS = {}
        for i, b in enumerate(bases):
            bx = float(b["x"])
            by = float(b["y"])
            BASE_STATIONS[f"Custom Base {i+1}"] = (bx, by)
        print(f"[START]   → BASE_STATIONS: {BASE_STATIONS}", file=sys.stderr, flush=True)

    _custom_survivors = survivors if survivors else None
    _custom_drones = drones if drones else None
    print(f"[START]   → Survivors: {len(_custom_survivors or [])}, Drones: {len(_custom_drones or [])}", file=sys.stderr, flush=True)
    _setup_event.set()   # allow run_simulation_headless to create the model
    _pause_event.set()   # allow the simulation loop to start ticking


# ─────────────────────────────────────────────────────────────
# 2. AGENTS
# ─────────────────────────────────────────────────────────────

def _get_osrm_route(start_lng: float, start_lat: float, end_lng: float, end_lat: float) -> list[tuple[float, float]]:
    """Query the public OSRM mapping API to get street-realistic path coordinates."""
    url = f"http://router.project-osrm.org/route/v1/driving/{start_lng},{start_lat};{end_lng},{end_lat}?steps=false&geometries=geojson&overview=full"
    try:
        from urllib.request import Request, urlopen
        import json
        req = Request(url, headers={'User-Agent': 'MetroManilaRescue/1.0'})
        with urlopen(req, timeout=3.0) as resp:
            data = json.loads(resp.read().decode())
            if data.get("code") == "Ok":
                # LineString coordinates are [lng, lat]
                coords = data["routes"][0]["geometry"]["coordinates"]
                return [(float(c[0]), float(c[1])) for c in coords]
    except Exception as e:
        print(f"[OSRM ERROR] {e}", file=sys.stderr)
    return []

def _astar_route(start_lng: float, start_lat: float, end_lng: float, end_lat: float, steps: int = 30) -> list[tuple[float, float]]:
    """Virtual discretized A* pathfinder across the continuous space."""
    import heapq
    import math
    
    # 1. Discretize the continuous space into a virtual grid of `steps x steps` cells
    min_lng, max_lng = GEO_BOUNDS["swLng"], GEO_BOUNDS["neLng"]
    min_lat, max_lat = GEO_BOUNDS["swLat"], GEO_BOUNDS["neLat"]
    
    lng_step = (max_lng - min_lng) / steps
    lat_step = (max_lat - min_lat) / steps
    
    def to_grid(lng, lat):
        gx = int(max(0, min(steps - 1, (lng - min_lng) / lng_step)))
        gy = int(max(0, min(steps - 1, (lat - min_lat) / lat_step)))
        return gx, gy
        
    def to_geo(gx, gy):
        lng = min_lng + (gx + 0.5) * lng_step
        lat = min_lat + (gy + 0.5) * lat_step
        return lng, lat
        
    start = to_grid(start_lng, start_lat)
    goal = to_grid(end_lng, end_lat)
    
    # Standard A* on the virtual grid
    def heuristic(a, b):
        return math.hypot(a[0] - b[0], a[1] - b[1])
        
    frontier = []
    heapq.heappush(frontier, (0, start))
    came_from = {start: None}
    cost_so_far = {start: 0.0}
    
    while frontier:
        _, current = heapq.heappop(frontier)
        
        if current == goal:
            break
            
        # 8-way movement
        for dx, dy in [(-1,-1), (-1,0), (-1,1), (0,-1), (0,1), (1,-1), (1,0), (1,1)]:
            nx, ny = current[0] + dx, current[1] + dy
            if 0 <= nx < steps and 0 <= ny < steps:
                next_node = (nx, ny)
                # Diagonal cost is slightly higher (sqrt(2) approx 1.414)
                move_cost = 1.414 if (dx != 0 and dy != 0) else 1.0
                new_cost = cost_so_far[current] + move_cost
                
                if next_node not in cost_so_far or new_cost < cost_so_far[next_node]:
                    cost_so_far[next_node] = new_cost
                    priority = new_cost + heuristic(next_node, goal)
                    heapq.heappush(frontier, (priority, next_node))
                    came_from[next_node] = current
                    
    # Reconstruct path and map back to geo coordinates
    if goal not in came_from and start != goal:
        return [] # No path found (shouldn't happen in an empty grid, but just in case)
        
    path = []
    current = goal
    while current != start:
        path.append(current)
        if current in came_from:
            current = came_from[current]
        else:
            break
            
    path.reverse()
    
    # Convert grid points back to geo coords, ensuring the final point is the exact target
    geo_path = [to_geo(gx, gy) for gx, gy in path[:-1]] if len(path) > 1 else []
    if path:
        geo_path.append((end_lng, end_lat))
        
    return geo_path

class DroneStatus(Enum):
    IDLE        = "idle"
    MOVING      = "moving"
    SCANNING    = "scanning"
    RESCUING    = "rescuing"
    CHARGING    = "charging"
    LOW_BATT    = "low_batt"
    MALFUNCTION  = "malfunction"   # fault detected — pausing then RTB
    REPAIRING    = "repairing"    # at base, repair in progress
    QUAKE_SURVEY = "quake_survey" # stopped at earthquake zone, doing seismic survey
    QUAKE_RTB    = "quake_rtb"   # returning from earthquake zone to resume sweep


class DroneRole(Enum):
    """Formation swarm roles"""
    RESCUE = "rescue"     # 5 rescue drones in 3-2-1 formation
    COMMAND = "command"   # 1 command drone coordinating formation


def haversine_distance(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    """Return physical distance in kilometers between two GPS coordinates."""
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c


class SurvivorAgent(mesa.Agent):
    def __init__(self, model, district: str):
        super().__init__(model)
        self.district = district
        self.rescued  = False
        self.detected = False   # Added to track if drone has scanned this survivor
        self.critical = random.random() < 0.3   # 30% are critical cases

    def step(self):
        pass   # survivors are passive


# ─────────────────────────────────────────────────────────────
# ARC FORMATION HELPERS
# ─────────────────────────────────────────────────────────────

def _offset_geo(center_lng: float, center_lat: float, bearing_deg: float, distance_km: float) -> tuple[float, float]:
    """
    Offset a geographic point by bearing (degrees) and distance (km).
    Bearing: 0° = East, 90° = North, 180° = West, 270° = South
    """
    lat_offset = (distance_km / _KM_PER_LAT) * math.cos(math.radians(bearing_deg))
    lng_offset = (distance_km / _KM_PER_LNG) * math.sin(math.radians(bearing_deg))
    return (center_lng + lng_offset, center_lat + lat_offset)


class DroneAgent(mesa.Agent):
    """
    Command-driven rescue drone.

    Movement is ONLY triggered by explicit MCP tool calls:
      • mcp_move_to()          — sets self.target to (x, y)
      • mcp_recall_drone()     — sets self.target to base_pos

    The drone never picks its own target; it idles until ordered.
    """

    def __init__(self, model, base_pos: tuple, base_name: str,
                 role: "DroneRole" = None, formation_slot: str = None):
        super().__init__(model)
        self.base_pos  = base_pos
        self.base_name = base_name
        self.x, self.y = base_pos
        self.battery   = random.randint(70, 100)
        self.status    = DroneStatus.IDLE
        self.target    = None   # (x, y) set by MCP commands only
        self.rescued   = 0
        self.total_distance = 0
        self.scan_timer = 0
        self.path = []  # Stores the full A* path to current target

        # Formation swarm fields
        self.role = role or DroneRole.RESCUE
        self.formation_slot = formation_slot or "R1"
        self.arc_waypoints: list[tuple[float, float]] = []
        self.arc_waypoint_index: int = 0
        self.arc_heading_deg: float = 0.0  # Heading in degrees (0=East, 90=North)

        # Zone ring fields (OUTER → MIDDLE → INNER, outside-in strategy)
        self.zone_waypoints: dict = {"OUTER": [], "MIDDLE": [], "INNER": []}
        self.current_zone: str = "OUTER"
        self.zone_wp_idx: int = 0

        # Role-swap fields — set properly after formation_slot is assigned
        _slot = formation_slot or "R1"
        self.ring_role: str      = "OUTER" if _slot in ("R1", "R2", "R3") else "MIDDLE_INNER"
        self.display_color: str  = ""      # overrides dashboard ring colour when set
        self._swap_triggered: bool = False # prevents duplicate swaps per battery trip
        self._original_slot: str = _slot   # remembers slot before any swap
        self._replacement_dispatch_count: int = 0

        # For heading update: track previous position
        self._prev_x, self._prev_y = self.x, self.y

        # ── CV verification hold ──────────────────────────────────────────
        # Set by mcp_thermal_scan when it detects survivors. While True, the
        # drone refuses new move commands — it must stay put so the agent can
        # run mcp_cv_scan twice (double-confirm) before resuming the sweep.
        # Cleared by mcp_cv_scan once all contacts are confirmed AND the
        # minimum hold window has elapsed (so the UI CV animation has time
        # to play).
        self.cv_hold: bool = False
        self.cv_hold_until_tick: int = 0
        self.cv_hold_contact_count: int = 0

        # ── Malfunction fields ────────────────────────────────────────────────
        self.malfunction: bool = False
        self.malfunction_pause: int = 0   # ticks to freeze at fault site
        self.repair_timer: int = 0         # ticks remaining at base for repair

        # ── Earthquake zone fields ────────────────────────────────────────────
        self.quake_survey_ticks: int  = 0    # ticks remaining for seismic survey
        self.quake_converging:   bool = False # flying to quake zone center
        self.quake_returning:    bool = False # A* back to pre-quake position
        self.pre_quake_target: tuple | None = None  # position to return to after quake
        self.pre_quake_wps:   list        = []      # saved sector waypoints
        self.pre_quake_idx:   int         = 0       # saved waypoint index

    def _step_toward(self, tx: float, ty: float):
        """Move one step continuous vector toward (tx, ty) and deduct battery."""
        if self.battery <= 0:
            return

        remaining_step = SPEED_PER_TICK
        step_km = 0.0
        battery_used = 0.0
        
        while remaining_step > 0.001:
            if not getattr(self, "path", None):
                # Fallback vector line to final target
                wp_x, wp_y = tx, ty
                dist_km = haversine_distance(self.x, self.y, wp_x, wp_y)
                if dist_km < 0.001:
                    break   # Arrived at final destination vector
            else:
                wp_x, wp_y = self.path[0]
                dist_km = haversine_distance(self.x, self.y, wp_x, wp_y)
                if dist_km < 0.001:
                    self.path.pop(0)
                    continue
                
            if dist_km <= remaining_step:
                # Arrive at wp_x, wp_y
                step_km += dist_km
                battery_used += dist_km * BATTERY_DRAIN
                self.x, self.y = wp_x, wp_y
                remaining_step -= dist_km
                if getattr(self, "path", None):
                    self.path.pop(0)
            else:
                ratio = remaining_step / dist_km
                self.x += (wp_x - self.x) * ratio
                self.y += (wp_y - self.y) * ratio
                step_km += remaining_step
                battery_used += remaining_step * BATTERY_DRAIN
                remaining_step = 0
                
        # Clamp to bounds to prevent Mesa ContinuousSpace crash
        # Subtract 1e-6 because Mesa raises Exception if pos >= x_max
        self.x = max(GEO_BOUNDS["swLng"], min(GEO_BOUNDS["neLng"] - 1e-6, self.x))
        self.y = max(GEO_BOUNDS["swLat"], min(GEO_BOUNDS["neLat"] - 1e-6, self.y))
        
        # Update Mesa model location
        self.model.grid.move_agent(self, (self.x, self.y))
        
        # Deduct battery scaling to real distance. `BATTERY_DRAIN` is % per km.
        self.battery = max(0, self.battery - battery_used)
        
        self.total_distance += step_km
        self.model.metrics["total_distance"]     += step_km
        self.model.metrics["total_battery_used"] += battery_used

        # Update formation heading based on movement direction
        if hasattr(self, '_prev_x') and hasattr(self, '_prev_y'):
            dlng = self.x - self._prev_x
            dlat = self.y - self._prev_y
            if abs(dlng) > 1e-8 or abs(dlat) > 1e-8:
                self.arc_heading_deg = math.degrees(
                    math.atan2(dlat * _KM_PER_LAT, dlng * _KM_PER_LNG)
                ) % 360
        self._prev_x, self._prev_y = self.x, self.y

    def _scan_and_rescue(self) -> bool:
        """Mark survivors as detected within VISION_RADIUS (100m).
        Rescue is handled exclusively by mcp_thermal_scan to prevent hallucination."""
        degree_radius = VISION_RADIUS / 111.0
        neighbors = self.model.grid.get_neighbors(
            self.pos, include_center=True, radius=degree_radius
        )
        self.model.mapped_cells.add((self.x, self.y))

        found_survivors = False
        for agent in neighbors:
            if isinstance(agent, SurvivorAgent) and not agent.rescued:
                agent.detected = True
                found_survivors = True

        return found_survivors

    def step(self):
        # ── Malfunction: freeze → RTB via A* → repair at base → rejoin ──────
        if self.malfunction:
            if self.repair_timer > 0:
                # At base being repaired
                self.status = DroneStatus.REPAIRING
                self.repair_timer -= 1
                if self.repair_timer == 0:
                    self.malfunction = False
                    self.status = DroneStatus.IDLE
                    self._swap_triggered = False
                    # Steal waypoints to rejoin mission immediately
                    with _team_lock:
                        busiest = max(
                            _drone_sector_wps.keys(),
                            key=lambda d: len(_drone_sector_wps.get(d, [])) - _drone_sector_idx.get(d, 0),
                            default=None,
                        )
                        if busiest:
                            rem = len(_drone_sector_wps[busiest]) - _drone_sector_idx.get(busiest, 0)
                            if rem > 1:
                                half = rem // 2
                                my_id = f"drone_{self.unique_id}"
                                _drone_sector_wps[my_id] = _drone_sector_wps[busiest][-half:]
                                _drone_sector_idx[my_id] = 0
                                _drone_sector_wps[busiest] = _drone_sector_wps[busiest][:-half]
                    if _current_model:
                        _current_model.rescue_log.append({
                            "tick": _current_model.tick, "type": "repair_complete",
                            "msg": f"drone_{self.unique_id} REPAIR COMPLETE — rejoining sweep",
                            "drone": f"drone_{self.unique_id}",
                        })
                return

            # Pausing at malfunction site before RTB
            if self.malfunction_pause > 0:
                self.status = DroneStatus.MALFUNCTION
                self.malfunction_pause -= 1
                if self.malfunction_pause == 0:
                    # Start A* route back to base
                    route = _astar_route(self.x, self.y, self.base_pos[0], self.base_pos[1])
                    self.path = route if route else []
                    self.target = self.base_pos
                return

            # Travelling back to base (malfunction RTB)
            self.status = DroneStatus.MALFUNCTION
            dist_to_base = haversine_distance(self.x, self.y, self.base_pos[0], self.base_pos[1])
            if dist_to_base < 0.02:
                self.x, self.y = self.base_pos
                self.model.grid.move_agent(self, self.base_pos)
                self.path = []
                self.target = None
                self.repair_timer = 22  # ~7.7 s repair at base
            else:
                self._step_toward(*self.base_pos)
            return

        # ── Earthquake zone response (overrides normal AI commands) ─────────────
        # Phase 1: survey — frozen at quake zone, seismic scan animation
        if self.quake_survey_ticks > 0:
            self.status = DroneStatus.QUAKE_SURVEY
            self.quake_survey_ticks -= 1
            if self.quake_survey_ticks == 0:
                # Survey done — start A* return to pre-quake position
                self.quake_returning = True
                if self.pre_quake_target:
                    route = _astar_route(self.x, self.y,
                                         self.pre_quake_target[0], self.pre_quake_target[1])
                    self.path  = route if route else []
                    self.target = self.pre_quake_target
                else:
                    # No saved position — resume from base
                    route = _astar_route(self.x, self.y, self.base_pos[0], self.base_pos[1])
                    self.path  = route if route else []
                    self.target = self.base_pos
                if _current_model:
                    my_id = f"drone_{self.unique_id}"
                    _drone_sector_wps[my_id] = self.pre_quake_wps
                    _drone_sector_idx[my_id] = self.pre_quake_idx
            return

        # Phase 2: converging — A* flying toward quake zone center
        if self.quake_converging and _quake_zone_active:
            self.status = DroneStatus.QUAKE_SURVEY
            zone = _quake_zone_active
            dist = haversine_distance(self.x, self.y, zone["lng"], zone["lat"])
            if dist < 0.06:
                # Arrived — start survey
                self.x, self.y = zone["lng"], zone["lat"]
                self.model.grid.move_agent(self, (self.x, self.y))
                self.quake_converging  = False
                self.quake_survey_ticks = 20   # ≈7 s seismic survey
                self.path  = []
                self.target = None
            else:
                self._step_toward(zone["lng"], zone["lat"])
            return

        # Phase 3: returning — A* back to pre-quake position
        if self.quake_returning:
            self.status = DroneStatus.QUAKE_RTB
            if self.target:
                dist = haversine_distance(self.x, self.y, self.target[0], self.target[1])
                if dist < 0.03:
                    self.x, self.y = self.target
                    self.model.grid.move_agent(self, (self.x, self.y))
                    self.quake_returning = False
                    self.target = None
                    self.path   = []
                    self.status = DroneStatus.IDLE
                else:
                    self._step_toward(*self.target)
            else:
                self.quake_returning = False
                self.status = DroneStatus.IDLE
            return

        # ── Detect entering an earthquake zone (triggers collective response) ──
        if not _quake_responded and _quake_zones:
            for zone in _quake_zones:
                dist = haversine_distance(self.x, self.y, zone["lng"], zone["lat"])
                if dist < zone["radius_km"]:
                    _trigger_quake_response(self, zone)
                    return

        # ── Emergency: low battery → role-swap then return to base ──
        if self.battery <= LOW_BATTERY:
            # If this drone has unfinished waypoints, dispatch a replacement so
            # the mission can continue while it returns to base.
            if not self._swap_triggered:
                _dispatch_replacement(self)
            self.status = DroneStatus.LOW_BATT
            # Use haversine distance instead of exact float equality — the drone
            # may arrive within centimetres of base_pos but never exactly equal.
            dist_to_base = haversine_distance(self.x, self.y, self.base_pos[0], self.base_pos[1])
            if dist_to_base < 0.02:  # within 20 m → snap and start charging
                self.x, self.y = self.base_pos
                self.model.grid.move_agent(self, self.base_pos)
                self.status  = DroneStatus.CHARGING
                self.path = []
                self.battery = min(100, self.battery + CHARGE_RATE)
                if self.battery >= 80:
                    self.status = DroneStatus.IDLE
                    self.target = None
                    self._swap_triggered = False  # ready for next trip
            else:
                if getattr(self, "target", None) != self.base_pos:
                    self.target = self.base_pos
                    route = _astar_route(self.x, self.y, self.base_pos[0], self.base_pos[1])
                    self.path = route if route else []
                self._step_toward(*self.base_pos)
            return

        # ── Charging at base ──────────────────────────────────────
        if self.status == DroneStatus.CHARGING:
            self.battery = min(100, self.battery + CHARGE_RATE)
            if self.battery >= 80:
                self.status = DroneStatus.IDLE
                self._swap_triggered = False  # ready for next trip
                my_id = f"drone_{self.unique_id}"

                # REJOIN: steal half of the busiest teammate's remaining waypoints
                with _team_lock:
                    busiest = max(
                        _drone_sector_wps.keys(),
                        key=lambda d: len(_drone_sector_wps.get(d, [])) - _drone_sector_idx.get(d, 0),
                        default=None,
                    )
                    rejoined = False
                    if busiest and busiest != my_id:
                        rem = len(_drone_sector_wps[busiest]) - _drone_sector_idx.get(busiest, 0)
                        if rem > 1:
                            half = rem // 2
                            _drone_sector_wps[my_id] = _drone_sector_wps[busiest][-half:]
                            _drone_sector_idx[my_id] = 0
                            _drone_sector_wps[busiest] = _drone_sector_wps[busiest][:-half]
                            rejoined = True
                            print(f"[REJOIN] {my_id} charged. Pulled {half} wps from {busiest}.",
                                  file=sys.stderr, flush=True)

                    # Fallback: if nobody has waypoints left, assign from the current sector fresh
                    if not rejoined:
                        sector = TEAM_SECTORS[_current_team_sector] if not _team_sector_complete else None
                        if sector:
                            sector_data = _team_sector_all_wps.get(sector["id"], {})
                            all_wps: list = []
                            for v in sector_data.values():
                                all_wps.extend(v)
                            if all_wps:
                                _drone_sector_wps[my_id] = all_wps
                                _drone_sector_idx[my_id] = 0
                                rejoined = True
                                print(f"[REJOIN] {my_id} charged — no teammates to steal from; "
                                      f"assigned {len(all_wps)} wps from current sector.",
                                      file=sys.stderr, flush=True)

                    if not rejoined:
                        print(f"[REJOIN] {my_id} charged but no waypoints available — awaiting AI command.",
                              file=sys.stderr, flush=True)
            return

        # ── Scanning in progress ──────────────────────────────────
        if self.scan_timer > 0:
            self.scan_timer -= 1
            self._scan_and_rescue()
            if self.scan_timer == 0:
                self.status = DroneStatus.IDLE
            return

        # ── CV verification hold: freeze movement until cv_scan releases ──
        # Thermal scan sets cv_hold=True when it finds unrescued contacts so
        # the operator can run mcp_cv_scan twice to double-confirm. While held,
        # the drone must not move — even if a residual target is still set.
        if getattr(self, "cv_hold", False):
            self.path = []
            self.target = None
            self.status = DroneStatus.SCANNING
            return

        # ── Follow command agent orders only — no autonomous targeting ──
        if self.target is not None:
            tx, ty = self.target
            dist_to_target = haversine_distance(self.x, self.y, tx, ty)
            if dist_to_target < 0.02:  # within 20 m → arrived
                # Snap to exact target so base comparison works
                self.x, self.y = tx, ty
                self.model.grid.move_agent(self, (tx, ty))
                self.path = []
                # Arrived at commanded destination
                dist_to_base = haversine_distance(self.x, self.y, self.base_pos[0], self.base_pos[1])
                if dist_to_base < 0.02:  # at the central base → charge
                    self.status = DroneStatus.CHARGING
                    self.target = None
                else:
                    self.status = DroneStatus.SCANNING
                    self.scan_timer = 8   # 8 ticks ≈ 2.8 s scanning pause (faster CV animation)
                    self.target = None   # wait for next MCP command
            else:
                self.status = DroneStatus.MOVING
                if self.model.tick % 10 == 0:
                    print(f"[MOVE] drone_{self.unique_id}: ({self.x:.5f},{self.y:.5f}) → ({tx:.5f},{ty:.5f}), dist={dist_to_target:.3f}km, batt={self.battery:.0f}%", file=sys.stderr, flush=True)
                self._step_toward(tx, ty)
        else:
            self.status = DroneStatus.IDLE


# ─────────────────────────────────────────────────────────────
# 3. MODEL
# ─────────────────────────────────────────────────────────────

class MetroManilaRescueModel(mesa.Model):
    def __init__(
        self,
        num_survivors:  int = NUM_SURVIVORS,
        num_drones:     int = NUM_DRONES,
        disaster_cells: int = DISASTER_CELLS,
        rng:            int = 42,
    ):
        global _current_model
        super().__init__(rng=rng)
        random.seed(rng)   # fix Python random calls (disaster cells, survivors, battery)
        _current_model = self

        self.grid    = mesa.space.ContinuousSpace(x_max=GEO_BOUNDS["neLng"], y_max=GEO_BOUNDS["neLat"], torus=False, x_min=GEO_BOUNDS["swLng"], y_min=GEO_BOUNDS["swLat"])
        self.running = True
        self.tick    = 0

        self.metrics = {
            "rescued":            0,
            "total_survivors":    num_survivors,
            "total_distance":     0,
            "total_battery_used": 0,
        }
        self.rescue_log: list[dict] = []
        
        self.mapped_cells: set[tuple] = set()

        self.datacollector = mesa.DataCollector(
            model_reporters={
                "Rescued":   lambda m: m.metrics["rescued"],
                "Remaining": lambda m: m.metrics["total_survivors"] - m.metrics["rescued"],
            }
        )

        self.disaster_cells: set[tuple] = set()
        self._seed_disaster(disaster_cells)
        self._place_survivors(num_survivors)
        self._place_drones(num_drones)
        self._init_team_sectors()   # Pre-compute shared sector waypoint queue
        self._init_quake_zones()    # Compute earthquake zone centres (matches frontend)

    def _seed_disaster(self, n: int):
        """Mark n high-risk cells as flooded/disaster zones."""
        # With continuous space, "cells" are conceptual. We'll pick random points.
        # For now, we'll just pick random points within the bounds.
        # A more sophisticated approach would involve defining disaster polygons.
        for _ in range(n):
            x = random.uniform(GEO_BOUNDS["swLng"], GEO_BOUNDS["neLng"])
            y = random.uniform(GEO_BOUNDS["swLat"], GEO_BOUNDS["neLat"])
            self.disaster_cells.add((x, y))

    def _place_survivors(self, n: int):
        """Place survivors from the user-defined list, or randomly if none set."""
        if _custom_survivors is not None:
            print(f"[SIM] ✓ Placing {len(_custom_survivors)} custom survivor(s)...", file=sys.stderr, flush=True)
            for pd in _custom_survivors:
                x = float(pd["x"])
                y = float(pd["y"])
                district = "Metro Manila"
                agent = SurvivorAgent(self, district)
                agent.critical = bool(pd.get("critical", False))
                self.grid.place_agent(agent, (x, y))
            self.metrics["total_survivors"] = len(_custom_survivors)
            return

        # ── Random fallback (no user placement) ──────────────────────────────
        # Place survivors uniformly within the 2km scan circle around BASE_CENTER
        max_radius_km = 2.0
        placed = 0
        while placed < n:
            # Uniform sampling inside a circle: r = sqrt(rand) * max_r
            r_km  = math.sqrt(random.random()) * max_radius_km
            theta = random.random() * 2 * math.pi
            lng   = BASE_CENTER[0] + (r_km / _KM_PER_LNG) * math.cos(theta)
            lat   = BASE_CENTER[1] + (r_km / _KM_PER_LAT) * math.sin(theta)
            # Clamp to geo bounds just in case
            lng = max(GEO_BOUNDS["swLng"], min(GEO_BOUNDS["neLng"], lng))
            lat = max(GEO_BOUNDS["swLat"], min(GEO_BOUNDS["neLat"], lat))
            agent = SurvivorAgent(self, "Metro Manila")
            agent.critical = random.random() < 0.25  # 25% critical
            self.grid.place_agent(agent, (lng, lat))
            placed += 1

    def _assign_role(self, drone: "DroneAgent", idx: int, total: int):
        """Assign sweep sectors: all 5 drones are rescue drones. Command is handled externally at base."""
        slot_names = ["R1", "R2", "R3", "R4", "R5"]

        # 5 sectors matching dashboard map colors
        # NE=Red(0-90°), SE=Blue(90-180°), SW=Green(180-270°), NW=Yellow(270-360°), N=Magenta(-45-45°)
        rescue_regions = [
            {"direction": 45,  "angle_start": 0,   "angle_end": 90,  "name": "NE"},
            {"direction": 135, "angle_start": 90,  "angle_end": 180, "name": "SE"},
            {"direction": 225, "angle_start": 180, "angle_end": 270, "name": "SW"},
            {"direction": 315, "angle_start": 270, "angle_end": 360, "name": "NW"},
            {"direction": 0,   "angle_start": -45, "angle_end": 45,  "name": "N"},
        ]

        # All drones are rescue drones — the Command Agent runs at the base, not as a drone
        drone.role = DroneRole.RESCUE
        drone.formation_slot = slot_names[idx % 5]
        drone.ring_role = "OUTER" if drone.formation_slot in ("R1", "R2", "R3") else "MIDDLE_INNER"
        drone._original_slot = drone.formation_slot
        region = rescue_regions[idx % 5]
        angle_start = region["angle_start"]
        angle_end   = region["angle_end"]
        region_name = region["name"]

        sweep_waypoints = self._generate_sweep_waypoints(
            angle_start, angle_end, max_radius_km=2.0, arc_step_km=0.4, points_per_arc=6
        )
        drone.arc_waypoints = sweep_waypoints

        # Partition into 3 ring zones based on distance from base (outside-in)
        zone_wps: dict = {"OUTER": [], "MIDDLE": [], "INNER": []}
        for wp in sweep_waypoints:
            if wp == BASE_CENTER:
                continue
            dist = haversine_distance(BASE_CENTER[0], BASE_CENTER[1], wp[0], wp[1])
            if dist >= 1.3:
                zone_wps["OUTER"].append(wp)
            elif dist >= 0.6:
                zone_wps["MIDDLE"].append(wp)
            else:
                zone_wps["INNER"].append(wp)
        drone.zone_waypoints = zone_wps
        drone.current_zone = next((z for z in ("OUTER", "MIDDLE", "INNER") if zone_wps[z]), "OUTER")
        drone.zone_wp_idx = 0

        print(f"[SIM]   → RESCUE({drone.formation_slot}): {region_name} ({angle_start}°–{angle_end}°) "
              f"→ {len(zone_wps['OUTER'])} OUTER / {len(zone_wps['MIDDLE'])} MIDDLE / {len(zone_wps['INNER'])} INNER waypoints",
              file=sys.stderr, flush=True)

    def _generate_sweep_waypoints(self, angle_start: float, angle_end: float,
                                   max_radius_km: float = 2.0, arc_step_km: float = None,
                                   points_per_arc: int = None) -> list[tuple[float, float]]:
        """
        BOUSTROPHEDON COVERAGE PATH — same algorithm as robot vacuums.

        How a Roomba covers a room:
        1. Move in parallel lines spaced by brush width (= scan diameter)
        2. At the wall, turn 180° and sweep the next line in the opposite direction
        3. This back-and-forth pattern guarantees 100% floor coverage

        For a pie-slice sector, we adapt this:
        - "Lines" become concentric ARCS at increasing radius
        - Arc spacing = 0.7 × scan_radius (70% overlap for guaranteed coverage)
        - Points per arc = calculated from arc length ÷ scan_diameter
        - Direction alternates each arc (boustrophedon = "ox turning" in Greek)

        Coverage guarantee: every point in the sector is within scan_radius
        of at least one waypoint.
        """
        cx, cy = BASE_CENTER
        waypoints = []

        # ── Coverage spacing from scan parameters ──
        scan_radius = VISION_RADIUS                  # 1.0 km
        scan_diameter = scan_radius * 2               # 2.0 km
        # Arc-to-arc spacing: 70% of scan diameter ensures overlap
        step = arc_step_km or (scan_diameter * 0.35)  # ~0.7 km
        # Along-arc spacing: scan diameter (points overlap at edges)
        point_spacing_km = scan_diameter * 0.5        # 1.0 km

        # ── Generate concentric arcs from OUTER to INNER (outside-in) ──
        # Build arc radii list descending: max_radius_km down to step
        arc_radii = []
        r = max_radius_km
        while r >= step - 1e-9:
            arc_radii.append(round(r, 6))
            r -= step

        for arc_index, radius_km in enumerate(arc_radii):
            # Calculate arc length and number of points needed
            angle_span = abs(angle_end - angle_start)
            arc_length_km = radius_km * math.radians(angle_span)
            n_points = points_per_arc or max(3, int(arc_length_km / point_spacing_km) + 1)

            # Generate evenly spaced points along this arc
            arc_points = []
            for i in range(n_points):
                frac = i / max(n_points - 1, 1)
                angle_deg = angle_start + frac * (angle_end - angle_start)

                lng, lat = _offset_geo(cx, cy, angle_deg, radius_km)
                # Clamp within map bounds
                lng = max(GEO_BOUNDS["swLng"] + 1e-4, min(GEO_BOUNDS["neLng"] - 1e-4, lng))
                lat = max(GEO_BOUNDS["swLat"] + 1e-4, min(GEO_BOUNDS["neLat"] - 1e-4, lat))
                arc_points.append((lng, lat))

            # BOUSTROPHEDON: alternate direction each arc
            # Even arcs sweep left→right, odd arcs sweep right→left
            if arc_index % 2 == 1:
                arc_points.reverse()

            waypoints.extend(arc_points)

        # Final waypoint: return to base
        waypoints.append(BASE_CENTER)

        n_arcs = len(arc_radii)
        print(f"[SIM]     Coverage: {n_arcs} arcs × ~{n_points if n_arcs > 0 else 0} pts = {len(waypoints)-1} scan points + return (outside-in)", file=sys.stderr, flush=True)
        print(f"[SIM]     Spacing: arc_step={step:.2f}km, point_step={point_spacing_km:.2f}km, scan_r={scan_radius}km", file=sys.stderr, flush=True)
        return waypoints

    def _place_drones(self, n: int):
        """Place drones from user-defined positions, or distribute across base stations if none set."""
        print(f"[SIM] _place_drones() called: _custom_drones={'NONE' if _custom_drones is None else f'{len(_custom_drones)} items'}, n={n}", file=sys.stderr, flush=True)
        if _custom_drones is not None:
            print(f"[SIM] ✓ Placing {len(_custom_drones)} custom drone(s)...", file=sys.stderr, flush=True)
            # All drones share one central base — the first (and typically only)
            # user-placed base, or BASE_CENTER if none was configured.
            if BASE_STATIONS:
                central_name, central_pos = next(iter(BASE_STATIONS.items()))
            else:
                central_name, central_pos = "Central Base", BASE_CENTER
            for i, pd in enumerate(_custom_drones):
                spawn_x = float(pd["x"])
                spawn_y = float(pd["y"])
                # Create drone with the central base as its charging/return point
                drone = DroneAgent(self, central_pos, central_name)
                # Assign formation role
                self._assign_role(drone, i, len(_custom_drones))
                # Place it on the grid at custom spawn position
                self.grid.place_agent(drone, (spawn_x, spawn_y))
                drone.x = spawn_x
                drone.y = spawn_y
                drone.status = DroneStatus.IDLE
                drone.target = None
                print(f"[SIM]   ✓ Drone {i+1}: spawn=({spawn_x:.5f},{spawn_y:.5f}) base={central_name}@({central_pos[0]:.5f},{central_pos[1]:.5f}) slot={drone.formation_slot}", file=sys.stderr, flush=True)
            return

        # ── Random fallback: all drones start at and return to BASE_CENTER ──────
        print(f"[SIM] ✗ No custom drones; placing {n} drones at central base", file=sys.stderr, flush=True)
        central_name = "Central Base"
        central_pos  = BASE_CENTER
        for i in range(n):
            drone = DroneAgent(self, central_pos, central_name)
            self._assign_role(drone, i, n)
            self.grid.place_agent(drone, central_pos)
            drone.status = DroneStatus.IDLE
            drone.target = None
            print(f"[SIM]   ✗ Default drone {i+1}: pos={central_pos} base={central_name} slot={drone.formation_slot}", file=sys.stderr, flush=True)

    def _init_team_sectors(self):
        """Pre-compute sweep waypoints for every team sector.
        S1, S3, S5 → 3-2 concentric arc sweep (OUTER/MIDDLE/INNER ring distribution)
        S2, S4     → fan-spread (each drone gets its own angular corridor FAN_0…FAN_4)
        """
        global _team_sector_all_wps, _current_team_sector, _team_sector_complete
        _team_sector_all_wps = {}

        for sector in TEAM_SECTORS:
            sweep = sector.get("sweep", "arc")

            if sweep == "fan":
                # Fan spread: pre-slice into 5 individual drone corridors
                print(f"[SIM] TeamSector {sector['name']} → FAN SPREAD generation…",
                      file=sys.stderr, flush=True)
                fan_data = _generate_fan_sweep_per_drone(
                    sector["angle_start"], sector["angle_end"],
                    n_drones=5, max_radius_km=2.0,
                )
                _team_sector_all_wps[sector["id"]] = fan_data
                total = sum(len(v) for v in fan_data.values())
                print(f"[SIM] TeamSector {sector['name']} (FAN): {total} total wps across 5 corridors",
                      file=sys.stderr, flush=True)
            else:
                # 3-2 arc sweep: tighter spacing guarantees OUTER+MIDDLE always populated
                raw_wps = self._generate_sweep_waypoints(
                    sector["angle_start"], sector["angle_end"],
                    max_radius_km=2.0,
                    arc_step_km=0.18,    # 180 m between arcs → denser coverage
                    points_per_arc=10,   # more points per arc → smoother sweep
                )
                rings: dict[str, list] = {"OUTER": [], "MIDDLE": [], "INNER": []}
                for wp in raw_wps:
                    if wp == BASE_CENTER:
                        continue
                    dist = haversine_distance(BASE_CENTER[0], BASE_CENTER[1], wp[0], wp[1])
                    # OUTER ≥ 1.1 km, MIDDLE 0.5–1.1 km, INNER < 0.5 km
                    # (lowered thresholds so both rings are always non-empty)
                    ring = "OUTER" if dist >= 1.1 else ("MIDDLE" if dist >= 0.5 else "INNER")
                    rings[ring].append((wp[0], wp[1], ring))
                # Safety: if OUTER or MIDDLE empty, redistribute from INNER
                for need, donor in [("OUTER", "MIDDLE"), ("MIDDLE", "INNER"),
                                    ("OUTER", "INNER")]:
                    if not rings[need] and rings[donor]:
                        half = len(rings[donor]) // 2
                        rings[need] = rings[donor][:half]
                        rings[donor] = rings[donor][half:]
                _team_sector_all_wps[sector["id"]] = rings
                n_o, n_m, n_i = len(rings["OUTER"]), len(rings["MIDDLE"]), len(rings["INNER"])
                print(f"[SIM] TeamSector {sector['name']} (ARC): {n_o+n_m+n_i} wps "
                      f"({n_o} OUTER / {n_m} MIDDLE / {n_i} INNER)", file=sys.stderr, flush=True)

        _current_team_sector = 0
        _team_sector_complete = False
        _load_sector_for_drones(TEAM_SECTORS[0]["id"])
        first = TEAM_SECTORS[0]
        print(f"[SIM] Team sectors ready — starting with {first['name']} "
              f"({first.get('sweep','arc').upper()} sweep)", file=sys.stderr, flush=True)

    def _init_quake_zones(self) -> None:
        """Compute earthquake zone GPS centres, matching the frontend QUAKE_ZONES."""
        global _quake_zones, _quake_responded, _quake_zone_active
        _quake_zones       = []
        _quake_responded   = False
        _quake_zone_active = None
        for bearing in _QUAKE_ZONE_BEARINGS:
            lng, lat = _offset_geo(BASE_CENTER[0], BASE_CENTER[1],
                                   bearing, _QUAKE_ZONE_DIST_KM)
            _quake_zones.append({"lng": lng, "lat": lat,
                                  "radius_km": _QUAKE_ZONE_RADIUS_KM})
        print(f"[SIM] Quake zones: {[(round(z['lng'],4), round(z['lat'],4)) for z in _quake_zones]}",
              file=sys.stderr, flush=True)

    def step(self):
        self.tick += 1
        self.agents.shuffle_do("step")
        self.datacollector.collect(self)

        # DEBUG: Log drone positions every 20 ticks
        if self.tick % 20 == 0:
            drone_info = []
            for a in self.agents:
                if isinstance(a, DroneAgent):
                    drone_info.append(f"drone_{a.unique_id}:({a.x},{a.y})[{a.status.value}]target={a.target}")
            if drone_info:
                print(f"[TICK {self.tick}] " + " ".join(drone_info), file=sys.stderr, flush=True)

        if self.metrics["rescued"] >= self.metrics["total_survivors"]:
            self.running = False
        # Malfunction is triggered by mcp_thermal_scan on the 10th cumulative scan, not here.


def _trigger_quake_response(detecting_drone: "DroneAgent", zone: dict) -> None:
    """
    Called when detecting_drone enters an earthquake zone.
    1. Stops the detecting drone for seismic survey.
    2. Commands every other active drone to converge via A*.
    3. After survey each drone returns to its pre-quake position via A*.
    """
    global _quake_responded, _quake_zone_active
    _quake_responded  = True
    _quake_zone_active = zone

    my_id = f"drone_{detecting_drone.unique_id}"

    # Save state & start survey for detecting drone
    detecting_drone.pre_quake_target  = (detecting_drone.x, detecting_drone.y)
    detecting_drone.pre_quake_wps     = list(_drone_sector_wps.get(my_id, []))
    detecting_drone.pre_quake_idx     = _drone_sector_idx.get(my_id, 0)
    detecting_drone.quake_survey_ticks = 25   # ≈8.75 s
    detecting_drone.path   = []
    detecting_drone.target = None
    detecting_drone.cv_hold = False
    detecting_drone.scan_timer = 0

    if _current_model:
        _current_model.rescue_log.append({
            "tick":  _current_model.tick,
            "type":  "quake_detected",
            "msg":   f"drone_{detecting_drone.unique_id} ENTERED EARTHQUAKE ZONE — all drones converging",
            "drone": f"drone_{detecting_drone.unique_id}",
        })
        # Command every other non-faulted drone to converge
        for agent in _current_model.agents:
            if not isinstance(agent, DroneAgent) or agent is detecting_drone:
                continue
            if agent.malfunction or agent.repair_timer > 0:
                continue
            did = f"drone_{agent.unique_id}"
            agent.pre_quake_target  = (agent.x, agent.y)
            agent.pre_quake_wps     = list(_drone_sector_wps.get(did, []))
            agent.pre_quake_idx     = _drone_sector_idx.get(did, 0)
            agent.quake_converging  = True
            agent.quake_survey_ticks = 0
            agent.quake_returning   = False
            agent.cv_hold  = False
            agent.scan_timer = 0
            agent.path = []
            agent.target = None
            # A* route to quake zone center (movement handled in step())
            route = _astar_route(agent.x, agent.y, zone["lng"], zone["lat"])
            agent.path   = route if route else []
            agent.target = (zone["lng"], zone["lat"])

    print(f"[SIM] 🌍 QUAKE ZONE triggered by drone_{detecting_drone.unique_id} "
          f"at ({zone['lng']:.4f},{zone['lat']:.4f})", file=sys.stderr, flush=True)


# ─────────────────────────────────────────────────────────────
# 4. MCP TOOL FUNCTIONS
#    Called by mcp_server.py to expose tools to the AI agent.
#    All read/write via the _current_model global.
# ─────────────────────────────────────────────────────────────

def _do_role_swap(retiring_drone: "DroneAgent") -> None:
    """
    Called when an OUTER drone (R1/R2/R3) drops below LOW_BATTERY.

    Mechanics:
      1. Find the best available MIDDLE_INNER drone to promote.
      2. Transfer the retiring drone's remaining sector waypoints to the replacement.
      3. Promote the replacement to OUTER ring (slot, ring_role, display_color).
      4. Demote the retiring drone to MIDDLE_INNER — it will take the inner role
         after it returns to base and recharges.
    """
    if _current_model is None:
        return

    retiring_id = f"drone_{retiring_drone.unique_id}"

    # Find a replacement: active MIDDLE_INNER drone not already heading to base
    candidates = [
        a for a in _current_model.agents
        if isinstance(a, DroneAgent)
        and a.ring_role == "MIDDLE_INNER"
        and a.status not in (DroneStatus.CHARGING, DroneStatus.LOW_BATT)
        and a.unique_id != retiring_drone.unique_id
    ]
    if not candidates:
        # No one to swap with — just return to base silently
        return

    # Pick the drone with the most remaining sector waypoints (highest coverage utility)
    def _remaining(d):
        did = f"drone_{d.unique_id}"
        return len(_drone_sector_wps.get(did, [])) - _drone_sector_idx.get(did, 0)

    replacement = max(candidates, key=_remaining)
    replacement_id = f"drone_{replacement.unique_id}"

    with _team_lock:
        # Handoff: transfer retiring drone's remaining waypoints to the front of replacement's queue
        ret_wps = _drone_sector_wps.get(retiring_id, [])
        ret_idx = _drone_sector_idx.get(retiring_id, 0)
        handoff = ret_wps[ret_idx:]

        if handoff:
            repl_wps  = _drone_sector_wps.get(replacement_id, [])
            repl_idx  = _drone_sector_idx.get(replacement_id, 0)
            repl_tail = repl_wps[repl_idx:]
            _drone_sector_wps[replacement_id] = handoff + repl_tail
            _drone_sector_idx[replacement_id] = 0

        # Clear the retiring drone's queue — it no longer holds outer waypoints
        _drone_sector_wps[retiring_id] = []
        _drone_sector_idx[retiring_id] = 0

    # Swap formation slots so replacement is recognised as OUTER in _load_sector_for_drones
    old_replacement_slot = replacement.formation_slot
    replacement.formation_slot = retiring_drone._original_slot
    replacement.ring_role      = "OUTER"
    replacement.display_color  = "#FFD700"   # gold = promoted to outer

    # Retiring drone demoted to inner after recharge
    retiring_drone.formation_slot = old_replacement_slot
    retiring_drone.ring_role      = "MIDDLE_INNER"
    retiring_drone.display_color  = "#00BFFF"  # blue = reassigned to inner
    retiring_drone._swap_triggered = True

    print(
        f"[SWAP] {retiring_id} battery={retiring_drone.battery:.0f}% — heading to base. "
        f"{replacement_id} promoted to OUTER ({len(handoff)} wps handed off). "
        f"After recharge {retiring_id} becomes INNER.",
        file=sys.stderr, flush=True,
    )
    if _current_model:
        _current_model.rescue_log.append({
            "tick":  _current_model.tick,
            "type":  "role_swap",
            "msg":   f"{retiring_id} recalled → {replacement_id} now OUTER ring ({len(handoff)} wps)",
            "drone": retiring_id,
        })


def _dispatch_replacement(retiring_drone: "DroneAgent") -> None:
    """
    Replacement dispatch for low-battery drones.

    When a drone hits LOW_BATTERY, it returns to base and hands off any
    remaining assigned waypoints to the best available teammate so coverage
    continues without waiting for recharge.
    """
    if _current_model is None:
        return

    # Keep existing OUTER promotion behavior for tactical ring continuity.
    if retiring_drone.ring_role == "OUTER":
        _do_role_swap(retiring_drone)
        return

    retiring_id = f"drone_{retiring_drone.unique_id}"
    with _team_lock:
        retiring_queue = _drone_sector_wps.get(retiring_id, [])
        retiring_idx = _drone_sector_idx.get(retiring_id, 0)
        handoff = retiring_queue[retiring_idx:]
        if not handoff:
            retiring_drone._swap_triggered = True
            return

        candidates = [
            a for a in _current_model.agents
            if isinstance(a, DroneAgent)
            and a.unique_id != retiring_drone.unique_id
            and a.status not in (DroneStatus.CHARGING, DroneStatus.LOW_BATT)
            and a.battery > LOW_BATTERY
        ]
        if not candidates:
            retiring_drone._swap_triggered = True
            return

        def _candidate_score(d: "DroneAgent"):
            did = f"drone_{d.unique_id}"
            remaining = len(_drone_sector_wps.get(did, [])) - _drone_sector_idx.get(did, 0)
            return (d.battery, -remaining)

        replacement = max(candidates, key=_candidate_score)
        replacement_id = f"drone_{replacement.unique_id}"

        repl_wps = _drone_sector_wps.get(replacement_id, [])
        repl_idx = _drone_sector_idx.get(replacement_id, 0)
        repl_tail = repl_wps[repl_idx:]

        _drone_sector_wps[replacement_id] = handoff + repl_tail
        _drone_sector_idx[replacement_id] = 0
        _drone_sector_wps[retiring_id] = []
        _drone_sector_idx[retiring_id] = 0

    retiring_drone._swap_triggered = True
    replacement.display_color = replacement.display_color or "#B388FF"  # standby replacement highlight
    replacement._replacement_dispatch_count += 1

    print(
        f"[REPLACE] {retiring_id} low battery ({retiring_drone.battery:.0f}%) → returning base. "
        f"{replacement_id} received {len(handoff)} waypoint(s) as replacement unit.",
        file=sys.stderr, flush=True,
    )
    if _current_model:
        _current_model.rescue_log.append({
            "tick": _current_model.tick,
            "type": "replacement_dispatch",
            "msg": (
                f"{retiring_id} returning to base (low battery) — "
                f"{replacement_id} dispatched with {len(handoff)} handed-off waypoint(s)"
            ),
            "drone": retiring_id,
        })


def _generate_fan_sweep_per_drone(angle_start: float, angle_end: float,
                                   n_drones: int = 5,
                                   max_radius_km: float = 2.0,
                                   min_radius_km: float = 0.15) -> dict:
    """
    Fan-spread pattern: divide the sector's angular span into n_drones equal corridors.
    Each drone sweeps every radius level within its own narrow angular corridor (boustrophedon).
    Returns {"FAN_0": [(lng,lat,ring),...], ..., "FAN_4": [...]}.

    Visual effect: drones fan outward from base like fingers, each covering a radial strip.
    """
    cx, cy = BASE_CENTER
    angle_span = angle_end - angle_start
    sub_span = angle_span / n_drones
    arc_step = VISION_RADIUS * 1.4  # spacing between concentric arcs (~140 m)

    result = {}
    for d_idx in range(n_drones):
        sub_start = angle_start + d_idx * sub_span
        sub_end   = sub_start + sub_span

        waypoints: list[tuple[float, float]] = []
        r = max_radius_km
        arc_idx = 0
        while r >= min_radius_km - 1e-9:
            arc_len_km = r * math.radians(sub_span)
            n_pts = max(2, int(arc_len_km / (VISION_RADIUS * 2.0)) + 1)
            arc_pts = []
            for i in range(n_pts):
                frac = i / max(n_pts - 1, 1)
                angle_deg = sub_start + frac * sub_span
                lng, lat = _offset_geo(cx, cy, angle_deg, r)
                lng = max(GEO_BOUNDS["swLng"] + 1e-4, min(GEO_BOUNDS["neLng"] - 1e-4, lng))
                lat = max(GEO_BOUNDS["swLat"] + 1e-4, min(GEO_BOUNDS["neLat"] - 1e-4, lat))
                arc_pts.append((lng, lat))
            if arc_idx % 2 == 1:
                arc_pts.reverse()  # boustrophedon: alternate direction each ring
            waypoints.extend(arc_pts)
            r -= arc_step
            arc_idx += 1

        tagged: list[tuple[float, float, str]] = []
        for lng, lat in waypoints:
            dist = haversine_distance(cx, cy, lng, lat)
            ring = "OUTER" if dist >= 1.3 else ("MIDDLE" if dist >= 0.6 else "INNER")
            tagged.append((lng, lat, ring))

        result[f"FAN_{d_idx}"] = tagged
        print(f"[SIM]   Fan-{d_idx}: {sub_start:.0f}°–{sub_end:.0f}° → {len(tagged)} wps",
              file=sys.stderr, flush=True)

    return result


def _load_sector_for_drones(sector_id: str):
    """
    Pre-assign waypoints for the given sector to each drone's personal queue.

    Arc sectors (S1, S3, S5) — 3-2 ring formation:
      R1, R2, R3 → OUTER ring waypoints (interleaved round-robin)
      R4, R5     → MIDDLE ring waypoints (interleaved round-robin)
      INNER      → all 5 drones (round-robin)

    Fan sectors (S2, S4) — 5 individual corridors:
      Each drone gets its own pre-sliced angular corridor (FAN_0 … FAN_4).
    """
    global _drone_sector_wps, _drone_sector_idx

    sector_data = _team_sector_all_wps.get(sector_id, {})

    if _current_model is None:
        return

    drones = [a for a in _current_model.agents if isinstance(a, DroneAgent)]
    drones.sort(key=lambda d: d.unique_id)

    # Reset per-drone queues
    _drone_sector_wps = {f"drone_{d.unique_id}": [] for d in drones}
    _drone_sector_idx = {f"drone_{d.unique_id}": 0  for d in drones}

    # ── Fan spread (S2, S4): each drone owns a personal angular corridor ─────────
    if "FAN_0" in sector_data:
        for idx, d in enumerate(drones):
            did = f"drone_{d.unique_id}"
            fan_key = f"FAN_{idx % 5}"
            _drone_sector_wps[did] = list(sector_data.get(fan_key, []))
            print(f"[SIM] {sector_id} FAN {did}({d.formation_slot}): "
                  f"{len(_drone_sector_wps[did])} wps in corridor {idx}",
                  file=sys.stderr, flush=True)
        return

    # ── 3-2 arc ring (S1, S3, S5): ring-based distribution ──────────────────────
    outer_wps  = sector_data.get("OUTER", [])
    middle_wps = sector_data.get("MIDDLE", [])
    inner_wps  = sector_data.get("INNER", [])

    outer_drones  = [d for d in drones if d.formation_slot in ("R1", "R2", "R3")]
    middle_drones = [d for d in drones if d.formation_slot in ("R4", "R5")]

    for i, wp in enumerate(outer_wps):
        if outer_drones:
            did = f"drone_{outer_drones[i % len(outer_drones)].unique_id}"
            _drone_sector_wps[did].append(wp)

    for i, wp in enumerate(middle_wps):
        if middle_drones:
            did = f"drone_{middle_drones[i % len(middle_drones)].unique_id}"
            _drone_sector_wps[did].append(wp)

    for i, wp in enumerate(inner_wps):
        did = f"drone_{drones[i % len(drones)].unique_id}"
        _drone_sector_wps[did].append(wp)

    for d in drones:
        did = f"drone_{d.unique_id}"
        wps = _drone_sector_wps[did]
        rings_list = [w[2] for w in wps]
        print(f"[SIM] {sector_id} ARC {did}({d.formation_slot}): {len(wps)} wps "
              f"[{','.join(rings_list[:6])}{'…' if len(wps) > 6 else ''}]",
              file=sys.stderr, flush=True)


def _find_drone(drone_id: str) -> DroneAgent | None:
    """Return the DroneAgent matching drone_id (e.g. 'drone_3'), or None."""
    if _current_model is None:
        return None
    for agent in _current_model.agents:
        if isinstance(agent, DroneAgent) and f"drone_{agent.unique_id}" == drone_id:
            return agent
    return None


def mcp_get_active_drones() -> list[str]:
    """Return IDs of all active drones. Always call this first — never hardcode IDs."""
    if _current_model is None:
        return []
    drones = [f"drone_{a.unique_id}" for a in _current_model.agents if isinstance(a, DroneAgent)]
    if not drones:
        print(f"[MCP] WARNING: get_active_drones() returned 0 drones. Model exists but fleet is empty!", file=sys.stderr, flush=True)
    return drones


def mcp_get_battery_status(drone_id: str) -> dict:
    """Return battery level and a low-battery warning if applicable."""
    drone = _find_drone(drone_id)
    if drone is None:
        return {"error": f"Drone {drone_id} not found"}
    return {
        "drone_id": drone_id,
        "battery":  drone.battery,
        "status":   drone.status.value,
        "warning":  "LOW BATTERY — RECALL IMMEDIATELY" if drone.battery <= LOW_BATTERY else None,
    }


# Minimum battery % that must remain on arrival at base (safety margin)
BATT_SAFE_RESERVE = 15


def mcp_battery_plan(drone_id: str, next_wp_x: float, next_wp_y: float) -> dict:
    """
    Battery management algorithm.

    Given the drone's current position and the next target waypoint, calculates:
      • Cost to fly to the waypoint (BATTERY_DRAIN % per km)
      • Cost to fly from the waypoint back to base
      • Battery remaining after full round-trip
      • Maximum flyable range from current position
      • RECOMMENDATION: CONTINUE | RETURN_AFTER_WP | RETURN_NOW

    Rule set:
      battery_after_wp     = current - cost_to_wp
      battery_after_return = battery_after_wp - cost_wp_to_base
      CONTINUE        → battery_after_return >= BATT_SAFE_RESERVE   (can do WP + return safely)
      RETURN_AFTER_WP → can_reach_wp  AND  battery_after_return < BATT_SAFE_RESERVE
      RETURN_NOW      → battery_after_wp < BATT_SAFE_RESERVE         (not enough to even reach WP safely)
    """
    drone = _find_drone(drone_id)
    if drone is None:
        return {"error": f"Drone {drone_id} not found"}

    current_battery = drone.battery
    curr_x, curr_y  = drone.x, drone.y
    base_x, base_y  = drone.base_pos  # use drone's actual home base, not hardcoded BASE_CENTER

    # Distances (km)
    dist_to_wp       = haversine_distance(curr_x, curr_y, next_wp_x, next_wp_y)
    dist_wp_to_base  = haversine_distance(next_wp_x, next_wp_y, base_x, base_y)
    dist_curr_to_base= haversine_distance(curr_x, curr_y, base_x, base_y)

    # Battery costs (%)
    cost_to_wp       = dist_to_wp      * BATTERY_DRAIN
    cost_wp_to_base  = dist_wp_to_base * BATTERY_DRAIN
    cost_to_base_now = dist_curr_to_base * BATTERY_DRAIN

    # Post-action battery levels
    battery_after_wp     = current_battery - cost_to_wp
    battery_after_return = battery_after_wp - cost_wp_to_base

    # Range: how far can we fly before hitting the reserve floor
    max_range_km = max(0.0, (current_battery - BATT_SAFE_RESERVE) / BATTERY_DRAIN)

    can_reach_wp     = battery_after_wp     >= BATT_SAFE_RESERVE
    can_return_safely= battery_after_return >= BATT_SAFE_RESERVE

    if can_reach_wp and can_return_safely:
        recommendation = "CONTINUE"
        reason = (
            f"Battery sufficient for full round-trip. "
            f"After WP: ~{battery_after_wp:.1f}% | After return: ~{battery_after_return:.1f}% "
            f"(reserve floor: {BATT_SAFE_RESERVE}%)."
        )
    elif can_reach_wp and not can_return_safely:
        recommendation = "RETURN_AFTER_WP"
        reason = (
            f"Can reach waypoint ({battery_after_wp:.1f}% remaining) but return trip costs "
            f"{cost_wp_to_base:.1f}% — would arrive at base with only {battery_after_return:.1f}% "
            f"(below {BATT_SAFE_RESERVE}% reserve). Complete WP scan then return."
        )
    else:
        recommendation = "RETURN_NOW"
        reason = (
            f"Insufficient battery for waypoint trip. Cost to WP: {cost_to_wp:.1f}%, "
            f"available: {current_battery:.1f}%. Return cost from here: {cost_to_base_now:.1f}%. "
            f"Returning to base immediately."
        )

    return {
        "drone_id":              drone_id,
        "current_battery_pct":  round(current_battery, 1),
        "current_pos":          {"lng": round(curr_x, 5), "lat": round(curr_y, 5)},
        "next_wp":              {"lng": round(next_wp_x, 5), "lat": round(next_wp_y, 5)},
        "base_pos":             {"lng": round(base_x, 5), "lat": round(base_y, 5)},
        "dist_to_wp_km":        round(dist_to_wp, 3),
        "dist_wp_to_base_km":   round(dist_wp_to_base, 3),
        "dist_to_base_km":      round(dist_curr_to_base, 3),
        "cost_to_wp_pct":       round(cost_to_wp, 2),
        "cost_wp_to_base_pct":  round(cost_wp_to_base, 2),
        "cost_to_base_now_pct": round(cost_to_base_now, 2),
        "battery_after_wp_pct":     round(battery_after_wp, 1),
        "battery_after_return_pct": round(battery_after_return, 1),
        "max_range_km":         round(max_range_km, 2),
        "safe_reserve_pct":     BATT_SAFE_RESERVE,
        "can_reach_wp":         can_reach_wp,
        "can_return_safely":    can_return_safely,
        "recommendation":       recommendation,
        "reason":               reason,
        "drain_rate_pct_per_km": BATTERY_DRAIN,
    }


def mcp_get_drone_info(drone_id: str) -> dict:
    """Return full drone state: position, battery, base, target, survivors rescued."""
    drone = _find_drone(drone_id)
    if drone is None:
        return {"error": f"Drone {drone_id} not found"}
    return {
        "drone_id":              drone_id,
        "position":              {"x": drone.x, "y": drone.y},
        "battery":               drone.battery,
        "status":                drone.status.value,
        "base_name":             drone.base_name,
        "base_position":         {"x": drone.base_pos[0], "y": drone.base_pos[1]},
        "survivors_rescued":     drone.rescued,
        "target":                {"x": drone.target[0], "y": drone.target[1]} if drone.target else None,
        "estimated_range_cells": max(0, (drone.battery - LOW_BATTERY) // BATTERY_DRAIN),
        "cv_hold":               bool(getattr(drone, "cv_hold", False)),
        "cv_hold_until_tick":    int(getattr(drone, "cv_hold_until_tick", 0)),
        "cv_hold_contacts":      int(getattr(drone, "cv_hold_contact_count", 0)),
    }


def mcp_get_all_drones_status() -> list[dict]:
    """Return status of every drone at once for fleet-wide situational awareness."""
    if _current_model is None:
        return []
    result = [
        mcp_get_drone_info(f"drone_{a.unique_id}")
        for a in _current_model.agents
        if isinstance(a, DroneAgent)
    ]
    print(f"[DEBUG] Fleet size: {len(result)} drones", file=sys.stderr, flush=True)
    if result:
        print(f"[DEBUG] Fleet status: {[(d['drone_id'], d['status'], d['position']) for d in result]}", file=sys.stderr, flush=True)
    else:
        print(f"[DEBUG] NO DRONES IN FLEET!", file=sys.stderr, flush=True)
    return result


def mcp_move_to(drone_id: str, x: float, y: float) -> str:
    """Order a drone to navigate to (x, y). Refuses if battery is critically low."""
    drone = _find_drone(drone_id)
    if drone is None:
        return f"ERROR: Drone {drone_id} not found."
    if drone.battery <= LOW_BATTERY:
        return (
            f"REFUSED: {drone_id} battery is {drone.battery}% — below {LOW_BATTERY}% threshold. "
            f"Call recall_drone_to_base('{drone_id}') first."
        )
    if getattr(drone, "cv_hold", False):
        remaining = max(0, drone.cv_hold_until_tick - (_current_model.tick if _current_model else 0))
        return (
            f"REFUSED: {drone_id} is CV_HOLD — thermal scan detected "
            f"{drone.cv_hold_contact_count} unrescued contact(s) at current position. "
            f"Call mcp_cv_scan('{drone_id}') twice to double-confirm HUMAN before moving. "
            f"(min hold: {remaining} more tick(s))"
        )
    x = max(GEO_BOUNDS["swLng"], min(GEO_BOUNDS["neLng"], float(x)))
    y = max(GEO_BOUNDS["swLat"], min(GEO_BOUNDS["neLat"], float(y)))
    drone.target = (x, y)
    route = _get_osrm_route(drone.x, drone.y, x, y)
    drone.path = route if route else []
    dist_km = haversine_distance(drone.x, drone.y, x, y)
    cost = dist_km * BATTERY_DRAIN
    print(f"[COMMAND] {drone_id}: target set to ({x:.4f},{y:.4f}), current=({drone.x:.4f},{drone.y:.4f}), dist={dist_km:.2f}km, cost={cost:.1f}%", file=sys.stderr, flush=True)
    if _current_model:
        _current_model.rescue_log.append({
            "tick":     _current_model.tick,
            "type":     "mcp_cmd",
            "msg":      f"{drone_id} executing mcp_move_to({x:.4f}, {y:.4f})",
            "drone":    drone_id
        })
    return (
        f"OK: {drone_id} heading to ({x:.4f},{y:.4f}). "
        f"Current pos: ({drone.x:.4f},{drone.y:.4f}). "
        f"Distance: {dist_km:.2f} km. "
        f"Est. battery cost: ~{cost:.1f}%. "
        f"Current battery: {drone.battery:.1f}%. "
        f"Battery after arrival: ~{max(0, drone.battery - cost):.1f}%."
    )

def mcp_override_drone_target(drone_id: str, x: float, y: float) -> str:
    """CENTRAL COMMAND ONLY: Force a drone to abandon its current path and route to new coordinates."""
    drone = _find_drone(drone_id)
    if drone is None:
        return f"ERROR: Drone {drone_id} not found."
    if getattr(drone, "cv_hold", False):
        remaining = max(0, drone.cv_hold_until_tick - (_current_model.tick if _current_model else 0))
        return (
            f"REFUSED: {drone_id} is CV_HOLD — must finish double-confirm first "
            f"({drone.cv_hold_contact_count} contact(s), {remaining} tick(s) left). "
            f"Use recall_drone_to_base for battery emergencies only."
        )

    x = max(GEO_BOUNDS["swLng"], min(GEO_BOUNDS["neLng"], float(x)))
    y = max(GEO_BOUNDS["swLat"], min(GEO_BOUNDS["neLat"], float(y)))
    
    drone.target = (x, y)
    route = _get_osrm_route(drone.x, drone.y, x, y)
    drone.path = route if route else []
    dist_km = haversine_distance(drone.x, drone.y, x, y)
    
    if _current_model:
        _current_model.rescue_log.append({
            "tick":     _current_model.tick,
            "type":     "emergency_override",
            "msg":      f"CENTRAL COMMAND: {drone_id} redirected to ({x:.4f}, {y:.4f})",
            "drone":    drone_id
        })
        
    return f"OVERRIDE SUCCESS: {drone_id} forced to ({x:.4f}, {y:.4f}). Distance: {dist_km:.2f}km."

def mcp_recall_drone(drone_id: str) -> str:
    """Immediately return a drone to its home base for charging."""
    drone = _find_drone(drone_id)
    if drone is None:
        return f"ERROR: Drone {drone_id} not found."
    bx, by = drone.base_pos
    drone.target = (bx, by)
    route = _astar_route(drone.x, drone.y, bx, by)
    drone.path = route if route else []
    dist_km = haversine_distance(drone.x, drone.y, bx, by)
    
    if _current_model:
        _current_model.rescue_log.append({
            "tick":     _current_model.tick,
            "type":     "mcp_cmd",
            "msg":      f"{drone_id} executing mcp_recall_drone({bx:.4f}, {by:.4f})",
            "drone":    drone_id
        })
        
    return (
        f"RECALL: {drone_id} returning to {drone.base_name} at ({bx:.4f},{by:.4f}). "
        f"Distance: {dist_km:.2f} km. Battery: {drone.battery:.1f}%."
    )

RESCUE_RADIUS_KM = VISION_RADIUS  # match scan radius — all detected survivors are rescued

def mcp_thermal_scan(drone_id: str) -> dict:
    """
    Thermal scan within VISION_RADIUS (100m blue circle).
    Detected survivors get rescued after CV double-confirm (mcp_cv_scan × 2).
    Malfunction triggers on the 10th cumulative thermal scan across all drones.
    """
    global _thermal_scan_count, _malfunction_triggered
    drone = _find_drone(drone_id)
    if drone is None:
        return {"error": f"Drone {drone_id} not found"}

    detected   = []
    rescued_now = []

    # Count every scan — malfunction fires on the 10th
    _thermal_scan_count += 1
    if not _malfunction_triggered and _thermal_scan_count >= 10:
        candidates = [
            a for a in (_current_model.agents if _current_model else [])
            if isinstance(a, DroneAgent)
            and a.status in (DroneStatus.MOVING, DroneStatus.SCANNING, DroneStatus.IDLE)
            and not a.malfunction and a.battery > LOW_BATTERY + 10
        ]
        if candidates:
            victim = random.choice(candidates)
            victim.malfunction = True
            victim.malfunction_pause = 8
            victim.path = []
            victim.target = None
            victim.cv_hold = False
            victim.scan_timer = 0
            _malfunction_triggered = True
            if _current_model:
                _current_model.rescue_log.append({
                    "tick":  _current_model.tick,
                    "type":  "malfunction",
                    "msg":   f"drone_{victim.unique_id} SYSTEM FAULT — returning to base for repair",
                    "drone": f"drone_{victim.unique_id}",
                })

    if _current_model:
        _current_model.rescue_log.append({
            "tick":  _current_model.tick,
            "type":  "mcp_cmd",
            "msg":   f"{drone_id} executing mcp_thermal_scan()",
            "drone": drone_id
        })

        degree_radius = VISION_RADIUS / 111.0

        # Record scan location
        try:
            record_scan(drone_id, drone.x, drone.y, VISION_RADIUS, _current_model.tick)
        except: pass
        _current_model.mapped_cells.add((drone.x, drone.y))

        for agent in _current_model.grid.get_neighbors(
            (drone.x, drone.y), include_center=True, radius=degree_radius
        ):
            if not isinstance(agent, SurvivorAgent) or agent.rescued:
                continue

            # Thermal scan = detection only. Rescue happens after CV double-confirm.
            # This keeps survivors in detected:true / rescued:false state so:
            #   • the green detection ring appears on the map
            #   • the YOLO CV visualisation has survivors to frame
            #   • cv_hold triggers and the drone stops for the CV scan cycle
            agent.detected = True
            detected.append({
                "x":        agent.pos[0],
                "y":        agent.pos[1],
                "critical": agent.critical,
                "district": "Metro Manila",
            })
            try:
                record_survivor(agent.pos[0], agent.pos[1], agent.critical, drone_id, False)
            except: pass

        # ── CV verification hold ─────────────────────────────────────
        # If any unrescued contacts remain in range, the drone MUST stop so the
        # operator can run mcp_cv_scan twice to double-confirm. Clear the path
        # and target immediately so the next model.step() cannot keep flying,
        # and set a minimum tick window so the dashboard's CV animation has
        # time to play before the agent resumes the sweep.
        if len(detected) > 0:
            drone.path = []
            drone.target = None
            drone.status = DroneStatus.SCANNING
            # Arm the hold ONLY on first detection. Every subsequent thermal
            # call at the same position must keep the drone parked but MUST
            # NOT extend cv_hold_until_tick — otherwise the release check in
            # mcp_cv_scan (tick >= cv_hold_until_tick) can never fire and
            # the drone would be stuck forever.
            if not drone.cv_hold:
                drone.cv_hold = True
                drone.cv_hold_contact_count = len(detected)
                drone.cv_hold_until_tick = _current_model.tick + 12  # 12 ticks ≈ 4.2 s (matches 2×2.4 s CV cycle)
                _current_model.rescue_log.append({
                    "tick":  _current_model.tick,
                    "type":  "cv_hold",
                    "msg":   f"{drone_id} HOLDING for CV verification of {len(detected)} contact(s)",
                    "drone": drone_id,
                })
            else:
                drone.cv_hold_contact_count = max(drone.cv_hold_contact_count, len(detected))

    return {
        "drone_id":        drone_id,
        "scan_position":   {"x": drone.x, "y": drone.y},
        "scan_radius_km":  VISION_RADIUS,
        "unrescued_count": len(detected),
        "survivors_in_range": detected,
        "rescued_now":     rescued_now,
        "rescued_count":   len(rescued_now),
        "cv_hold_active":  getattr(drone, "cv_hold", False),
    }


# ─────────────────────────────────────────────────────────────
# Computer-Vision Scan — second-pass verification of thermal hits
# ─────────────────────────────────────────────────────────────
# Per-drone confirmation counter: { drone_id: { (x_round,y_round): count } }
# A contact is "confirmed" only after TWO successful CV passes from the same
# drone at the same position — enforcing the move→thermal→stop→cv→double-confirm
# cycle defined in the mission rules.
_cv_confirmations: dict = {}


def _cv_key(x: float, y: float) -> tuple:
    return (round(x, 5), round(y, 5))


def mcp_cv_scan(drone_id: str) -> dict:
    """
    Computer-vision verification of survivors already detected by thermal scan.

    Workflow enforced:
      1. Drone must be STOPPED (no pending path) — otherwise this call errors.
      2. mcp_thermal_scan must have been run at this position first — otherwise
         there is nothing to analyse and the call returns no_contacts.
      3. Each call increments a per-(drone, position-rounded) confirmation counter.
         A survivor is "confirmed" only when the counter reaches 2 (double-confirm).

    Returns:
      drone_id, scan_position, scan_radius_km,
      analyses: list of per-survivor dicts with:
        x, y, critical
        confidence            — synthetic CV confidence (0.88–0.98 true, 0.40–0.65 decoy)
        pass_count            — how many CV passes performed on this contact
        confirmed             — True once pass_count >= 2 AND is_true_positive
        classification        — "HUMAN" | "FALSE_POSITIVE"
        zone                  — "CRITICAL" | "NORMAL" (from critical flag)
      all_confirmed: True if every contact has confirmed==True
      requires_another_pass:  True if at least one contact still needs a second pass
    """
    drone = _find_drone(drone_id)
    if drone is None:
        return {"error": f"Drone {drone_id} not found"}

    # Rule 1: drone must be stopped (no queued path & not moving)
    if getattr(drone, "path", None):
        return {
            "error": "drone_in_motion",
            "message": f"{drone_id} must be stopped before CV scan. Wait for movement to finish.",
        }

    if _current_model is None:
        return {"error": "Simulation not started yet."}

    _current_model.rescue_log.append({
        "tick":  _current_model.tick,
        "type":  "mcp_cmd",
        "msg":   f"{drone_id} executing mcp_cv_scan()",
        "drone": drone_id,
    })

    degree_radius = VISION_RADIUS / 111.0
    dkey = _cv_key(drone.x, drone.y)
    bucket = _cv_confirmations.setdefault(drone_id, {}).setdefault(dkey, {})

    analyses = []
    any_needs_another = False
    for agent in _current_model.grid.get_neighbors(
        (drone.x, drone.y), include_center=True, radius=degree_radius
    ):
        if not isinstance(agent, SurvivorAgent):
            continue
        if not getattr(agent, "detected", False):
            # CV scan only runs on thermal-detected targets
            continue
        skey = _cv_key(agent.pos[0], agent.pos[1])
        pass_count = bucket.get(skey, 0) + 1
        bucket[skey] = pass_count

        # Synthetic CV confidence. Real survivors always verify; a small
        # noise band is added so the confidence readout looks plausible.
        is_true_positive = True  # every SurvivorAgent is real in this sim
        if is_true_positive:
            confidence = round(0.88 + 0.10 * (pass_count / 3.0), 3)
        else:
            confidence = round(0.40 + 0.25 * (pass_count / 3.0), 3)

        confirmed = is_true_positive and pass_count >= 2
        analyses.append({
            "x":            agent.pos[0],
            "y":            agent.pos[1],
            "critical":     agent.critical,
            "confidence":   min(0.99, confidence),
            "pass_count":   pass_count,
            "confirmed":    confirmed,
            "classification": "HUMAN" if is_true_positive else "FALSE_POSITIVE",
            "zone":         "CRITICAL" if agent.critical else "NORMAL",
        })
        if not confirmed:
            any_needs_another = True

    hold_window_elapsed = (_current_model.tick >= drone.cv_hold_until_tick)
    all_confirmed = len(analyses) > 0 and not any_needs_another and hold_window_elapsed

    # ── Release CV hold once every contact is double-confirmed AND the
    # minimum hold window has elapsed (so the UI CV animation has had
    # time to play). If the window has not elapsed, keep the hold so the
    # next mcp_move_to is still refused.
    hold_released = False
    if all_confirmed and getattr(drone, "cv_hold", False):
        if _current_model.tick >= drone.cv_hold_until_tick:
            # CV double-confirmed — now rescue all detected survivors in range
            for agent in _current_model.grid.get_neighbors(
                (drone.x, drone.y), include_center=True, radius=degree_radius
            ):
                if not isinstance(agent, SurvivorAgent):
                    continue
                if agent.detected and not agent.rescued:
                    agent.rescued = True
                    drone.rescued += 1
                    _current_model.metrics["rescued"] += 1
                    _current_model.rescue_log.append({
                        "tick":     _current_model.tick,
                        "drone":    drone.base_name,
                        "district": "Metro Manila",
                        "critical": agent.critical,
                    })
                    rescued_now = getattr(mcp_cv_scan, "_rescued_now", None)
                    try:
                        record_survivor(agent.pos[0], agent.pos[1], agent.critical, drone_id, True)
                    except: pass

            drone.cv_hold = False
            drone.cv_hold_contact_count = 0
            drone.status = DroneStatus.IDLE
            hold_released = True
            _current_model.rescue_log.append({
                "tick":  _current_model.tick,
                "type":  "cv_hold_release",
                "msg":   f"{drone_id} CV confirmed — survivors rescued, hold released",
                "drone": drone_id,
            })

    return {
        "drone_id":              drone_id,
        "scan_position":         {"x": drone.x, "y": drone.y},
        "scan_radius_km":        VISION_RADIUS,
        "analyses":              analyses,
        "analysed_count":        len(analyses),
        "all_confirmed":         all_confirmed,
        "requires_another_pass": (any_needs_another and len(analyses) > 0) or (len(analyses) > 0 and not hold_window_elapsed),
        "cv_hold_active":        getattr(drone, "cv_hold", False),
        "cv_hold_released":      hold_released,
        "status": (
            "no_contacts" if not analyses
            else "confirmed" if all_confirmed
            else "hold_and_reverify" if (len(analyses) > 0 and not hold_window_elapsed and not any_needs_another)
            else "needs_second_pass"
        ),
    }


def mcp_get_mission_status() -> dict:
    """Return overall mission progress: tick, rescued count, and last 5 rescues."""
    if _current_model is None:
        return {"error": "Simulation not started yet."}
    m = _current_model.metrics
    return {
        "tick":               _current_model.tick,
        "mission_complete":   not _current_model.running,
        "survivors_rescued":  m["rescued"],
        "total_survivors":    m["total_survivors"],
        "rescue_percentage":  round(100 * m["rescued"] / max(m["total_survivors"], 1), 1),
        "total_distance":     m["total_distance"],
        "total_battery_used": m["total_battery_used"],
        "recent_rescues":     _current_model.rescue_log[-5:],
    }


def mcp_get_sector_info() -> str:
    """Return JSON string of logical sector centers so AI can distribute drones efficiently."""
    return json.dumps({
        name: {"center_x": c[0], "center_y": c[1]}
        for name, c in MANILA_CITY_SECTORS.items()
    })


def mcp_get_mapping_status() -> dict:
    """Return the total percentage mapped, and a list of sectors that are unmapped."""
    if _current_model is None:
        return {"error": "Simulation not started"}
    
    total = len(MANILA_CITY_SECTORS)
    unmapped_sectors = []
    
    # A sector is considered mapped if the drone has scanned within 2.0km of its center.
    for s_name, (cx, cy) in MANILA_CITY_SECTORS.items():
        is_mapped = False
        for (mx, my) in _current_model.mapped_cells:
            if haversine_distance(cx, cy, mx, my) <= 2.0:
                is_mapped = True
                break
        if not is_mapped:
            unmapped_sectors.append(s_name)
            
    # CRITICAL: Prevent the swarm from all targeting the same unmapped sector
    # by checking if any drone is ALREADY flying there right now.
    pending_targets = []
    for agent in _current_model.agents:
        if isinstance(agent, DroneAgent) and agent.target:
            pending_targets.append(agent.target)
            
    truly_unmapped = []
    for s_name in unmapped_sectors:
        cx, cy = MANILA_CITY_SECTORS[s_name]
        someone_is_heading_here = False
        for (tx, ty) in pending_targets:
            if haversine_distance(cx, cy, tx, ty) <= 2.0:
                someone_is_heading_here = True
                break
        if not someone_is_heading_here:
            truly_unmapped.append(s_name)
            
    # If everywhere is targeted but not finished, just return the ones left
    if not truly_unmapped and unmapped_sectors:
        truly_unmapped = unmapped_sectors
            
    random.shuffle(truly_unmapped)
            
    mapped_count = total - len(unmapped_sectors)
    pct = round(100 * mapped_count / total, 1) if total else 0
            
    return {
        "mapped_percentage": pct,
        "unmapped_sectors": truly_unmapped,
        "mapped_cells_count": mapped_count,
        "total_cells": total
    }

def mcp_get_known_survivors() -> list[dict]:
    """Returns grid coordinates of all known but unrescued survivors in the mapped area."""
    if _current_model is None:
        return []
        
    known = []
    for agent in _current_model.agents:
        if isinstance(agent, SurvivorAgent) and not agent.rescued:
            # Survivor is known if they are within 1.0km of any mapped cell
            is_known = False
            for (mx, my) in _current_model.mapped_cells:
                if haversine_distance(agent.pos[0], agent.pos[1], mx, my) <= 1.0:
                    is_known = True
                    break
                    
            if is_known:
                known.append({
                    "x": agent.pos[0],
                    "y": agent.pos[1],
                    "critical": agent.critical,
                    "district": getattr(agent, "district", "Metro Manila")
                })
    return known


def mcp_get_arc_waypoints(drone_id: str) -> dict:
    """Return arc waypoint list for a drone (used by command drone to navigate)."""
    drone = _find_drone(drone_id)
    if not drone:
        return {"error": f"{drone_id} not found"}
    return {
        "drone_id": drone_id,
        "arc_waypoints": drone.arc_waypoints,
        "current_index": drone.arc_waypoint_index,
        "total_waypoints": len(drone.arc_waypoints),
    }


def mcp_advance_arc_waypoint(drone_id: str) -> dict:
    """Advance command drone to next arc waypoint."""
    drone = _find_drone(drone_id)
    if not drone:
        return {"error": f"{drone_id} not found"}
    if drone.arc_waypoint_index < len(drone.arc_waypoints):
        drone.arc_waypoint_index += 1
    return {
        "drone_id": drone_id,
        "new_index": drone.arc_waypoint_index,
        "total_waypoints": len(drone.arc_waypoints),
    }


def mcp_get_next_sweep_waypoint(drone_id: str) -> dict:
    """
    BOUSTROPHEDON SWEEP TOOL — Get the next waypoint from the pre-computed
    robot-vacuum sweep path for a specific drone.
    
    Returns the next coordinate the drone should move to, using a coverage
    algorithm that guarantees scanning the entire assigned sector.
    """
    drone = _find_drone(drone_id)
    if not drone:
        return {"error": f"{drone_id} not found"}

    idx = drone.arc_waypoint_index
    total = len(drone.arc_waypoints)

    if idx >= total:
        return {
            "drone_id": drone_id,
            "status": "complete",
            "message": f"All {total} sweep waypoints scanned. Mission complete for {drone_id}.",
            "waypoint_index": idx,
            "total_waypoints": total,
        }

    wp = drone.arc_waypoints[idx]
    return {
        "drone_id": drone_id,
        "status": "next_waypoint",
        "waypoint_x": wp[0],
        "waypoint_y": wp[1],
        "waypoint_index": idx + 1,
        "total_waypoints": total,
        "message": f"Sweep waypoint {idx+1}/{total} for {drone_id}: go to ({wp[0]:.5f}, {wp[1]:.5f})",
    }


def mcp_get_zone_assignment(drone_id: str) -> dict:
    """
    Zone-Ring Assignment Tool.
    Returns the current ring zone (OUTER/MIDDLE/INNER) and the next waypoint
    the Command Agent should dispatch this drone to.
    Zones are searched outside-in: OUTER first, then MIDDLE, then INNER.
    """
    drone = _find_drone(drone_id)
    if not drone:
        return {"error": f"{drone_id} not found"}

    zones_order = ["OUTER", "MIDDLE", "INNER"]

    # Auto-advance to next non-empty zone if current is exhausted
    while True:
        zone_wps = drone.zone_waypoints.get(drone.current_zone, [])
        if drone.zone_wp_idx < len(zone_wps):
            break
        z_idx = zones_order.index(drone.current_zone)
        if z_idx + 1 < len(zones_order):
            drone.current_zone = zones_order[z_idx + 1]
            drone.zone_wp_idx = 0
        else:
            return {
                "drone_id": drone_id,
                "status": "all_zones_complete",
                "message": f"{drone_id} completed all ring zones (OUTER→MIDDLE→INNER). Sector fully swept.",
            }

    zone = drone.current_zone
    zone_wps = drone.zone_waypoints[zone]
    wp = zone_wps[drone.zone_wp_idx]
    z_idx = zones_order.index(zone)
    zone_radii = {"OUTER": "1.3–2.0 km", "MIDDLE": "0.6–1.3 km", "INNER": "0.0–0.6 km"}

    return {
        "drone_id":              drone_id,
        "status":                "next_waypoint",
        "zone":                  zone,
        "zone_index":            z_idx + 1,
        "total_zones":           3,
        "zone_radius_range":     zone_radii[zone],
        "waypoint_x":            wp[0],
        "waypoint_y":            wp[1],
        "waypoint_index":        drone.zone_wp_idx + 1,
        "total_waypoints_in_zone": len(zone_wps),
        "message": (f"Zone {zone} ({zone_radii[zone]}) WP {drone.zone_wp_idx+1}/{len(zone_wps)}: "
                    f"navigate to ({wp[0]:.5f}, {wp[1]:.5f})"),
    }


def mcp_advance_zone_waypoint(drone_id: str) -> dict:
    """
    Advance drone to the next waypoint within its current zone ring.
    Call this after the drone completes its on-site scan at the current position.
    When the zone is exhausted the next get_zone_assignment call will auto-advance
    to the next ring (OUTER → MIDDLE → INNER).
    """
    drone = _find_drone(drone_id)
    if not drone:
        return {"error": f"{drone_id} not found"}

    drone.zone_wp_idx += 1
    zone = drone.current_zone
    zone_wps = drone.zone_waypoints.get(zone, [])
    zone_complete = drone.zone_wp_idx >= len(zone_wps)

    return {
        "drone_id":     drone_id,
        "zone":         zone,
        "new_index":    drone.zone_wp_idx,
        "total_in_zone": len(zone_wps),
        "zone_complete": zone_complete,
        "message": (f"Advanced to WP {drone.zone_wp_idx}/{len(zone_wps)} in {zone} zone"
                    + (" — zone complete, next call will move to inner ring." if zone_complete else ".")),
    }


# ─────────────────────────────────────────────────────────────
# TEAM SECTOR MCP TOOLS
# All 5 drones share a single sector waypoint queue.
# ─────────────────────────────────────────────────────────────

def mcp_get_team_waypoint(drone_id: str) -> dict:
    """
    3-2-1 DISTRIBUTION SWEEP using per-drone pre-assigned queues:
    - R1, R2, R3 → OUTER ring (pre-assigned at sector load time)
    - R4, R5     → MIDDLE ring (pre-assigned at sector load time)
    - INNER      → distributed among all 5 after OUTER/MIDDLE
    Returns role_complete when this drone's slice is exhausted.
    """
    drone = _find_drone(drone_id)
    slot = drone.formation_slot if drone else "R?"

    with _team_lock:
        if _team_sector_complete:
            return {"status": "all_sectors_complete",
                    "message": "All 5 sectors fully searched. Mission complete."}

        sector = TEAM_SECTORS[_current_team_sector]

        # ── Per-drone queue lookup ──
        wps = _drone_sector_wps.get(drone_id, [])
        idx = _drone_sector_idx.get(drone_id, 0)

        if idx >= len(wps):
            # This drone has finished its pre-assigned slice
            return {
                "status":      "role_complete",
                "sector_id":   sector["id"],
                "sector_name": sector["name"],
                "slot":        slot,
                "message":     f"{drone_id}({slot}) finished its slice. Waiting for teammates.",
            }

        wp = wps[idx]
        _drone_sector_idx[drone_id] = idx + 1

        total_wps = sum(len(q) for q in _drone_sector_wps.values())
        total_done = sum(_drone_sector_idx.values())

        return {
            "status":          "next_waypoint",
            "sector_id":       sector["id"],
            "sector_name":     sector["name"],
            "sector_color":    sector["color"],
            "sector_index":    _current_team_sector + 1,
            "total_sectors":   len(TEAM_SECTORS),
            "waypoint_x":      wp[0],
            "waypoint_y":      wp[1],
            "ring":            wp[2],
            "waypoint_index":  total_done,
            "total_waypoints": total_wps,
            "message": (f"[{sector['name']}] {drone_id}({slot}) → {wp[2]} ring "
                        f"({total_done}/{total_wps}): ({wp[0]:.5f}, {wp[1]:.5f})"),
        }


def mcp_get_team_sector_status() -> dict:
    """Current team sector info — which sector is active, progress, per-drone breakdown."""
    with _team_lock:
        if _team_sector_complete:
            return {"status": "all_complete", "message": "All sectors searched."}

        sector = TEAM_SECTORS[_current_team_sector]
        total    = sum(len(q) for q in _drone_sector_wps.values())
        done     = sum(_drone_sector_idx.values())
        remaining = total - done

        drone_progress = {
            did: f"{_drone_sector_idx.get(did, 0)}/{len(_drone_sector_wps.get(did, []))}"
            for did in _drone_sector_wps
        }

        return {
            "status":               "active",
            "sector_index":         _current_team_sector + 1,
            "total_sectors":        len(TEAM_SECTORS),
            "sector_id":            sector["id"],
            "sector_name":          sector["name"],
            "color":                sector["color"],
            "angle_start":          sector["angle_start"],
            "angle_end":            sector["angle_end"],
            "sweep_type":           sector.get("sweep", "arc"),
            "waypoints_dispatched": done,
            "waypoints_remaining":  remaining,
            "total_waypoints":      total,
            "drone_progress":       drone_progress,
        }


def mcp_advance_team_sector() -> dict:
    """
    Advance all 5 drones to the next team sector.
    Call when get_team_waypoint returns role_complete.
    Checks all drones finished their slice before advancing.
    """
    global _current_team_sector, _team_sector_complete
    with _team_lock:
        sector = TEAM_SECTORS[_current_team_sector]

        # Guard: all drones must have finished their personal slice
        all_done = all(
            _drone_sector_idx.get(did, 0) >= len(_drone_sector_wps.get(did, []))
            for did in _drone_sector_wps
        )
        if not all_done and _drone_sector_wps:
            remaining = sum(
                max(0, len(_drone_sector_wps.get(did, [])) - _drone_sector_idx.get(did, 0))
                for did in _drone_sector_wps
            )
            return {"status": "not_ready", "remaining": remaining,
                    "message": f"Sector {sector['name']} has {remaining} waypoints left across fleet."}

        next_idx = _current_team_sector + 1
        if next_idx >= len(TEAM_SECTORS):
            _team_sector_complete = True
            return {"status": "all_sectors_complete",
                    "message": "All 5 team sectors searched! Mission complete!"}

        _current_team_sector = next_idx
        new_sector = TEAM_SECTORS[_current_team_sector]

        # Pre-assign per-drone waypoints for the new sector
        _load_sector_for_drones(new_sector["id"])

        new_total = sum(len(q) for q in _drone_sector_wps.values())
        print(f"[SIM] ▶ Team advanced: {sector['name']} → {new_sector['name']} "
              f"({new_total} total waypoints)", file=sys.stderr, flush=True)
        return {
            "status":           "advanced",
            "old_sector":       sector["name"],
            "new_sector_id":    new_sector["id"],
            "new_sector_name":  new_sector["name"],
            "new_sector_index": _current_team_sector + 1,
            "total_sectors":    len(TEAM_SECTORS),
            "total_waypoints":  new_total,
            "message": (f"Advanced from {sector['name']} to {new_sector['name']} — "
                        f"{new_total} total waypoints ready."),
        }


# ─────────────────────────────────────────────────────────────
# 5. HEADLESS RUNNER
#    Called by mcp_server.py in a background thread.
# ─────────────────────────────────────────────────────────────

def run_simulation_headless(step_interval: float = 0.35) -> None:
    """
    Run the Mesa simulation without any UI.
    Prints progress to stderr so it doesn't interfere with MCP JSON-RPC on stdout.
    Blocks at _setup_event until the user places survivors and clicks START.
    """
    global _current_model
    print("[SIM] Waiting for survivor placement…", file=sys.stderr, flush=True)
    _setup_event.wait()   # unblocked by configure_and_start()

    print("[SIM] Creating MetroManilaRescueModel...", file=sys.stderr, flush=True)
    model = MetroManilaRescueModel()
    _current_model = model  # Ensure model is globally set

    drone_count = sum(1 for a in model.agents if isinstance(a, DroneAgent))
    drone_statuses = {}
    for a in model.agents:
        if isinstance(a, DroneAgent):
            status = a.status.value if hasattr(a, 'status') else 'UNKNOWN'
            drone_statuses[f"drone_{a.unique_id}"] = status
    print(
        f"[SIM] Metro Manila Rescue started — "
        f"Survivors: {model.metrics['total_survivors']}, Drones: {drone_count}",
        file=sys.stderr, flush=True,
    )
    print(f"[SIM] Drone statuses at startup: {drone_statuses}", file=sys.stderr, flush=True)
    print(f"[SIM] Model is now ready for MCP queries!", file=sys.stderr, flush=True)

    while model.running:
        _pause_event.wait()      # blocks here until user clicks START (or RESUME)
        model.step()
        time.sleep(step_interval)
    print(
        f"[SIM] Mission complete — "
        f"Rescued {model.metrics['rescued']}/{model.metrics['total_survivors']} "
        f"in {model.tick} ticks.",
        file=sys.stderr, flush=True,
    )
