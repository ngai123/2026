"""
dashboard.py
============
Two-map interactive command-center dashboard.

Left map  — SURVIVOR PLACEMENT
  Click any point on the real Metro Manila map to drop a survivor pin.
  Toggle between Critical (🔴) and Stable (🟠) modes.
  Click an existing pin to remove it.
  Press START MISSION to commit placements and begin the simulation.

Right map — LIVE MISSION
  Same CartoDB dark basemap, no colored district overlays.
  Shows drone markers, survivor markers, and flood-zone highlights
  updating in real time from the Mesa simulation via WebSocket.

Bottom panel — Fleet status | Mission log | AI Reasoning
"""

import asyncio
import json
import sys
import threading
import time
import uvicorn
from collections import deque
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse, Response, FileResponse
from pathlib import Path
from pydantic import BaseModel

dashboard_app = FastAPI()

# ── AI event store (populated by POST /api/ai_event from command_agent) ───────
_ai_events: deque = deque(maxlen=200)
_ai_lock = threading.Lock()
_connected_clients: set = set()


# ── Pydantic models ───────────────────────────────────────────────────────────

class StartPayload(BaseModel):
    survivors: list = None    # [{x, y, critical}, …] — auto-generated if empty/None
    drones: list = None       # [{x, y}, …] — auto-generated if empty/None
    bases: list | None = None # [{x, y}, ...] — auto-generated if empty/None


class AIEventIn(BaseModel):
    drone_id:       str
    round:          int
    tick:           int
    prompt:         str
    llm_response:   str
    commands:       list
    idle_count:     int
    low_batt_count: int

class AIStreamIn(BaseModel):
    drone_id: str
    chunk: str

class AIPhaseIn(BaseModel):
    drone_id: str
    round: int
    phase: str
    data: dict
    timestamp: float = 0


# ── REST endpoints ─────────────────────────────────────────────────────────────

@dashboard_app.get("/api/default-placements")
async def api_default_placements():
    """Return default base, drones, and survivors for pre-initialization."""
    try:
        from src.core.metro_manila_rescue import _generate_default_placements
        survivors, drones, bases = _generate_default_placements()

        # Add critical flag to survivors
        for s in survivors:
            s["critical"] = False

        return {
            "ok": True,
            "bases": bases,
            "drones": drones,
            "survivors": survivors,
            "quadrants": [
                {"name": "Q_NE", "angle_start": 0, "angle_end": 90, "color": "#FF0000"},
                {"name": "Q_NW", "angle_start": 270, "angle_end": 360, "color": "#00FF00"},
                {"name": "Q_SW", "angle_start": 180, "angle_end": 270, "color": "#0000FF"},
                {"name": "Q_SE", "angle_start": 90, "angle_end": 180, "color": "#FFFF00"},
            ]
        }
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


@dashboard_app.post("/api/start")
async def api_start(payload: StartPayload = None):
    """Accept survivor/drone positions or auto-generate defaults if empty/None."""
    try:
        from src.core.metro_manila_rescue import configure_and_start
        # Pass None if empty lists, so configure_and_start auto-generates defaults
        survivors = payload.survivors if payload and payload.survivors else None
        drones = payload.drones if payload and payload.drones else None
        bases = payload.bases if payload and payload.bases else None
        configure_and_start(survivors, drones, bases)
        return {
            "ok": True,
            "survivors": len(survivors or []),
            "drones": len(drones or []),
            "auto_generated": survivors is None and drones is None and bases is None
        }
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


@dashboard_app.post("/api/pause")
async def api_pause():
    try:
        from src.core.metro_manila_rescue import set_mission_paused
        set_mission_paused(True)
        return {"ok": True}
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


@dashboard_app.post("/api/resume")
async def api_resume():
    try:
        from src.core.metro_manila_rescue import set_mission_paused
        set_mission_paused(False)
        return {"ok": True}
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


@dashboard_app.post("/api/ai_event")
async def api_ai_event(event: AIEventIn):
    with _ai_lock:
        _ai_events.append({
            "drone_id":       event.drone_id,
            "round":          event.round,
            "tick":           event.tick,
            "prompt":         event.prompt,
            "llm_response":   event.llm_response,
            "commands":       event.commands,
            "idle_count":     event.idle_count,
            "low_batt_count": event.low_batt_count,
            "ts":             time.time(),
        })
    return {"ok": True}

@dashboard_app.post("/api/ai_stream")
async def api_ai_stream(stream: AIStreamIn):
    msg = json.dumps({"type": "ai_stream", "drone_id": stream.drone_id, "chunk": stream.chunk, "ready": False})
    for client in list(_connected_clients):
        try:
            await client.send_text(msg)
        except Exception:
            pass
    return {"ok": True}


@dashboard_app.post("/api/ai_phase")
async def api_ai_phase(event: AIPhaseIn):
    """Broadcast AI phase events to all connected WebSocket clients for the X-Ray panel."""
    msg = json.dumps({
        "type": "ai_phase",
        "drone_id": event.drone_id,
        "round": event.round,
        "phase": event.phase,
        "data": event.data,
        "timestamp": event.timestamp,
        "ready": False,
    })
    for client in list(_connected_clients):
        try:
            await client.send_text(msg)
        except Exception:
            pass
    return {"ok": True}


@dashboard_app.get("/api/export")
async def api_export():
    try:
        from src.core.metro_manila_rescue import _current_model, DroneAgent
    except ImportError:
        return JSONResponse({"error": "simulation not available"}, status_code=503)

    model = _current_model
    with _ai_lock:
        ai_snap = list(_ai_events)

    payload: dict = {
        "exported_at":  time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "mission_stats": {},
        "drone_summary": [],
        "rescue_log":    [],
        "ai_events":     ai_snap,
    }
    if model:
        m = model.metrics
        payload["mission_stats"] = {
            "tick":               model.tick,
            "survivors_rescued":  m["rescued"],
            "total_survivors":    m["total_survivors"],
            "rescue_percentage":  round(100 * m["rescued"] / max(m["total_survivors"], 1), 1),
            "total_distance":     m["total_distance"],
            "total_battery_used": m["total_battery_used"],
            "mission_complete":   not model.running,
        }
        payload["rescue_log"]    = model.rescue_log
        payload["drone_summary"] = [
            {"id": f"drone_{a.unique_id}", "base": a.base_name,
             "rescued": a.rescued, "battery": a.battery,
             "total_distance": a.total_distance}
            for a in model.agents if isinstance(a, DroneAgent)
        ]
    return Response(
        content=json.dumps(payload, indent=2),
        media_type="application/json",
        headers={"Content-Disposition": 'attachment; filename="mission_export.json"'},
    )


@dashboard_app.get("/assets/{filename:path}")
async def serve_asset(filename: str):
    """Serve static assets (GLB models, textures, etc.) from the assets/ directory."""
    asset_path = Path("assets") / filename
    if not asset_path.exists() or not asset_path.is_file():
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Asset not found")
    return FileResponse(asset_path)


# ── WebSocket state snapshot ───────────────────────────────────────────────────

_mission_start_ts: float | None = None
_mission_end_ts:   float | None = None
_mission_anchor_model_id: int | None = None


def _get_state() -> dict:
    try:
        from src.core.metro_manila_rescue import (
            _current_model, _pause_event, _setup_event,
            DroneAgent, SurvivorAgent,
            mcp_get_team_sector_status,
        )
    except ImportError:
        return {"ready": False}

    mission_started = _setup_event.is_set()

    if _current_model is None:
        return {"ready": False, "mission_started": mission_started}

    # Anchor mission start/end timestamps on the server for stable elapsed/ETA.
    global _mission_start_ts, _mission_end_ts, _mission_anchor_model_id
    _mid = id(_current_model)
    if _mid != _mission_anchor_model_id:
        _mission_anchor_model_id = _mid
        _mission_start_ts = None
        _mission_end_ts = None
    if mission_started and _mission_start_ts is None:
        _mission_start_ts = time.time()
    if (not _current_model.running) and _mission_end_ts is None and _mission_start_ts is not None:
        _mission_end_ts = time.time()

    model  = _current_model
    paused = not _pause_event.is_set()
    drones, survivors = [], []

    for agent in model.agents:
        if isinstance(agent, DroneAgent) and agent.pos is not None:
            slot      = getattr(agent, "formation_slot", "R?")
            ring_role = getattr(agent, "ring_role", "OUTER" if slot in ("R1","R2","R3") else "MIDDLE_INNER")
            drones.append({
                "id":            f"drone_{agent.unique_id}",
                "x":             agent.pos[0],
                "y":             agent.pos[1],
                "battery":       agent.battery,
                "status":        agent.status.name,
                "base_name":     agent.base_name,
                "rescued_count": agent.rescued,
                "target":        {"x": agent.target[0], "y": agent.target[1]}
                                 if agent.target else None,
                "path":          [{"x": px, "y": py} for (px, py) in agent.path] if hasattr(agent, 'path') and agent.path else [],
                "slot":          slot,
                "ring_role":     ring_role,
                "display_color": getattr(agent, "display_color", ""),
                "cv_hold":       bool(getattr(agent, "cv_hold", False)),
                "cv_hold_contacts": int(getattr(agent, "cv_hold_contact_count", 0)),
                "scan_timer":    int(getattr(agent, "scan_timer", 0)),
            })
        elif isinstance(agent, SurvivorAgent) and agent.pos is not None:
            survivors.append({
                "x":        agent.pos[0],
                "y":        agent.pos[1],
                "rescued":  agent.rescued,
                "detected": agent.detected,
                "critical": agent.critical,
            })

    m = model.metrics
    with _ai_lock:
        ai_snap = list(_ai_events)[-20:]

    # Extract rescued survivor locations
    rescued_locations = []
    for s in survivors:
        if s["rescued"]:
            rescued_locations.append([s["x"], s["y"]])

    return {
        "ready":            True,
        "mission_started":  mission_started,
        "paused":           paused,
        "tick":             model.tick,
        "drones":           drones,
        "survivors":        survivors,
        "disaster_cells":   list(model.disaster_cells),
        "mapped_cells":     list(model.mapped_cells) if hasattr(model, 'mapped_cells') else [],
        "rescued_locations": rescued_locations,
        "rescued":          m["rescued"],
        "total":            m["total_survivors"],
        "distance":         m["total_distance"],
        "battery_used":     m["total_battery_used"],
        "mission_complete": not model.running,
        "mission_start_ts": _mission_start_ts,
        "mission_end_ts":   _mission_end_ts,
        "server_ts":        time.time(),
        "rescue_log":       model.rescue_log,
        "ai_events":        ai_snap,
        "team_sector":      mcp_get_team_sector_status(),
    }


# ── HTML ───────────────────────────────────────────────────────────────────────

_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Metro Manila Rescue — NDRRMC Command Center</title>
<link rel="stylesheet" href="https://unpkg.com/maplibre-gl@4.7.1/dist/maplibre-gl.css"/>
<script src="https://cdn.jsdelivr.net/npm/mermaid@10/dist/mermaid.min.js"></script>
<script src="https://cdnjs.cloudflare.com/ajax/libs/three.js/r128/three.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/three@0.128.0/examples/js/loaders/GLTFLoader.js"></script>
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&family=Outfit:wght@600;700;800&family=JetBrains+Mono:wght@400;500&display=swap');
/* TWO_PAGE_MARKER */

:root {
  /* Core Palette - Vibrant & Premium */
  --bg-deep: #050a14;
  --bg-dark: #0a1120;
  --bg-panel: rgba(13, 22, 40, 0.7);
  --bg-glass: rgba(16, 28, 54, 0.6);
  --border-light: rgba(255, 255, 255, 0.08);
  --border-glow: rgba(0, 245, 255, 0.2);
  
  --accent: #0088ff;      /* Vibrant Blue */
  --accent-glow: rgba(0, 136, 255, 0.4);
  --emerald: #00ff9f;    /* Neon Emerald */
  --emerald-glow: rgba(0, 255, 159, 0.3);
  --gold: #ff9500;       /* Vibrant Orange */
  --crimson: #ff2a6d;    /* Emergency Crimson */
  --indigo: #5c6fff;     /* AI Deep Learning */
  
  --text-primary: #f0f4f8;
  --text-secondary: #94a3b8;
  --text-dim: #64748b;
  
  --panel-blur: blur(12px);
  --transition-fast: 0.2s cubic-bezier(0.4, 0, 0.2, 1);
  --transition-smooth: 0.4s cubic-bezier(0.4, 0, 0.2, 1);
}

*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

html, body { height: 100%; overflow: hidden; }

body {
  background: var(--bg-deep);
  color: var(--text-primary);
  font-family: 'Inter', system-ui, sans-serif;
  display: flex;
  flex-direction: column;
  background-image: 
    radial-gradient(circle at 50% 0%, rgba(0, 245, 255, 0.05) 0%, transparent 50%),
    radial-gradient(circle at 0% 100%, rgba(92, 111, 255, 0.05) 0%, transparent 40%);
}

/* ── Typography Highlighting ──────── */
h1, h2, h3, .heading-font { font-family: 'Outfit', sans-serif; letter-spacing: -0.02em; }
.mono { font-family: 'JetBrains Mono', monospace; }

/* ── Header ─────────────────────── */
#hdr {
  height: 64px;
  background: var(--bg-panel);
  backdrop-filter: var(--panel-blur);
  border-bottom: 1px solid var(--border-light);
  display: flex;
  align-items: center;
  gap: 24px;
  padding: 0 24px;
  flex-shrink: 0;
  z-index: 1000;
  box-shadow: 0 4px 24px rgba(0, 0, 0, 0.4);
}

#hdr-title { display: flex; flex-direction: column; gap: 2px; }
#hdr-title h1 { 
  font-size: 16px; 
  background: linear-gradient(135deg, var(--text-primary), var(--accent));
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  font-weight: 800;
  text-transform: uppercase;
  letter-spacing: 0.05em;
}
#hdr-title p { font-size: 11px; color: var(--text-dim); text-transform: uppercase; letter-spacing: 0.1em; }

#hdr-stats { display: flex; gap: 12px; align-items: center; flex: 1; overflow: hidden; }

.stat-card {
  background: var(--bg-glass);
  border: 1px solid var(--border-light);
  border-radius: 8px;
  padding: 6px 12px;
  display: flex;
  flex-direction: column;
  min-width: 80px;
  transition: var(--transition-fast);
}
.stat-card:hover { border-color: var(--accent); background: rgba(0, 245, 255, 0.05); }
.stat-label { font-size: 9px; color: var(--text-dim); text-transform: uppercase; font-weight: 600; }
.stat-value { font-size: 13px; font-weight: 700; color: var(--text-primary); font-family: 'JetBrains Mono'; }
.stat-value.accent { color: var(--accent); }

#prog-wrap { 
  flex: 1; 
  max-width: 140px; 
  height: 4px; 
  background: rgba(255, 255, 255, 0.05); 
  border-radius: 2px; 
  overflow: hidden; 
}
#prog-bar { 
  height: 100%; 
  background: linear-gradient(90deg, var(--emerald), var(--accent));
  box-shadow: 0 0 8px var(--emerald-glow);
  width: 0%; 
  transition: width 0.6s cubic-bezier(0.34, 1.56, 0.64, 1); 
}

#sector-badge {
  background: rgba(255, 102, 0, 0.1);
  border: 1px solid rgba(255, 102, 0, 0.3);
  border-left-width: 4px;
  color: #ff9d5c;
  border-radius: 6px;
  padding: 8px 16px;
  font-size: 11px;
  font-weight: 600;
}

#hdr-right { display: flex; gap: 12px; align-items: center; }
.btn-premium {
  background: var(--bg-glass);
  border: 1px solid var(--border-light);
  color: var(--text-secondary);
  padding: 8px 16px;
  border-radius: 8px;
  font-size: 11px;
  font-weight: 700;
  cursor: pointer;
  transition: var(--transition-fast);
  text-transform: uppercase;
  letter-spacing: 0.02em;
}
.btn-premium:hover {
  background: var(--accent);
  color: var(--bg-deep);
  border-color: var(--accent);
  box-shadow: 0 0 16px var(--accent-glow);
}

#hdr-badge {
  padding: 6px 14px;
  border-radius: 20px;
  font-size: 10px;
  font-weight: 800;
  background: rgba(255, 255, 255, 0.03);
  color: var(--text-dim);
  border: 1px solid var(--border-light);
  text-transform: uppercase;
  letter-spacing: 0.05em;
}
#hdr-badge.active { background: rgba(0, 255, 159, 0.1); color: var(--emerald); border-color: var(--emerald); }
#hdr-badge.paused { background: rgba(255, 204, 51, 0.1); color: var(--gold); border-color: var(--gold); }
#hdr-badge.done { background: rgba(255, 42, 109, 0.1); color: var(--crimson); border-color: var(--crimson); }

/* ── Strategy Alert Overlay ─────── */
#strategy-alert-overlay {
  display: none;
  position: fixed;
  top: 0; left: 0; right: 0; bottom: 0;
  z-index: 99999;
  background: rgba(0, 0, 0, 0.88);
  align-items: center;
  justify-content: center;
  backdrop-filter: blur(4px);
}
#strategy-alert-box {
  background: #0a1120;
  border: 2px solid #ff6b35;
  border-radius: 12px;
  padding: 36px 40px;
  max-width: 640px;
  width: 90%;
  text-align: center;
  box-shadow: 0 0 60px rgba(255, 107, 53, 0.35), 0 0 120px rgba(255, 107, 53, 0.1);
  animation: saSlideIn 0.4s cubic-bezier(0.34, 1.56, 0.64, 1);
}
@keyframes saSlideIn {
  from { transform: scale(0.85) translateY(-20px); opacity: 0; }
  to   { transform: scale(1) translateY(0);        opacity: 1; }
}
@keyframes saBlink {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.25; }
}
#sa-warning-header {
  color: #ff6b35;
  font-size: 11px;
  font-weight: 800;
  letter-spacing: 0.18em;
  text-transform: uppercase;
  margin-bottom: 6px;
  font-family: 'JetBrains Mono', monospace;
}
#sa-title {
  color: #ffffff;
  font-size: 22px;
  font-weight: 900;
  letter-spacing: 0.06em;
  margin-bottom: 6px;
  text-transform: uppercase;
}
#sa-sector {
  color: #888;
  font-size: 11px;
  font-family: 'JetBrains Mono', monospace;
  margin-bottom: 20px;
  letter-spacing: 0.06em;
}
#sa-reason {
  color: #aaa;
  font-size: 12px;
  line-height: 1.6;
  margin-bottom: 24px;
  text-align: left;
  background: rgba(255, 107, 53, 0.04);
  border-left: 3px solid rgba(255, 107, 53, 0.4);
  padding: 10px 14px;
  border-radius: 0 6px 6px 0;
}
.sa-formation-cards {
  display: flex;
  gap: 20px;
  justify-content: center;
  align-items: center;
  margin-bottom: 22px;
}
.sa-card {
  flex: 1;
  background: rgba(255,255,255,0.03);
  border: 1px solid rgba(255,255,255,0.08);
  border-radius: 8px;
  padding: 14px 16px;
}
.sa-card.old { border-color: rgba(255, 68, 68, 0.4); }
.sa-card.new { border-color: rgba(0, 255, 136, 0.4); }
.sa-card-label { font-size: 9px; color: #555; letter-spacing: 0.12em; text-transform: uppercase; margin-bottom: 6px; font-family: 'JetBrains Mono', monospace; }
.sa-card-name { font-size: 14px; font-weight: 800; letter-spacing: 0.05em; }
.sa-card.old .sa-card-name { color: #ff4444; }
.sa-card.new .sa-card-name { color: #00ff88; }
.sa-card-detail { font-size: 10px; color: #666; margin-top: 4px; font-family: 'JetBrains Mono', monospace; }
.sa-arrow { font-size: 24px; color: #ff6b35; flex-shrink: 0; }
#sa-efficiency {
  color: #00ff88;
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.08em;
  margin-bottom: 20px;
  font-family: 'JetBrains Mono', monospace;
}
#sa-hold-text {
  color: #ff6b35;
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.1em;
  text-transform: uppercase;
  animation: saBlink 1s infinite;
  margin-bottom: 14px;
}
#sa-syslog {
  background: #050c1a;
  border: 1px solid rgba(255, 107, 53, 0.2);
  border-radius: 6px;
  padding: 10px 14px;
  font-size: 11px;
  color: #666;
  font-family: 'JetBrains Mono', monospace;
  text-align: left;
  transition: color 0.5s;
}

/* ── Formation Badge (in CMD sidebar) ── */
#formation-badge {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 2px 9px;
  background: rgba(0,136,255,0.08);
  border: 1px solid rgba(0,136,255,0.25);
  border-radius: 4px;
  font-size: 9px;
  font-weight: 700;
  letter-spacing: 0.08em;
  font-family: 'JetBrains Mono', monospace;
  transition: all 0.4s ease;
}
#formation-badge.fan-spread {
  background: rgba(255, 107, 53, 0.1);
  border-color: rgba(255, 107, 53, 0.4);
}
#formation-badge-label { color: var(--text-dim); }
#formation-badge-text  { color: var(--accent); }

/* ── Battery Plan Panel ─────── */
.batt-plan-card {
  background: rgba(255,255,255,0.02);
  border: 1px solid rgba(255,255,255,0.06);
  border-radius: 6px;
  padding: 8px 10px;
  font-family: 'JetBrains Mono', monospace;
  font-size: 10px;
  color: var(--text-dim);
  margin-bottom: 4px;
}
.batt-plan-row { display:flex; justify-content:space-between; margin-bottom: 3px; }
.batt-plan-label { color: #555; }
.batt-plan-val { font-weight: 700; }
.batt-plan-val.ok      { color: var(--emerald); }
.batt-plan-val.warn    { color: var(--gold); }
.batt-plan-val.danger  { color: var(--crimson); }
.batt-rec {
  margin-top: 6px;
  padding: 4px 8px;
  border-radius: 4px;
  font-size: 10px;
  font-weight: 800;
  letter-spacing: 0.08em;
  text-align: center;
}
.batt-rec.continue     { background: rgba(0,255,136,0.1); color: var(--emerald); border: 1px solid rgba(0,255,136,0.3); }
.batt-rec.return-after { background: rgba(255,204,51,0.1); color: var(--gold);   border: 1px solid rgba(255,204,51,0.3); }
.batt-rec.return-now   { background: rgba(255,42,109,0.1); color: var(--crimson);border: 1px solid rgba(255,42,109,0.3); }

/* ── View Toggle ────────────────── */
.view-toggle {
  display: flex;
  background: rgba(0,0,0,0.4);
  border: 1px solid var(--border-light);
  border-radius: 8px;
  overflow: hidden;
  margin-left: auto;
  margin-right: 12px;
}
.vt-btn {
  background: transparent;
  color: var(--text-dim);
  border: none;
  padding: 8px 16px;
  font-size: 11px;
  font-weight: 800;
  cursor: pointer;
  letter-spacing: 0.1em;
  transition: var(--transition-fast);
}
.vt-btn:hover { color: var(--text-primary); }
.vt-btn.active { background: var(--accent); color: var(--bg-deep); }

/* ── Main Layout ────────────────── */
#main { flex:1; display:flex; flex-direction:row; overflow:hidden; padding:12px; gap:12px; height: calc(100vh - 80px); }
#left-col { flex:1; display:flex; flex-direction:row; gap:12px; min-width:0; overflow:hidden; height:100%; transition: opacity 0.3s; }
#maps-row { flex:2.5; min-width:0; display:flex; }
.sidebar-panel { width: 320px; flex-shrink: 0; display: flex; flex-direction: column; }
.fpv-panel.sidebar-panel { width: 340px; }

/* ── View States ────────────────── */
#main.view-frontend #cmd-sidebar { display: none !important; }
#main.view-frontend #left-col { display: flex !important; }

#main.view-backend #left-col { display: none !important; }
#main.view-backend #cmd-sidebar {
  display: flex !important;
  width: 100% !important;
  flex-direction: column;
}
#main.view-backend #cmd-sidebar-inner {
  display: grid;
  grid-template-columns: 1fr 1fr;
  grid-template-rows: 1fr 1fr;
  gap: 12px;
  flex: 1;
  min-height: 0;
  padding: 16px;
  background: var(--bg-dark);
}
#main.view-backend .csb-section {
  max-height: none !important;
  border: 1px solid var(--border-light);
  border-radius: 8px;
  background: var(--bg-panel);
}


.map-card {
  flex: 1;
  position: relative;
  background: var(--bg-panel);
  border: 1px solid var(--border-light);
  border-radius: 12px;
  overflow: hidden;
  box-shadow: 0 8px 32px rgba(0, 0, 0, 0.3);
}
.map-el { width: 100%; height: 100%; z-index: 1; }

/* CV YOLO box overlay painted over the live tactical map */
#map-cv-canvas {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  z-index: 400;
  pointer-events: none;
}

.map-tag {
  position: absolute;
  top: 16px;
  left: 16px;
  z-index: 500;
  background: rgba(10, 17, 32, 0.85);
  backdrop-filter: blur(8px);
  color: var(--accent);
  border: 1px solid var(--border-glow);
  border-radius: 8px;
  font-size: 11px;
  font-weight: 700;
  padding: 6px 16px;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  pointer-events: none;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.5);
}

#live-status {
  position: absolute;
  bottom: 24px;
  left: 24px;
  z-index: 500;
  background: rgba(10, 17, 32, 0.85);
  backdrop-filter: blur(8px);
  border: 1px solid var(--border-light);
  border-radius: 10px;
  padding: 10px 20px;
  display: flex;
  gap: 24px;
  align-items: center;
}
.ls-item { font-size: 11px; color: var(--text-dim); font-weight: 500; }
.ls-item b { color: var(--text-primary); font-family: 'JetBrains Mono'; margin-left: 4px; }

/* ── Launch Control ─────────────── */
#launch-orbit {
  position: absolute;
  bottom: 24px;
  right: 24px;
  z-index: 500;
}
#btn-launch {
  padding: 12px 32px;
  border-radius: 12px;
  border: none;
  font-size: 14px;
  font-weight: 800;
  cursor: pointer;
  background: var(--emerald);
  color: var(--bg-deep);
  box-shadow: 0 0 24px var(--emerald-glow);
  transition: var(--transition-smooth);
  text-transform: uppercase;
  letter-spacing: 0.05em;
}
#btn-launch:hover:not(:disabled) {
  transform: translateY(-2px);
  box-shadow: 0 0 40px var(--emerald-glow);
  filter: brightness(1.1);
}
#btn-launch:active:not(:disabled) { transform: translateY(0); }
#btn-launch:disabled { opacity: 0.3; cursor: not-allowed; filter: grayscale(1); }

/* ── Bottom Infrastructure ───────── */
#bottom {
  height: 36%;
  display: flex;
  gap: 12px;
  flex-shrink: 0;
}

.infra-panel {
  flex: 1;
  display: flex;
  flex-direction: column;
  background: var(--bg-panel);
  backdrop-filter: var(--panel-blur);
  border: 1px solid var(--border-light);
  border-radius: 12px;
  overflow: hidden;
}

/* ── CMD Sidebar ─────────────────── */
#cmd-sidebar {
  width: 420px;
  flex-shrink: 0;
  display: flex;
  flex-direction: column;
  background: var(--bg-panel);
  backdrop-filter: var(--panel-blur);
  border: 1px solid var(--border-light);
  border-radius: 12px;
  overflow: hidden;
  height: 100%;
  box-shadow: -10px 0 30px rgba(0,0,0,0.4);
}
#cmd-sidebar-inner {
  display: flex;
  flex-direction: column;
  flex: 1;
  overflow: hidden;
}
#csb-hdr {
  padding: 12px 16px 10px;
  background: rgba(0,136,255,0.06);
  border-bottom: 1px solid var(--border-light);
  flex-shrink: 0;
}
#csb-title {
  font-size: 13px;
  font-weight: 800;
  color: var(--accent);
  font-family: 'Outfit', sans-serif;
  text-transform: uppercase;
  letter-spacing: 0.1em;
  margin-bottom: 8px;
  display: flex;
  align-items: center;
  gap: 8px;
}
#csb-phase {
  display: flex;
  align-items: center;
  gap: 4px;
  margin-bottom: 6px;
}
.csb-step { width: 18px; height: 18px; border-radius: 50%; border: 1px solid var(--border-light); display: flex; align-items: center; justify-content: center; font-size: 9px; font-weight: 800; color: var(--text-dim); flex-shrink: 0; transition: var(--transition-smooth); }
.csb-step.active { background: var(--accent); border-color: var(--accent); color: var(--bg-deep); box-shadow: 0 0 10px var(--accent-glow); }
.csb-step.done { border-color: var(--emerald); color: var(--emerald); }
.csb-step-line { flex: 1; height: 1px; background: var(--border-light); }
#csb-drone-label { font-size: 10px; color: var(--text-dim); font-family: 'JetBrains Mono'; }

.csb-section {
  display: flex;
  flex-direction: column;
  border-bottom: 1px solid var(--border-light);
  min-height: 0;
}
.csb-section.grows { flex: 1; overflow: hidden; }

.csb-sec-hdr {
  padding: 10px 14px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  cursor: pointer;
  flex-shrink: 0;
  user-select: none;
  transition: background var(--transition-fast);
}
.csb-sec-hdr:hover { background: rgba(255,255,255,0.03); }
.csb-sec-title { font-size: 11px; font-weight: 700; color: var(--text-secondary); letter-spacing: 0.02em; }
.csb-expand-btn {
  font-size: 9px;
  color: var(--accent);
  border: 1px solid var(--accent);
  padding: 3px 8px;
  border-radius: 6px;
  background: rgba(0, 136, 255, 0.1);
  cursor: pointer;
  transition: var(--transition-fast);
  text-transform: uppercase;
  font-weight: 800;
}
.csb-expand-btn:hover { background: var(--accent); color: var(--bg-deep); }

.csb-sec-body {
  flex: 1;
  overflow-y: auto;
  padding: 10px 14px;
  font-size: 11px;
  line-height: 1.7;
  font-family: 'JetBrains Mono', monospace;
  color: var(--emerald);
  min-height: 0;
}
.csb-sec-body.collapsed { display: none; }

/* reasoning section always shows the cursor at end */
#csb-reasoning-text { white-space: pre-wrap; word-break: break-word; }
.ai-cursor { display: inline-block; width: 2px; height: 1em; background: var(--emerald); vertical-align: text-bottom; margin-left: 1px; animation: blink-care 0.75s infinite; }
@keyframes blink-care { 50% { opacity: 0; } }
@keyframes malf-blink { 0%,100%{opacity:1;transform:translateX(-50%) scale(1)} 50%{opacity:0.2;transform:translateX(-50%) scale(1.3)} }

/* ── Drone Selector Badges ────────── */
#drone-selector {
  display: flex;
  gap: 4px;
  margin-top: 8px;
  flex-wrap: wrap;
}
.drone-badge {
  font-size: 9px;
  font-weight: 800;
  font-family: 'JetBrains Mono', monospace;
  letter-spacing: 0.05em;
  padding: 3px 8px;
  border-radius: 4px;
  border: 1px solid var(--border-light);
  background: rgba(255,255,255,0.03);
  color: var(--text-dim);
  cursor: pointer;
  transition: all 0.2s ease;
  user-select: none;
}
.drone-badge:hover {
  background: rgba(0,136,255,0.1);
  border-color: var(--accent);
  color: var(--text-secondary);
}
.drone-badge.active {
  background: var(--accent);
  border-color: var(--accent);
  color: var(--bg-deep);
  box-shadow: 0 0 8px var(--accent-glow);
}
.drone-badge.has-data {
  border-color: rgba(0,255,159,0.3);
  color: var(--emerald);
}
.drone-badge.active.has-data {
  background: var(--emerald);
  border-color: var(--emerald);
  color: var(--bg-deep);
  box-shadow: 0 0 8px var(--emerald-glow);
}
#drone-selector-hint {
  font-size: 8px;
  color: var(--text-dim);
  letter-spacing: 0.06em;
  text-transform: uppercase;
  margin-top: 3px;
}

/* ── Reasoning crossfade ──────────── */
#xpb-reasoning {
  position: relative;
}
#csb-reasoning-text {
  transition: opacity 0.3s ease;
}
#csb-reasoning-text.fading {
  opacity: 0.4;
}

/* ── Enriched reasoning formatting ── */
.reason-rule { color: var(--gold); font-weight: 700; }
.reason-ok { color: var(--emerald); }
.reason-warn { color: var(--gold); }
.reason-crit { color: var(--crimson); font-weight: 700; }
.reason-coord { color: var(--accent); }
.reason-header { color: var(--text-secondary); font-weight: 800; letter-spacing: 0.05em; text-transform: uppercase; font-size: 9px; display: block; margin-top: 6px; margin-bottom: 2px; }
.reason-divider { display: block; height: 1px; background: var(--border-light); margin: 4px 0; }

/* ── Drone activity timeline ──────── */
#drone-timeline {
  display: flex;
  gap: 3px;
  margin-bottom: 6px;
  align-items: center;
  min-height: 18px;
}
.tl-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--border-light);
  transition: all 0.3s ease;
  flex-shrink: 0;
}
.tl-dot.scan { background: var(--emerald); box-shadow: 0 0 4px var(--emerald-glow); }
.tl-dot.move { background: var(--accent); box-shadow: 0 0 4px var(--accent-glow); }
.tl-dot.recall { background: var(--crimson); }
.tl-dot.active { transform: scale(1.4); }
#tl-label {
  font-size: 8px;
  color: var(--text-dim);
  font-family: 'JetBrains Mono', monospace;
  margin-left: 6px;
  white-space: nowrap;
}

/* tool call friendly cards */
.tool-friendly {
  padding: 6px 10px;
  margin-bottom: 5px;
  background: rgba(255,255,255,0.03);
  border-left: 3px solid var(--accent);
  border-radius: 0 4px 4px 0;
  font-size: 10px;
  color: var(--text-primary);
  font-family: 'Inter', sans-serif;
  line-height: 1.5;
}
.tool-friendly .tf-icon { font-size: 14px; margin-right: 5px; }
.tool-friendly .tf-label { font-weight: 600; color: var(--accent); }
.tool-friendly .tf-result { color: var(--text-dim); font-size: 9px; margin-top: 2px; }

/* system prompt / orders */
.orders-text { font-family: 'Inter', sans-serif; font-size: 10px; color: var(--text-secondary); line-height: 1.6; white-space: pre-wrap; }

/* ── AI Chain-of-Thought Panel ─────────── */
#cot-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  margin-bottom: 10px;
  flex-wrap: wrap;
}
#cot-model-badge {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 3px 10px;
  background: linear-gradient(90deg, rgba(92,111,255,0.18), rgba(92,111,255,0.04));
  border: 1px solid rgba(92,111,255,0.45);
  border-radius: 12px;
  font-size: 9px;
  font-weight: 800;
  letter-spacing: 0.09em;
  font-family: 'JetBrains Mono', monospace;
  color: var(--indigo);
  text-transform: uppercase;
}
#cot-meta {
  display: inline-flex;
  gap: 8px;
  font-family: 'JetBrains Mono', monospace;
  font-size: 9px;
  color: var(--text-dim);
  letter-spacing: 0.06em;
}
#cot-meta span { padding: 2px 6px; border-left: 1px solid var(--border-light); }
#cot-meta span:first-child { border-left: none; padding-left: 0; }

#cot-stream { display: flex; flex-direction: column; gap: 10px; }
.cot-md-meta {
  margin-top: 8px;
  font-family: 'JetBrains Mono', monospace;
  font-size: 8.5px;
  letter-spacing: 0.08em;
  color: var(--text-dim);
}
#cot-md-render {
  margin-top: 8px;
  padding: 8px;
  border: 1px solid rgba(92,111,255,0.28);
  border-radius: 6px;
  background: rgba(92,111,255,0.05);
  max-height: 320px;
  overflow: auto;
}
#cot-md-render .mermaid { min-height: 120px; }

.cot-placeholder {
  font-size: 10.5px;
  color: var(--text-dim);
  font-style: italic;
  padding: 12px;
  text-align: center;
  font-family: 'Inter', sans-serif;
  border: 1px dashed rgba(255,255,255,0.08);
  border-radius: 6px;
}

.cot-situation {
  font-size: 11px;
  line-height: 1.55;
  color: var(--text-primary);
  font-family: 'Inter', sans-serif;
  padding: 8px 10px;
  border-left: 2px solid var(--indigo);
  background: rgba(92,111,255,0.06);
  border-radius: 3px;
}

.cot-obs-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 4px 8px;
  font-family: 'JetBrains Mono', monospace;
  font-size: 9.5px;
}
.cot-obs-row {
  display: flex;
  justify-content: space-between;
  gap: 6px;
  padding: 3px 6px;
  background: rgba(255,255,255,0.02);
  border-radius: 3px;
  border: 1px solid rgba(255,255,255,0.04);
}
.cot-obs-key { color: var(--text-dim); letter-spacing: 0.06em; text-transform: uppercase; font-size: 8.5px; }
.cot-obs-val { color: var(--text-primary); font-weight: 700; }
.cot-obs-val.ok   { color: var(--emerald); }
.cot-obs-val.warn { color: var(--gold); }
.cot-obs-val.crit { color: var(--crimson); }

.cot-section-label {
  font-family: 'JetBrains Mono', monospace;
  font-size: 8.5px;
  font-weight: 800;
  letter-spacing: 0.14em;
  color: var(--text-dim);
  text-transform: uppercase;
  margin-top: 2px;
  display: flex;
  align-items: center;
  gap: 6px;
}
.cot-section-label::after {
  content: '';
  flex: 1;
  height: 1px;
  background: linear-gradient(90deg, var(--border-light), transparent);
}

.cot-thoughts {
  position: relative;
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding-left: 6px;
}
.cot-thoughts::before {
  content: '';
  position: absolute;
  left: 16px; top: 10px; bottom: 10px;
  width: 2px;
  background: linear-gradient(180deg, var(--indigo), rgba(92,111,255,0.15));
  border-radius: 1px;
}
.cot-thought {
  position: relative;
  display: flex;
  align-items: flex-start;
  gap: 10px;
  opacity: 0;
  transform: translateX(-6px);
  animation: cot-thought-in 0.35s ease forwards;
}
@keyframes cot-thought-in {
  to { opacity: 1; transform: translateX(0); }
}
.cot-thought-num {
  position: relative;
  z-index: 1;
  flex: 0 0 22px;
  width: 22px;
  height: 22px;
  border-radius: 50%;
  background: radial-gradient(circle at 30% 30%, #7d8dff, var(--indigo));
  color: #fff;
  font-family: 'JetBrains Mono', monospace;
  font-size: 10px;
  font-weight: 800;
  display: flex;
  align-items: center;
  justify-content: center;
  box-shadow: 0 0 12px rgba(92,111,255,0.55);
  margin-top: 1px;
}
.cot-thought-body {
  flex: 1;
  font-family: 'Inter', sans-serif;
  font-size: 11.5px;
  line-height: 1.55;
  color: var(--text-primary);
  padding: 4px 2px 4px 0;
}
.cot-thought-body b,
.cot-thought-body strong { color: #fff; font-weight: 700; }

.cot-decision {
  font-family: 'Inter', sans-serif;
  font-size: 11.5px;
  font-weight: 600;
  line-height: 1.5;
  color: #0a1220;
  background: linear-gradient(90deg, var(--emerald), #4affa1);
  padding: 8px 12px;
  border-radius: 4px;
  box-shadow: 0 2px 12px rgba(0,255,159,0.25);
}
.cot-decision::before {
  content: '⚡ DECISION  ';
  font-family: 'JetBrains Mono', monospace;
  font-size: 8.5px;
  font-weight: 900;
  letter-spacing: 0.14em;
  opacity: 0.75;
  margin-right: 4px;
}
.cot-next {
  font-family: 'Inter', sans-serif;
  font-size: 10.5px;
  line-height: 1.5;
  color: var(--text-secondary);
  padding: 6px 10px;
  border-left: 2px solid var(--gold);
  background: rgba(255,200,80,0.05);
  border-radius: 3px;
}
.cot-next::before {
  content: '→ NEXT  ';
  font-family: 'JetBrains Mono', monospace;
  font-size: 8.5px;
  font-weight: 900;
  letter-spacing: 0.14em;
  color: var(--gold);
  margin-right: 4px;
}

#cot-raw-toggle {
  margin-top: 4px;
  padding: 4px 8px;
  font-family: 'JetBrains Mono', monospace;
  font-size: 8.5px;
  font-weight: 700;
  letter-spacing: 0.1em;
  color: var(--text-dim);
  cursor: pointer;
  user-select: none;
  border-top: 1px solid var(--border-light);
  text-transform: uppercase;
  transition: color 0.15s ease;
}
#cot-raw-toggle:hover { color: var(--emerald); }

#cot-raw {
  font-family: 'JetBrains Mono', monospace;
  font-size: 10px;
  line-height: 1.55;
  color: var(--emerald);
  white-space: pre-wrap;
  word-break: break-word;
  padding: 8px 10px;
  background: rgba(0,255,159,0.03);
  border: 1px solid rgba(0,255,159,0.12);
  border-radius: 3px;
  max-height: 260px;
  overflow-y: auto;
}

.cot-spinner {
  display: inline-block;
  width: 10px;
  height: 10px;
  border: 2px solid var(--indigo);
  border-top-color: transparent;
  border-radius: 50%;
  animation: cot-spin 0.8s linear infinite;
  vertical-align: middle;
}
@keyframes cot-spin { to { transform: rotate(360deg); } }

.cot-thinking {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px;
  border: 1px solid rgba(92,111,255,0.2);
  background: rgba(92,111,255,0.05);
  border-radius: 4px;
  font-family: 'JetBrains Mono', monospace;
  font-size: 10px;
  color: var(--indigo);
  letter-spacing: 0.05em;
}
.cot-thinking .cot-dots::after {
  content: '';
  animation: cot-dots 1.2s steps(4, end) infinite;
}
@keyframes cot-dots { 0%{content:''} 25%{content:'.'} 50%{content:'..'} 75%{content:'...'} }

.cot-error {
  padding: 10px;
  border: 1px solid rgba(255,60,90,0.35);
  background: rgba(255,60,90,0.06);
  color: var(--crimson);
  border-radius: 4px;
  font-family: 'JetBrains Mono', monospace;
  font-size: 10px;
}

/* Expand modal overlay */
#expand-modal {
  display: none;
  position: fixed;
  inset: 0;
  z-index: 9000;
  background: rgba(2, 6, 18, 0.92);
  backdrop-filter: blur(12px);
  padding: 40px;
  align-items: center;
  justify-content: center;
}
#expand-modal.open { display: flex; }
#modal-box {
  background: var(--bg-dark);
  border: 1px solid var(--border-glow);
  border-radius: 16px;
  width: 100%;
  max-width: 860px;
  max-height: 80vh;
  display: flex;
  flex-direction: column;
  box-shadow: 0 0 80px rgba(0,136,255,0.15);
}
#modal-hdr {
  padding: 16px 20px;
  border-bottom: 1px solid var(--border-light);
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-shrink: 0;
}
#modal-title { font-size: 14px; font-weight: 800; color: var(--accent); font-family: 'Outfit'; text-transform: uppercase; letter-spacing: 0.08em; }
#modal-close { background: none; border: 1px solid var(--border-light); color: var(--text-dim); padding: 4px 12px; border-radius: 6px; cursor: pointer; font-size: 12px; transition: var(--transition-fast); }
#modal-close:hover { border-color: var(--crimson); color: var(--crimson); }
#modal-content {
  flex: 1;
  overflow-y: auto;
  padding: 20px;
  font-size: 12px;
  line-height: 1.8;
  font-family: 'JetBrains Mono', monospace;
  white-space: pre-wrap;
  color: var(--emerald);
  word-break: break-word;
}

.panel-hdr {
  padding: 12px 16px;
  font-size: 12px;
  font-weight: 800;
  color: var(--accent);
  background: rgba(255, 255, 255, 0.02);
  border-bottom: 1px solid var(--border-light);
  display: flex;
  align-items: center;
  justify-content: space-between;
  text-transform: uppercase;
  letter-spacing: 0.08em;
  font-family: 'Outfit';
}
.panel-hdr .badge {
  font-size: 10px;
  background: rgba(0, 245, 255, 0.1);
  border: 1px solid var(--border-glow);
  padding: 2px 8px;
  border-radius: 4px;
  color: var(--accent);
  font-family: 'JetBrains Mono';
}

.panel-body {
  flex: 1;
  overflow-y: auto;
  padding: 12px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

/* ── Rescue Metrics Panel ───────── */
.metrics-panel { gap: 12px; padding: 14px; }

/* Hero donut */
.metrics-hero {
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 12px 14px;
  background: radial-gradient(circle at 20% 20%, rgba(0,245,255,0.08), rgba(0,136,255,0.02));
  border: 1px solid var(--border-light);
  border-radius: 12px;
}
.metrics-donut {
  position: relative;
  width: 96px;
  height: 96px;
  flex-shrink: 0;
}
.metrics-donut svg {
  width: 100%;
  height: 100%;
  transform: rotate(-90deg);
}
.metrics-donut-track {
  fill: none;
  stroke: rgba(255,255,255,0.07);
  stroke-width: 9;
}
.metrics-donut-fill {
  fill: none;
  stroke: url(#metrics-donut-grad);
  stroke-width: 9;
  stroke-linecap: round;
  transition: stroke-dashoffset 0.6s cubic-bezier(.2,.8,.2,1);
  filter: drop-shadow(0 0 6px var(--accent-glow));
}
.metrics-donut-fill.done { stroke: url(#metrics-donut-done); }
.metrics-donut-center {
  position: absolute;
  inset: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 1px;
}
.metrics-donut-pct {
  font-family: 'Outfit', 'Inter', sans-serif;
  font-size: 22px;
  font-weight: 800;
  color: var(--text-primary);
  line-height: 1;
  letter-spacing: -0.02em;
}
.metrics-donut-cap {
  font-family: 'JetBrains Mono', monospace;
  font-size: 8px;
  letter-spacing: 0.14em;
  color: var(--text-dim);
  text-transform: uppercase;
}
.metrics-hero-right {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 6px;
  min-width: 0;
}
.metrics-hero-headline {
  display: flex;
  align-items: baseline;
  gap: 6px;
  font-family: 'Outfit', 'Inter', sans-serif;
}
.metrics-hero-big {
  font-size: 26px;
  font-weight: 800;
  color: var(--emerald);
  line-height: 1;
  letter-spacing: -0.02em;
}
.metrics-hero-slash {
  font-family: 'JetBrains Mono', monospace;
  font-size: 13px;
  color: var(--text-dim);
}
.metrics-hero-total {
  font-family: 'JetBrains Mono', monospace;
  font-size: 13px;
  color: var(--text-secondary);
  font-weight: 700;
}
.metrics-hero-label {
  font-size: 8.5px;
  letter-spacing: 0.14em;
  color: var(--text-dim);
  text-transform: uppercase;
  font-weight: 700;
  font-family: 'JetBrains Mono', monospace;
}
.metrics-rescued-bar {
  position: relative;
  height: 4px;
  border-radius: 3px;
  background: rgba(255,255,255,0.05);
  overflow: hidden;
}
.metrics-rescued-bar > div {
  position: absolute; inset: 0 auto 0 0;
  width: 0%;
  background: linear-gradient(90deg, var(--emerald), #6bffb3);
  box-shadow: 0 0 6px rgba(0,255,159,0.4);
  transition: width 0.5s cubic-bezier(.2,.8,.2,1);
}
.metrics-rescued-line {
  display: flex;
  justify-content: space-between;
  font-family: 'JetBrains Mono', monospace;
  font-size: 9px;
  color: var(--text-dim);
  letter-spacing: 0.08em;
  text-transform: uppercase;
}
.metrics-rescued-line b { color: var(--emerald); font-weight: 800; }

/* Tile grid */
.metrics-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 8px;
}
.metric-card {
  position: relative;
  background: rgba(255,255,255,0.02);
  border: 1px solid var(--border-light);
  border-radius: 8px;
  padding: 9px 11px;
  display: flex;
  flex-direction: column;
  gap: 4px;
  transition: var(--transition-smooth);
  overflow: hidden;
}
.metric-card:hover {
  border-color: var(--border-glow);
  background: rgba(0,245,255,0.04);
}
.metric-card.critical-alert {
  border-color: rgba(255,60,90,0.55);
  background: rgba(255,60,90,0.06);
  animation: metric-critical-pulse 1.8s ease-in-out infinite;
}
@keyframes metric-critical-pulse {
  0%, 100% { box-shadow: 0 0 0 0 rgba(255,60,90,0.35); }
  50%      { box-shadow: 0 0 0 4px rgba(255,60,90,0); }
}
.metric-label {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: 8.5px;
  color: var(--text-dim);
  text-transform: uppercase;
  letter-spacing: 0.1em;
  font-weight: 700;
  font-family: 'JetBrains Mono', monospace;
}
.metric-value {
  font-size: 20px;
  font-weight: 800;
  color: var(--text-primary);
  font-family: 'JetBrains Mono', monospace;
  line-height: 1;
  letter-spacing: -0.01em;
}
.metric-value.accent  { color: var(--accent); }
.metric-value.emerald { color: var(--emerald); }
.metric-value.crimson { color: var(--crimson); }
.metric-value.gold    { color: #ffc850; }

.metric-sub {
  font-size: 9px;
  color: var(--text-dim);
  font-family: 'JetBrains Mono', monospace;
  letter-spacing: 0.05em;
  line-height: 1.2;
}
.metric-sub .up   { color: var(--emerald); font-weight: 800; }
.metric-sub .down { color: var(--crimson); font-weight: 800; }
.metric-sub .warn { color: var(--gold, #ffc850); font-weight: 800; }

.metric-delta {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  padding: 1px 5px;
  border-radius: 8px;
  font-family: 'JetBrains Mono', monospace;
  font-size: 8.5px;
  font-weight: 800;
  letter-spacing: 0.04em;
  background: rgba(0,255,159,0.1);
  color: var(--emerald);
  border: 1px solid rgba(0,255,159,0.2);
}
.metric-delta.neg {
  background: rgba(255,60,90,0.08);
  color: var(--crimson);
  border-color: rgba(255,60,90,0.2);
}
.metric-delta.zero {
  background: rgba(255,255,255,0.04);
  color: var(--text-dim);
  border-color: var(--border-light);
}

/* Fleet battery mini-bars */
.fleet-batt-bars {
  display: flex;
  gap: 3px;
  align-items: flex-end;
  height: 22px;
  margin-top: 2px;
}
.fleet-batt-bars .fbb {
  flex: 1;
  min-width: 4px;
  height: 100%;
  border-radius: 2px 2px 1px 1px;
  background: rgba(255,255,255,0.06);
  position: relative;
  overflow: hidden;
}
.fleet-batt-bars .fbb::after {
  content: '';
  position: absolute;
  left: 0; right: 0; bottom: 0;
  height: var(--lvl, 0%);
  background: linear-gradient(180deg, var(--emerald), #38d98a);
  transition: height 0.5s cubic-bezier(.2,.8,.2,1), background 0.3s ease;
}
.fleet-batt-bars .fbb.warn::after { background: linear-gradient(180deg, #ffc850, #f59e0b); }
.fleet-batt-bars .fbb.crit::after { background: linear-gradient(180deg, #ff3c5a, #b91c1c); }

/* Rescue-metrics replacement-cycle strip (replaces old malfunction mini-bars) */
.rm-cycle-strip {
  display: grid;
  grid-template-columns: 1fr 14px 1fr 14px 1fr 14px 1fr;
  align-items: center;
  gap: 4px;
  margin-top: 4px;
  margin-bottom: 4px;
}
.rm-cycle-node {
  position: relative;
  background: rgba(255,255,255,0.03);
  border: 1px solid rgba(255,255,255,0.08);
  border-radius: 6px;
  padding: 5px 4px 4px;
  text-align: center;
  transition: border-color 0.35s ease, background 0.35s ease, box-shadow 0.35s ease;
}
.rm-cycle-node.ok   { border-color: rgba(0,255,159,0.25); }
.rm-cycle-node.crit { border-color: rgba(255,60,90,0.25); }
.rm-cycle-node.pulse {
  box-shadow: 0 0 10px rgba(0,136,255,0.35), inset 0 0 8px rgba(0,136,255,0.10);
  border-color: rgba(0,136,255,0.65);
  background: rgba(0,136,255,0.08);
}
.rm-cycle-node.pulse.crit {
  box-shadow: 0 0 10px rgba(255,60,90,0.45), inset 0 0 8px rgba(255,60,90,0.12);
  border-color: rgba(255,60,90,0.75);
  background: rgba(255,60,90,0.10);
}
.rm-cycle-node.pulse.ok {
  box-shadow: 0 0 10px rgba(0,255,159,0.4), inset 0 0 8px rgba(0,255,159,0.10);
  border-color: rgba(0,255,159,0.75);
  background: rgba(0,255,159,0.08);
}
.rm-cycle-icon {
  font-size: 11px;
  line-height: 1;
  margin-bottom: 2px;
}
.rm-cycle-val {
  font-family: 'JetBrains Mono', monospace;
  font-size: 13px;
  font-weight: 800;
  color: var(--text-primary);
  line-height: 1;
}
.rm-cycle-label {
  margin-top: 2px;
  font-family: 'JetBrains Mono', monospace;
  font-size: 7px;
  letter-spacing: 0.08em;
  color: var(--text-dim);
  text-transform: uppercase;
  font-weight: 700;
}
.rm-cycle-arrow {
  height: 2px;
  background: linear-gradient(90deg, rgba(255,149,0,0.1), rgba(255,149,0,0.55), rgba(255,149,0,0.1));
  border-radius: 2px;
  position: relative;
}
.rm-cycle-arrow::after {
  content: '›';
  position: absolute;
  right: -4px;
  top: 50%;
  transform: translateY(-55%);
  font-size: 13px;
  font-weight: 800;
  color: rgba(255,149,0,0.7);
}

/* ── Operations Doctrine strip ─────────────────────────────────────── */
.ops-doctrine {
  background: linear-gradient(180deg, rgba(0,245,255,0.05), rgba(0,245,255,0.015));
  border: 1px solid rgba(0,245,255,0.18);
  border-radius: 6px;
  padding: 7px 9px 9px 9px;
  margin-bottom: 8px;
  position: relative;
}
.ops-doctrine-hdr {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 6px;
  padding-bottom: 5px;
  border-bottom: 1px dashed rgba(0,245,255,0.15);
}
.ops-doctrine-title {
  font-family: 'JetBrains Mono', monospace;
  font-size: 8px;
  letter-spacing: 0.14em;
  color: #00f5ff;
  font-weight: 700;
  text-transform: uppercase;
}
.ops-doctrine-sub {
  font-family: 'JetBrains Mono', monospace;
  font-size: 8px;
  letter-spacing: 0.08em;
  color: var(--text-dim);
  text-transform: uppercase;
  font-weight: 600;
}
.ops-doctrine-flow {
  display: grid;
  grid-template-columns: repeat(7, 1fr);
  gap: 2px;
  align-items: stretch;
  position: relative;
}
.ops-doctrine-flow::before {
  content: '';
  position: absolute;
  top: 9px;
  left: 7%;
  right: 7%;
  height: 1px;
  background: linear-gradient(90deg, rgba(0,245,255,0.08), rgba(0,245,255,0.3), rgba(0,245,255,0.08));
  z-index: 0;
}
.ops-stage {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: flex-start;
  gap: 4px;
  position: relative;
  z-index: 1;
  padding: 2px 0;
  transition: transform 0.18s ease;
}
.ops-stage-dot {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  background: rgba(30,42,58,0.9);
  border: 1px solid rgba(0,245,255,0.35);
  box-shadow: 0 0 0 2px rgba(10,14,22,0.9);
  transition: all 0.2s ease;
}
.ops-stage-lbl {
  font-family: 'JetBrains Mono', monospace;
  font-size: 7px;
  letter-spacing: 0.05em;
  color: var(--text-dim);
  font-weight: 700;
  text-transform: uppercase;
  text-align: center;
  line-height: 1.1;
  white-space: nowrap;
}
.ops-stage.active .ops-stage-dot {
  background: #00f5ff;
  border-color: #00f5ff;
  box-shadow: 0 0 0 2px rgba(10,14,22,0.9), 0 0 10px rgba(0,245,255,0.75);
  animation: ops-pulse 1.4s ease-in-out infinite;
}
.ops-stage.active .ops-stage-lbl {
  color: #00f5ff;
}
.ops-stage.done .ops-stage-dot {
  background: rgba(0,255,159,0.55);
  border-color: rgba(0,255,159,0.75);
}
@keyframes ops-pulse {
  0%, 100% { box-shadow: 0 0 0 2px rgba(10,14,22,0.9), 0 0 6px rgba(0,245,255,0.5); }
  50%      { box-shadow: 0 0 0 2px rgba(10,14,22,0.9), 0 0 14px rgba(0,245,255,0.9); }
}

/* Odometer: simple fade-on-change */
.odo-flash {
  animation: odo-flash 0.55s ease;
}
@keyframes odo-flash {
  0%   { transform: translateY(-3px); opacity: 0.4; }
  100% { transform: translateY(0);    opacity: 1; }
}

/* ── Battery Management Panel ────────────────────────────────────────── */
.bm-panel { gap: 10px; padding: 12px 14px; }

.bm-gauge {
  background: rgba(255,149,0,0.04);
  border: 1px solid rgba(255,149,0,0.18);
  border-radius: 10px;
  padding: 10px 12px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.bm-gauge-top {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  font-family: 'JetBrains Mono', monospace;
}
.bm-gauge-label {
  font-size: 9px;
  letter-spacing: 0.14em;
  font-weight: 800;
  color: var(--gold);
  text-transform: uppercase;
}
.bm-gauge-val {
  font-family: 'Outfit','Inter',sans-serif;
  font-size: 22px;
  font-weight: 800;
  color: var(--text-primary);
  letter-spacing: -0.02em;
  line-height: 1;
}
.bm-gauge-val.warn { color: var(--gold); }
.bm-gauge-val.crit { color: var(--crimson); }

.bm-gauge-track {
  position: relative;
  height: 14px;
  border-radius: 6px;
  background: rgba(255,255,255,0.05);
  overflow: hidden;
  box-shadow: inset 0 1px 0 rgba(255,255,255,0.03);
}
.bm-gauge-fill {
  position: absolute;
  top: 0; bottom: 0; left: 0;
  width: 0%;
  background: linear-gradient(90deg, var(--emerald), #6bffb3);
  box-shadow: 0 0 10px rgba(0,255,159,0.35);
  transition: width 0.55s cubic-bezier(.2,.8,.2,1), background 0.3s ease;
}
.bm-gauge-fill.warn { background: linear-gradient(90deg, #ff9500, #ffc850); box-shadow: 0 0 10px rgba(255,149,0,0.4); }
.bm-gauge-fill.crit { background: linear-gradient(90deg, #ff2a6d, #ff6b8b); box-shadow: 0 0 10px rgba(255,42,109,0.45); }

.bm-gauge-reserve {
  position: absolute;
  top: -2px; bottom: -2px;
  width: 2px;
  background: var(--crimson);
  box-shadow: 0 0 6px var(--crimson);
  opacity: 0.9;
  pointer-events: none;
}
.bm-gauge-reserve::after {
  content: 'RSV';
  position: absolute;
  top: -12px;
  left: 50%;
  transform: translateX(-50%);
  font-family: 'JetBrains Mono', monospace;
  font-size: 7.5px;
  font-weight: 800;
  letter-spacing: 0.1em;
  color: var(--crimson);
  white-space: nowrap;
}
.bm-gauge-sub {
  display: flex;
  justify-content: space-between;
  font-family: 'JetBrains Mono', monospace;
  font-size: 9px;
  color: var(--text-dim);
  letter-spacing: 0.06em;
  text-transform: uppercase;
}
.bm-gauge-sub b { color: var(--text-secondary); font-weight: 800; }

/* Per-drone roster */
.bm-roster {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.bm-row {
  display: grid;
  grid-template-columns: 52px 1fr 38px;
  align-items: center;
  gap: 8px;
  padding: 6px 8px;
  border-radius: 6px;
  background: rgba(255,255,255,0.02);
  border: 1px solid var(--border-light);
  transition: border-color 0.25s ease, background 0.25s ease;
}
.bm-row.recalling { border-color: rgba(255,42,109,0.4); background: rgba(255,42,109,0.05); }
.bm-row.return-after { border-color: rgba(255,149,0,0.4); background: rgba(255,149,0,0.05); }
.bm-row-label {
  font-family: 'JetBrains Mono', monospace;
  font-size: 10px;
  font-weight: 800;
  color: var(--text-primary);
  letter-spacing: 0.06em;
}
.bm-row-label .bm-chip {
  display: block;
  margin-top: 1px;
  font-size: 7.5px;
  letter-spacing: 0.08em;
  color: var(--text-dim);
  font-weight: 700;
}
.bm-row-label .bm-chip.crit  { color: var(--crimson); }
.bm-row-label .bm-chip.warn  { color: var(--gold); }
.bm-row-label .bm-chip.ok    { color: var(--emerald); }

.bm-bar-wrap {
  position: relative;
  height: 10px;
  border-radius: 5px;
  background: rgba(255,255,255,0.04);
  overflow: visible;
}
.bm-bar {
  position: absolute;
  top: 0; bottom: 0; left: 0;
  width: 0%;
  border-radius: 5px;
  background: linear-gradient(90deg, var(--emerald), #6bffb3);
  transition: width 0.5s cubic-bezier(.2,.8,.2,1), background 0.3s ease;
}
.bm-bar.warn { background: linear-gradient(90deg, var(--gold), #ffc850); }
.bm-bar.crit { background: linear-gradient(90deg, var(--crimson), #ff6b8b); }
.bm-proj {
  position: absolute;
  top: -2px; bottom: -2px;
  width: 2px;
  background: var(--indigo);
  box-shadow: 0 0 4px var(--indigo);
  transition: left 0.5s cubic-bezier(.2,.8,.2,1);
}
.bm-proj::after {
  content: '';
  position: absolute;
  top: 50%;
  left: 50%;
  width: 6px; height: 6px;
  border-radius: 50%;
  background: var(--indigo);
  transform: translate(-50%, -50%);
  box-shadow: 0 0 6px var(--indigo);
}
.bm-row-pct {
  font-family: 'JetBrains Mono', monospace;
  font-size: 11px;
  font-weight: 800;
  color: var(--text-primary);
  text-align: right;
  line-height: 1;
}
.bm-row-pct.warn { color: var(--gold); }
.bm-row-pct.crit { color: var(--crimson); }

.bm-empty {
  padding: 10px;
  text-align: center;
  font-size: 10px;
  font-family: 'Inter', sans-serif;
  color: var(--text-dim);
  font-style: italic;
  border: 1px dashed var(--border-light);
  border-radius: 6px;
}

/* Decision ticker */
.bm-ticker {
  display: flex;
  flex-direction: column;
  gap: 4px;
  max-height: 132px;
  overflow-y: auto;
  padding-right: 2px;
}
.bm-ticker-hdr {
  font-family: 'JetBrains Mono', monospace;
  font-size: 8.5px;
  letter-spacing: 0.14em;
  color: var(--text-dim);
  text-transform: uppercase;
  font-weight: 800;
  padding: 4px 2px;
  display: flex;
  align-items: center;
  gap: 6px;
}
.bm-ticker-hdr::after {
  content: '';
  flex: 1;
  height: 1px;
  background: linear-gradient(90deg, var(--border-light), transparent);
}
.bm-tk {
  display: grid;
  grid-template-columns: 42px 1fr auto;
  gap: 6px;
  align-items: center;
  padding: 4px 8px;
  border-radius: 4px;
  background: rgba(255,255,255,0.02);
  border-left: 2px solid var(--border-light);
  font-family: 'JetBrains Mono', monospace;
  font-size: 9.5px;
  color: var(--text-secondary);
  animation: bm-tk-in 0.3s ease;
}
@keyframes bm-tk-in {
  from { opacity: 0; transform: translateX(-4px); }
  to   { opacity: 1; transform: translateX(0); }
}
.bm-tk.continue    { border-left-color: var(--emerald); }
.bm-tk.return-after{ border-left-color: var(--gold); }
.bm-tk.return-now  { border-left-color: var(--crimson); }
.bm-tk-drone { font-weight: 800; color: var(--text-primary); letter-spacing: 0.05em; }
.bm-tk-body { color: var(--text-secondary); font-size: 9px; line-height: 1.35; }
.bm-tk-body .arrow { color: var(--text-dim); margin: 0 3px; }
.bm-tk-body b.ok   { color: var(--emerald); font-weight: 800; }
.bm-tk-body b.warn { color: var(--gold); font-weight: 800; }
.bm-tk-body b.crit { color: var(--crimson); font-weight: 800; }
.bm-tk-pill {
  font-size: 8px;
  letter-spacing: 0.1em;
  padding: 2px 6px;
  border-radius: 10px;
  font-weight: 800;
  text-transform: uppercase;
  background: rgba(255,255,255,0.05);
  color: var(--text-dim);
  white-space: nowrap;
}
.bm-tk.continue     .bm-tk-pill { background: rgba(0,255,159,0.1);  color: var(--emerald); }
.bm-tk.return-after .bm-tk-pill { background: rgba(255,149,0,0.12); color: var(--gold); }
.bm-tk.return-now   .bm-tk-pill { background: rgba(255,42,109,0.12); color: var(--crimson); }

.bm-state-bars {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 6px;
}
.bm-state-col {
  background: rgba(255,255,255,0.02);
  border: 1px solid var(--border-light);
  border-radius: 6px;
  padding: 6px 6px 5px;
}
.bm-state-col b {
  display: block;
  font-family: 'JetBrains Mono', monospace;
  font-size: 8px;
  color: var(--text-dim);
  margin-bottom: 4px;
}
.bm-state-track {
  height: 6px;
  border-radius: 4px;
  background: rgba(255,255,255,0.06);
  overflow: hidden;
}
.bm-state-fill {
  height: 100%;
  width: 0%;
  background: linear-gradient(90deg, var(--accent), var(--emerald));
  transition: width 0.45s ease;
}
.bm-state-val {
  margin-top: 4px;
  font-family: 'JetBrains Mono', monospace;
  font-size: 9px;
  color: var(--text-secondary);
  text-align: right;
}


.metrics-footer {
  margin-top: auto;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding-top: 8px;
  border-top: 1px solid var(--border-light);
  font-size: 10px;
  font-family: 'JetBrains Mono', monospace;
  color: var(--text-dim);
  letter-spacing: 0.06em;
}
.metrics-status { display: flex; align-items: center; gap: 6px; font-weight: 700; }
.metrics-status-dot {
  width: 8px; height: 8px; border-radius: 50%;
  background: var(--text-dim);
  box-shadow: 0 0 6px currentColor;
}
.metrics-status-dot.live    { background: var(--emerald); animation: pulseLive 1.4s ease-in-out infinite; }
.metrics-status-dot.paused  { background: #ffb020; }
.metrics-status-dot.done    { background: var(--accent); }
.metrics-tick b { color: var(--text-secondary); margin-left: 4px; }
@keyframes pulseLive {
  0%, 100% { opacity: 1; transform: scale(1); }
  50%      { opacity: 0.5; transform: scale(1.25); }
}

/* ── FPV Drone Camera Grid ─────── */
.fpv-grid {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 4px;
  overflow: hidden;
}
.fpv-slot {
  flex: 1;
  position: relative;
  border: 1px solid var(--border-light);
  border-radius: 6px;
  overflow: hidden;
  background: #050a14;
  min-height: 0;
}
.fpv-slot.active { border-color: var(--accent); box-shadow: 0 0 8px rgba(0,136,255,0.15); }
.fpv-map {
  width: 100%;
  height: 100%;
  position: absolute;
  inset: 0;
}
.fpv-map .maplibregl-canvas { border-radius: 5px; }
.fpv-map .maplibregl-ctrl-attrib { display: none !important; }
.fpv-map .maplibregl-ctrl { display: none !important; }
.fpv-hud {
  position: absolute;
  top: 0; left: 0; right: 0;
  z-index: 10;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 3px 8px;
  background: linear-gradient(180deg, rgba(0,0,0,0.75) 0%, transparent 100%);
  font-family: 'JetBrains Mono', monospace;
  font-size: 9px;
  font-weight: 700;
  color: var(--text-secondary);
  pointer-events: none;
  letter-spacing: 0.04em;
}
.fpv-hud .fpv-id { color: var(--accent); }
.fpv-hud .fpv-batt { font-weight: 800; }
.fpv-hud .fpv-status {
  font-size: 8px;
  padding: 1px 5px;
  border-radius: 3px;
  text-transform: uppercase;
  letter-spacing: 0.06em;
}
/* Mini-tile CV overlay — YOLO boxes and human reveal layered above the map */
.fpv-mini-cv {
  position: absolute;
  inset: 0;
  z-index: 8;
  pointer-events: none;
  border-radius: 5px;
}
.fpv-mini-cv-tag {
  position: absolute;
  left: 6px; bottom: 20px;
  z-index: 12;
  font-family: 'JetBrains Mono', monospace;
  font-size: 8px;
  font-weight: 800;
  letter-spacing: 0.08em;
  padding: 2px 6px;
  border-radius: 3px;
  background: rgba(0, 26, 22, 0.88);
  color: #00ffc8;
  border: 1px solid rgba(0, 255, 200, 0.5);
  text-shadow: 0 0 6px rgba(0,255,200,0.7);
  opacity: 0;
  transition: opacity 0.2s;
  pointer-events: none;
}
.fpv-mini-cv-tag.visible { opacity: 1; }
.fpv-mini-cv-tag.critical {
  color: #ff6b96;
  border-color: rgba(255,107,150,0.6);
  background: rgba(32, 6, 14, 0.88);
  text-shadow: 0 0 6px rgba(255,107,150,0.7);
}
.fpv-mini-cv-tag.confirmed {
  color: #00ff8c;
  border-color: rgba(0,255,140,0.7);
  background: rgba(0, 26, 12, 0.92);
  text-shadow: 0 0 8px rgba(0,255,140,0.9);
  animation: confirmedPulse 0.6s ease-out;
}
@keyframes confirmedPulse {
  0% { transform: scale(1.15); opacity: 0.5; }
  100% { transform: scale(1); opacity: 1; }
}

/* Bottom HUD bar for coordinates */
.fpv-hud-bottom {
  position: absolute;
  bottom: 0; left: 0; right: 0;
  z-index: 10;
  padding: 2px 8px;
  background: linear-gradient(0deg, rgba(0,0,0,0.7) 0%, transparent 100%);
  font-family: 'JetBrains Mono', monospace;
  font-size: 8px;
  color: var(--text-dim);
  pointer-events: none;
  display: flex;
  justify-content: space-between;
}

/* ═══════════════════════════════════════════════════════════════
   FPV COMPUTER VISION OVERLAY SYSTEM
   ═══════════════════════════════════════════════════════════════ */

/* ── Fullscreen Focus Mode ──────────────── */
#fpv-focus-overlay {
  display: none;
  position: fixed;
  inset: 0;
  z-index: 99998;
  background: #000;
  flex-direction: column;
}
#fpv-focus-overlay.active {
  display: flex;
}
#fpv-focus-map-wrap {
  flex: 1;
  position: relative;
  overflow: hidden;
}
#fpv-focus-map {
  width: 100%;
  height: 100%;
}
#fpv-focus-map .maplibregl-ctrl-attrib { display: none !important; }
#fpv-focus-map .maplibregl-ctrl { display: none !important; }

/* Focus mode CV canvas overlay */
#fpv-cv-canvas {
  position: absolute;
  inset: 0;
  z-index: 20;
  pointer-events: none;
}

/* Hidden offscreen Three.js canvas for GLB model rendering — shared by all FPV tiles */
#glb-offscreen {
  position: fixed;
  left: -9999px;
  top: -9999px;
  width: 256px;
  height: 256px;
  pointer-events: none;
}

/* Focus mode top HUD bar */
#fpv-focus-hud-top {
  position: absolute;
  top: 0; left: 0; right: 0;
  z-index: 30;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 24px;
  background: linear-gradient(180deg, rgba(0,0,0,0.85) 0%, rgba(0,0,0,0.4) 60%, transparent 100%);
  font-family: 'JetBrains Mono', monospace;
  font-size: 12px;
  color: #94a3b8;
  pointer-events: none;
}
#fpv-focus-hud-top > * { pointer-events: auto; }
.cv-hud-left { display: flex; align-items: center; gap: 16px; }
.cv-hud-right { display: flex; align-items: center; gap: 16px; }
.cv-mode-badge {
  display: flex; align-items: center; gap: 6px;
  padding: 4px 12px;
  background: rgba(0,255,136,0.08);
  border: 1px solid rgba(0,255,136,0.3);
  border-radius: 4px;
  font-size: 10px;
  font-weight: 800;
  color: #00ff88;
  letter-spacing: 0.08em;
}
.cv-mode-dot {
  width: 6px; height: 6px;
  border-radius: 50%;
  background: #00ff88;
  animation: cvDotBlink 1s ease-in-out infinite;
}
@keyframes cvDotBlink {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.2; }
}
.cv-drone-id {
  font-size: 14px;
  font-weight: 800;
  color: var(--accent);
}
.cv-batt {
  font-weight: 800;
}
.cv-coord {
  font-size: 10px;
  color: var(--text-dim);
}
.cv-frame-counter {
  font-size: 10px;
  color: var(--text-dim);
}
.cv-ts {
  font-size: 10px;
  color: #64748b;
}

/* Focus mode bottom HUD bar */
#fpv-focus-hud-bottom {
  position: absolute;
  bottom: 0; left: 0; right: 0;
  z-index: 30;
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  padding: 12px 24px;
  background: linear-gradient(0deg, rgba(0,0,0,0.85) 0%, rgba(0,0,0,0.4) 60%, transparent 100%);
  font-family: 'JetBrains Mono', monospace;
  font-size: 11px;
  color: #94a3b8;
  pointer-events: none;
}
.cv-bottom-left { display: flex; flex-direction: column; gap: 6px; }
.cv-bottom-right { display: flex; flex-direction: column; align-items: flex-end; gap: 6px; }

/* Threat level bar */
.cv-threat-bar {
  display: flex;
  align-items: center;
  gap: 8px;
}
.cv-threat-label {
  font-size: 9px;
  font-weight: 800;
  letter-spacing: 0.1em;
  color: #64748b;
}
.cv-threat-track {
  width: 180px;
  height: 6px;
  background: rgba(255,255,255,0.06);
  border-radius: 3px;
  overflow: hidden;
  position: relative;
}
.cv-threat-fill {
  height: 100%;
  width: 0%;
  border-radius: 3px;
  transition: width 1.2s cubic-bezier(0.4, 0, 0.2, 1), background 0.8s;
}
.cv-threat-fill.safe { background: linear-gradient(90deg, #00ff9f, #00cc80); width: 25%; }
.cv-threat-fill.moderate { background: linear-gradient(90deg, #ffaa00, #ff7700); width: 55%; }
.cv-threat-fill.critical { background: linear-gradient(90deg, #ff4444, #ff0044); width: 90%; }

/* Confidence readout */
.cv-confidence {
  font-size: 10px;
  color: var(--text-dim);
}
.cv-confidence-val {
  color: #00ff88;
  font-weight: 800;
}

/* Zone classification verdict */
#cv-verdict {
  position: absolute;
  top: 50%;
  left: 50%;
  transform: translate(-50%, -50%);
  z-index: 40;
  text-align: center;
  pointer-events: none;
  opacity: 0;
  transition: opacity 0.4s ease;
}
#cv-verdict.visible { opacity: 1; }
#cv-verdict-badge {
  display: inline-block;
  padding: 12px 32px;
  border-radius: 6px;
  font-family: 'Outfit', sans-serif;
  font-size: 22px;
  font-weight: 900;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  animation: cvVerdictPulse 2s ease-in-out infinite;
}
#cv-verdict-badge.critical-zone {
  background: rgba(255, 42, 109, 0.15);
  border: 2px solid rgba(255, 42, 109, 0.6);
  color: #ff2a6d;
  box-shadow: 0 0 40px rgba(255, 42, 109, 0.3);
}
#cv-verdict-badge.normal-zone {
  background: rgba(0, 255, 159, 0.1);
  border: 2px solid rgba(0, 255, 159, 0.5);
  color: #00ff9f;
  box-shadow: 0 0 40px rgba(0, 255, 159, 0.2);
}
@keyframes cvVerdictPulse {
  0%, 100% { transform: scale(1); }
  50% { transform: scale(1.03); }
}
#cv-verdict-sub {
  margin-top: 8px;
  font-family: 'JetBrains Mono', monospace;
  font-size: 11px;
  color: #94a3b8;
  letter-spacing: 0.06em;
}

/* Inference log (streaming vision-model narration) */
#cv-infer-log {
  position: absolute;
  bottom: 110px;
  left: 24px;
  z-index: 32;
  display: flex;
  flex-direction: column;
  gap: 2px;
  font-family: 'JetBrains Mono', monospace;
  font-size: 10.5px;
  pointer-events: none;
  max-width: 440px;
}
#cv-infer-log .ln {
  opacity: 0;
  transform: translateX(-8px);
  transition: opacity 0.25s ease, transform 0.25s ease;
  color: #00ff9f;
  text-shadow: 0 0 8px rgba(0,255,159,0.25);
  letter-spacing: 0.02em;
}
#cv-infer-log .ln.in { opacity: 0.92; transform: translateX(0); }
#cv-infer-log .ln .k { color: #64748b; margin-right: 4px; }
#cv-infer-log .ln .v.crit { color: #ff2a6d; }
#cv-infer-log .ln .v.ok { color: #00ff9f; }

/* Close button */
#fpv-focus-close {
  position: absolute;
  top: 16px; right: 16px;
  z-index: 50;
  background: rgba(255,255,255,0.05);
  border: 1px solid rgba(255,255,255,0.15);
  color: #94a3b8;
  width: 36px; height: 36px;
  border-radius: 8px;
  font-size: 18px;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all 0.2s;
}
#fpv-focus-close:hover {
  background: rgba(255,42,109,0.2);
  border-color: rgba(255,42,109,0.5);
  color: #ff2a6d;
}

/* Demo scan trigger button */
#cv-demo-btn {
  position: absolute;
  bottom: 16px; right: 16px;
  z-index: 50;
  background: rgba(0, 255, 136, 0.08);
  border: 1px solid rgba(0, 255, 136, 0.35);
  color: #00ff88;
  padding: 8px 20px;
  border-radius: 6px;
  font-family: 'JetBrains Mono', monospace;
  font-size: 11px;
  font-weight: 800;
  letter-spacing: 0.1em;
  cursor: pointer;
  transition: all 0.2s;
}
#cv-demo-btn:hover {
  background: rgba(0, 255, 136, 0.18);
  border-color: rgba(0, 255, 136, 0.6);
  box-shadow: 0 0 16px rgba(0, 255, 136, 0.2);
}
#cv-demo-btn:active {
  transform: scale(0.96);
}
.cv-key-hint {
  position: absolute;
  bottom: 52px; right: 16px;
  z-index: 50;
  font-family: 'JetBrains Mono', monospace;
  font-size: 9px;
  color: #475569;
  letter-spacing: 0.05em;
  pointer-events: none;
}

/* Scan progress indicator */
.cv-scan-progress {
  position: absolute;
  bottom: 60px; left: 50%;
  transform: translateX(-50%);
  z-index: 35;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 4px;
  pointer-events: none;
  opacity: 0;
  transition: opacity 0.3s;
}
.cv-scan-progress.visible { opacity: 1; }
.cv-scan-progress-label {
  font-family: 'JetBrains Mono', monospace;
  font-size: 10px;
  font-weight: 800;
  color: #00ff88;
  letter-spacing: 0.15em;
}
.cv-scan-progress-bar {
  width: 240px;
  height: 3px;
  background: rgba(255,255,255,0.06);
  border-radius: 2px;
  overflow: hidden;
}
.cv-scan-progress-fill {
  height: 100%;
  width: 0%;
  background: linear-gradient(90deg, #00ff88, #0088ff);
  box-shadow: 0 0 8px rgba(0,255,136,0.4);
  transition: width 0.15s linear;
}

/* Mini FPV slot focus button */
.fpv-focus-btn {
  position: absolute;
  top: 2px; right: 2px;
  z-index: 15;
  background: rgba(0,0,0,0.5);
  border: 1px solid rgba(255,255,255,0.1);
  color: #64748b;
  width: 20px; height: 20px;
  border-radius: 4px;
  font-size: 10px;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all 0.2s;
  pointer-events: auto;
}
.fpv-focus-btn:hover {
  background: rgba(0,136,255,0.2);
  border-color: var(--accent);
  color: var(--accent);
}

/* ── FPV Survivor-Lock Overlay ── */
.fpv-survivor-lock {
  position: absolute;
  inset: 0;
  z-index: 20;
  pointer-events: none;
  border: 2px solid transparent;
  border-radius: 5px;
  transition: border-color 0.3s;
}
.fpv-survivor-lock.active {
  border-color: #ffc850;
  box-shadow: inset 0 0 18px rgba(255,200,80,0.25), 0 0 12px rgba(255,200,80,0.3);
  animation: survivor-lock-pulse 1.1s ease-in-out infinite;
}
@keyframes survivor-lock-pulse {
  0%,100% { box-shadow: inset 0 0 18px rgba(255,200,80,0.25), 0 0 12px rgba(255,200,80,0.3); }
  50%      { box-shadow: inset 0 0 30px rgba(255,200,80,0.45), 0 0 24px rgba(255,200,80,0.5); }
}
.fpv-lock-label {
  position: absolute;
  bottom: 24px;
  left: 50%;
  transform: translateX(-50%);
  background: rgba(255,200,80,0.18);
  border: 1px solid rgba(255,200,80,0.55);
  border-radius: 4px;
  color: #ffc850;
  font-family: 'JetBrains Mono', monospace;
  font-size: 8px;
  font-weight: 800;
  letter-spacing: 0.14em;
  padding: 2px 8px;
  text-transform: uppercase;
  white-space: nowrap;
  opacity: 0;
  transition: opacity 0.3s;
  pointer-events: none;
}
.fpv-survivor-lock.active .fpv-lock-label { opacity: 1; }

/* ── RTB Event Feed ─────────────── */
#rtb-event-feed {
  display: flex;
  flex-direction: column;
  gap: 5px;
  margin-top: 8px;
  max-height: 120px;
  overflow: hidden;
}
.rtb-event-card {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 5px 9px;
  background: rgba(255,255,255,0.02);
  border: 1px solid rgba(255,255,255,0.05);
  border-left: 3px solid var(--gold);
  border-radius: 0 5px 5px 0;
  font-family: 'JetBrains Mono', monospace;
  font-size: 9px;
  color: var(--text-secondary);
  animation: rtb-slide-in 0.4s ease;
}
@keyframes rtb-slide-in {
  from { transform: translateX(-12px); opacity: 0; }
  to   { transform: translateX(0);     opacity: 1; }
}
.rtb-event-card.recall { border-left-color: var(--crimson); }
.rtb-event-card.charging { border-left-color: var(--emerald); }
.rtb-event-card.dispatch { border-left-color: var(--accent); }
.rtb-event-step { flex-shrink: 0; font-size: 12px; }
.rtb-event-body { flex: 1; min-width: 0; }
.rtb-event-drone { color: var(--gold); font-weight: 800; }
.rtb-event-card.recall .rtb-event-drone { color: var(--crimson); }
.rtb-event-card.charging .rtb-event-drone { color: var(--emerald); }
.rtb-event-card.dispatch .rtb-event-drone { color: var(--accent); }
.rtb-event-action { color: var(--text-dim); }
.rtb-event-tick { color: var(--text-dim); opacity: 0.6; font-size: 8px; margin-left: auto; flex-shrink: 0; }

/* ── Battery Management Enhanced ── */
.bm-sparkline-grid {
  display: grid;
  grid-template-columns: repeat(5, 1fr);
  gap: 6px;
  margin-top: 4px;
}
.bm-spark-cell {
  background: rgba(255,255,255,0.02);
  border: 1px solid rgba(255,255,255,0.05);
  border-radius: 5px;
  padding: 4px 5px;
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.bm-spark-label {
  font-family: 'JetBrains Mono', monospace;
  font-size: 7.5px;
  color: var(--text-dim);
  letter-spacing: 0.06em;
  text-transform: uppercase;
  text-align: center;
}
.bm-spark-val {
  font-family: 'JetBrains Mono', monospace;
  font-size: 11px;
  font-weight: 800;
  text-align: center;
  line-height: 1;
}
.bm-spark-svg {
  width: 100%;
  height: 28px;
}

.bm-kpi-row {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 8px;
  margin-top: 6px;
}
.bm-kpi-tile {
  background: rgba(255,255,255,0.02);
  border: 1px solid rgba(255,255,255,0.05);
  border-radius: 6px;
  padding: 8px 10px;
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.bm-kpi-label {
  font-family: 'JetBrains Mono', monospace;
  font-size: 8px;
  color: var(--text-dim);
  text-transform: uppercase;
  letter-spacing: 0.1em;
}
.bm-kpi-val {
  font-family: 'JetBrains Mono', monospace;
  font-size: 22px;
  font-weight: 800;
  line-height: 1;
}
.bm-kpi-val.crimson { color: var(--crimson); }
.bm-kpi-val.gold    { color: var(--gold); }
.bm-kpi-val.emerald { color: var(--emerald); }
.bm-kpi-sub {
  font-family: 'JetBrains Mono', monospace;
  font-size: 8px;
  color: var(--text-dim);
}

.bm-dispatch-timeline {
  display: flex;
  flex-direction: column;
  gap: 4px;
  max-height: 90px;
  overflow-y: auto;
  margin-top: 4px;
}
.bm-dt-entry {
  display: flex;
  align-items: center;
  gap: 6px;
  font-family: 'JetBrains Mono', monospace;
  font-size: 9px;
  color: var(--text-dim);
  padding: 3px 6px;
  background: rgba(255,255,255,0.02);
  border-radius: 3px;
  animation: rtb-slide-in 0.3s ease;
}
.bm-dt-tick { color: var(--accent); font-weight: 800; min-width: 28px; }
.bm-dt-icon { font-size: 11px; }
.bm-dt-msg  { flex: 1; color: var(--text-secondary); }

/* ── Fleet Drain Trend Chart ────────────────────────────────── */
.bm-trend-wrap {
  background: rgba(0,0,0,0.18);
  border: 1px solid rgba(255,149,0,0.15);
  border-radius: 8px;
  padding: 8px 10px 6px;
  margin-top: 4px;
}
.bm-trend-hdr {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  margin-bottom: 4px;
  font-family: 'JetBrains Mono', monospace;
}
.bm-trend-label {
  font-size: 8.5px;
  letter-spacing: 0.12em;
  font-weight: 800;
  color: var(--gold);
  text-transform: uppercase;
}
.bm-trend-val {
  font-size: 9px;
  color: var(--text-dim);
  letter-spacing: 0.06em;
}
.bm-trend-val b.delta-neg { color: var(--crimson); }
.bm-trend-val b.delta-pos { color: var(--emerald); }
.bm-trend-svg {
  width: 100%;
  height: 56px;
  display: block;
}
.bm-trend-axis {
  stroke: rgba(255,255,255,0.08);
  stroke-width: 0.5;
  stroke-dasharray: 2,2;
}
.bm-trend-thresh-rtb  { stroke: rgba(255,42,109,0.35); stroke-dasharray: 3,3; stroke-width: 0.7; }
.bm-trend-thresh-warn { stroke: rgba(255,149,0,0.30);  stroke-dasharray: 3,3; stroke-width: 0.7; }
.bm-trend-area  { fill: url(#bm-trend-grad); opacity: 0.85; }
.bm-trend-line  { fill: none; stroke: var(--emerald); stroke-width: 1.6; filter: drop-shadow(0 0 2px rgba(0,255,159,0.45)); }
.bm-trend-line.warn { stroke: var(--gold); filter: drop-shadow(0 0 2px rgba(255,149,0,0.45)); }
.bm-trend-line.crit { stroke: var(--crimson); filter: drop-shadow(0 0 2px rgba(255,42,109,0.45)); }

/* ── Replacement Cycle Diagram ──────────────────────────────── */
.bm-cycle {
  display: grid;
  grid-template-columns: repeat(5, 1fr);
  gap: 4px;
  margin-top: 4px;
  align-items: stretch;
}
.bm-cycle-node {
  position: relative;
  background: rgba(255,255,255,0.025);
  border: 1px solid rgba(255,255,255,0.06);
  border-radius: 6px;
  padding: 7px 4px 6px;
  text-align: center;
  transition: border-color 0.4s ease, background 0.4s ease, box-shadow 0.4s ease;
}
.bm-cycle-node.pulse {
  border-color: rgba(0,255,159,0.6);
  background: rgba(0,255,159,0.08);
  box-shadow: 0 0 10px rgba(0,255,159,0.25), inset 0 0 8px rgba(0,255,159,0.08);
}
.bm-cycle-node.pulse.crit {
  border-color: rgba(255,42,109,0.6);
  background: rgba(255,42,109,0.08);
  box-shadow: 0 0 10px rgba(255,42,109,0.25), inset 0 0 8px rgba(255,42,109,0.08);
}
.bm-cycle-icon {
  font-size: 13px;
  line-height: 1;
  margin-bottom: 3px;
}
.bm-cycle-label {
  font-family: 'JetBrains Mono', monospace;
  font-size: 7.5px;
  letter-spacing: 0.08em;
  color: var(--text-dim);
  text-transform: uppercase;
  font-weight: 800;
  margin-bottom: 2px;
}
.bm-cycle-val {
  font-family: 'JetBrains Mono', monospace;
  font-size: 13px;
  font-weight: 800;
  color: var(--text-primary);
  line-height: 1;
}
.bm-cycle-node:not(:last-child)::after {
  content: '›';
  position: absolute;
  right: -9px;
  top: 50%;
  transform: translateY(-50%);
  font-size: 14px;
  font-weight: 800;
  color: rgba(255,149,0,0.55);
  z-index: 2;
  pointer-events: none;
}
/* Legacy compat stubs */
.drone-card { display:none; }
.drone-row-top { display: flex; align-items: center; justify-content: space-between; }
.drone-id { font-size: 12px; font-weight: 800; color: var(--accent); font-family: 'JetBrains Mono'; }
.drone-status { font-size: 9px; font-weight: 800; padding: 2px 8px; border-radius: 4px; text-transform: uppercase; }
.drone-bars { display: none; }
.progress-bg { height: 4px; background: rgba(255, 255, 255, 0.05); border-radius: 2px; overflow: hidden; }
.progress-fill { height: 100%; border-radius: 2px; transition: width 0.4s ease; }
.drone-meta { display: none; }

/* ── Mission Intelligence (5-branch git tree) ────────────────── */
.mi-grid {
  display: grid;
  grid-template-columns: repeat(5, 1fr);
  gap: 16px;
  flex: 1;
  min-height: 0;
  overflow: hidden;
  padding: 0 4px;
}
.mi-branch {
  display: flex;
  flex-direction: column;
  min-width: 0;
  background: rgba(0,0,0,0.18);
  border-radius: 6px;
  border: 1px solid rgba(255,255,255,0.04);
  overflow: hidden;
}
.mi-branch-hdr {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 4px 6px;
  font-family: 'JetBrains Mono', monospace;
  font-size: 10px;
  font-weight: 700;
  color: var(--mi-col, var(--accent));
  background: linear-gradient(180deg, rgba(255,255,255,0.04), transparent);
  border-bottom: 2px solid var(--mi-col, var(--accent));
  letter-spacing: 0.04em;
}
.mi-branch-dot {
  width: 8px; height: 8px;
  border-radius: 50%;
  background: var(--mi-col, var(--accent));
  box-shadow: 0 0 8px var(--mi-col, var(--accent));
  flex-shrink: 0;
}
.mi-branch-label { flex: 1; }
.mi-branch-slot {
  font-size: 8px;
  opacity: 0.55;
  letter-spacing: 0.08em;
}
.mi-branch-track {
  position: relative;
  flex: 1;
  padding: 10px 4px 8px 16px;
  margin: 0 6px;
  border-left: 2px solid color-mix(in srgb, var(--mi-col, #888) 45%, transparent);
  display: flex;
  flex-direction: column-reverse;
  gap: 4px;
  overflow-y: auto;
  scrollbar-width: thin;
}
.mi-branch-track::-webkit-scrollbar { width: 3px; }
.mi-branch-track::-webkit-scrollbar-thumb { background: rgba(255,255,255,0.1); border-radius: 2px; }
.mi-branch-track::before {
  content: '';
  position: absolute;
  left: -6px;
  top: 2px;
  width: 10px;
  height: 10px;
  border-radius: 50%;
  background: var(--mi-col, var(--accent));
  border: 2px solid var(--bg-base, #0a0a0a);
  box-shadow: 0 0 8px var(--mi-col, var(--accent));
}
.mi-empty {
  font-family: 'JetBrains Mono', monospace;
  font-size: 9px;
  color: var(--text-dim);
  opacity: 0.5;
  font-style: italic;
  padding-left: 2px;
}
.mi-commit {
  position: relative;
  font-family: 'JetBrains Mono', monospace;
  font-size: 9px;
  line-height: 1.15;
  padding: 4px 5px;
  border-radius: 3px;
  background: color-mix(in srgb, var(--mi-col, #888) 16%, rgba(0,0,0,0.25));
  color: var(--text-primary);
  cursor: default;
  animation: miCommitIn 0.35s cubic-bezier(.2,.7,.3,1);
  border-left: 3px solid var(--mi-col, var(--accent));
  display: grid;
  grid-template-columns: auto 1fr;
  row-gap: 2px;
  column-gap: 4px;
  align-items: center;
}
.mi-commit:hover { background: color-mix(in srgb, var(--mi-col, #888) 28%, rgba(0,0,0,0.2)); }
.mi-commit:hover { background: rgba(255,255,255,0.06); }
.mi-commit::before {
  content: '';
  position: absolute;
  left: -20px;
  top: 50%;
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--mi-col, var(--accent));
  transform: translateY(-50%);
  box-shadow: 0 0 6px var(--mi-col, var(--accent));
  border: 2px solid var(--bg-base, #0a0a0a);
}
.mi-commit.kind-scan::before   { background: transparent; border: 2px solid var(--mi-col, var(--accent)); box-shadow: 0 0 4px var(--mi-col, var(--accent)); }
.mi-commit.kind-route::before  { background: var(--mi-col, var(--accent)); }
.mi-commit.kind-rescue::before { background: #00ff88; box-shadow: 0 0 10px #00ff88; border-color: #00ff88; }
.mi-commit.kind-recall::before,
.mi-commit.kind-crit::before   { background: var(--crimson, #ff2a6d); box-shadow: 0 0 10px var(--crimson, #ff2a6d); border-color: var(--crimson, #ff2a6d); animation: miCritPulse 1.2s ease-in-out infinite; }
.mi-commit.kind-reason::before { background: transparent; border: 2px dashed var(--mi-col, var(--accent)); box-shadow: none; }
.mi-commit.kind-cmd::before    { background: #00d9ff; border-radius: 1px; box-shadow: 0 0 8px #00d9ff; border-color: #00d9ff; transform: translateY(-50%) rotate(45deg); }
/* Default: drone-color tint. Only CRIT / RECALL override for urgency. */
.mi-commit.kind-recall,
.mi-commit.kind-crit {
  background: color-mix(in srgb, var(--crimson, #ff2a6d) 18%, color-mix(in srgb, var(--mi-col, #888) 10%, rgba(0,0,0,0.25)));
  border-left-color: var(--crimson, #ff2a6d);
}
.mi-commit-hash {
  font-size: 8px;
  color: var(--text-dim);
  opacity: 0.65;
  grid-column: 1;
  grid-row: 1;
}
.mi-commit-kind-pill {
  font-size: 8.5px;
  font-weight: 800;
  letter-spacing: 0.03em;
  padding: 2px 4px;
  border-radius: 2px;
  background: var(--mi-col, var(--accent));
  color: #000;
  text-transform: uppercase;
  grid-column: 1 / -1;
  grid-row: 2;
  text-align: center;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
/* Pills always show the drone's color; only recall/crit pill flips to red for urgency */
.mi-commit.kind-recall .mi-commit-kind-pill,
.mi-commit.kind-crit   .mi-commit-kind-pill { background: var(--crimson, #ff2a6d); color: #fff; }
.mi-commit-tick {
  font-size: 8px;
  color: var(--text-dim);
  opacity: 0.7;
  text-align: right;
  grid-column: 2;
  grid-row: 1;
}
.mi-branch-count {
  text-align: center;
  font-size: 8px;
  color: var(--text-dim);
  font-family: 'JetBrains Mono', monospace;
  padding: 3px 4px;
  border-top: 1px dashed rgba(255,255,255,0.05);
  letter-spacing: 0.05em;
  text-transform: uppercase;
}
.mi-focus {
  flex-shrink: 0;
  padding: 6px 8px;
  background: rgba(0,136,255,0.06);
  border-left: 3px solid var(--accent);
  border-radius: 3px;
  display: flex;
  align-items: center;
  gap: 8px;
  min-height: 26px;
}
.mi-focus-label {
  font-family: 'JetBrains Mono', monospace;
  font-size: 8px;
  letter-spacing: 0.1em;
  color: var(--text-dim);
  font-weight: 700;
  flex-shrink: 0;
}
.mi-focus-body {
  font-size: 11px;
  color: var(--text-primary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  flex: 1;
  font-family: 'JetBrains Mono', monospace;
}
@keyframes miCommitIn { from { opacity: 0; transform: translateX(-8px); } to { opacity: 1; transform: translateX(0); } }
@keyframes miCritPulse { 0%,100% { opacity: 1; transform: translateY(-50%) scale(1); } 50% { opacity: 0.45; transform: translateY(-50%) scale(1.25); } }

/* Skill commits expand on click to reveal the MCP tool calls that composed them */
.mi-commit-expandable { cursor: pointer; }
.mi-commit-chev {
  display: inline-block;
  margin-right: 3px;
  transition: transform 0.18s ease;
  color: var(--mi-col, var(--accent));
  opacity: 0.85;
}
.mi-commit.expanded .mi-commit-chev { transform: rotate(90deg); }
.mi-commit-sublist {
  grid-column: 1 / -1;
  grid-row: 3;
  display: none;
  flex-direction: column;
  gap: 2px;
  margin-top: 4px;
  padding: 4px 6px;
  background: rgba(0,0,0,0.35);
  border-radius: 2px;
  border-left: 2px solid color-mix(in srgb, var(--mi-col, #888) 55%, transparent);
}
.mi-commit.expanded .mi-commit-sublist { display: flex; }
.mi-commit-subrow {
  font-family: 'JetBrains Mono', monospace;
  font-size: 8.5px;
  color: var(--text-dim);
  line-height: 1.3;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.mi-tool-hit {
  color: #00ff9f;
  font-weight: 800;
}

/* ── Mission Intelligence Full View (modal) ───────────────────────────────── */
.mi-full-grid {
  display: grid;
  grid-template-columns: repeat(5, 1fr);
  gap: 12px;
  height: 100%;
}
.mi-full-branch {
  display: flex;
  flex-direction: column;
  background: rgba(0,0,0,0.3);
  border: 1px solid rgba(255,255,255,0.05);
  border-radius: 8px;
  overflow: hidden;
  min-width: 0;
}
.mi-full-hdr {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 8px 10px;
  font-family: 'JetBrains Mono', monospace;
  font-size: 12px;
  font-weight: 800;
  color: var(--mi-col, var(--accent));
  background: linear-gradient(180deg, rgba(255,255,255,0.04), transparent);
  border-bottom: 2px solid var(--mi-col, var(--accent));
  letter-spacing: 0.05em;
  flex-shrink: 0;
}
.mi-full-hdr-name { flex: 1; }
.mi-full-hdr-slot {
  font-size: 10px;
  opacity: 0.55;
  letter-spacing: 0.08em;
}
.mi-full-hdr-count {
  font-size: 10px;
  color: var(--text-dim);
  background: rgba(255,255,255,0.05);
  padding: 1px 6px;
  border-radius: 3px;
}
.mi-full-track {
  position: relative;
  padding: 12px 10px 12px 22px;
  margin: 0 4px;
  flex: 1;
  overflow-y: auto;
  border-left: 2px solid color-mix(in srgb, var(--mi-col, #888) 45%, transparent);
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.mi-full-track::before {
  content: '';
  position: absolute;
  left: -7px;
  top: 8px;
  width: 12px;
  height: 12px;
  border-radius: 50%;
  background: var(--mi-col, var(--accent));
  border: 2px solid var(--bg-base, #0a0a0a);
  box-shadow: 0 0 10px var(--mi-col, var(--accent));
}
.mi-full-empty {
  font-size: 11px;
  color: var(--text-dim);
  font-style: italic;
  opacity: 0.6;
}
.mi-full-commit {
  position: relative;
  display: grid;
  grid-template-columns: auto auto auto 1fr;
  gap: 6px;
  align-items: center;
  padding: 6px 8px;
  background: color-mix(in srgb, var(--mi-col, #888) 14%, rgba(0,0,0,0.25));
  border-left: 3px solid var(--mi-col, var(--accent));
  border-radius: 4px;
  font-family: 'JetBrains Mono', monospace;
  font-size: 11px;
}
.mi-full-commit::before {
  content: '';
  position: absolute;
  left: -18px;
  top: 50%;
  width: 10px;
  height: 10px;
  border-radius: 50%;
  background: var(--mi-col, var(--accent));
  transform: translateY(-50%);
  box-shadow: 0 0 8px var(--mi-col, var(--accent));
  border: 2px solid var(--bg-base, #0a0a0a);
}
.mi-full-commit.kind-scan::before   { background: transparent; border: 2px solid var(--mi-col, var(--accent)); }
.mi-full-commit.kind-rescue::before { background: #00ff88; border-color: #00ff88; box-shadow: 0 0 10px #00ff88; }
.mi-full-commit.kind-recall::before,
.mi-full-commit.kind-crit::before   { background: var(--crimson, #ff2a6d); border-color: var(--crimson, #ff2a6d); box-shadow: 0 0 10px var(--crimson, #ff2a6d); }
.mi-full-commit.kind-reason::before { background: transparent; border: 2px dashed var(--mi-col, var(--accent)); }
.mi-full-commit.kind-cmd::before    { background: #00d9ff; border-radius: 1px; border-color: #00d9ff; transform: translateY(-50%) rotate(45deg); }
.mi-full-commit.kind-recall,
.mi-full-commit.kind-crit   {
  background: color-mix(in srgb, var(--crimson, #ff2a6d) 20%, color-mix(in srgb, var(--mi-col, #888) 10%, rgba(0,0,0,0.25)));
  border-left-color: var(--crimson, #ff2a6d);
}
.mi-full-hash { font-size: 10px; color: var(--text-dim); opacity: 0.7; }
.mi-full-pill {
  font-size: 9px;
  font-weight: 800;
  letter-spacing: 0.05em;
  padding: 2px 5px;
  border-radius: 3px;
  background: var(--mi-col, var(--accent));
  color: #000;
  text-transform: uppercase;
}
.mi-full-commit.kind-recall .mi-full-pill,
.mi-full-commit.kind-crit   .mi-full-pill { background: var(--crimson, #ff2a6d); color: #fff; }
.mi-full-tick { font-size: 9px; color: var(--text-dim); opacity: 0.75; }
.mi-full-msg {
  font-size: 11px;
  color: var(--text-primary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

/* legacy stubs */
.log-entry, .log-time, .log-msg { display: none; }

/* ── AI X-RAY Refined ────────────── */
.xray-container {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.xray-pipeline {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 8px;
  background: rgba(0, 0, 0, 0.2);
  border-radius: 8px;
  border: 1px solid var(--border-light);
}
.step-dot {
  width: 20px;
  height: 20px;
  border-radius: 50%;
  border: 1px solid var(--border-light);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 10px;
  font-weight: 800;
  color: var(--text-dim);
  transition: var(--transition-smooth);
}
.step-dot.active { 
  background: var(--accent); 
  border-color: var(--accent); 
  color: var(--bg-deep); 
  box-shadow: 0 0 12px var(--accent-glow);
}
.step-dot.done { border-color: var(--emerald); color: var(--emerald); }

.xray-card {
  border: 1px solid var(--border-light);
  border-radius: 8px;
  overflow: hidden;
  background: rgba(0, 0, 0, 0.1);
}
.xray-card-hdr {
  background: rgba(255, 255, 255, 0.03);
  padding: 6px 12px;
  font-size: 10px;
  font-weight: 700;
  color: var(--text-secondary);
  border-bottom: 1px solid var(--border-light);
  font-family: 'JetBrains Mono';
}
.xray-card-body {
  padding: 10px;
  font-size: 11px;
  font-family: 'JetBrains Mono', monospace;
  color: var(--text-primary);
  line-height: 1.6;
  max-height: 200px;
  overflow-y: auto;
}
.xray-card-body.collapsed { display: none; }
#xpb-reasoning { color: var(--emerald); }

.cursor-blink { border-right: 2px solid var(--emerald); animation: blink-care 0.8s infinite; }
@keyframes blink-care { 50% { border-color: transparent; } }

/* ── MapLibre Customs ───────────── */
.maplibregl-map { background: #080d16 !important; }
.maplibregl-ctrl-group { border: none !important; margin: 24px !important; }
.maplibregl-ctrl-group button {
  background: rgba(13, 22, 40, 0.7) !important;
  backdrop-filter: blur(8px) !important;
  color: var(--accent) !important;
  border: 1px solid var(--border-light) !important;
  border-radius: 8px !important;
  margin-bottom: 4px !important;
}
.maplibregl-ctrl-attrib { font-size: 9px !important; opacity: 0.5; }
.maplibregl-popup-content { background: rgba(10,17,32,0.95); color: #f0f4f8; border: 1px solid rgba(255,255,255,0.08); border-radius: 8px; padding: 8px 12px; font-size: 11px; }
.maplibregl-popup-anchor-bottom .maplibregl-popup-tip { border-top-color: rgba(10,17,32,0.95); }
.maplibregl-popup-close-button { color: #94a3b8; font-size: 16px; }
.drone-marker-3d { pointer-events: auto; cursor: pointer; }
.drone-marker-3d:hover { filter: brightness(1.3); }

/* ── Scrollbars ─────────────────── */
::-webkit-scrollbar { width: 6px; height: 6px; }
::-webkit-scrollbar-track { background: transparent; }
::-webkit-scrollbar-thumb { background: var(--border-light); border-radius: 10px; }
::-webkit-scrollbar-thumb:hover { background: var(--text-dim); }

/* ── Loading Overlay ────────────── */
#loading {
  position: fixed;
  inset: 0;
  background: var(--bg-deep);
  z-index: 9999;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 24px;
}
.loader-hex { width: 60px; height: 60px; border: 4px solid var(--accent); border-top-color: transparent; border-radius: 50%; animation: spin 1s linear infinite; }
@keyframes spin { from { transform: rotate(0deg); } to { transform: rotate(360deg); } }
@keyframes firePulse {
  0%   { box-shadow: 0 0 12px rgba(255,100,0,0.75), 0 0 24px rgba(255,50,0,0.45), inset 0 -6px 10px rgba(100,0,0,0.65); transform: scale(1); }
  100% { box-shadow: 0 0 22px rgba(255,180,0,0.95), 0 0 40px rgba(255,80,0,0.70), inset 0 -6px 10px rgba(100,0,0,0.65); transform: scale(1.08); }
}
</style>
</head>
<body>

<div id="loading">
  <div class="loader-hex"></div>
  <span class="pulse mono" style="color: var(--accent); font-size: 14px; letter-spacing: 0.2em;">INITIALIZING COMMAND CENTER</span>
</div>

<!-- Header -->
<header id="hdr">
  <div id="hdr-title">
    <h1>Metro Manila Rescue</h1>
    <p>NDRRMC Strategic Command</p>
  </div>
  
  <div id="hdr-stats">
    <div class="stat-card">
      <span class="stat-label">Mission Time</span>
      <span class="stat-value mono" id="st-tick">—</span>
    </div>
    
    <div class="stat-card">
      <span class="stat-label">Neutralized</span>
      <span class="stat-value mono accent" id="st-resc">—/—</span>
    </div>
    
    <div id="prog-wrap"><div id="prog-bar"></div></div>
    
    <div class="stat-card">
      <span class="stat-label">Efficiency</span>
      <span class="stat-value mono accent"><span id="st-pct">0</span>%</span>
    </div>

    <div class="stat-card">
      <span class="stat-label">Total Dist</span>
      <span class="stat-value mono" id="st-dist">—</span>
    </div>

    <div class="stat-card">
      <span class="stat-label">RTB / Charging</span>
      <span class="stat-value mono accent" id="st-batt">—</span>
    </div>

    <div id="sector-badge">— WAITING FOR SECTOR DATA —</div>
  </div>

  <div id="view-toggle" class="view-toggle">
    <button id="btn-frontend" class="vt-btn active" onclick="switchView('frontend')">FRONTEND</button>
    <button id="btn-backend" class="vt-btn" onclick="switchView('backend')">BACKEND</button>
  </div>

  <div id="hdr-right">
    <button class="btn-premium" onclick="ctrlExport()">Export Log</button>
    <span id="hdr-badge">STANDBY</span>
  </div>
</header>

<!-- Expand Modal Overlay -->
<div id="expand-modal" onclick="closeModal()">
  <div id="modal-box" onclick="event.stopPropagation()">
    <div id="modal-hdr">
      <span id="modal-title">—</span>
      <button id="modal-close" onclick="closeModal()">✕ Close</button>
    </div>
    <div id="modal-content"></div>
  </div>
</div>

<!-- Main Mission Area -->
<div id="main" class="view-frontend">

  <!-- LEFT: Map + Fleet + Log -->
  <div id="left-col">
  
    <div class="fpv-panel sidebar-panel">
      <div class="panel-hdr">
        <span>Drone FPV</span>
        <span class="badge" id="fl-cnt">0</span>
      </div>
      <div class="fpv-grid" id="fl-body">
        <div class="fpv-slot" id="fpv-slot-0"><div class="fpv-map" id="fpv-map-0"></div><canvas class="fpv-mini-cv" id="fpv-mini-cv-0"></canvas><div class="fpv-mini-cv-tag" id="fpv-mini-cv-tag-0"></div><div class="fpv-hud" id="fpv-hud-0">STANDBY</div><div class="fpv-survivor-lock" id="fpv-lock-0"><div class="fpv-lock-label">🔒 SURVIVOR LOCK — CONFIRMING IDENTITY</div></div><button class="fpv-focus-btn" onclick="event.stopPropagation();openFpvFocus(0)" title="Expand CV View">⛶</button></div>
        <div class="fpv-slot" id="fpv-slot-1"><div class="fpv-map" id="fpv-map-1"></div><canvas class="fpv-mini-cv" id="fpv-mini-cv-1"></canvas><div class="fpv-mini-cv-tag" id="fpv-mini-cv-tag-1"></div><div class="fpv-hud" id="fpv-hud-1">STANDBY</div><div class="fpv-survivor-lock" id="fpv-lock-1"><div class="fpv-lock-label">🔒 SURVIVOR LOCK — CONFIRMING IDENTITY</div></div><button class="fpv-focus-btn" onclick="event.stopPropagation();openFpvFocus(1)" title="Expand CV View">⛶</button></div>
        <div class="fpv-slot" id="fpv-slot-2"><div class="fpv-map" id="fpv-map-2"></div><canvas class="fpv-mini-cv" id="fpv-mini-cv-2"></canvas><div class="fpv-mini-cv-tag" id="fpv-mini-cv-tag-2"></div><div class="fpv-hud" id="fpv-hud-2">STANDBY</div><div class="fpv-survivor-lock" id="fpv-lock-2"><div class="fpv-lock-label">🔒 SURVIVOR LOCK — CONFIRMING IDENTITY</div></div><button class="fpv-focus-btn" onclick="event.stopPropagation();openFpvFocus(2)" title="Expand CV View">⛶</button></div>
        <div class="fpv-slot" id="fpv-slot-3"><div class="fpv-map" id="fpv-map-3"></div><canvas class="fpv-mini-cv" id="fpv-mini-cv-3"></canvas><div class="fpv-mini-cv-tag" id="fpv-mini-cv-tag-3"></div><div class="fpv-hud" id="fpv-hud-3">STANDBY</div><div class="fpv-survivor-lock" id="fpv-lock-3"><div class="fpv-lock-label">🔒 SURVIVOR LOCK — CONFIRMING IDENTITY</div></div><button class="fpv-focus-btn" onclick="event.stopPropagation();openFpvFocus(3)" title="Expand CV View">⛶</button></div>
        <div class="fpv-slot" id="fpv-slot-4"><div class="fpv-map" id="fpv-map-4"></div><canvas class="fpv-mini-cv" id="fpv-mini-cv-4"></canvas><div class="fpv-mini-cv-tag" id="fpv-mini-cv-tag-4"></div><div class="fpv-hud" id="fpv-hud-4">STANDBY</div><div class="fpv-survivor-lock" id="fpv-lock-4"><div class="fpv-lock-label">🔒 SURVIVOR LOCK — CONFIRMING IDENTITY</div></div><button class="fpv-focus-btn" onclick="event.stopPropagation();openFpvFocus(4)" title="Expand CV View">⛶</button></div>
      </div>
    </div>

    <div id="maps-row">
      <div id="map-setup" style="display: none;"></div>
      <div class="map-card">
        <div class="map-tag live">Tactical Surface Map — Metro Manila</div>
        <div id="map-live" class="map-el"></div>
        <canvas id="map-cv-canvas"></canvas>
        <div id="live-status">
          <span class="ls-item">DRONES <b id="ls-drones">—</b></span>
          <span class="ls-item">DETECTED <b id="ls-resc">—/—</b></span>
          <span class="ls-item">TICK <b id="ls-tick">—</b></span>
        </div>
        <div id="launch-orbit">
          <button id="btn-launch" onclick="launchMission()">Initialize Mission</button>
        </div>
      </div>
    </div>

    <div class="infra-panel sidebar-panel">
      <div class="panel-hdr">
        <span>Rescue Metrics</span>
        <span class="badge" id="rm-pct-badge">0%</span>
      </div>
      <div class="panel-body metrics-panel">
        <!-- Operations Doctrine: 7-stage mission flow -->
        <div class="ops-doctrine" title="Canonical per-waypoint cycle — each stage lights when the fleet is currently in it">
          <div class="ops-doctrine-hdr">
            <span class="ops-doctrine-title">OPERATIONS DOCTRINE</span>
            <span class="ops-doctrine-sub" id="ops-doctrine-sub">standing by</span>
          </div>
          <div class="ops-doctrine-flow">
            <div class="ops-stage" id="ops-stage-0" data-stage="assign"><span class="ops-stage-dot"></span><span class="ops-stage-lbl">ASSIGN</span></div>
            <div class="ops-stage" id="ops-stage-1" data-stage="move"><span class="ops-stage-dot"></span><span class="ops-stage-lbl">MOVE</span></div>
            <div class="ops-stage" id="ops-stage-2" data-stage="thermal"><span class="ops-stage-dot"></span><span class="ops-stage-lbl">THERMAL</span></div>
            <div class="ops-stage" id="ops-stage-3" data-stage="hold"><span class="ops-stage-dot"></span><span class="ops-stage-lbl">CV HOLD</span></div>
            <div class="ops-stage" id="ops-stage-4" data-stage="confirm"><span class="ops-stage-dot"></span><span class="ops-stage-lbl">CONFIRM</span></div>
            <div class="ops-stage" id="ops-stage-5" data-stage="rescue"><span class="ops-stage-dot"></span><span class="ops-stage-lbl">RESCUE</span></div>
            <div class="ops-stage" id="ops-stage-6" data-stage="advance"><span class="ops-stage-dot"></span><span class="ops-stage-lbl">ADVANCE</span></div>
          </div>
        </div>
        <!-- Hero: donut + rescued lede -->
        <div class="metrics-hero">
          <div class="metrics-donut">
            <svg viewBox="0 0 100 100" aria-hidden="true">
              <defs>
                <linearGradient id="metrics-donut-grad" x1="0" y1="0" x2="1" y2="1">
                  <stop offset="0%"  stop-color="#00f5ff"/>
                  <stop offset="100%" stop-color="#00ff9f"/>
                </linearGradient>
                <linearGradient id="metrics-donut-done" x1="0" y1="0" x2="1" y2="1">
                  <stop offset="0%"  stop-color="#00ff9f"/>
                  <stop offset="100%" stop-color="#6bffb3"/>
                </linearGradient>
              </defs>
              <circle class="metrics-donut-track" cx="50" cy="50" r="42"/>
              <circle id="rm-donut" class="metrics-donut-fill" cx="50" cy="50" r="42"
                      stroke-dasharray="263.9" stroke-dashoffset="263.9"/>
            </svg>
            <div class="metrics-donut-center">
              <div class="metrics-donut-pct" id="rm-pct">0%</div>
              <div class="metrics-donut-cap">Detected</div>
            </div>
          </div>
          <div class="metrics-hero-right">
            <div class="metrics-hero-label">Rescued</div>
            <div class="metrics-hero-headline">
              <span class="metrics-hero-big" id="rm-rescued">0</span>
              <span class="metrics-hero-slash">/</span>
              <span class="metrics-hero-total" id="rm-total">0</span>
            </div>
            <div class="metrics-rescued-bar"><div id="rm-rescued-bar"></div></div>
            <div class="metrics-rescued-line">
              <span>Detected <b id="rm-detected">0</b></span>
              <span id="rm-rate">0.0/min</span>
            </div>
          </div>
        </div>

        <!-- Tile grid -->
        <div class="metrics-grid">
          <div class="metric-card" id="rm-card-critical">
            <div class="metric-label">
              <span>Critical</span>
              <span class="metric-delta zero" id="rm-critical-delta">·</span>
            </div>
            <div class="metric-value crimson" id="rm-critical">0</div>
            <div class="metric-sub" id="rm-critical-sub">none waiting</div>
          </div>
          <div class="metric-card">
            <div class="metric-label">
              <span>Detected</span>
              <span class="metric-delta zero" id="rm-detected-delta">·</span>
            </div>
            <div class="metric-value accent" id="rm-detected-big">0</div>
            <div class="metric-sub" id="rm-detected-sub">awaiting sweep</div>
          </div>
          <div class="metric-card">
            <div class="metric-label"><span>Elapsed</span></div>
            <div class="metric-value" id="rm-elapsed">—</div>
            <div class="metric-sub" id="rm-eta">ETA —</div>
          </div>
          <div class="metric-card">
            <div class="metric-label"><span>Active Drones</span></div>
            <div class="metric-value accent" id="rm-drones">0</div>
            <div class="metric-sub" id="rm-drones-sub">fleet idle</div>
          </div>
          <div class="metric-card" style="grid-column: 1 / -1;">
            <div class="metric-label">
              <span>🔁 Replacement Cycle</span>
              <span class="metric-delta zero" id="rm-battery">—</span>
            </div>
            <!-- Legacy bars hidden but kept so existing JS paths stay valid -->
            <div class="fleet-batt-bars" id="rm-battery-bars" style="display:none;"></div>
            <div class="rm-cycle-strip">
              <div class="rm-cycle-node" id="rmc-active">
                <div class="rm-cycle-icon">🛰</div>
                <div class="rm-cycle-val" id="rmc-active-val">0</div>
                <div class="rm-cycle-label">Active</div>
              </div>
              <div class="rm-cycle-arrow"></div>
              <div class="rm-cycle-node crit" id="rmc-rtb">
                <div class="rm-cycle-icon">↩️</div>
                <div class="rm-cycle-val" id="rmc-rtb-val">0</div>
                <div class="rm-cycle-label">RTB</div>
              </div>
              <div class="rm-cycle-arrow"></div>
              <div class="rm-cycle-node" id="rmc-charge">
                <div class="rm-cycle-icon">🔌</div>
                <div class="rm-cycle-val" id="rmc-charge-val">0</div>
                <div class="rm-cycle-label">Charging</div>
              </div>
              <div class="rm-cycle-arrow"></div>
              <div class="rm-cycle-node ok" id="rmc-replaced">
                <div class="rm-cycle-icon">🛸</div>
                <div class="rm-cycle-val" id="rmc-replaced-val">0</div>
                <div class="rm-cycle-label">Replaced</div>
              </div>
            </div>
            <div class="metric-sub" id="rm-battery-sub">fleet nominal — no recalls yet</div>
          </div>
        </div>

        <div class="metrics-footer">
          <div class="metrics-status">
            <span class="metrics-status-dot" id="rm-status-dot"></span>
            <span id="rm-status-text">STANDBY</span>
          </div>
          <div class="metrics-tick">TICK <b id="rm-tick">—</b></div>
        </div>
      </div>
    </div>

    <!-- Battery Management Panel -->
    <div class="infra-panel sidebar-panel">
      <div class="panel-hdr">
        <span>🔋 Battery Management</span>
        <span class="badge" id="bm-mode-badge">IDLE</span>
      </div>
      <div class="panel-body bm-panel">
        <!-- Fleet average gauge with safe-reserve floor -->
        <div class="bm-gauge">
          <div class="bm-gauge-top">
            <span class="bm-gauge-label">Fleet Average Battery</span>
            <span class="bm-gauge-val" id="bm-fleet-val">—</span>
          </div>
          <div class="bm-gauge-track" id="bm-fleet-track">
            <div class="bm-gauge-fill" id="bm-fleet-fill"></div>
            <div class="bm-gauge-reserve" id="bm-reserve" style="left: 50%"></div>
          </div>
          <div class="bm-gauge-sub">
            <span>drain <b id="bm-drain">2.4</b>%/km</span>
            <span>RTB threshold <b id="bm-reserve-val">50%</b></span>
            <span>max range <b id="bm-range">— km</b></span>
          </div>
        </div>

        <!-- KPI Tiles: RTB Count, Dispatches, Reserve -->
        <div class="bm-kpi-row">
          <div class="bm-kpi-tile">
            <div class="bm-kpi-label">⚡ Total RTB Events</div>
            <div class="bm-kpi-val crimson" id="bm-kpi-rtb">0</div>
            <div class="bm-kpi-sub" id="bm-kpi-rtb-sub">no recalls yet</div>
          </div>
          <div class="bm-kpi-tile">
            <div class="bm-kpi-label">🛸 New Drones Dispatched</div>
            <div class="bm-kpi-val accent" id="bm-kpi-dispatch">0</div>
            <div class="bm-kpi-sub" id="bm-kpi-dispatch-sub">replacements sent</div>
          </div>
        </div>

        <!-- Per-drone battery sparklines -->
        <div class="bm-ticker-hdr">Per-Drone Battery History</div>
        <div class="bm-sparkline-grid" id="bm-sparkline-grid"></div>

        <!-- Per-drone roster -->
        <div class="bm-roster" id="bm-roster">
          <div class="bm-empty">Waiting for drones to report in…</div>
        </div>

        <div class="bm-ticker-hdr">Fleet State Distribution</div>
        <div class="bm-state-bars" id="bm-state-bars">
          <div class="bm-state-col"><b>SWEEP</b><div class="bm-state-track"><div class="bm-state-fill" id="bm-state-sweeping"></div></div><div class="bm-state-val" id="bm-state-sweeping-val">0</div></div>
          <div class="bm-state-col"><b>SCAN</b><div class="bm-state-track"><div class="bm-state-fill" id="bm-state-scanning"></div></div><div class="bm-state-val" id="bm-state-scanning-val">0</div></div>
          <div class="bm-state-col"><b>RTB</b><div class="bm-state-track"><div class="bm-state-fill" id="bm-state-rtb"></div></div><div class="bm-state-val" id="bm-state-rtb-val">0</div></div>
          <div class="bm-state-col"><b>CHARGE</b><div class="bm-state-track"><div class="bm-state-fill" id="bm-state-charging"></div></div><div class="bm-state-val" id="bm-state-charging-val">0</div></div>
        </div>

        <!-- Fleet Drain Trend Chart (last ~60 ticks) -->
        <div class="bm-trend-wrap">
          <div class="bm-trend-hdr">
            <span class="bm-trend-label">⚡ Fleet Drain Trend</span>
            <span class="bm-trend-val" id="bm-trend-val">— · Δ <b id="bm-trend-delta">0%</b></span>
          </div>
          <svg class="bm-trend-svg" id="bm-trend-svg" viewBox="0 0 200 56" preserveAspectRatio="none">
            <defs>
              <linearGradient id="bm-trend-grad" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%"  stop-color="rgba(0,255,159,0.35)"/>
                <stop offset="55%" stop-color="rgba(0,255,159,0.10)"/>
                <stop offset="100%" stop-color="rgba(0,255,159,0.0)"/>
              </linearGradient>
            </defs>
            <line class="bm-trend-thresh-warn" x1="0" x2="200" y1="28" y2="28"/>
            <line class="bm-trend-thresh-rtb"  x1="0" x2="200" y1="42" y2="42"/>
            <line class="bm-trend-axis" x1="0" x2="200" y1="14" y2="14"/>
            <path class="bm-trend-area" id="bm-trend-area" d=""/>
            <path class="bm-trend-line" id="bm-trend-line" d=""/>
          </svg>
        </div>

        <!-- Decision ticker -->
        <div class="bm-ticker-hdr">Autonomous Energy Decisions</div>
        <div class="bm-ticker" id="bm-ticker">
          <div class="bm-empty">No battery plans evaluated yet.</div>
        </div>
      </div>
    </div>

  </div>

  <!-- RIGHT: AI Command Sidebar (full height) -->
  <div id="cmd-sidebar">

    <!-- Sidebar Header: hidden (elements preserved for JS compatibility) -->
    <div id="csb-hdr" style="display:none;">
      <div id="csb-title">
        <span id="ai-cnt" style="font-size:10px;background:rgba(0,136,255,0.15);border:1px solid var(--border-glow);padding:2px 8px;border-radius:4px;">IDLE</span>
        <span style="opacity:0.85;">SWARM COMMAND TELEMETRY</span>
      </div>
      <div id="csb-phase">
        <span class="csb-step" id="pdot-model" title="Loading AI model">M</span>
        <div class="csb-step-line"></div>
        <span class="csb-step" id="pdot-system_prompt" title="Reading mission orders">O</span>
        <div class="csb-step-line"></div>
        <span class="csb-step" id="pdot-state" title="Reviewing battlefield data">D</span>
        <div class="csb-step-line"></div>
        <span class="csb-step" id="pdot-reasoning" title="Thinking through strategy">T</span>
        <div class="csb-step-line"></div>
        <span class="csb-step" id="pdot-tool_calls" title="Executing commands">A</span>
        <div class="csb-step-line"></div>
        <span class="csb-step" id="pdot-decision" title="Final decision issued">✓</span>
      </div>
      <div style="display:flex; align-items:center; justify-content:space-between; margin-top:4px;">
        <div id="csb-drone-label" id="xray-drone-label" class="mono">AWAITING DEPLOYMENT</div>
        <div id="formation-badge">
          <span id="formation-badge-label">FORMATION:</span>
          <span id="formation-badge-text">3-2 ARC</span>
        </div>
      </div>
      <div id="drone-selector">
        <div class="drone-badge active" data-drone="ALL" onclick="selectXrayDrone('ALL')">ALL</div>
        <div class="drone-badge" data-drone="drone_21" onclick="selectXrayDrone('drone_21')">D-21</div>
        <div class="drone-badge" data-drone="drone_22" onclick="selectXrayDrone('drone_22')">D-22</div>
        <div class="drone-badge" data-drone="drone_23" onclick="selectXrayDrone('drone_23')">D-23</div>
        <div class="drone-badge" data-drone="drone_24" onclick="selectXrayDrone('drone_24')">D-24</div>
        <div class="drone-badge" data-drone="drone_25" onclick="selectXrayDrone('drone_25')">D-25</div>
        <div class="drone-badge" data-drone="CMD" onclick="selectXrayDrone('CMD')">CMD</div>
      </div>
      <div id="drone-selector-hint">Auto-rotating · Click a drone to pin</div>
    </div>

    <!-- INNER SCROLLABLE FOR SECTIONS -->
    <div id="cmd-sidebar-inner">

    <!-- Section 1: AI Chain of Thought -->
    <div class="csb-section">
      <div class="csb-sec-hdr" onclick="openModal('summary')">
        <span class="csb-sec-title">🧠 AI CHAIN OF THOUGHT</span>
        <span class="csb-expand-btn">⛶ ENLARGE</span>
      </div>
      <div class="csb-sec-body" id="xpb-tactical" style="color:var(--text-primary); background: rgba(0,0,0,0.15); border-left: none;">
        <div id="cot-header">
          <div id="cot-model-badge">AWAITING AI</div>
          <div id="cot-meta"><span id="cot-drone">—</span><span id="cot-round">—</span><span id="cot-time">—</span></div>
        </div>
        <div id="cot-stream">
          <div class="cot-placeholder">Watching the AI think… the drone's reasoning will appear here step-by-step.</div>
        </div>
        <div class="cot-md-meta" id="cot-md-meta">Markdown flowchart: waiting for AI artifact…</div>
        <div id="cot-md-render"></div>
        <div id="cot-raw-toggle" onclick="toggleCotRaw()" style="display:none;">▸ Show raw reasoning trace</div>
        <div id="cot-raw" style="display:none;"></div>
      </div>
    </div>

    <!-- Section 2: Deep Neural Trace (Technical) — MAIN, takes space -->
    <div class="csb-section grows">
      <div class="csb-sec-hdr" onclick="openModal('reasoning')">
        <span class="csb-sec-title">🧠 NEURAL REASONING TRACE</span>
        <span class="csb-expand-btn">⛶ ENLARGE</span>
      </div>
      <div class="csb-sec-body" id="xpb-reasoning">
        <div id="drone-timeline"></div>
        <span id="csb-reasoning-text" style="color:var(--emerald); word-spacing: 0.1em;">
          AWAITING NEURAL UPLINK...
        </span><span class="ai-cursor"></span>
      </div>
    </div>

    <!-- Section 2: Mission Intelligence (5 drone branch git-tree) -->
    <div class="csb-section" style="max-height:320px;">
      <div class="csb-sec-hdr" onclick="openModal('tools')">
        <span class="csb-sec-title">🌳 Mission Intelligence <span class="badge" id="log-cnt" style="margin-left:6px;">0</span></span>
        <span class="csb-expand-btn">⛶ Full view</span>
      </div>
      <div class="csb-sec-body" id="log-body" style="color:var(--text-primary); display:flex; flex-direction:column; gap:6px; overflow:hidden; padding-top:6px;">
        <div id="mi-grid" class="mi-grid">
          <div class="mi-branch" data-drone="drone_21" style="--mi-col:#FF4444;">
            <div class="mi-branch-hdr"><span class="mi-branch-dot"></span><span class="mi-branch-label">D-21</span><span class="mi-branch-slot">R1</span></div>
            <div class="mi-branch-track" id="mi-track-drone_21"><div class="mi-empty">idle</div></div>
            <div class="mi-branch-count" id="mi-count-drone_21">0 commits</div>
          </div>
          <div class="mi-branch" data-drone="drone_22" style="--mi-col:#5B8DFF;">
            <div class="mi-branch-hdr"><span class="mi-branch-dot"></span><span class="mi-branch-label">D-22</span><span class="mi-branch-slot">R2</span></div>
            <div class="mi-branch-track" id="mi-track-drone_22"><div class="mi-empty">idle</div></div>
            <div class="mi-branch-count" id="mi-count-drone_22">0 commits</div>
          </div>
          <div class="mi-branch" data-drone="drone_23" style="--mi-col:#44FF88;">
            <div class="mi-branch-hdr"><span class="mi-branch-dot"></span><span class="mi-branch-label">D-23</span><span class="mi-branch-slot">R3</span></div>
            <div class="mi-branch-track" id="mi-track-drone_23"><div class="mi-empty">idle</div></div>
            <div class="mi-branch-count" id="mi-count-drone_23">0 commits</div>
          </div>
          <div class="mi-branch" data-drone="drone_24" style="--mi-col:#FFD844;">
            <div class="mi-branch-hdr"><span class="mi-branch-dot"></span><span class="mi-branch-label">D-24</span><span class="mi-branch-slot">R4</span></div>
            <div class="mi-branch-track" id="mi-track-drone_24"><div class="mi-empty">idle</div></div>
            <div class="mi-branch-count" id="mi-count-drone_24">0 commits</div>
          </div>
          <div class="mi-branch" data-drone="drone_25" style="--mi-col:#FF66FF;">
            <div class="mi-branch-hdr"><span class="mi-branch-dot"></span><span class="mi-branch-label">D-25</span><span class="mi-branch-slot">R5</span></div>
            <div class="mi-branch-track" id="mi-track-drone_25"><div class="mi-empty">idle</div></div>
            <div class="mi-branch-count" id="mi-count-drone_25">0 commits</div>
          </div>
        </div>
        <div class="mi-focus" id="mi-focus">
          <span class="mi-focus-label">LAST ACTION</span>
          <span class="mi-focus-body" id="mi-focus-body">Awaiting mission telemetry…</span>
        </div>
      </div>
      <div id="xpb-tool_calls" style="display:none;"></div>
    </div>

    <!-- Section 3: Mission Orders (system prompt) -->
    <div class="csb-section" style="max-height:160px;">
      <div class="csb-sec-hdr" onclick="openModal('orders')">
        <span class="csb-sec-title">📋 Mission Orders</span>
        <span class="csb-expand-btn">⛶ Full view</span>
      </div>
      <div class="csb-sec-body" id="xpb-system_prompt" style="color:var(--text-dim);">
        <div class="orders-text">You are BAYANIHAN ACTUAL — the NDRRMC AI Command Officer for Operation BAYANIHAN.

SITUATION
Mw 7.4 earthquake struck the West Valley Fault at 06:47 PST. Epicentre: Marikina Valley. Structural collapse confirmed across Marikina, Pasig, Quezon City, and Taguig. Five thermal-imaging UAVs are armed and on standby at Batasan Complex Emergency Hub. This is their pre-launch readiness check.

YOUR ROLE
You are the last checkpoint before the swarm launches. Verify formation integrity, confirm battery health, and issue launch clearance. You do not move drones — you assess and authorise the autonomous sweep.

FORMATION — 3-2 RING SPLIT
  OUTER ring (1.3–2.0 km from Batasan Complex) — perimeter first, highest collapse risk
    R1, R2, R3 — OUTER ring, Sector Alpha waypoints
  MIDDLE + INNER rings (0–1.3 km) — urban core, high population density
    R4, R5 — MIDDLE + INNER ring, Sector Alpha waypoints

  All 5 drones sweep one sector together before the team advances.
  Sector rotation: Alpha (0°–72°) → Bravo (72°–144°) → Charlie (144°–216°) → Delta (216°–288°) → Echo (288°–360°)

BATTERY BEHAVIOUR
  Batteries drain at 15% per km. A 2 km outer-ring trip costs ~30%.
  When any OUTER drone drops below 50%:
    → Auto-recalled to base. A MIDDLE/INNER drone is promoted to OUTER (icon turns GOLD ⇑ PROMOTED).
    → Promoted drone receives the recalled drone's remaining waypoints.
    → Recalled drone recharges to 80% then rejoins as INNER (icon turns BLUE ⇓).

TOOL CALLING SEQUENCE
  1. get_active_drones()
     → ["drone_1", "drone_2", "drone_3", "drone_4", "drone_5"]

  2. get_all_drones_status()
     → [{"drone_id": "drone_1", "battery": 95, "status": "idle", "position": {"x": 121.0706, "y": 14.6540}}, ...]
     Rule: battery &lt; 80% = HOLD that drone from outer ring.

  3. get_sector_info()
     → {"Alpha": {"x": 121.0940, "y": 14.7200}, "Bravo": {"x": 121.1280, "y": 14.6800}, ...}

  4. get_team_sector_status()
     → {"current_sector": "Alpha", "sector_index": 1, "total_sectors": 5,
        "angle_start": 0, "angle_end": 72, "waypoints_remaining": 48,
        "drone_progress": {"drone_1": "0/16", "drone_2": "0/16", "drone_3": "0/16",
                           "drone_4": "0/8",  "drone_5": "0/8"}}

OUTPUT FORMAT
  FORMATION STATUS
    R1 [drone_id] — OUTER  — battery: XX% — READY / HOLD
    R2 [drone_id] — OUTER  — battery: XX% — READY / HOLD
    R3 [drone_id] — OUTER  — battery: XX% — READY / HOLD
    R4 [drone_id] — MIDDLE — battery: XX% — READY / HOLD
    R5 [drone_id] — INNER  — battery: XX% — READY / HOLD

  SECTOR ALPHA BRIEF
    Centre: (x, y) | Angle: 0°–72° | Total waypoints: N
    Battery cost to outer ring: ~30% (2 km × 15%/km)
    Thermal risk: LOW / MEDIUM / HIGH — justification

  LAUNCH CLEARANCE
    Status: GO / HOLD | Reason: [one sentence]</div>
      </div>
    </div>

    </div><!-- #cmd-sidebar-inner -->

    <!-- Hidden compatibility elements for xpb-state, xpb-decision -->
    <div style="display:none">
      <div id="xpb-state"></div>
      <div id="xpb-decision"></div>
      <div id="xray-drone-label"></div>
    </div>

  </div><!-- #cmd-sidebar -->

</div><!-- #main -->

<script src="https://unpkg.com/maplibre-gl@4.7.1/dist/maplibre-gl.js"></script>
<script>
'use strict';

// ══════════════════════════════════════════════════════════════════════════════
// THREE.JS GLB HUMAN MODEL RENDERER
// Renders realistic_male_character.glb to a shared offscreen canvas.
// All FPV tiles and the full-screen overlay call _drawGLBModel() to blit
// the current Three.js frame onto their Canvas2D contexts.
// ══════════════════════════════════════════════════════════════════════════════

let _glbRenderer  = null;
let _glbScene     = null;
let _glbCamera    = null;
let _glbMixer     = null;
let _glbClock     = null;
let _glbReady     = false;
let _glbModel     = null;

function _initGLBRenderer() {
  if (typeof THREE === 'undefined') { console.warn('[GLB] THREE not loaded'); return; }
  const canvas = document.getElementById('glb-offscreen');
  if (!canvas) return;

  _glbClock = new THREE.Clock();

  _glbRenderer = new THREE.WebGLRenderer({ canvas, alpha: true, antialias: true, powerPreference: 'high-performance' });
  _glbRenderer.setSize(256, 256);
  _glbRenderer.setPixelRatio(1);
  _glbRenderer.outputEncoding = THREE.sRGBEncoding;
  _glbRenderer.setClearColor(0x000000, 0);  // fully transparent background

  _glbScene = new THREE.Scene();

  _glbCamera = new THREE.PerspectiveCamera(42, 1, 0.05, 50);
  _glbCamera.position.set(0, 1.3, 2.6);
  _glbCamera.lookAt(0, 0.85, 0);

  // Cinematic lighting rig
  _glbScene.add(new THREE.AmbientLight(0xffffff, 0.55));
  const keyLight = new THREE.DirectionalLight(0xffffff, 1.5);
  keyLight.position.set(2, 3, 2);
  _glbScene.add(keyLight);
  const fillLight = new THREE.DirectionalLight(0x80cfff, 0.45);
  fillLight.position.set(-2, 1, -1);
  _glbScene.add(fillLight);
  const rimLight = new THREE.DirectionalLight(0x00ffcc, 0.3);
  rimLight.position.set(0, 2, -3);
  _glbScene.add(rimLight);

  const loader = new THREE.GLTFLoader();
  loader.load(
    '/assets/realistic_male_character.glb',
    (gltf) => {
      _glbModel = gltf.scene;
      // Auto-scale and center model inside the 256×256 viewport
      const box = new THREE.Box3().setFromObject(_glbModel);
      const size = box.getSize(new THREE.Vector3());
      const center = box.getCenter(new THREE.Vector3());
      const maxDim = Math.max(size.x, size.y, size.z);
      const scale = 1.55 / maxDim;
      _glbModel.scale.setScalar(scale);
      _glbModel.position.sub(center.multiplyScalar(scale));
      _glbModel.position.y -= box.min.y * scale;
      _glbScene.add(_glbModel);
      // Play first animation clip if available (idle/walk animation)
      if (gltf.animations && gltf.animations.length > 0) {
        _glbMixer = new THREE.AnimationMixer(_glbModel);
        _glbMixer.clipAction(gltf.animations[0]).play();
      }
      _glbReady = true;
      console.log('[GLB] realistic_male_character.glb loaded');
    },
    undefined,
    (err) => { console.warn('[GLB] Load failed:', err); }
  );

  // Dedicated RAF loop keeps the offscreen canvas animated at full speed
  (function _glbAnimate() {
    requestAnimationFrame(_glbAnimate);
    if (_glbMixer && _glbClock) _glbMixer.update(_glbClock.getDelta());
    if (_glbRenderer && _glbScene && _glbCamera) _glbRenderer.render(_glbScene, _glbCamera);
  })();
}

// Draw the GLB model onto any Canvas2D context at (cx, cy).
// `sizePx` is the desired height of the figure in canvas pixels.
// Falls back to the Canvas2D stick figure until the GLB is ready.
function _drawGLBModel(ctx, cx, cy, sizePx, alpha, critical) {
  const canvas = document.getElementById('glb-offscreen');
  if (!_glbReady || !canvas || sizePx <= 0) {
    // Fallback: Canvas2D human figure
    _cvDrawHumanFigure(ctx, cx, cy, sizePx / 22, alpha, critical);
    return;
  }
  const drawH = sizePx;
  const drawW = sizePx * 0.72;  // model is ~3:4 aspect in the 256×256 frame

  ctx.save();
  ctx.globalAlpha = alpha;
  ctx.drawImage(canvas, cx - drawW / 2, cy - drawH * 0.88, drawW, drawH);

  // Color tint overlay: cyan for normal, red-pink for critical
  ctx.globalCompositeOperation = 'screen';
  const rgb = critical ? '255,60,110' : '0,220,180';
  ctx.globalAlpha = 0.15 * alpha;
  ctx.fillStyle = `rgba(${rgb},1)`;
  ctx.fillRect(cx - drawW / 2, cy - drawH * 0.88, drawW, drawH);
  ctx.restore();

  // Ground shadow ellipse
  ctx.save();
  ctx.globalAlpha = 0.28 * alpha;
  ctx.fillStyle = 'rgba(0,0,0,0.9)';
  ctx.beginPath();
  ctx.ellipse(cx, cy, drawW * 0.38, 4, 0, 0, Math.PI * 2);
  ctx.fill();
  ctx.restore();
}

// Boot the renderer after the DOM is ready
window.addEventListener('DOMContentLoaded', () => { setTimeout(_initGLBRenderer, 120); });

// ── Geo mapping ───────────────────────────────────────────────────────────────
const GEO = { swLat:14.550, swLng:120.950, neLat:14.630, neLng:121.010, W:25, H:25 };

const gLL = (x,y) => [y, x];   // x=lng, y=lat  (for legacy compat)

// ── Team sector polygon references ───────────────────────────────────────────
const sectorPolygons = [];   // [{id, sec, idx}]
let _activeSectorIdx = -1;

// ── mapLive: declared here so all functions below can reference it safely ─────
// Assigned after maplibregl is ready (line ~1617). Using `let` avoids TDZ crash.
let mapLive;

// ── View Switching Logic ──────────────────────────────────────────────────────
function switchView(mode) {
  const main = document.getElementById('main');
  const btnFrontend = document.getElementById('btn-frontend');
  const btnBackend = document.getElementById('btn-backend');

  if (mode === 'frontend') {
    main.classList.remove('view-backend');
    main.classList.add('view-frontend');
    btnFrontend.classList.add('active');
    btnBackend.classList.remove('active');
    setTimeout(() => { mapLive.resize(); }, 300);
  } else {
    main.classList.remove('view-frontend');
    main.classList.add('view-backend');
    btnBackend.classList.add('active');
    btnFrontend.classList.remove('active');
  }
}

function updateActiveSector(teamSector) {
  if (!teamSector || !sectorPolygons.length) return;
  const idx = teamSector.sector_index != null ? teamSector.sector_index - 1 : -1;
  if (idx === _activeSectorIdx) return;
  _activeSectorIdx = idx;
  for (const {id, sec, idx: i} of sectorPolygons) {
    const active = (i === idx);
    if (mapLive.getLayer(id)) {
      mapLive.setPaintProperty(id, 'fill-opacity', active ? 0.25 : 0.05);
    }
    if (mapLive.getLayer(id + '-line')) {
      mapLive.setPaintProperty(id + '-line', 'line-opacity', active ? 0.9 : 0.3);
      mapLive.setPaintProperty(id + '-line', 'line-width', active ? 3 : 1.5);
    }
  }
  const badge = document.getElementById('sector-badge');
  if (badge && teamSector.sector_name) {
    const remaining = teamSector.waypoints_remaining ?? '?';
    const total     = teamSector.total_waypoints ?? '?';
    badge.textContent = `Sector ${teamSector.sector_index}/${teamSector.total_sectors} — ${teamSector.sector_name}  ${remaining}/${total} wps`;
    badge.style.borderLeftColor = teamSector.color || '#fff';
  }
  const fBadge    = document.getElementById('formation-badge');
  const fBadgeTxt = document.getElementById('formation-badge-text');
  const isFan = teamSector.sweep_type === 'fan';
  if (fBadge) {
    if (isFan) fBadge.classList.add('fan-spread');
    else       fBadge.classList.remove('fan-spread');
  }
  if (fBadgeTxt) {
    fBadgeTxt.textContent = isFan ? 'FAN SPREAD' : '3-2 ARC';
    fBadgeTxt.style.color = isFan ? '#ff6b35' : 'var(--accent)';
  }
}

// ── Base stations ─────────────────────────────────────────────────────────────
const BASES = {};

// ── MapLibre GL JS 3D Map Factory ─────────────────────────────────────────────
const MAP_INIT = { center:[120.980, 14.590], zoom:14, pitch:55, bearing:-15 };

// Vector building source — OpenFreeMap serves OpenMapTiles-schema PBF tiles (free, no key)
const BUILDING_SOURCE = {
  type: 'vector',
  tiles: ['https://tiles.openfreemap.org/planet/{z}/{x}/{y}.pbf'],
  maxzoom: 14,
  attribution: '&copy; <a href="https://openfreemap.org">OpenFreeMap</a>',
};

// 3D building paint — realistic materials with height-based color gradient
const BUILDING_PAINT = {
  'fill-extrusion-color': [
    'interpolate', ['linear'],
    ['coalesce', ['get', 'render_height'], ['*', ['coalesce', ['get', 'levels'], 3], 3.5], 10],
    0,    '#5a6472',   // Low buildings — concrete grey
    6,    '#636b78',
    12,   '#6d7682',
    25,   '#78828e',   // Mid-rise
    50,   '#8a939e',   // High-rise — lighter
    80,   '#6a7a92',   // Glass towers — blue-grey
    120,  '#5c6d88',
    200,  '#4e6080',   // Tallest — deep blue glass
  ],
  'fill-extrusion-height': [
    'interpolate', ['linear'], ['zoom'],
    13, 0,
    13.5, ['coalesce', ['get', 'render_height'], ['*', ['coalesce', ['get', 'levels'], 3], 3.5], 10],
  ],
  'fill-extrusion-base': [
    'interpolate', ['linear'], ['zoom'],
    13, 0,
    13.5, ['coalesce', ['get', 'render_min_height'], 0],
  ],
  'fill-extrusion-opacity': [
    'interpolate', ['linear'], ['zoom'],
    13, 0,
    14, 0.88,
    16, 0.94,
  ],
};

const MAP_STYLE = {
  version: 8,
  name: 'NDRRMC Satellite 3D',
  sources: {
    // ESRI World Imagery — free real satellite photography, no API key needed
    'esri-satellite': {
      type: 'raster',
      tiles: ['https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}'],
      tileSize: 256,
      maxzoom: 19,
      attribution: '&copy; Esri, Maxar, Earthstar Geographics',
    },
    // ESRI Transportation reference overlay — roads and labels on satellite
    'esri-transport': {
      type: 'raster',
      tiles: ['https://server.arcgisonline.com/ArcGIS/rest/services/Reference/World_Transportation/MapServer/tile/{z}/{y}/{x}'],
      tileSize: 256,
      maxzoom: 19,
    },
    'terrain-dem': {
      type: 'raster-dem',
      tiles: ['https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png'],
      tileSize: 256,
      encoding: 'terrarium',
    },
    'buildings-vec': BUILDING_SOURCE,
  },
  // Manila is a flat coastal city — terrain exaggeration creates unrealistic bumps
  // Keep the source for sky depth but disable the exaggeration effect
  terrain: { source: 'terrain-dem', exaggeration: 0 },
  // Map-anchored light: simulates the sun at a fixed angle over Manila
  light: {
    anchor: 'map',
    color: '#ffe8c0',       // Warm midday sunlight
    intensity: 0.55,
    position: [1.15, 140, 45], // azimuth 140°, altitude 45° — realistic Manila sun
  },
  layers: [
    // Real satellite imagery as base
    {
      id: 'esri-satellite-base',
      type: 'raster',
      source: 'esri-satellite',
      paint: {
        'raster-brightness-max': 0.78,
        'raster-contrast': 0.08,
        'raster-saturation': -0.15,  // Slight desaturate for tactical night-op look
      },
    },
    // Road and label overlay on top of satellite
    {
      id: 'esri-transport-overlay',
      type: 'raster',
      source: 'esri-transport',
      paint: { 'raster-opacity': 0.55 },
    },
    // 3D buildings on top
    {
      id: 'buildings-3d',
      type: 'fill-extrusion',
      source: 'buildings-vec',
      'source-layer': 'building',
      minzoom: 13,
      paint: BUILDING_PAINT,
    },
  ],
  // Atmospheric horizon for depth
  sky: {
    'sky-color': '#0d1e3a',
    'sky-horizon-blend': 0.4,
    'horizon-color': '#1e3a6a',
    'horizon-fog-blend': 0.6,
    'fog-color': '#0a1628',
    'fog-ground-blend': 0.85,
  },
};

// Create main live map
mapLive = new maplibregl.Map({
  container: 'map-live',
  style: MAP_STYLE,
  center: MAP_INIT.center,
  zoom: MAP_INIT.zoom,
  pitch: MAP_INIT.pitch,
  bearing: MAP_INIT.bearing,
  maxZoom: 18,
  antialias: true,
});

mapLive.addControl(new maplibregl.NavigationControl({showCompass:true, visualizePitch:true}), 'bottom-right');

// Hidden setup map (not visible, for compatibility)
const mapSetup = { on:()=>{}, fitBounds:()=>{}, invalidateSize:()=>{} };

// ── Helper: create GeoJSON circle polygon ────────────────────────────────────
function geoCircle(lng, lat, radiusKm, steps=64) {
  const coords = [];
  for (let i = 0; i <= steps; i++) {
    const angle = (i / steps) * 2 * Math.PI;
    const dLat = (radiusKm / 111.0) * Math.cos(angle);
    const dLng = (radiusKm / (111.0 * Math.cos(lat * Math.PI / 180))) * Math.sin(angle);
    coords.push([lng + dLng, lat + dLat]);
  }
  return coords;
}

// ── Load and visualize default placements on 3D map ──────────────────────────
let _mapReady = false;
mapLive.on('load', () => {
  _mapReady = true;
  _initMapCvCanvas();
  initializeDefaults();
});

async function initializeDefaults() {
  try {
    const res = await fetch('/api/default-placements');
    const data = await res.json();
    if (!data.ok) return;

    const baseX = data.bases[0].x;
    const baseY = data.bases[0].y;
    // Store base coords globally so the sweep beam can reference them from the render loop
    window._missionBaseX = baseX;
    window._missionBaseY = baseY;

    // ── TEAM SECTORS as pie-slice overlays ───────────────────────────────────────
    const TEAM_SECTORS_DEF = [
      {id:'S1', angle_start:0,   angle_end:72,  color:'#FF6600', name:'α Alpha'},
      {id:'S2', angle_start:72,  angle_end:144, color:'#FF2222', name:'β Bravo'},
      {id:'S3', angle_start:144, angle_end:216, color:'#2244FF', name:'γ Charlie'},
      {id:'S4', angle_start:216, angle_end:288, color:'#22BB22', name:'δ Delta'},
      {id:'S5', angle_start:288, angle_end:360, color:'#BB22BB', name:'ε Echo'},
    ];
    const maxRkm = 2.0;
    for (let i = 0; i < TEAM_SECTORS_DEF.length; i++) {
      const sec = TEAM_SECTORS_DEF[i];
      const startRad = sec.angle_start * Math.PI / 180;
      const endRad   = sec.angle_end   * Math.PI / 180;
      const coords = [[baseX, baseY]];
      for (let a = startRad; a <= endRad + 0.01; a += 0.04) {
        const dLat = (maxRkm / 111.0) * Math.cos(a);
        const dLng = (maxRkm / (111.0 * Math.cos(baseY * Math.PI / 180))) * Math.sin(a);
        coords.push([baseX + dLng, baseY + dLat]);
      }
      coords.push([baseX, baseY]);
      const srcId  = 'sector-' + sec.id;
      const fillId = 'sector-fill-' + sec.id;
      const lineId = 'sector-line-' + sec.id;
      mapLive.addSource(srcId, { type:'geojson', data:{ type:'Feature', geometry:{ type:'Polygon', coordinates:[coords] } } });
      mapLive.addLayer({ id:fillId, type:'fill', source:srcId, paint:{ 'fill-color':sec.color, 'fill-opacity':0.05 } });
      mapLive.addLayer({ id:lineId, type:'line', source:srcId, paint:{ 'line-color':sec.color, 'line-width':1.5, 'line-opacity':0.3, 'line-dasharray':[4,3] } });
      sectorPolygons.push({id:fillId, sec, idx:i});
    }

    // ── COASTAL FLOOD ZONE: narrow storm-surge crescent along the western scan rim ──
    // Scenario is a typhoon / coastal storm surge along Manila Bay — NOT a tsunami.
    // Restricted to sectors S3 (Charlie, compass 144°–216°) and S4 (Delta, 216°–288°).
    // Using math convention (0°=E, 90°=N, 180°=W, 270°=S): compass 144° → math 306°,
    // compass 288° → math 162°. Iterating math 162°→306° traces compass 288°→144°.
    const _FLOOD_R_KM        = maxRkm;      // 2.0 — outer edge coincides with scan rim
    const _FLOOD_WIDTH_KM    = 0.35;        // strip thickness
    const _FLOOD_ARC_START   = 162;         // math deg — compass 288° (S4/S5 boundary)
    const _FLOOD_ARC_END     = 306;         // math deg — compass 144° (S2/S3 boundary)
    const _kmPerLat          = 111.0;
    const _kmPerLng          = 111.0 * Math.cos(baseY * Math.PI / 180);
    const _arcPoint = (deg, rKm) => {
      const rad = deg * Math.PI / 180;
      return [
        baseX + (rKm * Math.cos(rad)) / _kmPerLng,
        baseY + (rKm * Math.sin(rad)) / _kmPerLat,
      ];
    };
    const _floodInnerR = _FLOOD_R_KM - _FLOOD_WIDTH_KM;
    const outerArc = [];
    const innerArc = [];
    for (let d = _FLOOD_ARC_START; d <= _FLOOD_ARC_END; d += 2) {
      outerArc.push(_arcPoint(d, _FLOOD_R_KM));
    }
    for (let d = _FLOOD_ARC_END; d >= _FLOOD_ARC_START; d -= 2) {
      innerArc.push(_arcPoint(d, _floodInnerR));
    }
    const floodCoords = [...outerArc, ...innerArc, outerArc[0]];

    mapLive.addSource('flood-coastal', {
      type: 'geojson',
      data: { type: 'Feature', geometry: { type: 'Polygon', coordinates: [floodCoords] } },
    });

    // 3D water extrusion — 2.5m flood depth
    mapLive.addLayer({
      id: 'flood-coastal-ext', type: 'fill-extrusion', source: 'flood-coastal',
      paint: {
        'fill-extrusion-color':   '#0055BB',
        'fill-extrusion-height':  2.5,
        'fill-extrusion-base':    0,
        'fill-extrusion-opacity': 0.58,
      },
    });

    // Brighter surface shimmer on top of extrusion
    mapLive.addLayer({
      id: 'flood-coastal-surf', type: 'fill', source: 'flood-coastal',
      paint: { 'fill-color': '#00AAFF', 'fill-opacity': 0.20 },
    });


    // Label at the mid-point of the flood zone
    const floodLabelEl = document.createElement('div');
    floodLabelEl.innerHTML = `
      <div style="display:flex;flex-direction:column;align-items:center;pointer-events:none">
        <div style="font-size:10px;font-weight:900;color:#00CFFF;
                    background:rgba(0,8,28,0.88);border:1.5px solid #0066CC;
                    padding:3px 9px;border-radius:4px;letter-spacing:0.1em;
                    white-space:nowrap;box-shadow:0 0 10px #0066CCAA">
          ⚠ COASTAL FLOOD ZONE
        </div>
        <div style="font-size:8px;color:#88CCFF;background:rgba(0,8,28,0.75);
                    padding:1px 6px;border-radius:2px;margin-top:2px;white-space:nowrap">
          Manila Bay Storm Surge
        </div>
      </div>`;
    // Place the label at the midpoint of the crescent: due west of base, midway through the strip.
    const _floodLabelPt = _arcPoint(180, (_FLOOD_R_KM + _floodInnerR) / 2);
    new maplibregl.Marker({ element: floodLabelEl, anchor: 'center' })
      .setLngLat(_floodLabelPt)
      .addTo(mapLive);

    // Animate flood water — slow opacity pulse simulating water movement
    let _floodDir = 1, _floodOp = 0.58;
    (function _animateFlood() {
      _floodOp += 0.003 * _floodDir;
      if (_floodOp >= 0.72) _floodDir = -1;
      if (_floodOp <= 0.38) _floodDir =  1;
      if (mapLive.getLayer('flood-coastal-ext')) {
        mapLive.setPaintProperty('flood-coastal-ext',  'fill-extrusion-opacity', _floodOp);
        mapLive.setPaintProperty('flood-coastal-surf', 'fill-opacity', _floodOp * 0.33);
      }
      requestAnimationFrame(_animateFlood);
    })();

    // ── EARTHQUAKE DAMAGE ZONES: collapse hotspots in sectors 1, 2, 3 ─────────
    // Radius 0.245 km (half of the 30%-area circle). Placed along each sector's
    // bisector (compass 0°=N, clockwise) at 1.1 km from base so each circle sits
    // inside its 72° pie slice. With the flood restricted to S3+S4, the S3 quake
    // at compass 180° still has 0.305 km radial clearance from the flood's inner
    // edge (1.65 km), so no overlap.
    const _QUAKE_RADIUS_KM = 0.245;
    const _QUAKE_DIST_KM   = 1.1;
    const QUAKE_ZONES = [
      {sectorId:'S1', name:'Alpha',   bearingDeg:36},
      {sectorId:'S2', name:'Bravo',   bearingDeg:108},
      {sectorId:'S3', name:'Charlie', bearingDeg:180},
    ];

    QUAKE_ZONES.forEach((fz) => {
      // Convert compass bearing to dLat/dLng offset (matches geoCircle convention: 0°=N)
      const rad  = fz.bearingDeg * Math.PI / 180;
      const dLat = (_QUAKE_DIST_KM / 111.0) * Math.cos(rad);
      const dLng = (_QUAKE_DIST_KM / (111.0 * Math.cos(baseY * Math.PI / 180))) * Math.sin(rad);
      const cx   = baseX + dLng;
      const cy   = baseY + dLat;

      const circCoords = geoCircle(cx, cy, _QUAKE_RADIUS_KM, 48);
      const srcId = 'quake-' + fz.sectorId;
      mapLive.addSource(srcId, {
        type: 'geojson',
        data: { type: 'Feature', geometry: { type: 'Polygon', coordinates: [circCoords] } },
      });

      // Ground-level glow only (no 3D extrusion column)
      mapLive.addLayer({
        id: 'quake-fill-' + fz.sectorId, type: 'fill', source: srcId,
        paint: { 'fill-color': '#FF4400', 'fill-opacity': 0.32 },
      });
      // Hot outline
      mapLive.addLayer({
        id: 'quake-line-' + fz.sectorId, type: 'line', source: srcId,
        paint: { 'line-color': '#FFCC00', 'line-width': 2.2, 'line-opacity': 0.85 },
      });

      const quakeEl = document.createElement('div');
      quakeEl.innerHTML = `
        <div style="display:flex;flex-direction:column;align-items:center;pointer-events:none">
          <div style="font-size:28px;line-height:1;
                      text-shadow:0 0 10px rgba(255,120,0,0.95), 0 0 18px rgba(255,60,0,0.7)">
            🌍
          </div>
          <div style="font-size:10px;font-weight:900;color:#FFDD00;
                      background:rgba(40,0,0,0.9);border:1.5px solid #FF4400;
                      padding:2px 8px;border-radius:4px;letter-spacing:0.1em;
                      white-space:nowrap;margin-top:3px;
                      box-shadow:0 0 12px rgba(255,80,0,0.75)">
            🌍 EARTHQUAKE ZONE — ${fz.name.toUpperCase()}
          </div>
        </div>`;
      new maplibregl.Marker({ element: quakeEl, anchor: 'center' })
        .setLngLat([cx, cy])
        .addTo(mapLive);
    });


    // ── Ring zone circles ────────────────────────────────────────────────────
    const ringZones = [
      {r:0.6, color:'#FFFFFF', label:'INNER'},
      {r:1.3, color:'#F9C74F', label:'MIDDLE'},
      {r:2.0, color:'#FF6B6B', label:'OUTER'},
    ];
    ringZones.forEach((z, ri) => {
      const circCoords = geoCircle(baseX, baseY, z.r);
      mapLive.addSource('ring-'+ri, {
        type:'geojson',
        data:{ type:'Feature', geometry:{ type:'Polygon', coordinates:[circCoords] } },
      });
      mapLive.addLayer({
        id:'ring-line-'+ri, type:'line', source:'ring-'+ri,
        paint:{ 'line-color':z.color, 'line-width':1.2, 'line-opacity':0.4, 'line-dasharray':[4,4] },
      });
    });

    // ── Place base marker (3D) ───────────────────────────────────────────────
    const baseEl = document.createElement('div');
    baseEl.innerHTML = `<div style="display:flex;flex-direction:column;align-items:center">
      <svg width="28" height="28" viewBox="0 0 20 20">
        <polygon points="10,2 18,18 2,18" fill="#43AA8B" stroke="#000" stroke-width="1.5"/>
        <text x="10" y="14" text-anchor="middle" font-size="8" font-weight="bold" fill="#000">B</text>
      </svg>
      <div style="font-size:8px;font-weight:700;color:#43AA8B;background:rgba(0,0,0,.8);padding:1px 4px;border-radius:2px;white-space:nowrap">BASE</div>
    </div>`;
    new maplibregl.Marker({element:baseEl}).setLngLat([baseX, baseY])
      .setPopup(new maplibregl.Popup({offset:15}).setHTML('<b>Central Base</b>'))
      .addTo(mapLive);

    // Store placements for compat
    for (let i = 0; i < data.drones.length && i < 6; i++) {
      const d = data.drones[i];
      drones[`${d.x},${d.y}`] = {x: d.x, y: d.y};
    }
    for (const s of data.survivors) {
      placed[`${s.x},${s.y}`] = {x: s.x, y: s.y, critical: s.critical};
    }
    // Register default base so launchMission() sends the correct base position.
    // Without this, custBases is empty → backend uses hardcoded BASE_STATIONS instead
    // of the green triangle shown on the map.
    custBases[`${baseX},${baseY}`] = {x: baseX, y: baseY};

    refreshSetupUI();
  } catch (e) {
    console.error('Default init error:', e);
  }
}
if (_mapReady) initializeDefaults();

// ── Placement state ───────────────────────────────────────────────────────────
const placed = {};    // "x,y" → {x, y, critical}
const drones = {};    // "x,y" → {x, y}
const custBases = {}; // "x,y" → {x, y}

let placeMode = 'survivor';
let critMode   = false;
let missionGo  = false;
let cmdBriefed   = false;
let debriefActive = false;

const DRONE_COL = {
  IDLE:"#A8D8EA", MOVING:"#00B4D8", SCANNING:"#F9C74F",
  RESCUING:"#43AA8B", CHARGING:"#F3722C", LOW_BATT:"#FF006E",
  MALFUNCTION:"#FF2020", REPAIRING:"#FF6600",
  QUAKE_SURVEY:"#FF8C00", QUAKE_RTB:"#FFA500",
};
const DRONE_LBL = {
  IDLE:"Idle", MOVING:"Moving", SCANNING:"Scanning",
  RESCUING:"Rescuing!", CHARGING:"Charging", LOW_BATT:"Low Batt!",
  MALFUNCTION:"⚠ FAULT", REPAIRING:"Repairing…",
  QUAKE_SURVEY:"🌍 Seismic", QUAKE_RTB:"↩ RTB",
};
const DRONE_BG = {
  IDLE:"#0f2030", MOVING:"#082030", SCANNING:"#2a2000",
  RESCUING:"#082820", CHARGING:"#281500", LOW_BATT:"#280010",
  MALFUNCTION:"#300000", REPAIRING:"#281400",
  QUAKE_SURVEY:"#2a1800", QUAKE_RTB:"#201200",
};

// ── Placement (simplified for MapLibre — setup map is hidden) ─────────────────

function refreshSetupUI() {
  const s = Object.keys(placed).length;
  const d = Object.keys(drones).length;
  const b = Object.keys(custBases).length;
  const sc = document.getElementById('setup-counts');
  if (sc) {
    sc.innerHTML = 
      `<b>${s}</b> survivor${s!==1?'s':''} · <b>${d}</b> drone${d!==1?'s':''} · <b>${b}</b> base${b!==1?'s':''}`;
  }
  const btnLaunch = document.getElementById('btn-launch');
  if (btnLaunch) {
    btnLaunch.disabled = (s===0 || d===0);
  }
}

function setSurvivorMode() {
  placeMode = 'survivor';
  updateModeButtons();
}

function setDroneMode() {
  placeMode = 'drone';
  updateModeButtons();
}

function setBaseMode() {
  placeMode = 'base';
  updateModeButtons();
}

function updateModeButtons() {
  const survivorBtn = document.getElementById('btn-survivor-mode');
  const droneBtn = document.getElementById('btn-drone-mode');
  const baseBtn = document.getElementById('btn-base-mode');
  const critBtn = document.getElementById('btn-crit-mode');

  // Reset all
  [survivorBtn, droneBtn, baseBtn].forEach(b => {
    b.style.borderColor = '#999';
    b.style.color = '#999';
    b.style.background = 'var(--bg3)';
  });
  critBtn.style.display = 'none';

  if (placeMode === 'survivor') {
    survivorBtn.style.borderColor = 'var(--accent)';
    survivorBtn.style.color = 'var(--accent)';
    survivorBtn.style.background = 'rgba(126, 200, 227, 0.1)';
    critBtn.style.display = 'inline-block';
  } else if (placeMode === 'drone') {
    droneBtn.style.borderColor = '#00D9FF';
    droneBtn.style.color = '#00D9FF';
    droneBtn.style.background = 'rgba(0, 217, 255, 0.1)';
  } else if (placeMode === 'base') {
    baseBtn.style.borderColor = '#43AA8B';
    baseBtn.style.color = '#43AA8B';
    baseBtn.style.background = 'rgba(67, 170, 139, 0.1)';
  }
}

function toggleMode() {
  critMode = !critMode;
  const btn = document.getElementById('btn-crit-mode');
  btn.textContent  = critMode ? '🔴 CRITICAL' : '🟠 STABLE';
  btn.style.borderColor = critMode ? 'var(--red)' : 'var(--orange)';
  btn.style.color = critMode ? 'var(--red)' : 'var(--orange)';
}

function clearAll() {
  if (missionGo) return;
  for (const k of Object.keys(placed)) delete placed[k];
  for (const k of Object.keys(drones)) delete drones[k];
  for (const k of Object.keys(custBases)) delete custBases[k];
  refreshSetupUI();
}

async function launchMission() {
  const survivors = Object.values(placed).map(s => ({x:s.x, y:s.y, critical:s.critical}));
  const dronePos = Object.values(drones).map(d => ({x:d.x, y:d.y}));
  const basePos = Object.keys(custBases).length > 0 ? Object.values(custBases).map(b => ({x:b.x, y:b.y})) : null;

  if (!survivors.length || !dronePos.length) {
    alert('❌ Place at least 1 survivor AND 1 drone before launching!');
    return;
  }

  document.getElementById('btn-launch').disabled  = true;
  document.getElementById('btn-launch').textContent = '⏳ Launching…';

  const res = await fetch('/api/start', {
    method:'POST',
    headers:{'Content-Type':'application/json'},
    body: JSON.stringify({survivors, drones: dronePos, bases: basePos}),
  }).catch(() => null);

  if (res?.ok) {
    missionGo = true;
    document.getElementById('btn-launch').textContent  = '▶ MISSION ACTIVE';
    document.getElementById('btn-clear').disabled      = true;
    document.getElementById('btn-survivor-mode').disabled = true;
    document.getElementById('btn-drone-mode').disabled = true;
    document.getElementById('btn-crit-mode').disabled = true;
    document.getElementById('live-tag').textContent    = '② Live Mission — ACTIVE';
  } else {
    document.getElementById('btn-launch').disabled    = false;
    document.getElementById('btn-launch').textContent = '▶ START MISSION';
    alert('❌ Failed to start mission. Is the server running?');
  }
}

// ── Live map markers (MapLibre GL JS) ─────────────────────────────────────────
const droneMarkers    = {};   // id → maplibregl.Marker
const dronePos        = {};   // id → {cur:[lng,lat], tgt:[lng,lat], t0, dur}
const droneStatuses   = {};   // id → status string (MOVING, SCANNING, IDLE, etc.)
const dronePaths      = {};   // id → source name
let   disasterDone    = false;
let   scannedCells    = new Set();
let   rescuedCells    = new Set();
let   _scannedFeats   = [];
let   _rescuedFeats   = [];
let   _survivorFeats  = [];
let   _survivorRingFeats = [];

// ── Smooth animation engine ���─────────────────────────────────────────────────
// WebSocket pushes state every ~400ms. Instead of snapping markers, we lerp
// from their current rendered position to the new target over ANIM_DURATION_MS
// using requestAnimationFrame for 60fps fluid motion.
const ANIM_DURATION_MS = 380;  // slightly under ws interval for seamless chaining

function _lerp(a, b, t) { return a + (b - a) * t; }
function _easeInOut(t) { return t < 0.5 ? 2*t*t : -1+(4-2*t)*t; }

function _animLoop(now) {
  for (const id of Object.keys(dronePos)) {
    const dp = dronePos[id];
    if (!dp || !droneMarkers[id]) continue;

    const elapsed = now - dp.t0;
    const rawT = Math.min(elapsed / dp.dur, 1);
    const t = _easeInOut(rawT);

    const lng = _lerp(dp.from[0], dp.tgt[0], t);
    const lat = _lerp(dp.from[1], dp.tgt[1], t);
    droneMarkers[id].setLngLat([lng, lat]);
    dp.cur = [lng, lat];

    // Also update flight path start point to follow the drone smoothly
    if (_mapReady && mapLive.getSource('path-' + id)) {
      const pathData = dp._pathCoords;
      if (pathData && pathData.length > 0) {
        const smoothCoords = [[lng, lat], ...pathData.slice(1)];
        mapLive.getSource('path-' + id).setData({
          type:'Feature', geometry:{ type:'LineString', coordinates: smoothCoords },
        });
      }
    }
  }
  requestAnimationFrame(_animLoop);
}
requestAnimationFrame(_animLoop);

function _droneMarkerHtml(status, battery, label, droneId, ringRole, displayColor) {
  const isMalf    = status === 'malfunction';
  const isRepair  = status === 'repairing';
  const isFault   = isMalf || isRepair;
  const c = DRONE_COL[status] || '#0088ff';
  const bc = battery <= 20 ? '#ff2a6d' : battery <= 50 ? '#ff9500' : '#00ff9f';

  const isOuter = !isFault && ringRole === 'OUTER';
  const isPromoted = displayColor === '#FFD700';
  const isDemoted  = displayColor === '#00BFFF';
  const roleColor = isFault     ? '#FF2020'
    : isPromoted  ? '#FFD700'
    : isDemoted   ? '#00BFFF'
    : isOuter     ? '#ff9500' : '#0088ff';
  const propColor = isFault     ? '#FF2020'
    : displayColor ? displayColor
    : isOuter      ? '#ff9500' : c;

  // Always render a ring badge — PROMOTED/INNER always visible, OUTER/MID only after briefing
  let badgeLabel = isOuter ? 'OUTER' : 'MID';
  if (isPromoted) badgeLabel = '⇑ PROMOTED';
  if (isDemoted)  badgeLabel = '⇓ INNER';
  const showRoleBadge = !isFault && (isPromoted || isDemoted || (cmdBriefed && !debriefActive));
  const roleBadge = showRoleBadge
    ? `<div style="font-size:7px;font-weight:900;background:${roleColor};color:${isPromoted||isDemoted?'#000':'#000'};padding:0 4px;border-radius:2px;letter-spacing:0.5px;line-height:1.4">${badgeLabel}</div>`
    : '';

  // Blinking yellow exclamation badge for malfunction/repairing
  const faultBadge = isFault
    ? `<div style="font-size:13px;line-height:1;animation:malf-blink 0.7s step-start infinite;position:absolute;top:-14px;left:50%;transform:translateX(-50%)">⚠️</div>`
    : '';

  // Red glow filter for faulty drones, normal glow otherwise
  const glowFilter = isFault
    ? 'drop-shadow(0 0 8px #ff2020cc) drop-shadow(0 0 16px #ff000066)'
    : `drop-shadow(0 0 10px ${roleColor}88)`;

  return `<div class="drone-marker-3d" style="position:relative;display:flex;flex-direction:column;align-items:center;gap:2px;filter:${glowFilter}">
    ${faultBadge}
    ${roleBadge}
    <svg viewBox="0 0 26 26" width="34" height="34">
      <circle cx="13" cy="13" r="12" fill="none" stroke="${roleColor}" stroke-width="${isFault?1.5:0.5}" stroke-dasharray="${isFault?'':'2,2'}"/>
      <line x1="13" y1="13" x2="4"  y2="4"  stroke="${c}" stroke-width="2.5" stroke-linecap="round"/>
      <line x1="13" y1="13" x2="22" y2="4"  stroke="${c}" stroke-width="2.5" stroke-linecap="round"/>
      <line x1="13" y1="13" x2="4"  y2="22" stroke="${c}" stroke-width="2.5" stroke-linecap="round"/>
      <line x1="13" y1="13" x2="22" y2="22" stroke="${c}" stroke-width="2.5" stroke-linecap="round"/>
      <circle cx="4"  cy="4"  r="3.5" fill="${propColor}" stroke="rgba(255,255,255,.5)" stroke-width="1"/>
      <circle cx="22" cy="4"  r="3.5" fill="${propColor}" stroke="rgba(255,255,255,.5)" stroke-width="1"/>
      <circle cx="4"  cy="22" r="3.5" fill="${propColor}" stroke="rgba(255,255,255,.5)" stroke-width="1"/>
      <circle cx="22" cy="22" r="3.5" fill="${propColor}" stroke="rgba(255,255,255,.5)" stroke-width="1"/>
      <circle cx="13" cy="13" r="5.5" fill="${c}" stroke="${roleColor}" stroke-width="2"/>
      <text x="13" y="16.5" text-anchor="middle" font-size="5" fill="rgba(0,0,0,.9)" font-weight="bold">${isFault?'!':label}</text>
    </svg>
    <div style="font-size:8px;font-weight:800;background:rgba(0,0,0,0.85);color:${roleColor};padding:1px 5px;border-radius:10px;border:1px solid ${roleColor}">${droneId.replace('drone_','D-')}</div>
    <div style="font-size:8px;font-weight:700;background:rgba(0,0,0,0.7);color:${isFault?'#FF2020':bc};padding:0 4px;border-radius:4px">${isFault?(isRepair?'REPAIR':'FAULT'):(Math.round(battery)+'%')}</div>
  </div>`;
}

function updateDrones(dronesData) {
  const now = performance.now();
  for (const d of dronesData) {
    const lbl = d.id.replace('drone_','');
    const html = _droneMarkerHtml(d.status, d.battery, lbl, d.id, d.ring_role || 'OUTER', d.display_color || '');
    const newTgt = [d.x, d.y];

    if (droneMarkers[d.id]) {
      // Update icon HTML (status/battery changes)
      droneMarkers[d.id].getElement().innerHTML = html;

      // Start new animation from current rendered position to new target
      const prev = dronePos[d.id];
      const from = prev ? prev.cur : newTgt;
      dronePos[d.id] = { from: [...from], tgt: newTgt, cur: [...from], t0: now, dur: ANIM_DURATION_MS, _pathCoords: null };
    } else {
      // Create new marker
      const el = document.createElement('div');
      el.innerHTML = html;
      el.className = 'drone-marker-3d';
      const popup = new maplibregl.Popup({offset:20, closeButton:false}).setHTML(
        `<b>${d.id}</b><br>Status: ${DRONE_LBL[d.status]||d.status}<br>Battery: ${Math.round(d.battery)}%`
      );
      droneMarkers[d.id] = new maplibregl.Marker({element:el, anchor:'center'})
        .setLngLat(newTgt)
        .setPopup(popup)
        .addTo(mapLive);
      dronePos[d.id] = { from: newTgt, tgt: newTgt, cur: [...newTgt], t0: now, dur: ANIM_DURATION_MS, _pathCoords: null };
    }
    droneStatuses[d.id] = d.status || 'IDLE';

    // Update popup
    const popupHtml = `<b>${d.id}</b><br>
      Status: <b>${DRONE_LBL[d.status]||d.status}</b><br>
      Battery: <b>${Math.round(d.battery)}%</b> · (${d.x.toFixed(4)}, ${d.y.toFixed(4)})<br>
      Base: ${d.base_name} · Rescued: ${d.rescued_count}
      ${d.target?`<br>Target: (${d.target.x.toFixed(4)}, ${d.target.y.toFixed(4)})`:''}`;
    droneMarkers[d.id].getPopup()?.setHTML(popupHtml);

    // Flight path line
    if (d.path && d.path.length > 0 && _mapReady) {
      const coords = [[d.x, d.y]].concat(d.path.map(p => [p.x, p.y]));
      const pathColor = d.status === 'LOW_BATT' ? '#FF006E' : '#00D9FF';
      const srcName = 'path-' + d.id;

      // Store path coords so animation loop can update the start point
      dronePos[d.id]._pathCoords = coords;

      if (mapLive.getSource(srcName)) {
        mapLive.getSource(srcName).setData({
          type:'Feature', geometry:{ type:'LineString', coordinates: coords },
        });
        mapLive.setPaintProperty('path-line-' + d.id, 'line-color', pathColor);
      } else {
        mapLive.addSource(srcName, {
          type:'geojson',
          data:{ type:'Feature', geometry:{ type:'LineString', coordinates: coords } },
        });
        mapLive.addLayer({
          id:'path-line-' + d.id, type:'line', source: srcName,
          paint:{ 'line-color': pathColor, 'line-width':2.5, 'line-opacity':0.7, 'line-dasharray':[3,4] },
        });
      }
    } else {
      if (dronePos[d.id]) dronePos[d.id]._pathCoords = null;
      if (_mapReady && mapLive.getSource('path-'+d.id)) {
        mapLive.getSource('path-'+d.id).setData({type:'Feature',geometry:{type:'LineString',coordinates:[]}});
      }
    }
  }
}

// Matches Leaflet: L.circleMarker (small dots) + L.circle radius:50 (detection ring)
function updateSurvivors(survivors) {
  if (!_mapReady) return;

  // Small dot markers — same as Leaflet L.circleMarker radius 2-4
  _survivorFeats = survivors.map((s,i) => ({
    type:'Feature',
    geometry:{ type:'Point', coordinates:[s.x, s.y] },
    properties:{
      rescued: s.rescued, detected: s.detected, critical: s.critical,
      color: s.rescued ? '#43AA8B' : (s.critical ? '#FF2D55' : '#FF9F1C'),
      radius: s.critical && !s.rescued ? 4 : 2,
      opacity: s.rescued ? 0.45 : 0.9,
    },
  }));

  // 50m detection ring — same as Leaflet L.circle radius:50, red, shown when detected & not rescued
  _survivorRingFeats = survivors
    .filter(s => s.detected && !s.rescued)
    .map(s => ({
      type:'Feature',
      geometry:{ type:'Point', coordinates:[s.x, s.y] },
      properties:{
        ringColor: '#FF0000',
      },
    }));

  // Dot markers
  if (mapLive.getSource('survivors')) {
    mapLive.getSource('survivors').setData({type:'FeatureCollection', features:_survivorFeats});
  } else {
    mapLive.addSource('survivors', { type:'geojson', data:{type:'FeatureCollection', features:_survivorFeats} });
    mapLive.addLayer({
      id:'survivors-layer', type:'circle', source:'survivors',
      paint:{
        'circle-radius': ['get','radius'],
        'circle-color': ['get','color'],
        'circle-opacity': ['get','opacity'],
        'circle-stroke-width': 1.5,
        'circle-stroke-color': '#ffffff',
        'circle-stroke-opacity': 0.8,
      },
    });
  }

  // 50m detection rings (circle layer with meter-accurate zoom scaling)
  // Manila lat ~14.5: 50m ≈ 5.4px@z14, 10.8@z15, 21.6@z16, 43@z17
  if (mapLive.getSource('survivor-rings')) {
    mapLive.getSource('survivor-rings').setData({type:'FeatureCollection', features:_survivorRingFeats});
  } else {
    mapLive.addSource('survivor-rings', { type:'geojson', data:{type:'FeatureCollection', features:_survivorRingFeats} });
    mapLive.addLayer({
      id:'survivor-rings-fill', type:'circle', source:'survivor-rings',
      paint:{
        'circle-radius': ['interpolate',['exponential',2],['zoom'], 14,5.4, 15,10.8, 16,21.6, 17,43, 18,86],
        'circle-color': '#FF0000',
        'circle-opacity': 0.20,
        'circle-stroke-width': 2,
        'circle-stroke-color': '#FF0000',
        'circle-stroke-opacity': 0.5,
      },
    });
  }
}

// ── Main-map CV YOLO overlay ─────────────────────────────────────────────────
// Draws a YOLO-style bounding box on each non-rescued survivor (the orange dots)
// so the tactical map mirrors the CV detections shown on the FPV focus view.
let _mapCvCtx = null;
let _mapCvAnimId = null;

function _initMapCvCanvas() {
  const c = document.getElementById('map-cv-canvas');
  if (!c) return;
  _mapCvCtx = c.getContext('2d');
  _mapCvResize();
  window.addEventListener('resize', _mapCvResize);
  if (mapLive) {
    mapLive.on('resize', _mapCvResize);
    mapLive.on('move', () => {});  // render loop redraws every frame, no-op
  }
  if (!_mapCvAnimId) _mapCvAnimId = requestAnimationFrame(_mapCvRenderLoop);
}

function _mapCvResize() {
  const c = document.getElementById('map-cv-canvas');
  const host = document.getElementById('map-live');
  if (!c || !host) return;
  const dpr = window.devicePixelRatio || 1;
  c.width = Math.max(1, Math.round(host.clientWidth * dpr));
  c.height = Math.max(1, Math.round(host.clientHeight * dpr));
  c.style.width = host.clientWidth + 'px';
  c.style.height = host.clientHeight + 'px';
  if (_mapCvCtx) _mapCvCtx.setTransform(dpr, 0, 0, dpr, 0, 0);
}

// ── Earthquake zone animation state ─────────────────────────────────────────
// Fully frontend-driven — makes the convergence/survey/return sequence look
// smooth on the map regardless of actual backend drone positions.
const _quakeAnim = {
  active:    false,
  startT:    0,
  zoneLng:   0, zoneLat: 0,    // GPS centre of the triggered quake zone
  droneSnap: [],               // [{lng,lat}] positions snapped when event fired
};
const QUAKE_PHASE_MS = { alert:3000, converge:9000, survey:12000, disperse:7000 };
const QUAKE_TOTAL_MS = QUAKE_PHASE_MS.alert + QUAKE_PHASE_MS.converge
                     + QUAKE_PHASE_MS.survey + QUAKE_PHASE_MS.disperse; // 31 s

function _startQuakeAnim(zoneLng, zoneLat) {
  _quakeAnim.active   = true;
  _quakeAnim.startT   = performance.now();
  _quakeAnim.zoneLng  = zoneLng;
  _quakeAnim.zoneLat  = zoneLat;
  // Snapshot current drone positions
  _quakeAnim.droneSnap = Object.values(dronePos)
    .map(dp => dp ? { lng: dp.cur[0], lat: dp.cur[1] } : null)
    .filter(Boolean);
}

function _drawQuakeAnim(ctx, W, H, now) {
  if (!_quakeAnim.active || !_mapReady) return;
  const elapsed = now - _quakeAnim.startT;
  if (elapsed > QUAKE_TOTAL_MS) { _quakeAnim.active = false; return; }

  let zx, zy;
  try { const pt = mapLive.project([_quakeAnim.zoneLng, _quakeAnim.zoneLat]); zx = pt.x; zy = pt.y; }
  catch (e) { return; }

  const { alert: tA, converge: tC, survey: tS, disperse: tD } = QUAKE_PHASE_MS;
  ctx.save();

  if (elapsed < tA) {
    // ── Phase 1: SEISMIC ALERT — big shockwave rings from zone ──
    const t = elapsed / tA;
    for (let i = 0; i < 4; i++) {
      const rt = Math.min(1, (t * 4 - i) );
      if (rt <= 0) continue;
      ctx.strokeStyle = `rgba(255,140,0,${(1-rt)*0.9})`;
      ctx.lineWidth = 3;
      ctx.beginPath(); ctx.arc(zx, zy, rt * 140, 0, Math.PI*2); ctx.stroke();
    }
    ctx.font = '900 22px "JetBrains Mono",monospace';
    ctx.textAlign = 'center';
    const flash = Math.sin(now/120) > 0 ? 1 : 0.3;
    ctx.fillStyle = `rgba(255,200,0,${flash})`;
    ctx.fillText('⚠ SEISMIC ALERT', zx, zy - 30);

  } else if (elapsed < tA + tC) {
    // ── Phase 2: CONVERGE — draw dashed lines from each drone to zone ──
    const t = (elapsed - tA) / tC;
    _quakeAnim.droneSnap.forEach(d => {
      let dx, dy;
      try { const pt = mapLive.project([d.lng, d.lat]); dx = pt.x; dy = pt.y; } catch(e){ return; }
      ctx.strokeStyle = `rgba(255,140,0,${0.6 + 0.3*Math.sin(now/180)})`;
      ctx.lineWidth = 1.5;
      ctx.setLineDash([6, 5]);
      ctx.beginPath();
      ctx.moveTo(dx, dy);
      ctx.lineTo(dx + (zx-dx)*t, dy + (zy-dy)*t);
      ctx.stroke();
      ctx.setLineDash([]);
      // Drone dot moving toward zone
      const cx2 = dx + (zx-dx)*t, cy2 = dy + (zy-dy)*t;
      ctx.fillStyle = 'rgba(255,140,0,0.85)';
      ctx.beginPath(); ctx.arc(cx2, cy2, 5, 0, Math.PI*2); ctx.fill();
    });
    // Zone pulsing ring
    const pulse = 0.4 + 0.6*Math.sin(now/200);
    ctx.strokeStyle = `rgba(255,160,0,${pulse})`;
    ctx.lineWidth = 2.5;
    ctx.setLineDash([8,5]);
    ctx.beginPath(); ctx.arc(zx, zy, 44, 0, Math.PI*2); ctx.stroke();
    ctx.setLineDash([]);
    ctx.font = '700 11px "JetBrains Mono",monospace';
    ctx.textAlign = 'center';
    ctx.fillStyle = 'rgba(255,200,0,0.9)';
    ctx.fillText('ALL DRONES CONVERGING', zx, zy + 60);

  } else if (elapsed < tA + tC + tS) {
    // ── Phase 3: SURVEY — seismic rings expanding outward from zone ──
    const t = (elapsed - tA - tC) / tS;
    for (let i = 0; i < 5; i++) {
      const rt = ((t * 5 - i) % 1 + 1) % 1;
      ctx.strokeStyle = `rgba(255,140,0,${(1-rt)*0.75})`;
      ctx.lineWidth = 2;
      ctx.beginPath(); ctx.arc(zx, zy, rt * 110, 0, Math.PI*2); ctx.stroke();
    }
    // Cluster of dots at zone (representing converged drones)
    _quakeAnim.droneSnap.forEach((_, i) => {
      const angle = (i / _quakeAnim.droneSnap.length) * Math.PI * 2;
      const r = 16;
      ctx.fillStyle = 'rgba(255,165,0,0.9)';
      ctx.beginPath(); ctx.arc(zx + Math.cos(angle)*r, zy + Math.sin(angle)*r, 5, 0, Math.PI*2); ctx.fill();
    });
    ctx.fillStyle = 'rgba(8,14,26,0.88)';
    const lw = 180, lh = 22;
    ctx.fillRect(zx - lw/2, zy - 46, lw, lh);
    ctx.strokeStyle = 'rgba(255,140,0,0.8)'; ctx.lineWidth = 1;
    ctx.strokeRect(zx - lw/2, zy - 46, lw, lh);
    ctx.font = '700 11px "JetBrains Mono",monospace';
    ctx.fillStyle = 'rgba(255,200,0,1)'; ctx.textAlign = 'center';
    ctx.fillText('🌍  SEISMIC SURVEY IN PROGRESS', zx, zy - 30);

  } else {
    // ── Phase 4: DISPERSE — lines returning to original positions ──
    const t = (elapsed - tA - tC - tS) / tD;
    _quakeAnim.droneSnap.forEach(d => {
      let dx, dy;
      try { const pt = mapLive.project([d.lng, d.lat]); dx = pt.x; dy = pt.y; } catch(e){ return; }
      const cx2 = zx + (dx-zx)*t, cy2 = zy + (dy-zy)*t;
      ctx.strokeStyle = `rgba(100,200,255,${0.5*(1-t)})`;
      ctx.lineWidth = 1.5; ctx.setLineDash([5,5]);
      ctx.beginPath(); ctx.moveTo(zx, zy); ctx.lineTo(cx2, cy2); ctx.stroke();
      ctx.setLineDash([]);
      ctx.fillStyle = `rgba(100,200,255,${0.85*(1-t)})`;
      ctx.beginPath(); ctx.arc(cx2, cy2, 5, 0, Math.PI*2); ctx.fill();
    });
    ctx.font = '700 11px "JetBrains Mono",monospace';
    ctx.textAlign = 'center';
    ctx.fillStyle = `rgba(100,220,255,${1-t})`;
    ctx.fillText('DRONES RETURNING TO SWEEP', zx, zy + 60);
  }

  ctx.restore();
}

// ── Arc sweep sector visualization ───────────────────────────────────────────
// Shows an animated rotating beam within the currently active sector so the
// 3-2 arc formation is always visible even when drone positions are sparse.
let _sweepBeamAngle = 0;
let _sweepBeamLastT = 0;

function _drawSweepBeam(ctx, W, H, now, baseX, baseY) {
  if (!_mapReady || _activeSectorIdx < 0) return;
  const SECTORS_DEF = [
    {a0:0,a1:72},{a0:72,a1:144},{a0:144,a1:216},{a0:216,a1:288},{a0:288,a1:360}
  ];
  const sec = SECTORS_DEF[_activeSectorIdx];
  if (!sec) return;

  let bx, by;
  try { const pt = mapLive.project([baseX, baseY]); bx = pt.x; by = pt.y; }
  catch (e) { return; }

  // Advance beam angle (full sector sweep every ~6 s)
  const dt = now - _sweepBeamLastT;
  _sweepBeamLastT = now;
  const sectorSpan = sec.a1 - sec.a0;
  _sweepBeamAngle = (_sweepBeamAngle + (sectorSpan / 6000) * dt) % sectorSpan;
  const beamDeg = sec.a0 + _sweepBeamAngle;

  // Convert compass bearing to canvas direction (0°N = up = -π/2 in canvas coords)
  const beamRad = (beamDeg - 90) * Math.PI / 180;
  const maxPx = Math.max(W, H) * 0.55;  // beam length in screen pixels

  ctx.save();
  // Trailing gradient beam
  const grad = ctx.createLinearGradient(bx, by, bx + Math.cos(beamRad)*maxPx, by + Math.sin(beamRad)*maxPx);
  grad.addColorStop(0,   'rgba(0,200,255,0.18)');
  grad.addColorStop(0.7, 'rgba(0,200,255,0.08)');
  grad.addColorStop(1,   'rgba(0,200,255,0)');
  ctx.strokeStyle = grad;
  ctx.lineWidth = 18;
  ctx.lineCap = 'round';
  ctx.beginPath();
  ctx.moveTo(bx, by);
  ctx.lineTo(bx + Math.cos(beamRad)*maxPx, by + Math.sin(beamRad)*maxPx);
  ctx.stroke();
  // Sharp leading edge
  ctx.strokeStyle = 'rgba(0,220,255,0.55)';
  ctx.lineWidth = 2;
  ctx.beginPath();
  ctx.moveTo(bx, by);
  ctx.lineTo(bx + Math.cos(beamRad)*maxPx, by + Math.sin(beamRad)*maxPx);
  ctx.stroke();
  ctx.restore();
}

// Rotating focus sweep state — cycles through every detected+unrescued survivor
// so the audience clearly sees EACH ONE get the YOLO zoom-and-confirm treatment.
const _yoloSweep = {
  idx: 0,            // index into the detected survivor list
  phaseT0: 0,        // wall-clock when the current focus started
  focusKey: null,    // stable key of the survivor currently being focused
  confByKey: {},     // { survivorKey: { conf, locked } } so scores stay stable
};
const YOLO_FOCUS_DUR = 2400;   // ms each survivor: 720 scan + 840 analyzing + 840 confirmed

// Survivors confirmed by FPV verdict — synced from mini-FPV tiles to main map
const _confirmedSurvivorKeys = new Set();

// Survivors near a blue scan circle — YOLO frames activate when a drone scans their vicinity
const _yoloActivatedKeys = new Set();
const YOLO_SCAN_RAD = 0.0015; // ~167m — slightly wider than the 100m backend scan radius

function _activateYoloNear(lng, lat) {
  if (!_survivorFeats || !_survivorFeats.length) return;
  for (const f of _survivorFeats) {
    if (f.properties?.rescued) continue;
    const [flng, flat] = f.geometry.coordinates;
    if (Math.abs(flng - lng) < YOLO_SCAN_RAD && Math.abs(flat - lat) < YOLO_SCAN_RAD) {
      _yoloActivatedKeys.add(_yoloSurvivorKey(f));
    }
  }
}

function _mapConfirmSurvivor(target) {
  if (!target) return;
  const key = `${target.x.toFixed(6)},${target.y.toFixed(6)}`;
  _confirmedSurvivorKeys.add(key);
}

function _yoloSurvivorKey(f) {
  const [lng, lat] = f.geometry.coordinates;
  return `${lng.toFixed(6)},${lat.toFixed(6)}`;
}

function _mapCvRenderLoop() {
  _mapCvAnimId = requestAnimationFrame(_mapCvRenderLoop);
  if (!_mapCvCtx || !_mapReady) return;
  const host = document.getElementById('map-live');
  if (!host) return;
  const W = host.clientWidth, H = host.clientHeight;
  if (W <= 0 || H <= 0) return;
  const ctx = _mapCvCtx;

  // Sync canvas buffer size every frame
  const dpr = window.devicePixelRatio || 1;
  const needW = Math.round(W * dpr), needH = Math.round(H * dpr);
  const cvEl = document.getElementById('map-cv-canvas');
  if (cvEl && (cvEl.width !== needW || cvEl.height !== needH)) {
    cvEl.width = needW; cvEl.height = needH;
    cvEl.style.width = W + 'px'; cvEl.style.height = H + 'px';
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  }

  ctx.clearRect(0, 0, W, H);
  const now = performance.now();

  // ── Mirror every active FPV mini-CV scan onto the 2.5D map.
  // _miniCvStates[slot] tracks which survivor each drone is currently CV-scanning.
  // We project that geographic position onto the main map and draw a smaller frame,
  // phase-synchronised with the FPV tile (same phase, same progress within that phase).
  // Nothing is drawn when all FPV slots are idle — canvas stays clear.
  const activeScans = [];
  for (let slot = 0; slot < 5; slot++) {
    const st = _miniCvStates ? _miniCvStates[slot] : null;
    if (!st || st.phase === 'idle' || !st.target) continue;
    const phaseDur = MINI_CV_DUR[st.phase] || 1000;
    const t = Math.min(1, (now - st.phaseT0) / phaseDur);

    // Map FPV phases → 3-state main-map phases
    let mapPhase, phaseLocalT;
    if (st.phase === 'scanning' || st.phase === 'zooming') {
      mapPhase = 'scanning';  phaseLocalT = t;
    } else if (st.phase === 'analyzing') {
      mapPhase = 'analyzing'; phaseLocalT = t;
    } else {
      mapPhase = 'confirmed'; phaseLocalT = t;  // verdict / pullback
    }
    activeScans.push({ target: st.target, mapPhase, phaseLocalT, phaseT0: st.phaseT0 });
  }

  if (activeScans.length === 0) return;

  // ── Draw one polished HUD frame per active FPV slot ──────────────────────────
  // easeOutCubic for smooth frame entrance (first 220 ms of any phase)
  const easeOut3 = t => 1 - Math.pow(1 - t, 3);

  for (const { target, mapPhase, phaseLocalT, phaseT0 } of activeScans) {
    let px, py;
    try { const pt = mapLive.project([target.x, target.y]); px = pt.x; py = pt.y; }
    catch (e) { continue; }
    if (px < -80 || py < -80 || px > W + 80 || py > H + 80) continue;

    const critical = !!target.critical;

    // Entrance scale: frame pops in smoothly over the first 220 ms of each phase
    const entryElapsed = now - (phaseT0 || now);
    const entryScale = easeOut3(Math.min(1, entryElapsed / 220));

    const halfBase = critical ? 27 : 23;
    // Tiny pulse in/out during confirmed; otherwise stable
    const pulse = mapPhase === 'confirmed'
      ? 1 + 0.04 * Math.sin(now / 160)
      : 1 + 0.06 * Math.sin(phaseLocalT * Math.PI * 2);
    const half = halfBase * pulse * entryScale;
    const x1 = px - half, y1 = py - half, x2 = px + half, y2 = py + half;
    const tk  = half * 0.46;   // corner bracket length

    // Phase palette
    const [r, g, b] = mapPhase === 'scanning'  ? [0, 220, 255]
                    : mapPhase === 'analyzing' ? [255, 185, 0]
                    :                           [0, 255, 138];

    ctx.save();

    // ── Cover the orange dot during analyzing/confirmed ───────────────────
    if (mapPhase !== 'scanning') {
      const coverA = mapPhase === 'analyzing' ? 0.55 + phaseLocalT * 0.4 : 0.95;
      ctx.fillStyle = `rgba(8,14,26,${coverA * entryScale})`;
      ctx.beginPath(); ctx.arc(px, py, 8, 0, Math.PI * 2); ctx.fill();
    }

    // ── Phase-specific inner effects ──────────────────────────────────────
    if (mapPhase === 'scanning') {
      // Fast sweep line — completes twice in the phase (2 passes)
      const passT = (phaseLocalT * 2) % 1;
      const sweepY = y1 + (y2 - y1) * passT;
      const sg = ctx.createLinearGradient(0, sweepY - 12, 0, sweepY + 12);
      sg.addColorStop(0,   `rgba(${r},${g},${b},0)`);
      sg.addColorStop(0.4, `rgba(${r},${g},${b},0.7)`);
      sg.addColorStop(0.5, `rgba(${r},${g},${b},1)`);
      sg.addColorStop(0.6, `rgba(${r},${g},${b},0.7)`);
      sg.addColorStop(1,   `rgba(${r},${g},${b},0)`);
      ctx.fillStyle = sg;
      ctx.fillRect(x1, sweepY - 12, half * 2, 24);
      // Bright leading edge line
      ctx.strokeStyle = `rgba(${r},${g},${b},0.9)`;
      ctx.lineWidth = 1.5;
      ctx.beginPath(); ctx.moveTo(x1, sweepY); ctx.lineTo(x2, sweepY); ctx.stroke();

    } else if (mapPhase === 'analyzing') {
      // Rotating radar arc around the target
      const arcStart = now / 600;  // rotates continuously
      ctx.strokeStyle = `rgba(${r},${g},${b},0.75)`;
      ctx.lineWidth = 2;
      ctx.beginPath();
      ctx.arc(px, py, half * 1.55, arcStart, arcStart + Math.PI * 1.3);
      ctx.stroke();
      ctx.strokeStyle = `rgba(${r},${g},${b},0.25)`;
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.arc(px, py, half * 1.55, 0, Math.PI * 2); ctx.stroke();
      // Center crosshair dot
      ctx.fillStyle = `rgba(${r},${g},${b},0.85)`;
      ctx.beginPath(); ctx.arc(px, py, 2.5, 0, Math.PI * 2); ctx.fill();

    } else {
      // Confirmed — multi-layer glow
      const gPulse = 0.55 + 0.45 * Math.sin(now / 220);
      for (const [blur, alpha] of [[20, 0.5*gPulse], [10, 0.7*gPulse], [4, 1]]) {
        ctx.shadowColor = `rgba(${r},${g},${b},${alpha})`;
        ctx.shadowBlur = blur;
        ctx.strokeStyle = `rgba(${r},${g},${b},${alpha * 0.6})`;
        ctx.lineWidth = 1;
        ctx.strokeRect(x1 - 2, y1 - 2, half * 2 + 4, half * 2 + 4);
      }
      ctx.shadowBlur = 0;
    }

    // ── Bounding box ──────────────────────────────────────────────────────
    ctx.shadowBlur = 0;
    ctx.strokeStyle = `rgba(${r},${g},${b},${entryScale})`;
    ctx.lineWidth = mapPhase === 'confirmed' ? 2 : 1.5;
    ctx.setLineDash(mapPhase === 'scanning' ? [4, 3] : []);
    ctx.strokeRect(x1, y1, half * 2, half * 2);
    ctx.setLineDash([]);

    // ── Animated corner brackets (draw-on effect: grow from 0 to full length) ──
    const tkA = tk * easeOut3(Math.min(1, entryElapsed / 160));
    ctx.strokeStyle = `rgba(${r},${g},${b},1)`;
    ctx.lineWidth = mapPhase === 'confirmed' ? 3.5 : 2.8;
    ctx.lineCap = 'square';
    ctx.beginPath();
    ctx.moveTo(x1,       y1 + tkA); ctx.lineTo(x1,       y1);       ctx.lineTo(x1 + tkA, y1);
    ctx.moveTo(x2 - tkA, y1);       ctx.lineTo(x2,       y1);       ctx.lineTo(x2,       y1 + tkA);
    ctx.moveTo(x1,       y2 - tkA); ctx.lineTo(x1,       y2);       ctx.lineTo(x1 + tkA, y2);
    ctx.moveTo(x2 - tkA, y2);       ctx.lineTo(x2,       y2);       ctx.lineTo(x2,       y2 - tkA);
    ctx.stroke();
    ctx.lineCap = 'butt';

    // ── 3D model — materialises during analyzing, solid at confirmed ──────
    const modelAlpha = mapPhase === 'scanning'  ? 0
                     : mapPhase === 'analyzing' ? phaseLocalT * entryScale
                     :                           1.0;
    const modelSize  = mapPhase === 'analyzing' ? 20 + phaseLocalT * 18
                     : mapPhase === 'confirmed' ? 38
                     : 0;
    if (modelAlpha > 0.05) _drawGLBModel(ctx, px, py, modelSize, modelAlpha, critical);

    // ── Compact label tag ─────────────────────────────────────────────────
    const stateTxt = mapPhase === 'scanning'  ? '■ SCAN'
                   : mapPhase === 'analyzing' ? '◎ ANALYZING'
                   :                           '✓ LOCK';
    const tagA   = entryScale * 0.95;
    const tagCol = `rgba(${r},${g},${b},${tagA})`;
    ctx.font = '700 8px "JetBrains Mono",monospace';
    const stw = ctx.measureText(stateTxt).width + 10;
    ctx.fillStyle = `rgba(6,10,20,${tagA * 0.92})`;
    ctx.fillRect(x1, y2 + 3, stw, 13);
    ctx.fillStyle = tagCol;
    ctx.textAlign = 'left';
    ctx.fillText(stateTxt, x1 + 5, y2 + 12);

    ctx.restore();
  }

  // ── Earthquake animation overlay ─────────────────────────────────────
  _drawQuakeAnim(ctx, W, H, now);

  // ── Active-sector arc sweep beam ─────────────────────────────────────
  // Draw after YOLO frames so the beam sits below the boxes visually.
  // baseX/baseY come from the default-placements API (stored in window).
  if (window._missionBaseX != null) {
    _drawSweepBeam(ctx, W, H, now, window._missionBaseX, window._missionBaseY);
  }
}

// Scanned area: flat BLUE circle polygon, 100m radius, painted on the ground surface
function drawScannedAreas(cells) {
  if (!cells?.length || !_mapReady) return;
  let changed = false;
  for (const [x, y] of cells) {
    const key = `${x.toFixed(6)},${y.toFixed(6)}`;
    if (scannedCells.has(key)) continue;
    scannedCells.add(key);
    changed = true;
    // Build a flat polygon circle (100m radius) matching backend VISION_RADIUS
    const ring = geoCircle(x, y, 0.10, 32);  // 0.10 km = 100m
    _scannedFeats.push({
      type: 'Feature',
      geometry: { type: 'Polygon', coordinates: [ring] },
    });
  }
  if (!changed) return;

  if (mapLive.getSource('scanned')) {
    mapLive.getSource('scanned').setData({ type: 'FeatureCollection', features: _scannedFeats });
  } else {
    mapLive.addSource('scanned', { type: 'geojson', data: { type: 'FeatureCollection', features: _scannedFeats } });
    // Flat filled polygon — no extrusion, no pitch distortion
    mapLive.addLayer({
      id: 'scanned-fill', type: 'fill', source: 'scanned',
      paint: {
        'fill-color': '#0088FF',
        'fill-opacity': 0.18,
      },
    });
    // Crisp outline ring
    mapLive.addLayer({
      id: 'scanned-outline', type: 'line', source: 'scanned',
      paint: {
        'line-color': '#00CFFF',
        'line-width': 1.5,
        'line-opacity': 0.7,
      },
    });
  }
}

// Rescued area: flat GREEN circle polygon, 50m radius, rendered above blue scanned layer
function drawRescuedAreas(locations) {
  if (!locations?.length || !_mapReady) return;
  let changed = false;
  for (const [x, y] of locations) {
    const key = `${x.toFixed(6)},${y.toFixed(6)}`;
    if (rescuedCells.has(key)) continue;
    rescuedCells.add(key);
    changed = true;
    // Build a flat polygon circle (50m radius)
    const ring = geoCircle(x, y, 0.05, 32);  // 0.05 km = 50m
    _rescuedFeats.push({
      type: 'Feature',
      geometry: { type: 'Polygon', coordinates: [ring] },
    });
  }
  if (!changed) return;

  if (mapLive.getSource('rescued')) {
    mapLive.getSource('rescued').setData({ type: 'FeatureCollection', features: _rescuedFeats });
  } else {
    mapLive.addSource('rescued', { type: 'geojson', data: { type: 'FeatureCollection', features: _rescuedFeats } });
    // Flat filled polygon — solid enough to be clearly visible above blue layer
    mapLive.addLayer({
      id: 'rescued-fill', type: 'fill', source: 'rescued',
      paint: {
        'fill-color': '#00FF88',
        'fill-opacity': 0.35,
      },
    });
    // Bright green outline
    mapLive.addLayer({
      id: 'rescued-outline', type: 'line', source: 'rescued',
      paint: {
        'line-color': '#00FF88',
        'line-width': 2,
        'line-opacity': 0.9,
      },
    });
  }
}

function drawDisaster(cells) {
  // No-op: disaster zones not drawn to avoid map clutter
}

// ── FPV Drone Camera System ──────────────────────────────────────────────────
// Each drone gets a mini MapLibre 3D map locked to its position and heading.
// The camera follows the drone in first-person, pitched forward.

const fpvMaps     = {};   // slotIndex → maplibregl.Map
const fpvDroneIds = {};   // slotIndex → drone_id currently assigned
const fpvReady    = {};   // slotIndex → boolean
const fpvPrevPos  = {};   // drone_id → {lng, lat} for bearing calc
const fpvTargetState = {}; // slotIndex → {lng, lat, bearing, t0} for smooth camera
const FPV_CAM_DURATION = 400;

// Shared style for all FPV maps — same satellite imagery + 3D buildings, drone POV
const FPV_STYLE = {
  version: 8,
  sources: {
    'esri-satellite': {
      type: 'raster',
      tiles: ['https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}'],
      tileSize: 256, maxzoom: 19,
    },
    'esri-transport': {
      type: 'raster',
      tiles: ['https://server.arcgisonline.com/ArcGIS/rest/services/Reference/World_Transportation/MapServer/tile/{z}/{y}/{x}'],
      tileSize: 256, maxzoom: 19,
    },
    'terrain-dem': {
      type: 'raster-dem',
      tiles: ['https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png'],
      tileSize: 256, encoding: 'terrarium',
    },
    'buildings-vec': BUILDING_SOURCE,
  },
  terrain: { source: 'terrain-dem', exaggeration: 0 },
  light: {
    anchor: 'map',
    color: '#ffe8c0',
    intensity: 0.55,
    position: [1.15, 140, 45],
  },
  layers: [
    {
      id: 'esri-satellite-fpv', type: 'raster', source: 'esri-satellite',
      paint: { 'raster-brightness-max': 0.78, 'raster-contrast': 0.08, 'raster-saturation': -0.15 },
    },
    {
      id: 'esri-transport-fpv', type: 'raster', source: 'esri-transport',
      paint: { 'raster-opacity': 0.55 },
    },
    {
      id: 'buildings-fpv',
      type: 'fill-extrusion',
      source: 'buildings-vec',
      'source-layer': 'building',
      minzoom: 13,
      paint: BUILDING_PAINT,
    },
  ],
  sky: {
    'sky-color': '#0d1e3a',
    'sky-horizon-blend': 0.4,
    'horizon-color': '#1e3a6a',
    'horizon-fog-blend': 0.6,
    'fog-color': '#0a1628',
    'fog-ground-blend': 0.85,
  },
};

function _createFpvMap(slotIdx) {
  const containerId = 'fpv-map-' + slotIdx;
  const container = document.getElementById(containerId);
  if (!container || fpvMaps[slotIdx]) return;

  const m = new maplibregl.Map({
    container: containerId,
    style: JSON.parse(JSON.stringify(FPV_STYLE)),
    center: MAP_INIT.center,
    zoom: 16.5,
    pitch: 72,
    bearing: 0,
    interactive: false,    // no user interaction — camera is drone-locked
    attributionControl: false,
    antialias: true,
  });

  m.on('load', () => {
    fpvReady[slotIdx] = true;

    // ── Flat blue scanned-area polygons (matches main map exactly) ──────────
    m.addSource('fpv-scanned-'+slotIdx, { type:'geojson', data:{type:'FeatureCollection',features:[]} });
    m.addLayer({ id:'fpv-scanned-fill-'+slotIdx, type:'fill', source:'fpv-scanned-'+slotIdx,
      paint:{ 'fill-color':'#0088FF', 'fill-opacity':0.18 } });
    m.addLayer({ id:'fpv-scanned-outline-'+slotIdx, type:'line', source:'fpv-scanned-'+slotIdx,
      paint:{ 'line-color':'#00CFFF', 'line-width':1.5, 'line-opacity':0.7 } });

    // ── Flat green rescued-area polygons (matches main map exactly) ─────────
    m.addSource('fpv-rescued-'+slotIdx, { type:'geojson', data:{type:'FeatureCollection',features:[]} });
    m.addLayer({ id:'fpv-rescued-fill-'+slotIdx, type:'fill', source:'fpv-rescued-'+slotIdx,
      paint:{ 'fill-color':'#00FF88', 'fill-opacity':0.35 } });
    m.addLayer({ id:'fpv-rescued-outline-'+slotIdx, type:'line', source:'fpv-rescued-'+slotIdx,
      paint:{ 'line-color':'#00FF88', 'line-width':2, 'line-opacity':0.9 } });

    // ── Survivor dot markers — hidden once detected; the CV overlay draws
    //    a human figure + YOLO box at the same position instead.
    m.addSource('fpv-survivors-'+slotIdx, { type:'geojson', data:{type:'FeatureCollection',features:[]} });
    m.addLayer({ id:'fpv-survivors-layer-'+slotIdx, type:'circle', source:'fpv-survivors-'+slotIdx,
      paint:{
        'circle-radius': ['get','radius'],
        'circle-color': ['get','color'],
        'circle-opacity': ['get','opacity'],
        'circle-stroke-width': 1.5,
        'circle-stroke-color': '#ffffff',
        'circle-stroke-opacity': 0.8,
      } });

    // ── Flat red detection rings around detected survivors ───────────────────
    m.addSource('fpv-survivor-rings-'+slotIdx, { type:'geojson', data:{type:'FeatureCollection',features:[]} });
    m.addLayer({ id:'fpv-survivor-rings-fill-'+slotIdx, type:'circle', source:'fpv-survivor-rings-'+slotIdx,
      paint:{
        'circle-radius': ['interpolate',['exponential',2],['zoom'], 14,5.4, 15,10.8, 16,21.6, 17,43, 18,86],
        'circle-color':'#FF0000', 'circle-opacity':0.20,
        'circle-stroke-width':2, 'circle-stroke-color':'#FF0000', 'circle-stroke-opacity':0.5,
      } });
  });

  fpvMaps[slotIdx] = m;
}

function _bearingFromTo(lng1, lat1, lng2, lat2) {
  const dLng = (lng2 - lng1) * Math.PI / 180;
  const lat1r = lat1 * Math.PI / 180;
  const lat2r = lat2 * Math.PI / 180;
  const y = Math.sin(dLng) * Math.cos(lat2r);
  const x = Math.cos(lat1r) * Math.sin(lat2r) - Math.sin(lat1r) * Math.cos(lat2r) * Math.cos(dLng);
  return ((Math.atan2(y, x) * 180 / Math.PI) + 360) % 360;
}

// ── Per-slot mini CV system ──────────────────────────────────────────────────
// Runs directly on each small FPV tile (fpv-map-N) so CV animations play on
// the real drone feeds, not just the expanded focus view. Triggered whenever
// a drone's slot sees a newly-detected survivor inside its 100m scan radius.

const MINI_CV_DUR = { scanning: 1100, zooming: 500, analyzing: 1000, verdict: 800, pullback: 450 };
const _miniCvStates = {};        // slotIdx → { phase, phaseT0, target }
const _miniCvSeenBySlot = {};    // slotIdx → Set of already-scheduled survivor keys
const _miniCvQueueBySlot = {};   // slotIdx → FIFO queue of pending targets

function _miniCvState(slot) {
  if (!_miniCvStates[slot]) {
    _miniCvStates[slot] = { phase: 'idle', phaseT0: 0, target: null };
    _miniCvSeenBySlot[slot] = new Set();
    _miniCvQueueBySlot[slot] = [];
  }
  return _miniCvStates[slot];
}

function _miniCvStart(slot, target) {
  const st = _miniCvState(slot);
  st.target = target;
  _miniCvAdvance(slot, 'scanning');
}

function _miniCvAdvance(slot, phase) {
  const st = _miniCvState(slot);
  st.phase = phase;
  st.phaseT0 = performance.now();

  const tag = document.getElementById('fpv-mini-cv-tag-' + slot);
  if (tag) {
    const label = ({
      scanning:  'CV // ACQUIRING',
      zooming:   'CV // ENHANCE',
      analyzing: 'CV // CLASSIFY',
      verdict:   'CV // CONFIRMED',
      pullback:  'CV // LOCKED',
      idle:      '',
    })[phase] || '';
    tag.textContent = label;
    tag.classList.toggle('visible', phase !== 'idle');
    // Confirmed phase → green badge; critical targets → red (not during verdict)
    tag.classList.toggle('critical', !!(st.target && st.target.critical && phase !== 'verdict'));
    tag.classList.toggle('confirmed', phase === 'verdict');
  }

  const m = fpvMaps[slot];
  if (!m || !fpvReady[slot]) return;

  if (phase === 'scanning' && st.target) {
    // Drone stopped — zoom in toward the survivor immediately
    m.easeTo({
      center: [st.target.x, st.target.y],
      zoom: 17.8,
      pitch: 58,
      duration: 1400,
      easing: t => t < 0.5 ? 2*t*t : -1+(4-2*t)*t,
    });
  } else if (phase === 'zooming' && st.target) {
    // Deep zoom-in for the human figure reveal
    m.easeTo({
      center: [st.target.x, st.target.y],
      zoom: 19.5,
      pitch: 45,
      duration: MINI_CV_DUR.zooming,
    });
  } else if (phase === 'verdict' && st.target) {
    // Sync confirmed survivor to the main 2.5D map
    _mapConfirmSurvivor(st.target);
  } else if (phase === 'pullback') {
    const ds = fpvTargetState[slot];
    if (ds) {
      m.easeTo({
        center: [ds.lng, ds.lat],
        zoom: 16.5,
        pitch: 72,
        bearing: ds.bearing,
        duration: MINI_CV_DUR.pullback,
      });
    }
  }
}

function _miniCvProject(m, target) {
  try {
    const p = m.project([target.x, target.y]);
    return { x: p.x, y: p.y, ok: true };
  } catch (e) { return { x: 0, y: 0, ok: false }; }
}

function _miniCvResizeCanvas(slot) {
  const c = document.getElementById('fpv-mini-cv-' + slot);
  const host = document.getElementById('fpv-map-' + slot);
  if (!c || !host) return null;
  const W = host.clientWidth, H = host.clientHeight;
  if (W <= 0 || H <= 0) return null;
  const dpr = window.devicePixelRatio || 1;
  const wantW = Math.round(W * dpr), wantH = Math.round(H * dpr);
  if (c.width !== wantW || c.height !== wantH) {
    c.width = wantW; c.height = wantH;
    c.style.width = W + 'px'; c.style.height = H + 'px';
  }
  const ctx = c.getContext('2d');
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  return { ctx, W, H };
}

function _miniCvDrawScanLine(ctx, W, H, t) {
  // Two fast passes per phase — makes it look snappy
  const passT = (t * 2.5) % 1;
  const y = passT * H;
  // Wide soft gradient + bright hard line + faint trail below
  const grad = ctx.createLinearGradient(0, y - 40, 0, y + 20);
  grad.addColorStop(0,    'rgba(0,255,210,0)');
  grad.addColorStop(0.55, 'rgba(0,255,210,0.12)');
  grad.addColorStop(0.85, 'rgba(0,255,210,0.55)');
  grad.addColorStop(1,    'rgba(0,255,210,0)');
  ctx.fillStyle = grad;
  ctx.fillRect(0, y - 40, W, 60);
  // Hard bright leading edge
  ctx.save();
  ctx.shadowColor = 'rgba(0,255,210,0.9)';
  ctx.shadowBlur = 6;
  ctx.strokeStyle = 'rgba(0,255,210,0.95)';
  ctx.lineWidth = 1.6;
  ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(W, y); ctx.stroke();
  ctx.restore();
}

function _miniCvDrawTargetBox(ctx, W, H, m, target, alphaMul, now, confirmed) {
  if (!target) return;
  const p = _miniCvProject(m, target);
  if (!p.ok) return;
  const rgb = confirmed ? '0,255,138' : (target.critical ? '255,70,110' : '0,220,255');
  const a = alphaMul * (confirmed ? 1 : (0.85 + 0.15 * Math.sin(now / 150)));
  const half = 32;
  const x1 = p.x - half, y1 = p.y - half, x2 = p.x + half, y2 = p.y + half;
  const tk = 11;

  ctx.save();

  // Outer glow only on confirmed
  if (confirmed) {
    const gp = 0.6 + 0.4 * Math.sin(now / 200);
    ctx.shadowColor = `rgba(${rgb},${gp})`;
    ctx.shadowBlur = 14;
  }

  // Bounding box
  ctx.strokeStyle = `rgba(${rgb},${a})`;
  ctx.lineWidth = confirmed ? 2.4 : 1.6;
  ctx.setLineDash(confirmed ? [] : [4, 2]);
  ctx.strokeRect(x1, y1, half * 2, half * 2);
  ctx.setLineDash([]);
  ctx.shadowBlur = 0;

  // Corner brackets — thicker, sharper
  ctx.strokeStyle = `rgba(${rgb},1)`;
  ctx.lineWidth = confirmed ? 3.8 : 3.0;
  ctx.lineCap = 'square';
  ctx.beginPath();
  ctx.moveTo(x1, y1 + tk); ctx.lineTo(x1, y1); ctx.lineTo(x1 + tk, y1);
  ctx.moveTo(x2 - tk, y1); ctx.lineTo(x2, y1); ctx.lineTo(x2, y1 + tk);
  ctx.moveTo(x1, y2 - tk); ctx.lineTo(x1, y2); ctx.lineTo(x1 + tk, y2);
  ctx.moveTo(x2 - tk, y2); ctx.lineTo(x2, y2); ctx.lineTo(x2, y2 - tk);
  ctx.stroke();
  ctx.lineCap = 'butt';

  // Center crosshair dot
  if (!confirmed) {
    ctx.fillStyle = `rgba(${rgb},${a * 0.7})`;
    ctx.beginPath(); ctx.arc(p.x, p.y, 2, 0, Math.PI * 2); ctx.fill();
  }

  // Label plate
  ctx.font = '700 9px "JetBrains Mono",monospace';
  const conf = (0.88 + 0.10 * Math.min(1, alphaMul)).toFixed(2);
  const lbl = confirmed
    ? (target.critical ? `✓ CRIT ${conf}` : `✓ LOCK ${conf}`)
    : (target.critical ? `CRITICAL ${conf}` : `HUMAN ${conf}`);
  const lw = ctx.measureText(lbl).width + 8;
  ctx.fillStyle = `rgba(4,10,18,${0.88 * alphaMul})`;
  ctx.fillRect(x1, y1 - 14, lw, 13);
  ctx.fillStyle = `rgba(${rgb},1)`;
  ctx.textAlign = 'left';
  ctx.fillText(lbl, x1 + 4, y1 - 4);

  if (confirmed) {
    const badge = '■ CONFIRMED';
    const bw = ctx.measureText(badge).width + 8;
    ctx.fillStyle = 'rgba(0,20,10,0.92)';
    ctx.fillRect(x1, y2 + 3, bw, 13);
    ctx.fillStyle = 'rgba(0,255,138,1)';
    ctx.fillText(badge, x1 + 4, y2 + 13);
  }

  ctx.restore();
}

function _miniCvDrawHumanReveal(ctx, W, H, m, target, t) {
  if (!target) return;
  const p = _miniCvProject(m, target);
  if (!p.ok) return;
  const ease = 1 - Math.pow(1 - Math.max(0, Math.min(1, t)), 2);  // easeOutQuad
  _drawGLBModel(ctx, p.x, p.y, 24 + ease * 50, 0.15 + ease * 0.85, !!target.critical);
}

function _miniCvDrawAnalyzeRings(ctx, W, H, m, target, t) {
  if (!target) return;
  const p = _miniCvProject(m, target);
  if (!p.ok) return;
  const rgb = target.critical ? '255,70,110' : '0,220,255';
  ctx.save();
  // Rotating radar sweep arc
  const sweepAngle = (t * Math.PI * 4) % (Math.PI * 2);
  ctx.strokeStyle = `rgba(${rgb},0.8)`;
  ctx.lineWidth = 2;
  ctx.beginPath();
  ctx.arc(p.x, p.y, 38, sweepAngle, sweepAngle + 1.2);
  ctx.stroke();
  // 2 expanding rings with trails
  for (let i = 0; i < 2; i++) {
    const rt = Math.min(1, t * 1.6 - i * 0.3);
    if (rt <= 0) continue;
    ctx.strokeStyle = `rgba(${rgb},${(1 - rt) * 0.7})`;
    ctx.lineWidth = 1.2;
    ctx.setLineDash([5, 3]);
    ctx.beginPath(); ctx.arc(p.x, p.y, 44 * rt, 0, Math.PI * 2); ctx.stroke();
  }
  ctx.setLineDash([]);
  ctx.restore();
}

function _miniCvDrawVerdictFlash(ctx, W, H, target, t) {
  // Sharp fast flash then fade — duration maps to verdict phase length
  const flashT = Math.max(0, 1 - t * 2.5);
  if (flashT <= 0) return;
  const isC = target && target.critical;
  // Full-screen flash
  ctx.fillStyle = isC ? `rgba(255,50,90,${0.28 * flashT})` : `rgba(0,255,200,${0.22 * flashT})`;
  ctx.fillRect(0, 0, W, H);
  // Bright ring burst from target center
  if (target) {
    const p = _miniCvProject({ project: (xy) => { try { return fpvMaps[0]?.project?.(xy) || {x:W/2,y:H/2}; } catch(e){ return {x:W/2,y:H/2}; } } }, target);
    const rgb = isC ? '255,50,90' : '0,255,200';
    ctx.strokeStyle = `rgba(${rgb},${flashT * 0.9})`;
    ctx.lineWidth = 3;
    ctx.beginPath();
    ctx.arc(W/2, H/2, (1 - flashT) * 60 + 10, 0, Math.PI * 2);
    ctx.stroke();
  }
}

// Always-on pass: cyan HUMAN box + human silhouette on every detected survivor
// visible in this slot, so confirmed contacts stay annotated even between
// full CV cycles.
function _miniCvDrawConfirmedLocks(ctx, W, H, m, now, excludeKey) {
  if (!_survivorFeats || !_survivorFeats.length) return;
  for (const f of _survivorFeats) {
    const p = f.properties || {};
    if (p.rescued || !p.detected) continue;
    const [lng, lat] = f.geometry.coordinates;
    const key = `${lng.toFixed(6)},${lat.toFixed(6)}`;
    if (excludeKey && key === excludeKey) continue;  // animated target draws itself
    let px, py;
    try { const pt = m.project([lng, lat]); px = pt.x; py = pt.y; }
    catch (e) { continue; }
    if (px < -30 || py < -30 || px > W + 30 || py > H + 30) continue;
    const critical = !!p.critical;
    const rgb = critical ? '255,80,120' : '0,255,200';
    const a = 0.82 + 0.18 * Math.sin(now / 220 + px * 0.01);
    const half = 22;
    const x1 = px - half, y1 = py - half;
    ctx.save();
    ctx.strokeStyle = `rgba(${rgb},${a})`;
    ctx.lineWidth = 1.3;
    ctx.setLineDash([]);
    ctx.strokeRect(x1, y1, half * 2, half * 2);
    ctx.strokeStyle = `rgba(${rgb},${Math.min(1, a + 0.15)})`;
    ctx.lineWidth = 2.1;
    const tk = 8;
    ctx.beginPath();
    ctx.moveTo(x1, y1 + tk); ctx.lineTo(x1, y1); ctx.lineTo(x1 + tk, y1);
    ctx.moveTo(x1 + half * 2 - tk, y1); ctx.lineTo(x1 + half * 2, y1); ctx.lineTo(x1 + half * 2, y1 + tk);
    ctx.moveTo(x1, y1 + half * 2 - tk); ctx.lineTo(x1, y1 + half * 2); ctx.lineTo(x1 + tk, y1 + half * 2);
    ctx.moveTo(x1 + half * 2 - tk, y1 + half * 2); ctx.lineTo(x1 + half * 2, y1 + half * 2); ctx.lineTo(x1 + half * 2, y1 + half * 2 - tk);
    ctx.stroke();
    _drawGLBModel(ctx, px, py, 30, a, critical);
    ctx.restore();
  }
}

function _miniCvRenderSlot(slot, now) {
  const surf = _miniCvResizeCanvas(slot);
  if (!surf) return;
  const { ctx, W, H } = surf;
  ctx.clearRect(0, 0, W, H);

  const m = fpvMaps[slot];
  if (!m || !fpvReady[slot]) return;

  const st = _miniCvState(slot);

  // Drain queue: when a cycle finishes, start the next survivor after a short
  // beat so the operator can read the verdict before the next scan begins.
  if (st.phase === 'idle') {
    const q = _miniCvQueueBySlot[slot];
    if (q && q.length > 0) {
      const gap = st.phaseT0 ? 1200 : 0;  // 1.2s pause between targets
      if (now - (st.phaseT0 || 0) >= gap) {
        _miniCvStart(slot, q.shift());
      }
    } else {
      // Queue exhausted — reset the seen-set after a brief pause so every
      // detected survivor cycles through the animation continuously.
      const seen = _miniCvSeenBySlot[slot];
      if (seen && seen.size > 0 && st.phaseT0 && now - st.phaseT0 > 1800) {
        seen.clear();
      }
    }
  }

  const targetKey = st.target
    ? `${st.target.x.toFixed(6)},${st.target.y.toFixed(6)}`
    : null;

  // Always draw confirmed HUMAN locks so every detected orange dot becomes a human.
  _miniCvDrawConfirmedLocks(ctx, W, H, m, now, targetKey);

  if (st.phase === 'idle') return;
  const dur = MINI_CV_DUR[st.phase] || 1000;
  const t = Math.min((now - st.phaseT0) / dur, 1);

  switch (st.phase) {
    case 'scanning':
      _miniCvDrawScanLine(ctx, W, H, t);
      _miniCvDrawTargetBox(ctx, W, H, m, st.target, 1, now, false);
      if (t >= 1) _miniCvAdvance(slot, 'zooming');
      break;
    case 'zooming':
      _miniCvDrawTargetBox(ctx, W, H, m, st.target, 1, now, false);
      _miniCvDrawHumanReveal(ctx, W, H, m, st.target, t);
      if (t >= 1) _miniCvAdvance(slot, 'analyzing');
      break;
    case 'analyzing':
      _miniCvDrawTargetBox(ctx, W, H, m, st.target, 1, now, true);
      _miniCvDrawHumanReveal(ctx, W, H, m, st.target, 1);
      _miniCvDrawAnalyzeRings(ctx, W, H, m, st.target, t);
      if (t >= 1) _miniCvAdvance(slot, 'verdict');
      break;
    case 'verdict':
      _miniCvDrawTargetBox(ctx, W, H, m, st.target, 1, now, true);
      _miniCvDrawHumanReveal(ctx, W, H, m, st.target, 1);
      _miniCvDrawAnalyzeRings(ctx, W, H, m, st.target, 1);
      _miniCvDrawVerdictFlash(ctx, W, H, st.target, t);
      if (t >= 1) _miniCvAdvance(slot, 'pullback');
      break;
    case 'pullback':
      _miniCvDrawTargetBox(ctx, W, H, m, st.target, 1 - t, now, true);
      _miniCvDrawHumanReveal(ctx, W, H, m, st.target, 1 - t);
      if (t >= 1) _miniCvAdvance(slot, 'idle');
      break;
  }
}

function _miniCvRenderLoop(now) {
  for (let slot = 0; slot < 5; slot++) {
    _miniCvRenderSlot(slot, now);
  }
  requestAnimationFrame(_miniCvRenderLoop);
}
requestAnimationFrame(_miniCvRenderLoop);

// Queue a CV cycle on this slot for every newly-detected survivor in range.
// If a cycle is already running, additional survivors are appended and scanned
// one-by-one as the queue drains — so every survivor gets its own verification.
//
// Two triggers guarantee every drone plays the zoom+frame+confirm animation:
//   1. proximity — any detected survivor within ~280m of this drone
//   2. cv_hold rising edge — when the backend parks the drone for CV verify,
//      any in-range detected survivor is force-queued even if previously seen.
//      This is what ties the FPV animation to the mission's doctrine so the
//      user visibly sees zoom-in on every survivor, for every drone.
const _miniCvLastHold = {};   // slotIdx → last seen cv_hold boolean
function _miniCvCheckDetections(slot, drone) {
  if (!drone || !_survivorFeats || !_survivorFeats.length) return;
  _miniCvState(slot);  // ensure bookkeeping structures exist
  const seen = _miniCvSeenBySlot[slot];
  const q = _miniCvQueueBySlot[slot];
  // 0.0025 deg ≈ 280m — wider than the 200m thermal radius so we never miss a
  // survivor that the backend flagged detected just inside the scan perimeter.
  const scanRadiusDeg = 0.0025;
  const holdRising = !!drone.cv_hold && !_miniCvLastHold[slot];
  _miniCvLastHold[slot] = !!drone.cv_hold;

  for (const f of _survivorFeats) {
    const p = f.properties || {};
    if (p.rescued || !p.detected) continue;
    const [lng, lat] = f.geometry.coordinates;
    const key = `${lng.toFixed(6)},${lat.toFixed(6)}`;
    const dx = Math.abs(lng - drone.x);
    const dy = Math.abs(lat - drone.y);
    const inRange = (dx < scanRadiusDeg && dy < scanRadiusDeg);
    if (!inRange) continue;
    // Force-replay on the cv_hold rising edge so every drone's zoom-in animation
    // is guaranteed to fire the moment the backend parks it for CV verify.
    if (holdRising) {
      seen.add(key);
      q.push({ x: lng, y: lat, critical: !!p.critical, key });
      continue;
    }
    if (seen.has(key)) continue;
    seen.add(key);
    q.push({ x: lng, y: lat, critical: !!p.critical, key });
  }
}

// Smooth FPV camera animation loop — runs alongside main drone animation
function _fpvAnimLoop(now) {
  for (const slotIdx of Object.keys(fpvTargetState)) {
    // While mini CV is holding the camera (zoomed in on a survivor or easing
    // back), don't fight it with the drone-follow jumpTo.
    const mst = _miniCvStates[slotIdx];
    if (mst && mst.phase !== 'idle' && mst.phase !== 'scanning') continue;

    const st = fpvTargetState[slotIdx];
    const m  = fpvMaps[slotIdx];
    if (!st || !m || !fpvReady[slotIdx]) continue;

    const elapsed = now - st.t0;
    const rawT = Math.min(elapsed / FPV_CAM_DURATION, 1);
    const t = rawT < 0.5 ? 2*rawT*rawT : -1+(4-2*rawT)*rawT;  // ease-in-out

    const lng = _lerp(st.fromLng, st.lng, t);
    const lat = _lerp(st.fromLat, st.lat, t);

    // Smooth bearing interpolation (handle 360° wrap)
    let dBear = st.bearing - st.fromBearing;
    if (dBear > 180) dBear -= 360;
    if (dBear < -180) dBear += 360;
    const bearing = st.fromBearing + dBear * t;

    m.jumpTo({ center: [lng, lat], bearing: bearing });
  }
  requestAnimationFrame(_fpvAnimLoop);
}
requestAnimationFrame(_fpvAnimLoop);

function updateFleet(dronesArr) {
  document.getElementById('fl-cnt').textContent = dronesArr.length;

  for (let i = 0; i < dronesArr.length && i < 5; i++) {
    const d = dronesArr[i];
    const slotEl = document.getElementById('fpv-slot-' + i);

    // Create FPV map on first encounter
    if (!fpvMaps[i]) {
      _createFpvMap(i);
    }
    fpvDroneIds[i] = d.id;

    // Compute bearing: toward target if moving, else from previous position delta
    let bearing = fpvTargetState[i]?.bearing || 0;
    if (d.target) {
      bearing = _bearingFromTo(d.x, d.y, d.target.x, d.target.y);
    } else if (fpvPrevPos[d.id]) {
      const p = fpvPrevPos[d.id];
      const dx = d.x - p.lng;
      const dy = d.y - p.lat;
      if (Math.abs(dx) > 0.00001 || Math.abs(dy) > 0.00001) {
        bearing = _bearingFromTo(p.lng, p.lat, d.x, d.y);
      }
    }

    // Set animation target for smooth camera — start from wherever the camera IS right now
    const prev = fpvTargetState[i];
    const curLng = prev ? _lerp(prev.fromLng, prev.lng, Math.min((performance.now()-prev.t0)/FPV_CAM_DURATION,1)) : d.x;
    const curLat = prev ? _lerp(prev.fromLat, prev.lat, Math.min((performance.now()-prev.t0)/FPV_CAM_DURATION,1)) : d.y;
    let curBear = prev ? prev.bearing : bearing;
    if (prev) {
      let dB = prev.bearing - prev.fromBearing;
      if (dB > 180) dB -= 360; if (dB < -180) dB += 360;
      curBear = prev.fromBearing + dB * Math.min((performance.now()-prev.t0)/FPV_CAM_DURATION,1);
    }
    fpvTargetState[i] = {
      lng: d.x, lat: d.y, bearing: bearing,
      fromLng: curLng, fromLat: curLat, fromBearing: curBear,
      t0: performance.now(),
    };

    fpvPrevPos[d.id] = { lng: d.x, lat: d.y };

    // Update data layers in this FPV map
    if (fpvReady[i] && fpvMaps[i]) {
      const m = fpvMaps[i];
      // Sync scanned areas
      if (m.getSource('fpv-scanned-'+i)) {
        m.getSource('fpv-scanned-'+i).setData({type:'FeatureCollection', features:_scannedFeats});
      }
      // Sync rescued areas
      if (m.getSource('fpv-rescued-'+i)) {
        m.getSource('fpv-rescued-'+i).setData({type:'FeatureCollection', features:_rescuedFeats});
      }
      // Sync survivors
      if (m.getSource('fpv-survivors-'+i)) {
        m.getSource('fpv-survivors-'+i).setData({type:'FeatureCollection', features:_survivorFeats});
      }
      // Sync 20m green survivor rings
      if (m.getSource('fpv-survivor-rings-'+i)) {
        m.getSource('fpv-survivor-rings-'+i).setData({type:'FeatureCollection', features:_survivorRingFeats});
      }
    }

    // Fire a real CV animation on this slot's tile when a newly-detected
    // survivor shows up within 100m of this drone.
    _miniCvCheckDetections(i, d);

    // Update HUD overlay
    const statusCol = DRONE_COL[d.status] || '#ccc';
    const battCol = d.battery <= 20 ? '#ff2a6d' : d.battery <= 50 ? '#ff9500' : '#00ff9f';
    const n = d.id.replace('drone_', '');
    const slot = d.slot || ('R'+(i+1));

    const hudEl = document.getElementById('fpv-hud-' + i);
    if (hudEl) {
      hudEl.innerHTML = `<span class="fpv-id">${slot} D-${n}</span>
        <span class="fpv-batt" style="color:${battCol}">${Math.round(d.battery)}%</span>
        <span class="fpv-status" style="background:${statusCol}33;color:${statusCol}">${DRONE_LBL[d.status]||d.status}</span>`;
    }

    // Add bottom HUD if not present
    let bottomHud = slotEl?.querySelector('.fpv-hud-bottom');
    if (!bottomHud && slotEl) {
      bottomHud = document.createElement('div');
      bottomHud.className = 'fpv-hud-bottom';
      slotEl.appendChild(bottomHud);
    }
    if (bottomHud) {
      const hdg = Math.round(bearing);
      bottomHud.innerHTML = `<span>HDG ${hdg}°</span><span>${d.x.toFixed(4)}, ${d.y.toFixed(4)}</span><span>Rescued: ${d.rescued_count}</span>`;
    }

    // Active indicator
    if (slotEl) {
      slotEl.classList.toggle('active', d.status === 'MOVING' || d.status === 'SCANNING');
    }

    // ── Survivor Lock Overlay ─────────────────────────────────────────────
    // Activate the golden-border survivor lock overlay whenever the drone is
    // SCANNING and the mini-CV system has detected at least one contact on
    // this slot. Deactivate as soon as the drone leaves SCANNING state.
    const lockEl = document.getElementById('fpv-lock-' + i);
    if (lockEl) {
      const isScanning = d.status === 'SCANNING';
      const mst = _miniCvStates[i];
      const hasContact = mst && (mst.phase === 'zooming' || mst.phase === 'analyzing' || mst.phase === 'verdict');
      const lockActive = isScanning && (hasContact || (mst && mst.phase !== 'idle'));
      lockEl.classList.toggle('active', lockActive);

      // FPV zoom-in when survivor locked: zoom from 17 → 19 then hold
      if (lockActive && fpvMaps[i] && fpvReady[i]) {
        const curZ = fpvMaps[i].getZoom();
        if (curZ < 18.5) {
          fpvMaps[i].easeTo({ zoom: 19, duration: 1500, easing: t => t < 0.5 ? 2*t*t : -1+(4-2*t)*t });
        }
      } else if (!isScanning && fpvMaps[i] && fpvReady[i]) {
        // Zoom back out when scan is done
        const curZ2 = fpvMaps[i].getZoom();
        if (curZ2 > 17.2) {
          fpvMaps[i].easeTo({ zoom: 17, duration: 1200, easing: t => t*(2-t) });
        }
      }
    }
  }
}


function flyLive(x,y) { mapLive.flyTo({center:[x,y], zoom:16, pitch:60, duration:800}); }

// Click on FPV slot → fly main map to that drone
document.querySelectorAll('.fpv-slot').forEach((el, i) => {
  el.style.cursor = 'pointer';
  el.addEventListener('click', () => {
    const st = fpvTargetState[i];
    if (st) flyLive(st.lng, st.lat);
  });
});

// ══════════════════════════════════════════════════════════════════════════════
// FPV COMPUTER VISION OVERLAY SYSTEM
// Full-screen focus mode with Canvas2D scan animation, target lock, danger zones
// ══════════════════════════════════════════════════════════════════════════════

let _cvFocusMap = null;
let _cvFocusReady = false;
let _cvFocusSlot = -1;
let _cvFocusDroneData = null;
let _cvAnimId = null;
let _cvPhase = 'idle';       // idle | scanning | locked | zooming | analyzing | verdict | pullback
let _cvPhaseT0 = 0;
let _cvTargetSurvivor = null;
let _cvFrameCount = 0;
let _cvDetectedHistory = new Set();  // survivor keys already triggered
let _cvQueue = [];                   // queued survivor detections for this focused drone
let _cvScanLineY = 0;
let _cvActiveHazard = null;  // { type, polygon:[[lng,lat],...], contains:bool }
let _cvInferenceLines = [];
let _cvInferenceTimers = [];
let _cvLockFlashT0 = 0;      // timestamp of chromatic aberration flash trigger

// ── Streaming inference log (fake vision-model narration) ────────────────────
function _cvStartInferenceStream() {
  const box = document.getElementById('cv-infer-log');
  if (!box) return;
  // Clear any prior lines / pending timers
  _cvInferenceTimers.forEach(t => clearTimeout(t));
  _cvInferenceTimers = [];
  box.innerHTML = '';

  const inHz = !!(_cvActiveHazard && _cvActiveHazard.contains);
  const hazardType = _cvActiveHazard ? _cvActiveHazard.type : 'FLOOD';
  const conf = (92 + Math.random() * 7.5).toFixed(2);
  const poseOpts = ['supine', 'prone', 'seated', 'motionless'];
  const pose = poseOpts[Math.floor(Math.random() * poseOpts.length)];
  const overlap = inHz ? 'TRUE' : 'FALSE';
  const verdict = inHz ? 'CRITICAL' : 'NORMAL';

  const lines = [
    { k: 'detect_human',                    v: conf,             cls: 'ok' },
    { k: 'pose_estimate',                   v: pose,             cls: 'ok' },
    { k: `hazard_overlap(${hazardType.toLowerCase()}_zone)`, v: overlap, cls: inHz ? 'crit' : 'ok' },
    { k: 'classify_zone',                   v: verdict,          cls: inHz ? 'crit' : 'ok' },
  ];

  // Emit across the analyzing phase duration (roughly)
  const span = CV_PHASE_DUR.analyzing - 200;
  const step = Math.max(180, Math.floor(span / lines.length));
  lines.forEach((ln, i) => {
    const t = setTimeout(() => {
      const el = document.createElement('div');
      el.className = 'ln';
      el.innerHTML = `<span class="k">›</span><span class="k">${ln.k}:</span> <span class="v ${ln.cls}">${ln.v}</span>`;
      box.appendChild(el);
      requestAnimationFrame(() => el.classList.add('in'));
    }, 120 + i * step);
    _cvInferenceTimers.push(t);
  });
}

function _cvClearInferenceStream() {
  _cvInferenceTimers.forEach(t => clearTimeout(t));
  _cvInferenceTimers = [];
  const box = document.getElementById('cv-infer-log');
  if (box) box.innerHTML = '';
}

// ── Hazard polygon generation & point-in-polygon ─────────────────────────────
function _cvPointInPolygon(lng, lat, ring) {
  let inside = false;
  for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
    const xi = ring[i][0], yi = ring[i][1];
    const xj = ring[j][0], yj = ring[j][1];
    const intersect = ((yi > lat) !== (yj > lat)) &&
      (lng < (xj - xi) * (lat - yi) / ((yj - yi) || 1e-12) + xi);
    if (intersect) inside = !inside;
  }
  return inside;
}

function _cvGenerateHazard(survivor) {
  // Build an irregular blob polygon near the survivor. If survivor is critical,
  // center the polygon so it contains the survivor; otherwise offset it nearby.
  const isCritical = !!survivor.critical;
  const hazardType = Math.random() < 0.5 ? 'FLOOD' : 'EARTHQUAKE';
  const radiusDeg = 0.00045 + Math.random() * 0.00025;   // ~50-80m
  let cx, cy;
  if (isCritical) {
    cx = survivor.x + (Math.random() - 0.5) * radiusDeg * 0.4;
    cy = survivor.y + (Math.random() - 0.5) * radiusDeg * 0.4;
  } else {
    const ang = Math.random() * Math.PI * 2;
    const off = radiusDeg * 1.7;
    cx = survivor.x + Math.cos(ang) * off;
    cy = survivor.y + Math.sin(ang) * off;
  }
  const n = 14;
  const ring = [];
  for (let i = 0; i < n; i++) {
    const a = (i / n) * Math.PI * 2;
    const r = radiusDeg * (0.75 + Math.random() * 0.5);
    ring.push([cx + Math.cos(a) * r, cy + Math.sin(a) * r]);
  }
  ring.push(ring[0]);
  const contains = _cvPointInPolygon(survivor.x, survivor.y, ring);
  const color = hazardType === 'FLOOD' ? '#0077ff' : '#ff4d1f';
  const border = hazardType === 'FLOOD' ? '#00aaff' : '#ff7a3d';
  return {
    type: hazardType,
    polygon: ring,
    contains,
    feature: {
      type: 'Feature',
      geometry: { type: 'Polygon', coordinates: [ring] },
      properties: { color, border, opacity: 0.28 },
    },
  };
}

// Phase durations (ms) — tuned for live pitch demo (~6s total)
const CV_PHASE_DUR = {
  scanning:  2800,
  locked:    1200,
  zooming:   1800,
  analyzing: 3000,
  verdict:   2800,
  pullback:  1500,
};

// Canonical mini-FPV zoom (matches _createFpvMap). Focus view must show the
// same physical ground area — since the focus container is much wider than a
// mini tile, we add log2(widthRatio) zoom levels to compensate.
const FPV_MINI_ZOOM = 16.5;
const FPV_MINI_PITCH = 72;
function _fpvFocusBaseZoom() {
  const miniEl = document.getElementById('fpv-map-0');
  const focusEl = document.getElementById('fpv-focus-map');
  const miniW = (miniEl && miniEl.clientWidth) || 340;
  const focusW = (focusEl && focusEl.clientWidth) || window.innerWidth || 1920;
  if (miniW <= 0 || focusW <= 0) return FPV_MINI_ZOOM;
  return FPV_MINI_ZOOM + Math.log2(focusW / miniW);
}

function openFpvFocus(slotIdx) {
  _cvFocusSlot = slotIdx;
  const overlay = document.getElementById('fpv-focus-overlay');
  overlay.classList.add('active');

  // Create focus map if needed
  if (!_cvFocusMap) {
    const baseZoom = _fpvFocusBaseZoom();
    _cvFocusMap = new maplibregl.Map({
      container: 'fpv-focus-map',
      style: JSON.parse(JSON.stringify(FPV_STYLE)),
      center: MAP_INIT.center,
      zoom: baseZoom,
      pitch: FPV_MINI_PITCH,
      bearing: 0,
      interactive: false,
      attributionControl: false,
      antialias: true,
    });
    _cvFocusMap.on('load', () => {
      _cvFocusReady = true;
      // Add survivor layers
      _cvFocusMap.addSource('cv-survivors', { type:'geojson', data:{type:'FeatureCollection',features:[]} });
      _cvFocusMap.addLayer({ id:'cv-survivors-layer', type:'circle', source:'cv-survivors',
        paint:{
          'circle-radius': ['get','radius'],
          'circle-color': ['get','color'],
          'circle-opacity': ['get','opacity'],
          'circle-stroke-width': 2,
          'circle-stroke-color': '#ffffff',
          'circle-stroke-opacity': 0.9,
        }
      });
      // Scanned areas
      _cvFocusMap.addSource('cv-scanned', { type:'geojson', data:{type:'FeatureCollection',features:[]} });
      _cvFocusMap.addLayer({ id:'cv-scanned-fill', type:'fill', source:'cv-scanned',
        paint:{ 'fill-color':'#0088FF', 'fill-opacity':0.18 } });
      // Rescued areas
      _cvFocusMap.addSource('cv-rescued', { type:'geojson', data:{type:'FeatureCollection',features:[]} });
      _cvFocusMap.addLayer({ id:'cv-rescued-fill', type:'fill', source:'cv-rescued',
        paint:{ 'fill-color':'#00FF88', 'fill-opacity':0.35 } });
      // Hazard polygons (flood / earthquake) — observed by drone during zone classification
      _cvFocusMap.addSource('cv-hazard', { type:'geojson', data:{type:'FeatureCollection',features:[]} });
      _cvFocusMap.addLayer({ id:'cv-hazard-fill', type:'fill', source:'cv-hazard',
        paint:{
          'fill-color': ['get','color'],
          'fill-opacity': ['get','opacity'],
        }
      });
      _cvFocusMap.addLayer({ id:'cv-hazard-line', type:'line', source:'cv-hazard',
        paint:{
          'line-color': ['get','border'],
          'line-width': 2,
          'line-dasharray': [3, 2],
          'line-opacity': 0.85,
        }
      });
    });
  }

  // Sync camera to drone position
  const st = fpvTargetState[slotIdx];
  if (st && _cvFocusReady) {
    _cvFocusMap.jumpTo({ center: [st.lng, st.lat], bearing: st.bearing, zoom: _fpvFocusBaseZoom(), pitch: FPV_MINI_PITCH });
  }

  // Size canvas
  _cvResizeCanvas();

  // Start CV render loop
  if (!_cvAnimId) {
    _cvAnimId = requestAnimationFrame(_cvRenderLoop);
  }
}

function closeFpvFocus() {
  document.getElementById('fpv-focus-overlay').classList.remove('active');
  _cvFocusSlot = -1;
  _cvPhase = 'idle';
  _cvTargetSurvivor = null;
  _cvActiveHazard = null;
  _cvClearInferenceStream();
  if (_cvFocusMap && _cvFocusReady && _cvFocusMap.getSource('cv-hazard')) {
    _cvFocusMap.getSource('cv-hazard').setData({type:'FeatureCollection', features:[]});
  }
  _cvQueue = [];
  // Hide verdict
  document.getElementById('cv-verdict').classList.remove('visible');
  document.getElementById('cv-scan-progress').classList.remove('visible');
}

function _cvResizeCanvas() {
  const canvas = document.getElementById('fpv-cv-canvas');
  const wrap = document.getElementById('fpv-focus-map-wrap');
  if (canvas && wrap) {
    canvas.width = wrap.clientWidth;
    canvas.height = wrap.clientHeight;
  }
}
window.addEventListener('resize', _cvResizeCanvas);

// ── Canvas2D Rendering Engine ─────────────────────────────────────────────────

function _cvRenderLoop(now) {
  _cvAnimId = requestAnimationFrame(_cvRenderLoop);
  if (_cvFocusSlot < 0) return;

  const canvas = document.getElementById('fpv-cv-canvas');
  if (!canvas) return;
  const ctx = canvas.getContext('2d');
  const W = canvas.width, H = canvas.height;
  if (W === 0 || H === 0) return;

  ctx.clearRect(0, 0, W, H);
  _cvFrameCount++;

  // Update HUD elements
  _cvUpdateHUD(now);

  // Sync focus map camera to drone position
  _cvSyncCamera(now);

  // Always draw base HUD chrome
  _cvDrawCornerBrackets(ctx, W, H);
  _cvDrawGrid(ctx, W, H, now);

  // Phase-specific rendering
  const elapsed = now - _cvPhaseT0;
  const dur = CV_PHASE_DUR[_cvPhase] || 1;
  const t = Math.min(elapsed / dur, 1);

  switch (_cvPhase) {
    case 'scanning':
      _cvDrawScanLine(ctx, W, H, t, now);
      _cvDrawScanHUD(ctx, W, H, t);
      if (t >= 1) _cvAdvancePhase('locked');
      break;
    case 'locked':
      _cvDrawSurvivorYoloBoxes(ctx, W, H, 1, now, 1);  // lock onto every survivor
      _cvDrawSurvivorDetection(ctx, W, H, 1, now, 1);  // full-bright HUMAN box
      _cvDrawTargetLock(ctx, W, H, t);
      _cvDrawScanHUD(ctx, W, H, 1);
      if (t >= 1) _cvAdvancePhase('zooming');
      break;
    case 'zooming':
      _cvDrawSurvivorYoloBoxes(ctx, W, H, 1, now, 1 - t * 0.5);  // keep survivor locks visible
      _cvDrawSurvivorDetection(ctx, W, H, 1, now, 1 - t * 0.6);  // keep survivor box prominent
      _cvDrawTargetLock(ctx, W, H, 1);
      _cvDrawTargetHuman(ctx, W, H, t);  // orange dot → human figure reveal
      _cvDrawZoomEffect(ctx, W, H, t);
      if (t >= 1) _cvAdvancePhase('analyzing');
      break;
    case 'analyzing':
      _cvDrawTargetLock(ctx, W, H, 1);
      _cvDrawTargetHuman(ctx, W, H, 1);
      _cvDrawDangerZones(ctx, W, H, t);
      if (t >= 1) _cvAdvancePhase('verdict');
      break;
    case 'verdict':
      _cvDrawTargetLock(ctx, W, H, 1);
      _cvDrawTargetHuman(ctx, W, H, 1);
      _cvDrawDangerZones(ctx, W, H, 1);
      if (t >= 1) _cvAdvancePhase('pullback');
      break;
    case 'pullback':
      if (t >= 1) {
        _cvPhase = 'idle';
        document.getElementById('cv-verdict').classList.remove('visible');
        document.getElementById('cv-scan-progress').classList.remove('visible');
        // Check queue for next detection; if exhausted clear history so all
        // survivors cycle through the animation again continuously.
        if (_cvQueue.length > 0) {
          _cvTargetSurvivor = _cvQueue.shift();
          _cvAdvancePhase('scanning');
        } else {
          _cvDetectedHistory.clear();  // allow full re-cycle
        }
      }
      break;
    case 'idle':
      // Passive scanning animation
      _cvDrawIdleScan(ctx, W, H, now);
      break;
  }

  // Chromatic aberration flash (triggered on lock) — drawn last, over everything
  if (_cvLockFlashT0) {
    const ft = (now - _cvLockFlashT0) / 420;
    if (ft >= 1) {
      _cvLockFlashT0 = 0;
    } else {
      _cvDrawChromaFlash(ctx, W, H, ft);
    }
  }
}

function _cvDrawChromaFlash(ctx, W, H, t) {
  // Brief RGB split + white flash at the center, decaying over ~420ms
  const decay = 1 - t;
  const shift = 14 * decay;

  // Central pop of light
  const cx = W / 2, cy = H / 2;
  const rad = Math.max(W, H) * (0.15 + t * 0.25);
  const grad = ctx.createRadialGradient(cx, cy, 0, cx, cy, rad);
  grad.addColorStop(0, `rgba(255,255,255,${0.55 * decay})`);
  grad.addColorStop(0.4, `rgba(180,220,255,${0.22 * decay})`);
  grad.addColorStop(1, 'rgba(0,0,0,0)');
  ctx.fillStyle = grad;
  ctx.fillRect(0, 0, W, H);

  // RGB channel split bars across the frame
  ctx.save();
  ctx.globalCompositeOperation = 'screen';
  ctx.fillStyle = `rgba(255,40,90,${0.28 * decay})`;
  ctx.fillRect(-shift, 0, W, H);
  ctx.fillStyle = `rgba(0,200,255,${0.28 * decay})`;
  ctx.fillRect(shift, 0, W, H);
  ctx.restore();

  // Horizontal scan-jitter bars
  ctx.fillStyle = `rgba(255,255,255,${0.06 * decay})`;
  const band = 14;
  for (let i = 0; i < 4; i++) {
    const y = Math.random() * H;
    ctx.fillRect(0, y, W, band);
  }
}

function _cvAdvancePhase(newPhase) {
  _cvPhase = newPhase;
  _cvPhaseT0 = performance.now();

  const scanProg = document.getElementById('cv-scan-progress');
  const scanLabel = document.getElementById('cv-scan-label');
  const scanFill = document.getElementById('cv-scan-fill');
  const verdict = document.getElementById('cv-verdict');

  switch (newPhase) {
    case 'scanning':
      scanProg.classList.add('visible');
      scanLabel.textContent = 'THERMAL SCANNING';
      scanFill.style.width = '0%';
      verdict.classList.remove('visible');
      // Pre-generate hazard polygon for this survivor (used from zooming onward)
      if (_cvTargetSurvivor) {
        _cvActiveHazard = _cvGenerateHazard(_cvTargetSurvivor);
      }
      _cvInferenceLines = [];
      _cvDecoyBoxes = null;  // regenerate decoy detections for this scan
      _cvClearInferenceStream();
      break;
    case 'locked':
      scanLabel.textContent = 'TARGET ACQUIRED';
      scanFill.style.width = '35%';
      _cvLockFlashT0 = performance.now();  // trigger chromatic aberration flash
      break;
    case 'zooming':
      scanLabel.textContent = 'ZOOM ENHANCE';
      scanFill.style.width = '55%';
      // Render hazard polygon on focus map so it's visible when camera settles
      if (_cvFocusMap && _cvFocusReady && _cvActiveHazard && _cvFocusMap.getSource('cv-hazard')) {
        _cvFocusMap.getSource('cv-hazard').setData({
          type: 'FeatureCollection', features: [_cvActiveHazard.feature]
        });
      }
      // Zoom camera in
      if (_cvFocusMap && _cvFocusReady && _cvTargetSurvivor) {
        _cvFocusMap.easeTo({
          center: [_cvTargetSurvivor.x, _cvTargetSurvivor.y],
          zoom: _fpvFocusBaseZoom() + 2.5,
          pitch: 55,
          duration: CV_PHASE_DUR.zooming,
        });
      }
      break;
    case 'analyzing':
      scanLabel.textContent = 'ZONE CLASSIFICATION';
      scanFill.style.width = '80%';
      // Update confidence
      const conf = (92 + Math.random() * 7.5).toFixed(1);
      document.getElementById('cv-confidence').innerHTML =
        `SURVIVOR CONFIDENCE: <span class="cv-confidence-val">${conf}%</span>`;
      // Start streaming inference log
      _cvStartInferenceStream();
      break;
    case 'verdict':
      scanLabel.textContent = 'ANALYSIS COMPLETE';
      scanFill.style.width = '100%';
      // Show verdict — driven by polygon intersection, not survivor flag
      const inHazard = !!(_cvActiveHazard && _cvActiveHazard.contains);
      const hazardType = _cvActiveHazard ? _cvActiveHazard.type : 'FLOOD';
      const badge = document.getElementById('cv-verdict-badge');
      const sub = document.getElementById('cv-verdict-sub');
      badge.className = inHazard ? 'critical-zone' : 'normal-zone';
      badge.textContent = inHazard ? '⚠ CRITICAL ZONE' : '✓ NORMAL ZONE';
      sub.textContent = inHazard
        ? `SURVIVOR INSIDE ${hazardType} HAZARD POLYGON — PRIORITY DISPATCH`
        : `SURVIVOR OUTSIDE ${hazardType} HAZARD POLYGON — STANDARD EXTRACTION`;
      verdict.classList.add('visible');
      // Update threat bar
      const threatFill = document.getElementById('cv-threat-fill');
      threatFill.className = 'cv-threat-fill ' + (inHazard ? 'critical' : 'safe');
      break;
    case 'pullback':
      // Pull camera back & clear hazard overlay
      if (_cvFocusMap && _cvFocusReady) {
        const st = fpvTargetState[_cvFocusSlot];
        if (st) {
          _cvFocusMap.easeTo({
            center: [st.lng, st.lat],
            zoom: _fpvFocusBaseZoom(),
            pitch: FPV_MINI_PITCH,
            bearing: st.bearing,
            duration: CV_PHASE_DUR.pullback,
          });
        }
        if (_cvFocusMap.getSource('cv-hazard')) {
          _cvFocusMap.getSource('cv-hazard').setData({type:'FeatureCollection', features:[]});
        }
      }
      _cvActiveHazard = null;
      break;
  }
}

// ── Camera Sync ────────────────────────────────────────────────────────────────

function _cvSyncCamera(now) {
  if (!_cvFocusReady || !_cvFocusMap || _cvFocusSlot < 0) return;
  const st = fpvTargetState[_cvFocusSlot];
  if (!st) return;

  // During active phases (zooming/analyzing/verdict), camera is controlled by easeTo
  if (['zooming', 'analyzing', 'verdict'].includes(_cvPhase)) return;

  // Otherwise, track the drone position smoothly
  const elapsed = now - st.t0;
  const rawT = Math.min(elapsed / FPV_CAM_DURATION, 1);
  const t = rawT < 0.5 ? 2*rawT*rawT : -1+(4-2*rawT)*rawT;

  const lng = _lerp(st.fromLng, st.lng, t);
  const lat = _lerp(st.fromLat, st.lat, t);

  let dBear = st.bearing - st.fromBearing;
  if (dBear > 180) dBear -= 360;
  if (dBear < -180) dBear += 360;
  const bearing = st.fromBearing + dBear * t;

  _cvFocusMap.jumpTo({ center: [lng, lat], bearing: bearing });

  // Sync data layers
  if (_cvFocusMap.getSource('cv-survivors')) {
    _cvFocusMap.getSource('cv-survivors').setData({type:'FeatureCollection', features:_survivorFeats});
  }
  if (_cvFocusMap.getSource('cv-scanned')) {
    _cvFocusMap.getSource('cv-scanned').setData({type:'FeatureCollection', features:_scannedFeats});
  }
  if (_cvFocusMap.getSource('cv-rescued')) {
    _cvFocusMap.getSource('cv-rescued').setData({type:'FeatureCollection', features:_rescuedFeats});
  }
}

// ── HUD Update ─────────────────────────────────────────────────────────────────

function _cvUpdateHUD(now) {
  const st = fpvTargetState[_cvFocusSlot];
  const droneId = fpvDroneIds[_cvFocusSlot];
  if (!st || !droneId) return;

  // Find drone data from last known state
  if (_cvFocusDroneData) {
    const d = _cvFocusDroneData;
    const slot = d.slot || ('R' + (_cvFocusSlot + 1));
    const n = d.id.replace('drone_', '');
    document.getElementById('cv-drone-label').textContent = `${slot} D-${n}`;
    const battCol = d.battery <= 20 ? '#ff2a6d' : d.battery <= 50 ? '#ff9500' : '#00ff9f';
    const battEl = document.getElementById('cv-batt-label');
    battEl.textContent = Math.round(d.battery) + '%';
    battEl.style.color = battCol;
    document.getElementById('cv-coord-label').textContent = `${d.x.toFixed(4)}, ${d.y.toFixed(4)}`;
    document.getElementById('cv-hdg').textContent = `HDG ${Math.round(st.bearing)}°`;
  }

  document.getElementById('cv-frame').textContent = `FRM ${String(_cvFrameCount).padStart(4, '0')}`;
  const d = new Date();
  document.getElementById('cv-ts').textContent =
    `${String(d.getHours()).padStart(2,'0')}:${String(d.getMinutes()).padStart(2,'0')}:${String(d.getSeconds()).padStart(2,'0')}`;
}

// ── Canvas Drawing Functions ──────────────────────────────────────────────────

function _cvDrawCornerBrackets(ctx, W, H) {
  const len = 40, off = 20, lw = 2;
  ctx.strokeStyle = 'rgba(0, 255, 136, 0.4)';
  ctx.lineWidth = lw;
  ctx.setLineDash([]);

  // Top-left
  ctx.beginPath(); ctx.moveTo(off, off + len); ctx.lineTo(off, off); ctx.lineTo(off + len, off); ctx.stroke();
  // Top-right
  ctx.beginPath(); ctx.moveTo(W - off - len, off); ctx.lineTo(W - off, off); ctx.lineTo(W - off, off + len); ctx.stroke();
  // Bottom-left
  ctx.beginPath(); ctx.moveTo(off, H - off - len); ctx.lineTo(off, H - off); ctx.lineTo(off + len, H - off); ctx.stroke();
  // Bottom-right
  ctx.beginPath(); ctx.moveTo(W - off - len, H - off); ctx.lineTo(W - off, H - off); ctx.lineTo(W - off, H - off - len); ctx.stroke();
}

function _cvDrawGrid(ctx, W, H, now) {
  const gridSpacing = 80;
  const opacity = 0.06 + Math.sin(now / 3000) * 0.02;
  ctx.strokeStyle = `rgba(0, 255, 136, ${opacity})`;
  ctx.lineWidth = 0.5;
  ctx.setLineDash([]);

  // Vertical lines
  for (let x = gridSpacing; x < W; x += gridSpacing) {
    ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, H); ctx.stroke();
  }
  // Horizontal lines
  for (let y = gridSpacing; y < H; y += gridSpacing) {
    ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(W, y); ctx.stroke();
  }
}

function _cvDrawIdleScan(ctx, W, H, now) {
  // Slow horizontal scan line
  const period = 4000;
  const yPos = (now % period) / period * H;
  const grad = ctx.createLinearGradient(0, yPos - 30, 0, yPos + 30);
  grad.addColorStop(0, 'rgba(0, 255, 136, 0)');
  grad.addColorStop(0.5, 'rgba(0, 255, 136, 0.15)');
  grad.addColorStop(1, 'rgba(0, 255, 136, 0)');
  ctx.fillStyle = grad;
  ctx.fillRect(0, yPos - 30, W, 60);

  // Scan line
  ctx.strokeStyle = 'rgba(0, 255, 136, 0.3)';
  ctx.lineWidth = 1;
  ctx.setLineDash([]);
  ctx.beginPath(); ctx.moveTo(0, yPos); ctx.lineTo(W, yPos); ctx.stroke();
}

// ── YOLO-style decoy bounding boxes during scanning ──────────────────────────
let _cvDecoyBoxes = null;
function _cvEnsureDecoyBoxes(W, H) {
  if (_cvDecoyBoxes && _cvDecoyBoxes.W === W && _cvDecoyBoxes.H === H) return _cvDecoyBoxes;
  const boxes = [];
  const labels = ['debris', 'vehicle', 'rubble', 'tree', 'structure', 'vehicle', 'debris', 'rooftop'];
  const targetN = 6;
  let guard = 0;
  while (boxes.length < targetN && guard++ < 40) {
    const bw = 70 + Math.random() * 90;
    const bh = 60 + Math.random() * 80;
    const bx = 40 + Math.random() * Math.max(40, W - bw - 80);
    const by = 70 + Math.random() * Math.max(40, H - bh - 200);
    // Avoid strict center square (reserved for target)
    if (Math.abs(bx + bw/2 - W/2) < 90 && Math.abs(by + bh/2 - H/2) < 90) continue;
    boxes.push({
      x: bx, y: by, w: bw, h: bh,
      label: labels[Math.floor(Math.random() * labels.length)],
      conf: (0.42 + Math.random() * 0.45).toFixed(2),
      appearAt: Math.random() * 0.35,  // all boxes must be visible by 35% through scan
      flick: Math.random() * 6.28,
    });
  }
  _cvDecoyBoxes = { W, H, boxes };
  return _cvDecoyBoxes;
}

function _cvDrawDecoyBoxes(ctx, W, H, t, now, alphaMul) {
  if (alphaMul === undefined) alphaMul = 1;
  if (alphaMul <= 0) return;
  const cache = _cvEnsureDecoyBoxes(W, H);
  ctx.setLineDash([]);
  ctx.font = '800 10px "JetBrains Mono"';
  for (const b of cache.boxes) {
    if (t < b.appearAt) continue;
    const localT = Math.min((t - b.appearAt) / 0.2, 1);
    const flicker = 0.85 + Math.sin(now / 140 + b.flick) * 0.15;
    const alpha = (0.6 + localT * 0.4) * flicker * alphaMul;
    // Box outline
    ctx.strokeStyle = `rgba(255, 180, 0, ${alpha})`;
    ctx.lineWidth = 2;
    ctx.strokeRect(b.x, b.y, b.w, b.h);
    // Thicker corner ticks for that "detector" look
    ctx.strokeStyle = `rgba(255, 220, 80, ${alpha})`;
    ctx.lineWidth = 3;
    const tk = 10;
    ctx.beginPath();
    ctx.moveTo(b.x, b.y + tk); ctx.lineTo(b.x, b.y); ctx.lineTo(b.x + tk, b.y);
    ctx.moveTo(b.x + b.w - tk, b.y); ctx.lineTo(b.x + b.w, b.y); ctx.lineTo(b.x + b.w, b.y + tk);
    ctx.moveTo(b.x, b.y + b.h - tk); ctx.lineTo(b.x, b.y + b.h); ctx.lineTo(b.x + tk, b.y + b.h);
    ctx.moveTo(b.x + b.w - tk, b.y + b.h); ctx.lineTo(b.x + b.w, b.y + b.h); ctx.lineTo(b.x + b.w, b.y + b.h - tk);
    ctx.stroke();
    // Label plate
    const labelText = `${b.label} ${b.conf}`;
    const tw = ctx.measureText(labelText).width + 10;
    ctx.fillStyle = `rgba(20, 14, 0, ${0.8 * alpha})`;
    ctx.fillRect(b.x, b.y - 16, tw, 15);
    ctx.fillStyle = `rgba(255, 220, 80, ${alpha})`;
    ctx.textAlign = 'left';
    ctx.fillText(labelText, b.x + 5, b.y - 4);
  }
}

// Realistic survivor figure — head + shaded torso + jointed arms and legs with
// a subtle wave animation and ground shadow. Rendered entirely in canvas2D so
// it runs on every FPV mini-tile and the main-map overlay simultaneously
// without the overhead of a WebGL humanoid per slot.
function _cvDrawHumanFigure(ctx, cx, cy, scale, alpha, critical) {
  const s = scale;
  const rgb = critical ? '255, 90, 130' : '120, 240, 255';
  const rgbDark = critical ? '140, 30, 60' : '10, 80, 120';
  const rgbLight = critical ? '255, 170, 190' : '200, 255, 255';
  const t = performance.now() / 1000;
  const sway = Math.sin(t * 2.2) * 0.08;  // subtle wave sway in radians

  ctx.save();
  ctx.translate(cx, cy);
  ctx.scale(s, s);

  // Ground shadow ellipse
  ctx.save();
  ctx.fillStyle = `rgba(0, 0, 0, ${0.32 * alpha})`;
  ctx.beginPath();
  ctx.ellipse(0, 22, 10, 3, 0, 0, Math.PI * 2);
  ctx.fill();
  ctx.restore();

  // Outer halo (confirmed-lock glow)
  const halo = ctx.createRadialGradient(0, 0, 0, 0, 0, 24);
  halo.addColorStop(0, `rgba(${rgb}, ${0.28 * alpha})`);
  halo.addColorStop(1, `rgba(${rgb}, 0)`);
  ctx.fillStyle = halo;
  ctx.beginPath(); ctx.arc(0, 0, 24, 0, Math.PI * 2); ctx.fill();

  // ── Legs (stance) ─────────────────────────────────────────────
  ctx.save();
  ctx.lineCap = 'round';
  ctx.lineJoin = 'round';

  const legGrad = ctx.createLinearGradient(0, 4, 0, 22);
  legGrad.addColorStop(0, `rgba(${rgbDark}, ${alpha})`);
  legGrad.addColorStop(1, `rgba(${rgb}, ${alpha})`);
  ctx.strokeStyle = legGrad;
  ctx.lineWidth = 3.2;

  // Left leg: hip → knee → foot
  ctx.beginPath();
  ctx.moveTo(-1.5, 4);
  ctx.lineTo(-3.5, 13);
  ctx.lineTo(-4.5, 21);
  ctx.stroke();

  // Right leg: hip → knee → foot (slightly bent)
  ctx.beginPath();
  ctx.moveTo(1.5, 4);
  ctx.lineTo(3.5, 13);
  ctx.lineTo(4.5, 21);
  ctx.stroke();
  ctx.restore();

  // ── Torso ─────────────────────────────────────────────────────
  ctx.save();
  const torsoGrad = ctx.createLinearGradient(-5, -8, 5, 6);
  torsoGrad.addColorStop(0, `rgba(${rgbLight}, ${alpha})`);
  torsoGrad.addColorStop(0.5, `rgba(${rgb}, ${alpha})`);
  torsoGrad.addColorStop(1, `rgba(${rgbDark}, ${alpha})`);
  ctx.fillStyle = torsoGrad;
  // Trapezoidal torso: wider shoulders, narrow waist
  ctx.beginPath();
  ctx.moveTo(-5, -6);
  ctx.lineTo(5, -6);
  ctx.lineTo(4, 5);
  ctx.lineTo(-4, 5);
  ctx.closePath();
  ctx.fill();
  // Torso outline
  ctx.strokeStyle = `rgba(${rgbDark}, ${alpha * 0.9})`;
  ctx.lineWidth = 0.8;
  ctx.stroke();
  ctx.restore();

  // ── Arms (one waving, one at side) ────────────────────────────
  ctx.save();
  ctx.lineCap = 'round';
  ctx.lineJoin = 'round';
  const armGrad = ctx.createLinearGradient(0, -10, 0, 5);
  armGrad.addColorStop(0, `rgba(${rgbLight}, ${alpha})`);
  armGrad.addColorStop(1, `rgba(${rgb}, ${alpha})`);
  ctx.strokeStyle = armGrad;
  ctx.lineWidth = 2.6;

  // Left arm: shoulder → elbow → hand (down at side)
  ctx.beginPath();
  ctx.moveTo(-4.5, -5);
  ctx.lineTo(-7, 0);
  ctx.lineTo(-7.5, 6);
  ctx.stroke();

  // Right arm: shoulder → elbow → hand raised up (waving with sway)
  const waveA = Math.cos(sway * 2) * 1.2;
  const waveB = Math.sin(sway * 3) * 1.5;
  ctx.beginPath();
  ctx.moveTo(4.5, -5);
  ctx.lineTo(8 + waveA, -10);
  ctx.lineTo(9 + waveB, -16 + Math.sin(t * 4) * 0.8);
  ctx.stroke();
  ctx.restore();

  // ── Neck ──────────────────────────────────────────────────────
  ctx.save();
  ctx.strokeStyle = `rgba(${rgbDark}, ${alpha})`;
  ctx.lineWidth = 1.8;
  ctx.beginPath();
  ctx.moveTo(0, -6);
  ctx.lineTo(0, -9);
  ctx.stroke();
  ctx.restore();

  // ── Head ──────────────────────────────────────────────────────
  ctx.save();
  ctx.translate(0, -13);

  // Hair / scalp (darker cap)
  ctx.fillStyle = `rgba(${rgbDark}, ${alpha})`;
  ctx.beginPath();
  ctx.arc(0, 0, 4.2, Math.PI * 1.05, Math.PI * 1.95, false);
  ctx.fill();

  // Face — radial gradient for a 3D look
  const headGrad = ctx.createRadialGradient(-1.2, -1, 0, 0, 0, 4.2);
  headGrad.addColorStop(0, `rgba(${rgbLight}, ${alpha})`);
  headGrad.addColorStop(0.7, `rgba(${rgb}, ${alpha})`);
  headGrad.addColorStop(1, `rgba(${rgbDark}, ${alpha})`);
  ctx.fillStyle = headGrad;
  ctx.beginPath();
  ctx.arc(0, 0, 4, 0, Math.PI * 2);
  ctx.fill();

  // Eyes — tiny dark dots
  ctx.fillStyle = `rgba(12, 18, 26, ${alpha * 0.95})`;
  ctx.beginPath();
  ctx.arc(-1.3, -0.3, 0.55, 0, Math.PI * 2);
  ctx.arc(1.3, -0.3, 0.55, 0, Math.PI * 2);
  ctx.fill();

  // Head outline
  ctx.strokeStyle = `rgba(${rgbDark}, ${alpha})`;
  ctx.lineWidth = 0.6;
  ctx.beginPath();
  ctx.arc(0, 0, 4, 0, Math.PI * 2);
  ctx.stroke();
  ctx.restore();

  // ── Confirmed-lock outline glow (subtle) ──────────────────────
  ctx.save();
  ctx.shadowColor = `rgba(${rgb}, ${alpha * 0.8})`;
  ctx.shadowBlur = 8;
  ctx.strokeStyle = `rgba(${rgb}, 0)`;
  ctx.lineWidth = 0.01;
  ctx.strokeRect(-6, -17, 12, 38);
  ctx.restore();

  ctx.restore();
}

// Project every non-rescued survivor onto the FPV focus canvas and draw a
// YOLO-style bounding box on each — so the boxes truly lock to the orange dots
// rather than floating at random positions.
function _cvDrawSurvivorYoloBoxes(ctx, W, H, t, now, alphaMul) {
  if (alphaMul === undefined) alphaMul = 1;
  if (alphaMul <= 0) return;
  if (!_cvFocusMap || !_cvFocusReady) return;
  if (!_survivorFeats || !_survivorFeats.length) return;

  const targetKey = _cvTargetSurvivor
    ? `${_cvTargetSurvivor.x.toFixed(6)},${_cvTargetSurvivor.y.toFixed(6)}`
    : null;

  ctx.save();
  ctx.font = '800 10px "JetBrains Mono", monospace';
  for (const f of _survivorFeats) {
    const p = f.properties || {};
    if (p.rescued) continue;
    const [lng, lat] = f.geometry.coordinates;
    let px, py;
    try {
      const pt = _cvFocusMap.project([lng, lat]);
      px = pt.x; py = pt.y;
    } catch (e) { continue; }
    // Only draw if in-frame (plus margin)
    if (px < -60 || py < -60 || px > W + 60 || py > H + 60) continue;

    // Skip the featured target — _cvDrawSurvivorDetection draws it with extra HUD
    const key = `${lng.toFixed(6)},${lat.toFixed(6)}`;
    if (targetKey && key === targetKey) continue;

    const critical = !!p.critical;
    const detected = !!p.detected;
    if (!detected) continue;  // only draw locks for confirmed detections
    // Stagger appear-in by a deterministic hash of coords
    const appearAt = ((Math.abs(lng * 1000 + lat * 1000) % 100) / 100) * 0.35;
    if (t < appearAt) continue;
    const localT = Math.min((t - appearAt) / 0.2, 1);
    const flicker = 0.85 + Math.sin(now / 150 + lng * 1000) * 0.15;
    const [r, g, bCol] = [0, 255, 200];
    const a = (0.6 + 0.4 * localT) * flicker * alphaMul;

    const half = critical ? 46 : 36;
    const x1 = px - half, y1 = py - half, x2 = px + half, y2 = py + half;

    // Solid rect for confirmed detections
    ctx.strokeStyle = `rgba(${r},${g},${bCol},${a})`;
    ctx.lineWidth = 2;
    ctx.setLineDash([]);
    ctx.strokeRect(x1, y1, half * 2, half * 2);

    // Thick corner brackets
    ctx.strokeStyle = `rgba(${r},${g},${bCol},${Math.min(1, a + 0.1)})`;
    ctx.lineWidth = 3;
    const tk = Math.max(8, half * 0.3);
    ctx.beginPath();
    ctx.moveTo(x1, y1 + tk); ctx.lineTo(x1, y1); ctx.lineTo(x1 + tk, y1);
    ctx.moveTo(x2 - tk, y1); ctx.lineTo(x2, y1); ctx.lineTo(x2, y1 + tk);
    ctx.moveTo(x1, y2 - tk); ctx.lineTo(x1, y2); ctx.lineTo(x1 + tk, y2);
    ctx.moveTo(x2 - tk, y2); ctx.lineTo(x2, y2); ctx.lineTo(x2, y2 - tk);
    ctx.stroke();

    // Label plate
    const conf = (0.92 + Math.sin(now / 400 + lng * 100) * 0.04).toFixed(2);
    const label = critical ? `HUMAN•CRIT ${conf}` : `HUMAN ${conf}`;
    const tw = ctx.measureText(label).width + 10;
    ctx.fillStyle = `rgba(20,14,0,${0.82 * a})`;
    ctx.fillRect(x1, y1 - 17, tw, 15);
    ctx.fillStyle = `rgba(${r},${g},${bCol},${a})`;
    ctx.textAlign = 'left';
    ctx.fillText(label, x1 + 5, y1 - 5);
  }
  ctx.restore();
}

// Prominent "HUMAN" detection box locked to projected survivor position.
// Only draws if the survivor position has been projected on screen (i.e. focus map is ready).
function _cvDrawSurvivorDetection(ctx, W, H, t, now, alphaMul) {
  if (!_cvTargetSurvivor) return;
  const p = _cvProjectSurvivor(W, H);
  if (!p.projected) return;
  const appearAt = 0.15;
  if (t < appearAt) return;
  const localT = Math.min((t - appearAt) / 0.3, 1);
  const pulse = 0.85 + Math.sin(now / 180) * 0.15;
  const alpha = (0.7 + 0.3 * localT) * pulse * (alphaMul ?? 1);
  const half = 56;
  const cx = p.x, cy = p.y;
  const x1 = cx - half, y1 = cy - half, x2 = cx + half, y2 = cy + half;

  // Outer soft glow
  ctx.save();
  ctx.shadowColor = 'rgba(0, 255, 200, 0.9)';
  ctx.shadowBlur = 16;
  ctx.strokeStyle = `rgba(0, 255, 200, ${alpha})`;
  ctx.lineWidth = 2.5;
  ctx.setLineDash([]);
  ctx.strokeRect(x1, y1, half * 2, half * 2);
  ctx.restore();

  // Thick corner brackets
  ctx.strokeStyle = `rgba(0, 255, 200, ${alpha})`;
  ctx.lineWidth = 4;
  const tk = 14;
  ctx.beginPath();
  ctx.moveTo(x1, y1 + tk); ctx.lineTo(x1, y1); ctx.lineTo(x1 + tk, y1);
  ctx.moveTo(x2 - tk, y1); ctx.lineTo(x2, y1); ctx.lineTo(x2, y1 + tk);
  ctx.moveTo(x1, y2 - tk); ctx.lineTo(x1, y2); ctx.lineTo(x1 + tk, y2);
  ctx.moveTo(x2 - tk, y2); ctx.lineTo(x2, y2); ctx.lineTo(x2, y2 - tk);
  ctx.stroke();

  // Label plate "HUMAN 0.97"
  ctx.font = '800 11px "JetBrains Mono"';
  const conf = (0.93 + Math.sin(now / 400) * 0.03).toFixed(2);
  const labelText = `HUMAN ${conf}`;
  const tw = ctx.measureText(labelText).width + 12;
  ctx.fillStyle = `rgba(0, 40, 36, ${0.92 * alpha})`;
  ctx.fillRect(x1, y1 - 19, tw, 18);
  ctx.fillStyle = `rgba(0, 255, 200, ${alpha})`;
  ctx.textAlign = 'left';
  ctx.fillText(labelText, x1 + 6, y1 - 5);

  // Tracer line from HUD to box (reads as "sensor fusion")
  ctx.strokeStyle = `rgba(0, 255, 200, ${0.35 * alpha})`;
  ctx.lineWidth = 1;
  ctx.setLineDash([3, 3]);
  ctx.beginPath();
  ctx.moveTo(20, 20);
  ctx.lineTo(x1, y1);
  ctx.stroke();
  ctx.setLineDash([]);
}

function _cvDrawScanLine(ctx, W, H, t, now) {
  // Fast multi-pass scan
  const passCount = 3;
  const passT = (t * passCount) % 1;
  const yPos = passT * H;

  // Bright scan line
  const grad = ctx.createLinearGradient(0, yPos - 60, 0, yPos + 60);
  grad.addColorStop(0, 'rgba(0, 255, 136, 0)');
  grad.addColorStop(0.3, 'rgba(0, 255, 136, 0.08)');
  grad.addColorStop(0.5, 'rgba(0, 255, 136, 0.25)');
  grad.addColorStop(0.7, 'rgba(0, 255, 136, 0.08)');
  grad.addColorStop(1, 'rgba(0, 255, 136, 0)');
  ctx.fillStyle = grad;
  ctx.fillRect(0, yPos - 60, W, 120);

  ctx.strokeStyle = 'rgba(0, 255, 136, 0.6)';
  ctx.lineWidth = 2;
  ctx.setLineDash([]);
  ctx.beginPath(); ctx.moveTo(0, yPos); ctx.lineTo(W, yPos); ctx.stroke();

  // Static noise effect (random dots)
  ctx.fillStyle = 'rgba(0, 255, 136, 0.04)';
  for (let i = 0; i < 120; i++) {
    const nx = Math.random() * W;
    const ny = Math.random() * H;
    ctx.fillRect(nx, ny, 2, 2);
  }

  // Real survivor locks — YOLO boxes anchored to every orange dot in frame
  _cvDrawSurvivorYoloBoxes(ctx, W, H, t, now, 1);

  // Featured target — prominent "HUMAN" lock on the drone's current target
  _cvDrawSurvivorDetection(ctx, W, H, t, now, 1);

  // Update scan progress bar
  const scanFill = document.getElementById('cv-scan-fill');
  if (scanFill) scanFill.style.width = Math.round(t * 30) + '%';
}

function _cvDrawScanHUD(ctx, W, H, t) {
  // "THERMAL IMAGING" label
  ctx.font = '800 11px "JetBrains Mono"';
  ctx.fillStyle = `rgba(0, 255, 136, ${0.5 + Math.sin(performance.now() / 500) * 0.3})`;
  ctx.textAlign = 'left';
  ctx.fillText('THERMAL IMAGING ACTIVE', 30, H - 80);

  // Detection range
  ctx.font = '500 10px "JetBrains Mono"';
  ctx.fillStyle = 'rgba(148, 163, 184, 0.7)';
  ctx.fillText('SCAN RADIUS: 100m  |  IR BAND: 8-14μm', 30, H - 65);
}

// Project survivor lng/lat to canvas pixel coords; falls back to screen center
function _cvProjectSurvivor(W, H) {
  if (!_cvTargetSurvivor || !_cvFocusMap || !_cvFocusReady) {
    return { x: W / 2, y: H / 2, projected: false };
  }
  try {
    const p = _cvFocusMap.project([_cvTargetSurvivor.x, _cvTargetSurvivor.y]);
    // Clamp to visible area with a margin so the box doesn't leave frame
    const margin = 110;
    const x = Math.max(margin, Math.min(W - margin, p.x));
    const y = Math.max(margin, Math.min(H - margin, p.y));
    return { x, y, projected: true };
  } catch (e) {
    return { x: W / 2, y: H / 2, projected: false };
  }
}

// Draw the 3D GLB human figure locked to the featured survivor's projected
// position on the FPV focus canvas. t animates the emergence so the reveal
// feels like the CV model committing a detection (orange dot → full 3D model).
function _cvDrawTargetHuman(ctx, W, H, t) {
  if (!_cvTargetSurvivor) return;
  const p = _cvProjectSurvivor(W, H);
  if (!p.projected) return;
  const ease = t < 1 ? (1 - Math.pow(1 - t, 3)) : 1;  // cubic ease-out
  const sizePx = 90 + ease * 130;  // 90 → 220px in full-screen FPV
  const alpha = 0.18 + ease * 0.82;
  const critical = !!_cvTargetSurvivor.critical;
  _drawGLBModel(ctx, p.x, p.y, sizePx, alpha, critical);
}

function _cvDrawTargetLock(ctx, W, H, t) {
  if (!_cvTargetSurvivor) return;
  const p = _cvProjectSurvivor(W, H);
  const cx = p.x, cy = p.y;

  // Animated converging corner brackets
  const boxSize = 80 - t * 20;  // shrinks from 80 to 60
  const bracketLen = 18;
  const easeT = t < 0.5 ? 2*t*t : -1+(4-2*t)*t;

  ctx.strokeStyle = `rgba(255, 42, 109, ${0.6 + easeT * 0.4})`;
  ctx.lineWidth = 2.5;
  ctx.setLineDash([]);

  const x1 = cx - boxSize, y1 = cy - boxSize;
  const x2 = cx + boxSize, y2 = cy + boxSize;

  // Top-left
  ctx.beginPath(); ctx.moveTo(x1, y1 + bracketLen); ctx.lineTo(x1, y1); ctx.lineTo(x1 + bracketLen, y1); ctx.stroke();
  // Top-right
  ctx.beginPath(); ctx.moveTo(x2 - bracketLen, y1); ctx.lineTo(x2, y1); ctx.lineTo(x2, y1 + bracketLen); ctx.stroke();
  // Bottom-left
  ctx.beginPath(); ctx.moveTo(x1, y2 - bracketLen); ctx.lineTo(x1, y2); ctx.lineTo(x1 + bracketLen, y2); ctx.stroke();
  // Bottom-right
  ctx.beginPath(); ctx.moveTo(x2 - bracketLen, y2); ctx.lineTo(x2, y2); ctx.lineTo(x2, y2 - bracketLen); ctx.stroke();

  // Crosshair lines (thin, dashed)
  ctx.strokeStyle = 'rgba(255, 42, 109, 0.25)';
  ctx.lineWidth = 1;
  ctx.setLineDash([4, 4]);
  ctx.beginPath(); ctx.moveTo(cx, y1 - 20); ctx.lineTo(cx, y2 + 20); ctx.stroke();
  ctx.beginPath(); ctx.moveTo(x1 - 20, cy); ctx.lineTo(x2 + 20, cy); ctx.stroke();
  ctx.setLineDash([]);

  // Target label
  ctx.font = '800 11px "JetBrains Mono"';
  ctx.fillStyle = 'rgba(255, 42, 109, 0.9)';
  ctx.textAlign = 'left';
  const inHz = !!(_cvActiveHazard && _cvActiveHazard.contains);
  const critLabel = inHz ? 'CRITICAL' : 'STABLE';
  ctx.fillText(`TGT: SURVIVOR [${critLabel}]`, x2 + 12, y1 + 14);

  // Distance readout
  ctx.font = '500 10px "JetBrains Mono"';
  ctx.fillStyle = 'rgba(148, 163, 184, 0.8)';
  const dist = Math.round(20 + Math.random() * 60);
  ctx.fillText(`RANGE: ${dist}m`, x2 + 12, y1 + 30);
  ctx.fillText(`${_cvTargetSurvivor.x.toFixed(5)}, ${_cvTargetSurvivor.y.toFixed(5)}`, x2 + 12, y1 + 44);
}

function _cvDrawZoomEffect(ctx, W, H, t) {
  // Zoom vignette effect
  const innerRadius = W * 0.3 * (1 - t * 0.4);
  const outerRadius = W * 0.6;
  const grad = ctx.createRadialGradient(W/2, H/2, innerRadius, W/2, H/2, outerRadius);
  grad.addColorStop(0, 'rgba(0, 0, 0, 0)');
  grad.addColorStop(1, `rgba(0, 0, 0, ${0.3 * t})`);
  ctx.fillStyle = grad;
  ctx.fillRect(0, 0, W, H);

  // "ENHANCING" label
  if (t < 0.8) {
    ctx.font = '800 12px "JetBrains Mono"';
    ctx.fillStyle = `rgba(0, 136, 255, ${0.5 + Math.sin(performance.now() / 300) * 0.5})`;
    ctx.textAlign = 'center';
    ctx.fillText('ZOOM ENHANCE ×' + (1 + t * 3).toFixed(1), W/2, H - 100);
  }
}

function _cvDrawDangerZones(ctx, W, H, t) {
  const p = _cvProjectSurvivor(W, H);
  const cx = p.x, cy = p.y;
  const isCritical = !!(_cvActiveHazard && _cvActiveHazard.contains);

  // Three concentric rings expanding outward
  const maxR = Math.min(W, H) * 0.35;
  const rings = [
    { r: maxR * 0.25 * t, color: isCritical ? 'rgba(255, 42, 109, 0.25)' : 'rgba(0, 255, 136, 0.15)', border: isCritical ? 'rgba(255, 42, 109, 0.7)' : 'rgba(0, 255, 136, 0.5)', label: isCritical ? 'CRITICAL' : 'SAFE', labelColor: isCritical ? '#ff2a6d' : '#00ff9f' },
    { r: maxR * 0.55 * t, color: 'rgba(255, 170, 0, 0.1)', border: 'rgba(255, 170, 0, 0.4)', label: 'WARNING', labelColor: '#ffaa00' },
    { r: maxR * t,        color: 'rgba(0, 255, 136, 0.05)', border: 'rgba(0, 255, 136, 0.2)', label: 'PERIMETER', labelColor: '#00ff88' },
  ];

  // Draw rings outer to inner
  for (let i = rings.length - 1; i >= 0; i--) {
    const ring = rings[i];
    if (ring.r < 2) continue;

    // Fill
    ctx.fillStyle = ring.color;
    ctx.beginPath(); ctx.arc(cx, cy, ring.r, 0, Math.PI * 2); ctx.fill();

    // Border
    ctx.strokeStyle = ring.border;
    ctx.lineWidth = 1.5;
    ctx.setLineDash(i === 0 ? [] : [6, 4]);
    ctx.beginPath(); ctx.arc(cx, cy, ring.r, 0, Math.PI * 2); ctx.stroke();
    ctx.setLineDash([]);

    // Label on right side
    if (t > 0.5) {
      const labelOpacity = Math.min((t - 0.5) * 4, 1);
      ctx.font = '800 9px "JetBrains Mono"';
      ctx.fillStyle = ring.labelColor.replace(')', `, ${labelOpacity})`).replace('rgb', 'rgba');
      if (ring.labelColor.startsWith('#')) {
        const r = parseInt(ring.labelColor.slice(1,3), 16);
        const g = parseInt(ring.labelColor.slice(3,5), 16);
        const b = parseInt(ring.labelColor.slice(5,7), 16);
        ctx.fillStyle = `rgba(${r},${g},${b},${labelOpacity})`;
      }
      ctx.textAlign = 'left';
      ctx.fillText(ring.label, cx + ring.r + 8, cy + 4);
    }
  }

  // Center dot
  ctx.fillStyle = isCritical ? '#ff2a6d' : '#00ff9f';
  ctx.beginPath(); ctx.arc(cx, cy, 4, 0, Math.PI * 2); ctx.fill();
}

// ── Survivor Detection Hook ───────────────────────────────────────────────────
// Called from the main WebSocket update loop to check for new detections

function _cvCheckDetections(survivors, drones) {
  if (_cvFocusSlot < 0) return;
  const droneId = fpvDroneIds[_cvFocusSlot];
  if (!droneId) return;

  // Find this drone
  const drone = drones.find(d => d.id === droneId);
  if (!drone) return;
  _cvFocusDroneData = drone;

  // Check for newly detected, unrescued survivors near this drone
  const scanRadiusDeg = 0.001; // ~100m in degrees at Manila latitude (matches VISION_RADIUS)
  for (const s of survivors) {
    if (!s.detected || s.rescued) continue;
    const key = `${s.x.toFixed(6)},${s.y.toFixed(6)}`;
    if (_cvDetectedHistory.has(key)) continue;

    // Check if this survivor is near our focused drone
    const dx = Math.abs(s.x - drone.x);
    const dy = Math.abs(s.y - drone.y);
    if (dx < scanRadiusDeg && dy < scanRadiusDeg) {
      _cvDetectedHistory.add(key);
      const target = { x: s.x, y: s.y, critical: s.critical };

      if (_cvPhase === 'idle') {
        _cvTargetSurvivor = target;
        _cvAdvancePhase('scanning');
      } else {
        _cvQueue.push(target);
      }
    }
  }
}


// ── Manual Demo Trigger ───────────────────────────────────────────────────────
// For pitch demos: press SPACE in focus mode to simulate a survivor detection.

let _cvDemoCount = 0;

function triggerCvDemo() {
  if (_cvFocusSlot < 0) return;
  if (_cvPhase !== 'idle') return;  // wait for current animation to finish

  // Get drone position
  const st = fpvTargetState[_cvFocusSlot];
  if (!st) return;

  // Alternate between critical and stable for demo variety
  _cvDemoCount++;
  const isCritical = _cvDemoCount % 2 === 1;

  // Place simulated survivor slightly offset from drone position
  const offsetLng = (Math.random() - 0.5) * 0.0004;
  const offsetLat = (Math.random() - 0.5) * 0.0004;

  _cvTargetSurvivor = {
    x: st.lng + offsetLng,
    y: st.lat + offsetLat,
    critical: isCritical,
  };
  _cvAdvancePhase('scanning');
}

// Keyboard: Space = trigger demo scan, Escape = close focus mode
document.addEventListener('keydown', (e) => {
  if (e.code === 'Space' && _cvFocusSlot >= 0) {
    e.preventDefault();
    triggerCvDemo();
  }
  if (e.code === 'Escape' && _cvFocusSlot >= 0) {
    closeFpvFocus();
  }
});


// ── Mission Intelligence: 5-branch git tree ───────────────────────────────────
const MI_DRONES = ['drone_21','drone_22','drone_23','drone_24','drone_25'];
const MI_MAX_PER_BRANCH = 14;
const MI_STORE_MAX = 60;
const MI_DRONE_META = {
  drone_21: { color: '#FF4444', label: 'D-21', slot: 'R1' },
  drone_22: { color: '#5B8DFF', label: 'D-22', slot: 'R2' },
  drone_23: { color: '#44FF88', label: 'D-23', slot: 'R3' },
  drone_24: { color: '#FFD844', label: 'D-24', slot: 'R4' },
  drone_25: { color: '#FF66FF', label: 'D-25', slot: 'R5' },
};
const _miCounts = { drone_21:0, drone_22:0, drone_23:0, drone_24:0, drone_25:0 };
const _miStore  = { drone_21:[], drone_22:[], drone_23:[], drone_24:[], drone_25:[] };
let   _miTotal = 0;
let   _miHashSeed = 0;
let   renderedLogCount = 0;     // kept for compat with rest of pipeline
const _miSeenDroneCmds = new Set();

function _miSanitize(s) {
  return String(s || '').replace(/[<>&"']/g, c => ({
    '<':'&lt;','>':'&gt;','&':'&amp;','"':'&quot;',"'":'&#39;'
  }[c]));
}
function _miShortHash() {
  _miHashSeed = (_miHashSeed + 0x9e3779b1) >>> 0;
  return _miHashSeed.toString(16).padStart(8,'0').slice(0,7);
}
function _miKindLabel(kind) {
  switch (kind) {
    case 'scan':   return 'THERMAL SCAN';
    case 'route':  return 'MOVE TO';
    case 'rescue': return 'RESCUE';
    case 'recall': return 'RECALL';
    case 'reason': return 'THINK';
    case 'crit':   return 'CRIT';
    case 'cmd':    return 'ORDER';
    default:       return String(kind||'').toUpperCase().slice(0,12);
  }
}

const MI_TOOL_META = {
  'move_drone_to':         { kind: 'route',  label: 'MOVE TO' },
  'thermal_scan':          { kind: 'scan',   label: 'THERMAL SCAN' },
  'get_team_waypoint':     { kind: 'route',  label: 'GET WAYPOINT' },
  'recall_drone_to_base':  { kind: 'recall', label: 'RECALL' },
  'get_battery':           { kind: 'cmd',    label: 'BATTERY CHK' },
  'get_all_drones_status': { kind: 'cmd',    label: 'FLEET STATUS' },
  'get_active_drones':     { kind: 'cmd',    label: 'ROSTER' },
  'get_sector_info':       { kind: 'cmd',    label: 'SECTOR INFO' },
  'get_team_sector_status':{ kind: 'cmd',    label: 'SECTOR STATUS' },
  'update_drone_battery':  { kind: 'cmd',    label: 'BATT UPDATE' },
  'charge_drone':          { kind: 'cmd',    label: 'CHARGE' },
  'ascend_drone':          { kind: 'route',  label: 'ASCEND' },
  'descend_drone':         { kind: 'route',  label: 'DESCEND' },
  'hover_drone':           { kind: 'cmd',    label: 'HOVER' },
  'set_formation':         { kind: 'cmd',    label: 'FORMATION' },
  'promote_drone':         { kind: 'cmd',    label: 'PROMOTE' },
};

function _miToolMeta(toolName) {
  if (!toolName) return { kind: 'cmd', label: 'TOOL' };
  const m = MI_TOOL_META[toolName];
  if (m) return m;
  const pretty = String(toolName).replace(/_/g, ' ').toUpperCase().slice(0, 12);
  return { kind: 'cmd', label: pretty };
}
function _miInferAction(text) {
  const t = String(text || '').toLowerCase();
  if (/\b(launch|deploy|take\s*off|takeoff)/.test(t))                      return { kind: 'cmd',    label: 'DEPLOY' };
  if (/\b(recall|return[-\s]*to[-\s]*base|rtb|abort)/.test(t))             return { kind: 'recall', label: 'RECALL' };
  if (/\b(critical|emergency|urgent|mayday|crit)/.test(t))                 return { kind: 'crit',   label: 'CRIT ALERT' };
  if (/\b(rescue|survivor|evac|extract)/.test(t))                          return { kind: 'rescue', label: 'RESCUE' };
  if (/\b(thermal\s*scan|thermal|scan|sweep|search)/.test(t))              return { kind: 'scan',   label: 'THERMAL SCAN' };
  if (/\b(charge|charging|recharg)/.test(t))                               return { kind: 'cmd',    label: 'CHARGE' };
  if (/\b(battery\s*manag|manage\s*battery|reserve|low\s*batt|battery)/.test(t)) return { kind: 'cmd', label: 'BATTERY MGT' };
  if (/\b(rotate|advance|next\s*sector|pivot)/.test(t))                    return { kind: 'cmd',    label: 'ROTATE' };
  if (/\b(form|formation|split|ring|arc|cluster)/.test(t))                 return { kind: 'cmd',    label: 'FORMATION' };
  if (/\b(hold|halt|standby|wait|pause)/.test(t))                          return { kind: 'cmd',    label: 'HOLD' };
  if (/\b(move\s*to|waypoint|fly\s*to|vector|heading|route)/.test(t))      return { kind: 'route',  label: 'MOVE TO' };
  if (/\b(promote|promoted|outer|middle|inner)/.test(t))                   return { kind: 'cmd',    label: 'PROMOTE' };
  if (/\b(launch\s*clearance|clearance)/.test(t))                          return { kind: 'cmd',    label: 'CLEARANCE' };
  if (/\b(decision|decided|directive)/.test(t))                            return { kind: 'cmd',    label: 'DECISION' };
  if (/\b(assess|analy[sz]|situation|observ)/.test(t))                     return { kind: 'reason', label: 'ASSESS' };
  if (/\b(strateg|plan)/.test(t))                                          return { kind: 'reason', label: 'STRATEGY' };
  if (/\b(report|status|update)/.test(t))                                  return { kind: 'cmd',    label: 'REPORT' };
  return { kind: 'cmd', label: 'ORDER' };
}
function _miDroneKey(id) {
  if (!id) return null;
  const s = String(id);
  if (MI_DRONES.includes(s)) return s;
  const m = s.match(/(\d+)\s*$/);
  if (m) {
    const n = parseInt(m[1], 10);
    if (n >= 1 && n <= 5) return `drone_2${n}`;
    if (n >= 21 && n <= 25) return `drone_${n}`;
  }
  return null;
}

function _miUpdateFocus(droneId, label, msg) {
  const fb = document.getElementById('mi-focus-body');
  if (!fb) return;
  const dn = droneId ? droneId.replace('drone_','D-') : 'SYS';
  fb.textContent = `${dn} · ${String(label || '').toUpperCase()} · ${msg}`;
}

// Roll a round's tool-call list up into the composite SKILL the drone was
// executing — keeps the branch readable for the audience ("skill_verified_scan"
// is easier to follow than 5 raw tool calls). The tool breakdown is returned
// so the commit can still expand to show the underlying MCP calls on demand.
function _miSkillFromToolCalls(calls) {
  const names = new Set((calls || []).map(c => c && c.tool).filter(Boolean));
  if (names.has('computer_vision_scan')) {
    return { skill: 'skill_verified_scan', kind: 'scan', label: 'VERIFY', icon: '🎯' };
  }
  if (names.has('recall_drone_to_base')) {
    return { skill: 'skill_battery_check_recall', kind: 'recall', label: 'RECALL', icon: '↩️' };
  }
  if (names.has('thermal_scan')) {
    return { skill: 'skill_verified_scan', kind: 'scan', label: 'SCAN', icon: '🔍' };
  }
  if (names.has('get_team_waypoint')) {
    return { skill: 'skill_sweep_next', kind: 'route', label: 'SWEEP', icon: '🧭' };
  }
  if (names.has('move_drone_to')) {
    return { skill: 'skill_safe_navigate', kind: 'route', label: 'NAV', icon: '✈️' };
  }
  return { skill: 'skill_fleet_overview', kind: 'cmd', label: 'SKILL', icon: '🛠' };
}

// Render a single tool-call line inside an expanded skill commit.
function _miFormatToolLine(c) {
  const name = c && c.tool ? String(c.tool) : '';
  if (!name) return '';
  if (name === 'thermal_scan') {
    const sr = String((c.result || ''));
    const nm = sr.match(/(\d+)\s*survivor/i);
    const found = nm ? parseInt(nm[1], 10) : 0;
    return found > 0
      ? `thermal_scan() → <b class="mi-tool-hit">${found} contact${found === 1 ? '' : 's'}</b>`
      : `thermal_scan() → sweep clear`;
  }
  if (name === 'computer_vision_scan') {
    const pass = c.args && c.args.pass;
    return `computer_vision_scan()${pass ? ` · pass ${pass}` : ''}`;
  }
  if (name === 'move_drone_to') {
    const ax = c.args && c.args.x != null ? Number(c.args.x).toFixed(3) : '?';
    const ay = c.args && c.args.y != null ? Number(c.args.y).toFixed(3) : '?';
    return `move_drone_to(${ax}, ${ay})`;
  }
  if (name === 'get_team_waypoint') {
    let res = {};
    try { res = typeof c.result === 'string' ? JSON.parse(c.result) : (c.result || {}); } catch(e){}
    const x = res.waypoint_x != null ? Number(res.waypoint_x).toFixed(3) : '?';
    const y = res.waypoint_y != null ? Number(res.waypoint_y).toFixed(3) : '?';
    return `get_team_waypoint() → (${x}, ${y})`;
  }
  if (name === 'recall_drone_to_base') return `recall_drone_to_base() → RTB`;
  const argStr = c.args ? JSON.stringify(c.args).slice(0, 48) : '';
  return `${name}${argStr ? '(' + argStr + ')' : '()'}`;
}

function _miPushCommit(droneId, kind, msg, tick, label, toolCalls) {
  const key = _miDroneKey(droneId);
  if (!key) return;
  const track = document.getElementById(`mi-track-${key}`);
  const hash = _miShortHash();
  const kindClass = `kind-${kind}`;
  const tickStr = tick != null ? String(tick) : '';
  const pillLabel = String(label || _miKindLabel(kind) || '').toUpperCase().slice(0, 7);
  const tools = Array.isArray(toolCalls) ? toolCalls.slice() : null;

  const rec = { hash, kind, label: pillLabel, msg: msg || '', tick: tickStr, ts: Date.now(), tools };
  _miStore[key].push(rec);
  if (_miStore[key].length > MI_STORE_MAX) _miStore[key].shift();

  if (track) {
    const empty = track.querySelector('.mi-empty');
    if (empty) empty.remove();
    const el = document.createElement('div');
    el.className = `mi-commit ${kindClass}${tools && tools.length ? ' mi-commit-expandable' : ''}`;
    el.title = `${droneId || 'SYS'} · ${pillLabel} · ${msg || ''}`;
    const chevHash = tools && tools.length
      ? `<span class="mi-commit-chev" aria-hidden="true">▸</span>${hash.slice(0,4)}`
      : hash.slice(0,4);
    el.innerHTML = `
      <span class="mi-commit-hash">${chevHash}</span>
      <span class="mi-commit-kind-pill">${_miSanitize(pillLabel)}</span>
      <span class="mi-commit-tick">${tickStr}</span>
    `;
    el.addEventListener('mouseenter', () => _miUpdateFocus(droneId, pillLabel, msg || ''));
    if (tools && tools.length) {
      const sub = document.createElement('div');
      sub.className = 'mi-commit-sublist';
      sub.innerHTML = tools.map(c =>
        `<div class="mi-commit-subrow">› ${_miFormatToolLine(c)}</div>`
      ).join('');
      el.appendChild(sub);
      el.addEventListener('click', (ev) => {
        if (ev.detail === 0) return;
        el.classList.toggle('expanded');
      });
    }
    track.appendChild(el);
    while (track.children.length > MI_MAX_PER_BRANCH) {
      track.removeChild(track.firstChild);
    }
  }

  _miCounts[key] = (_miCounts[key] || 0) + 1;
  const cntEl = document.getElementById(`mi-count-${key}`);
  if (cntEl) cntEl.textContent = `${_miCounts[key]} commit${_miCounts[key] === 1 ? '' : 's'}`;

  _miTotal++;
  const totalEl = document.getElementById('log-cnt');
  if (totalEl) totalEl.textContent = _miTotal;

  _miUpdateFocus(droneId, pillLabel, msg || '');

  if (typeof _miRenderFullView === 'function') _miRenderFullView();
}

function _miPushBroadcast(kind, msg, tick, label) {
  const inferred = (!label && kind === 'cmd') ? _miInferAction(msg) : null;
  const finalKind  = inferred ? inferred.kind  : kind;
  const finalLabel = inferred ? inferred.label : label;
  MI_DRONES.forEach(d => _miPushCommit(d, finalKind, msg, tick, finalLabel));
}

// ── Full-view modal renderer ─────────────────────────────────────────────────
function _miRenderFullView() {
  const modal = document.getElementById('expand-modal');
  if (!modal || !modal.classList.contains('open')) return;
  const titleEl = document.getElementById('modal-title');
  if (!titleEl || !titleEl.textContent.includes('Actions')) return;
  const content = document.getElementById('modal-content');
  if (content) content.innerHTML = _miBuildFullViewHTML();
}
function _miBuildFullViewHTML() {
  const cols = MI_DRONES.map(d => {
    const meta = MI_DRONE_META[d];
    const entries = (_miStore[d] || []).slice().reverse();
    const rows = entries.length
      ? entries.map(r => `
          <div class="mi-full-commit kind-${r.kind}" style="--mi-col:${meta.color};" title="${_miSanitize(r.msg)}">
            <span class="mi-full-hash">${r.hash}</span>
            <span class="mi-full-pill">${_miSanitize(r.label)}</span>
            <span class="mi-full-tick">${_miSanitize(r.tick)}</span>
            <span class="mi-full-msg">${_miSanitize(r.msg) || '—'}</span>
          </div>`).join('')
      : `<div class="mi-full-empty">no activity</div>`;
    return `
      <div class="mi-full-branch" style="--mi-col:${meta.color};">
        <div class="mi-full-hdr">
          <span class="mi-branch-dot"></span>
          <span class="mi-full-hdr-name">${meta.label}</span>
          <span class="mi-full-hdr-slot">${meta.slot}</span>
          <span class="mi-full-hdr-count">${_miCounts[d] || 0}</span>
        </div>
        <div class="mi-full-track">${rows}</div>
      </div>`;
  }).join('');
  return `<div class="mi-full-grid">${cols}</div>`;
}

// ── Log panel (public API preserved) ──────────────────────────────────────────
function updateLog(log) {
  if (!log) return;
  if (log.length === renderedLogCount) return;
  const newLogs = log.slice(renderedLogCount);
  renderedLogCount = log.length;

  newLogs.forEach(e => {
    const tick = e.tick;
    if (e.type === 'mcp_cmd') {
      const msg = e.msg || 'cmd';
      // Each mcp_cmd carries its own `drone` field — route to that branch only.
      // Fan out only when the event is truly global (no drone attached).
      const droneKey = _miDroneKey(e.drone);
      const meta = _miInferMcpCmd(msg);
      if (droneKey) {
        _miPushCommit(droneKey, meta.kind, msg, tick, meta.label);
      } else {
        _miPushBroadcast(meta.kind, msg, tick, meta.label);
      }
      return;
    }
    if (e.type === 'emergency_override') {
      const droneKey = _miDroneKey(e.drone);
      if (droneKey) _miPushCommit(droneKey, 'crit', e.msg || 'override', tick, 'OVERRIDE');
      return;
    }
    if (e.type === 'malfunction') {
      const droneKey = _miDroneKey(e.drone);
      const msg = e.msg || 'System fault — returning to base';
      if (droneKey) _miPushCommit(droneKey, 'crit', msg, tick, '⚠ FAULT');
      // Also show a prominent log-body card
      const logBody = document.getElementById('log-body');
      if (logBody) {
        const card = document.createElement('div');
        card.style.cssText = 'padding:7px 10px;border-left:3px solid #FF2020;background:rgba(255,32,32,0.08);margin-bottom:4px;font-size:11px;border-radius:0 4px 4px 0;animation:malf-blink 1s ease 3';
        card.innerHTML = `<b style="color:#FF2020">⚠ SYSTEM FAULT</b> <span style="color:#888">${(e.drone||'').replace('drone_','D-')}</span> — <span style="color:#fff">${msg}</span>`;
        logBody.insertBefore(card, logBody.firstChild);
      }
      return;
    }
    if (e.type === 'repair_complete') {
      const droneKey = _miDroneKey(e.drone);
      const msg = e.msg || 'Repair complete — rejoining mission';
      if (droneKey) _miPushCommit(droneKey, 'cmd', msg, tick, '✓ REPAIRED');
      const logBody = document.getElementById('log-body');
      if (logBody) {
        const card = document.createElement('div');
        card.style.cssText = 'padding:7px 10px;border-left:3px solid #00FF88;background:rgba(0,255,136,0.06);margin-bottom:4px;font-size:11px;border-radius:0 4px 4px 0';
        card.innerHTML = `<b style="color:#00FF88">✓ REPAIRED</b> <span style="color:#888">${(e.drone||'').replace('drone_','D-')}</span> — <span style="color:#fff">${msg}</span>`;
        logBody.insertBefore(card, logBody.firstChild);
      }
      return;
    }
    if (e.type === 'quake_detected') {
      // Trigger the frontend seismic animation using the nearest quake zone centre
      // (computed from the same constants as the backend _QUAKE_ZONE_BEARINGS).
      const _QUAKE_BEARINGS = [36, 108, 180];
      const _QUAKE_DIST_KM  = 1.1;
      const bx = window._missionBaseX || 120.980;
      const by = window._missionBaseY || 14.590;
      const _kmPerLat = 111.0;
      const _kmPerLng = 111.0 * Math.cos(by * Math.PI / 180);
      // Pick the zone closest to the reporting drone's last known position
      let bestLng = bx, bestLat = by;
      let bestDist = Infinity;
      _QUAKE_BEARINGS.forEach(deg => {
        const rad = deg * Math.PI / 180;
        const lat = by + (_QUAKE_DIST_KM / _kmPerLat) * Math.cos(rad);
        const lng = bx + (_QUAKE_DIST_KM / _kmPerLng) * Math.sin(rad);
        const droneId = e.drone;
        const dp = dronePos[droneId];
        if (dp) {
          const dist = Math.hypot(lng - dp.cur[0], lat - dp.cur[1]);
          if (dist < bestDist) { bestDist = dist; bestLng = lng; bestLat = lat; }
        } else { bestLng = lng; bestLat = lat; }
      });
      _startQuakeAnim(bestLng, bestLat);
      // Log entry
      const droneKey2 = _miDroneKey(e.drone);
      if (droneKey2) _miPushCommit(droneKey2, 'crit', e.msg || 'Earthquake zone entered', tick, '🌍 QUAKE');
      const logBody2 = document.getElementById('log-body');
      if (logBody2) {
        const card2 = document.createElement('div');
        card2.style.cssText = 'padding:7px 10px;border-left:3px solid #FF8C00;background:rgba(255,140,0,0.08);margin-bottom:4px;font-size:11px;border-radius:0 4px 4px 0';
        card2.innerHTML = `<b style="color:#FF8C00">🌍 EARTHQUAKE ZONE</b> — <span style="color:#fff">ALL DRONES CONVERGING FOR SEISMIC SURVEY</span>`;
        logBody2.insertBefore(card2, logBody2.firstChild);
      }
      return;
    }

    const droneKey = _miDroneKey(e.drone);
    if (!droneKey) return;
    const kind = e.critical ? 'crit' : 'rescue';
    const label = e.critical ? 'CRIT' : 'RESCUE';
    _miPushCommit(droneKey, kind, e.district || '', tick, label);
  });
}

function _miInferMcpCmd(msg) {
  const s = String(msg || '');
  if (/mcp_move_to|move_drone_to|move\s+to\b/i.test(s))        return { kind: 'route',  label: 'MOVE TO' };
  if (/mcp_recall_drone|recall_drone_to_base|\brecall\b|\brtb\b/i.test(s)) return { kind: 'recall', label: 'RECALL' };
  if (/mcp_thermal_scan|thermal_scan|\bthermal\b|\bscan\b/i.test(s)) return { kind: 'scan',   label: 'THERMAL SCAN' };
  if (/mcp_override|override/i.test(s))                         return { kind: 'crit',   label: 'OVERRIDE' };
  if (/charg/i.test(s))                                         return { kind: 'cmd',    label: 'CHARGE' };
  if (/waypoint/i.test(s))                                      return { kind: 'route',  label: 'WAYPOINT' };
  if (/battery/i.test(s))                                       return { kind: 'cmd',    label: 'BATTERY' };
  return _miInferAction(s);
}

// ── AI phase → Mission Log bridge ─────────────────────────────────────────────
function _aiPhaseToLog(droneId, round, phase, data) {
  const d = data || {};
  const droneKey = _miDroneKey(droneId);
  const tickStr  = round != null ? `R${round}` : null;

  if (phase === 'reasoning' && d.status === 'complete' && d.text) {
    const text = String(d.text);
    const firstLine = text.split('\n').map(l => l.trim()).filter(Boolean)[0] || '';
    const isCMD = text.includes('COMMAND AGENT') || text.includes('COMMAND BRIEFING') || text.includes('FORMATION STATUS');
    if (isCMD) {
      _miPushBroadcast('cmd', firstLine, tickStr);
      return;
    }
    if (!droneKey) return;
    const sig = `${droneKey}:R${round}:reason`;
    if (_miSeenDroneCmds.has(sig)) return;
    _miSeenDroneCmds.add(sig);
    const inf = _miInferAction(firstLine);
    _miPushCommit(droneKey, inf.kind === 'cmd' ? 'reason' : inf.kind, firstLine, tickStr, inf.label);
    return;
  }

  if (phase === 'tool_calls' && Array.isArray(d.calls) && d.calls.length) {
    if (!droneKey) return;
    // Roll the tool calls up into the SKILL the drone executed this round.
    // One branch commit per round — the commit expands to show the underlying
    // tool calls so the audience sees skills first, not a wall of MCP noise.
    const sk = _miSkillFromToolCalls(d.calls);
    let kind = sk.kind;
    let label = sk.label;
    let survivorHit = 0;
    for (const c of d.calls) {
      if (c && c.tool === 'thermal_scan') {
        const nm = String(c.result || '').match(/(\d+)\s*survivor/i);
        if (nm) survivorHit = Math.max(survivorHit, parseInt(nm[1], 10));
      }
    }
    if (survivorHit > 0 && sk.kind === 'scan') {
      kind = 'rescue';
      label = `${survivorHit} FOUND`;
    }
    const msg = `${sk.icon || '•'} ${sk.skill}${survivorHit > 0 ? ` — ${survivorHit} survivor${survivorHit===1?'':'s'} verified` : ''}`;
    _miPushCommit(droneKey, kind, msg, tickStr, label, d.calls);
    return;
  }

  if (phase === 'battery_plan') {
    if (!droneKey) return;
    const action = (d.decision || d.action || '').toString().toUpperCase();
    let label = 'BATTERY MGT';
    let kind  = 'cmd';
    if (/RECALL|RTB/.test(action))         { label = 'RECALL';   kind = 'recall'; }
    else if (/CHARG/.test(action))         { label = 'CHARGE';   kind = 'cmd'; }
    else if (/PROMOTE/.test(action))       { label = 'PROMOTE';  kind = 'cmd'; }
    else if (/HOLD|RESERVE/.test(action))  { label = 'HOLD';     kind = 'cmd'; }
    const batt = d.battery != null ? ` · ${Number(d.battery).toFixed(0)}%` : '';
    const reason = d.reason ? ` — ${d.reason}` : '';
    _miPushCommit(droneKey, kind, `battery_plan${batt}${reason}`, tickStr, label);
    return;
  }

  if (phase === 'strategy_alert') {
    const msg = (d.message || d.text || 'strategic alert').toString();
    _miPushBroadcast('cmd', msg, tickStr, 'STRATEGY');
    return;
  }
}

// ── Battery Management panel ──────────────────────────────────────────────────
const _bmLastPlan   = {};    // drone_id → last battery_plan data
const _bmDecisionLog = [];   // recent plans (most recent first), capped
const BM_LOG_MAX = 8;
let _bmReservePct = 15;      // updated from plan safe_reserve_pct when available
let _bmDrainRate  = null;    // %/km from plan
let _bmMaxRangeEst = null;   // km

function _bmBatteryClass(pct) {
  if (pct > 50) return '';
  if (pct > 25) return 'warn';
  return 'crit';
}
function _bmStatusLabel(drone, plan) {
  const raw = (drone.status || '').toUpperCase();
  if (raw.includes('RECALL')) return { text: 'RETURNING', cls: 'crit' };
  if (plan) {
    const rec = (plan.recommendation || '').toUpperCase();
    if (rec === 'RETURN_NOW')       return { text: 'RECALL', cls: 'crit' };
    if (rec === 'RETURN_AFTER_WP')  return { text: 'SCAN THEN RTN', cls: 'warn' };
    if (rec === 'CONTINUE')         return { text: 'SWEEPING', cls: 'ok' };
  }
  const b = Math.round(drone.battery || 0);
  if (b <= 25) return { text: 'LOW BATT', cls: 'crit' };
  if (b <= 50) return { text: 'WATCH', cls: 'warn' };
  return { text: 'NOMINAL', cls: 'ok' };
}

function _bmRenderRoster(drones) {
  const host = document.getElementById('bm-roster');
  if (!host) return;
  if (!drones || !drones.length) {
    host.innerHTML = '<div class="bm-empty">Waiting for drones to report in…</div>';
    return;
  }
  // Sort by ascending battery (weakest first — most important)
  const list = drones.slice().sort((a, b) => (a.battery || 0) - (b.battery || 0));
  let html = '';
  for (const d of list) {
    const pct    = Math.max(0, Math.min(100, Math.round(d.battery || 0)));
    const cls    = _bmBatteryClass(pct);
    const plan   = _bmLastPlan[d.id];
    const proj   = plan && typeof plan.battery_after_return_pct === 'number'
                   ? Math.max(0, Math.min(100, plan.battery_after_return_pct))
                   : null;
    const status = _bmStatusLabel(d, plan);
    const label  = (d.id || '').replace('drone_', 'D-').toUpperCase() || '—';
    const rowCls = plan
      ? ((plan.recommendation || '').toUpperCase() === 'RETURN_NOW' ? 'recalling'
         : (plan.recommendation || '').toUpperCase() === 'RETURN_AFTER_WP' ? 'return-after' : '')
      : '';
    const projTitle = proj != null ? `Projected battery after next return trip: ${proj.toFixed(0)}%` : '';
    html += `
      <div class="bm-row ${rowCls}" title="${plan ? (plan.reason || '').replace(/"/g,'&quot;') : ''}">
        <div class="bm-row-label">${label}<span class="bm-chip ${status.cls}">${status.text}</span></div>
        <div class="bm-bar-wrap">
          <div class="bm-bar ${cls}" style="width:${pct}%"></div>
          ${proj != null ? `<div class="bm-proj" style="left:${proj}%" title="${projTitle}"></div>` : ''}
        </div>
        <div class="bm-row-pct ${cls}">${pct}%</div>
      </div>`;
  }
  host.innerHTML = html;
}

function _bmRenderFleetGauge(drones) {
  const fill  = document.getElementById('bm-fleet-fill');
  const val   = document.getElementById('bm-fleet-val');
  const rsv   = document.getElementById('bm-reserve');
  const rsvV  = document.getElementById('bm-reserve-val');
  const drain = document.getElementById('bm-drain');
  const range = document.getElementById('bm-range');
  const mode  = document.getElementById('bm-mode-badge');
  if (!fill || !val) return;

  const list = drones || [];
  let avg = 0;
  if (list.length) avg = Math.round(list.reduce((a, d) => a + (d.battery || 0), 0) / list.length);
  const cls = avg > 50 ? '' : avg > 25 ? 'warn' : 'crit';
  fill.style.width = (list.length ? avg : 0) + '%';
  fill.className = 'bm-gauge-fill ' + cls;
  val.textContent = list.length ? (avg + '%') : '—';
  val.className   = 'bm-gauge-val ' + cls;

  if (rsv)  rsv.style.left = _bmReservePct + '%';
  if (rsvV) rsvV.textContent = Math.round(_bmReservePct) + '%';
  if (drain) drain.textContent = _bmDrainRate != null ? (_bmDrainRate.toFixed(1) + '%') : '—%';
  if (range) {
    const r = _bmMaxRangeEst;
    range.textContent = r != null ? (r.toFixed(1) + ' km') : '— km';
  }
  if (mode) {
    if (!list.length) { mode.textContent = 'IDLE'; mode.style.color = 'var(--text-dim)'; return; }
    const returning = list.filter(d => (d.status || '').toUpperCase().includes('RECALL')).length;
    if (returning) {
      mode.textContent = returning + ' RECALL';
      mode.style.color = 'var(--crimson)';
    } else if (avg <= 25) {
      mode.textContent = 'CRITICAL';
      mode.style.color = 'var(--crimson)';
    } else if (avg <= 50) {
      mode.textContent = 'WATCH';
      mode.style.color = 'var(--gold)';
    } else {
      mode.textContent = 'NOMINAL';
      mode.style.color = 'var(--emerald)';
    }
  }
}

// ── Per-drone battery sparkline history ─────────────────────────────────────
const _bmSparkHistory = {};   // drone_id → [pct, pct, ...]  (last 20)
const BM_SPARK_MAX = 20;

function _bmUpdateSparkHistory(drones) {
  for (const d of (drones || [])) {
    const id = d.id || '';
    if (!_bmSparkHistory[id]) _bmSparkHistory[id] = [];
    const hist = _bmSparkHistory[id];
    const last = hist[hist.length - 1];
    const cur  = Math.round(d.battery || 0);
    if (last !== cur) {
      hist.push(cur);
      if (hist.length > BM_SPARK_MAX) hist.shift();
    }
  }
}

function _bmSparkPath(hist, w, h) {
  if (!hist || hist.length < 2) return '';
  const n = hist.length;
  const pts = hist.map((v, i) => {
    const x = (i / (n - 1)) * w;
    const y = h - (v / 100) * h;
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  });
  return 'M' + pts.join('L');
}

function _bmRenderSparklines(drones) {
  _bmUpdateSparkHistory(drones);
  const grid = document.getElementById('bm-sparkline-grid');
  if (!grid) return;
  const list = drones || [];
  if (!list.length) { grid.innerHTML = ''; return; }
  const W = 60, H = 28;
  let html = '';
  for (const d of list) {
    const id   = d.id || '';
    const hist = _bmSparkHistory[id] || [];
    const pct  = Math.round(d.battery || 0);
    const cls  = pct > 50 ? '#00ff9f' : pct > 25 ? '#ffc850' : '#ff3c5a';
    const label = id.replace('drone_', 'D-').toUpperCase();
    const path  = _bmSparkPath(hist, W, H);
    html += `<div class="bm-spark-cell">
      <div class="bm-spark-label">${label}</div>
      <div class="bm-spark-val" style="color:${cls}">${pct}%</div>
      <svg class="bm-spark-svg" viewBox="0 0 ${W} ${H}" preserveAspectRatio="none">
        ${path ? `<path d="${path}" fill="none" stroke="${cls}" stroke-width="1.5" opacity="0.85"/>` : ''}
        <line x1="0" y1="${H - (50/100)*H}" x2="${W}" y2="${H - (50/100)*H}" stroke="rgba(255,200,80,0.2)" stroke-width="0.5" stroke-dasharray="2,2"/>
      </svg>
    </div>`;
  }
  grid.innerHTML = html;
}

// ── RTB Event Feed ────────────────────────────────────────────────────────────
const _rtbFeedLog   = [];    // { type, drone, msg, tick }
const RTB_FEED_MAX  = 5;
let   _rtbFeedLastLen = 0;

function _rtbFeedIngest(rescueLog, tick) {
  if (!rescueLog) return;
  const newEntries = rescueLog.slice(_rtbFeedLastLen);
  _rtbFeedLastLen = rescueLog.length;

  for (const e of newEntries) {
    const t = (e.type || '');
    let type = null, icon = '', action = '';
    if (t === 'replacement_dispatch' || t === 'role_swap') {
      type = 'dispatch'; icon = '🛸'; action = 'Replacement dispatched';
    } else if (t === 'cv_hold') {
      type = 'recall'; icon = '🔒'; action = 'CV hold — survivor detected';
    } else if (e.msg && /LOW_BATT|low battery|returning to base|rtb/i.test(e.msg)) {
      type = 'recall'; icon = '⚡'; action = 'Low battery — RTB';
    } else if (e.msg && /charg/i.test(e.msg)) {
      type = 'charging'; icon = '🔋'; action = 'Charging at base';
    }
    if (type) {
      _rtbFeedLog.unshift({ type, icon, action,
        drone: (e.drone || e.msg || '').replace('drone_', 'D-').toUpperCase().slice(0, 12),
        tick: e.tick ?? tick });
      if (_rtbFeedLog.length > RTB_FEED_MAX) _rtbFeedLog.length = RTB_FEED_MAX;
    }
  }
}

function _rtbFeedRender() {
  const feed = document.getElementById('rtb-event-feed');
  if (!feed) return;
  if (!_rtbFeedLog.length) { feed.innerHTML = ''; return; }
  feed.innerHTML = _rtbFeedLog.map(e =>
    `<div class="rtb-event-card ${e.type}">
      <span class="rtb-event-step">${e.icon}</span>
      <div class="rtb-event-body">
        <span class="rtb-event-drone">${e.drone}</span>
        <span class="rtb-event-action"> — ${e.action}</span>
      </div>
      <span class="rtb-event-tick">t${e.tick}</span>
    </div>`
  ).join('');
}

// ── Battery KPI tiles ─────────────────────────────────────────────────────────
let _bmTotalRtb      = 0;
let _bmTotalDispatch = 0;
let _bmRescueLogLen  = 0;

function _bmUpdateKpis(rescueLog, tick) {
  if (!rescueLog) return;
  const newEntries = rescueLog.slice(_bmRescueLogLen);
  _bmRescueLogLen = rescueLog.length;

  for (const e of newEntries) {
    const t = (e.type || '');
    if (t === 'replacement_dispatch' || t === 'role_swap') {
      _bmTotalDispatch += 1;
    }
    if (e.msg && /LOW_BATT|low battery|low_battery|returning to base/i.test(e.msg)) {
      _bmTotalRtb += 1;
    }
  }

  const rtbEl  = document.getElementById('bm-kpi-rtb');
  const dspEl  = document.getElementById('bm-kpi-dispatch');
  const rtbSub = document.getElementById('bm-kpi-rtb-sub');
  const dspSub = document.getElementById('bm-kpi-dispatch-sub');
  if (rtbEl)  rtbEl.textContent  = _bmTotalRtb;
  if (dspEl)  dspEl.textContent  = _bmTotalDispatch;
  if (rtbSub) rtbSub.textContent = _bmTotalRtb ? 'drones recalled this mission' : 'no recalls yet';
  if (dspSub) dspSub.textContent = _bmTotalDispatch ? 'replacement drones sent' : 'none dispatched';
}

// ── Dispatch Timeline ─────────────────────────────────────────────────────────
const _bmDispatchLog = [];
const BM_DISPATCH_MAX = 10;
let   _bmDispatchLastLen = 0;

function _bmUpdateDispatchTimeline(rescueLog) {
  if (!rescueLog) return;
  const newEntries = rescueLog.slice(_bmDispatchLastLen);
  _bmDispatchLastLen = rescueLog.length;

  for (const e of newEntries) {
    const t = (e.type || '');
    if (t === 'replacement_dispatch' || t === 'role_swap') {
      _bmDispatchLog.unshift({ tick: e.tick ?? '?', msg: e.msg || 'Replacement dispatched', icon: '🛸' });
      if (_bmDispatchLog.length > BM_DISPATCH_MAX) _bmDispatchLog.length = BM_DISPATCH_MAX;
    }
  }

  const tl = document.getElementById('bm-dispatch-timeline');
  if (!tl) return;
  if (!_bmDispatchLog.length) {
    tl.innerHTML = '<div class="bm-empty">No drone swaps yet.</div>';
    return;
  }
  tl.innerHTML = _bmDispatchLog.map(e =>
    `<div class="bm-dt-entry">
      <span class="bm-dt-tick">t${e.tick}</span>
      <span class="bm-dt-icon">${e.icon}</span>
      <span class="bm-dt-msg">${e.msg.slice(0, 70)}</span>
    </div>`
  ).join('');
}

function _bmRenderStateBars(drones) {
  const list = drones || [];
  const total = list.length || 1;
  const counts = { sweeping: 0, scanning: 0, rtb: 0, charging: 0 };
  for (const d of list) {
    const st = String(d.status || '').toUpperCase();
    if (st.includes('CHARG')) counts.charging += 1;
    else if (st.includes('LOW_BATT') || st.includes('RECALL')) counts.rtb += 1;
    else if (st.includes('SCAN') || st.includes('RESCUE')) counts.scanning += 1;
    else counts.sweeping += 1;
  }
  const map = [
    ['sweeping', 'bm-state-sweeping', 'bm-state-sweeping-val'],
    ['scanning', 'bm-state-scanning', 'bm-state-scanning-val'],
    ['rtb', 'bm-state-rtb', 'bm-state-rtb-val'],
    ['charging', 'bm-state-charging', 'bm-state-charging-val'],
  ];
  for (const [k, fillId, valId] of map) {
    const fill = document.getElementById(fillId);
    const val = document.getElementById(valId);
    if (fill) fill.style.width = (100 * counts[k] / total).toFixed(1) + '%';
    if (val) val.textContent = String(counts[k]);
  }
}

// ── Fleet Drain Trend: aggregate average battery over last ~60 samples ─────
const _bmTrendHistory = [];
const BM_TREND_MAX = 60;

function _bmRenderTrendChart(drones) {
  const list = drones || [];
  const line = document.getElementById('bm-trend-line');
  const area = document.getElementById('bm-trend-area');
  const valEl = document.getElementById('bm-trend-val');
  const dEl   = document.getElementById('bm-trend-delta');
  if (!line || !area) return;

  if (!list.length) {
    line.setAttribute('d', '');
    area.setAttribute('d', '');
    if (valEl) valEl.firstChild.textContent = '— · Δ ';
    if (dEl) { dEl.textContent = '0%'; dEl.className = ''; }
    return;
  }

  const avg = list.reduce((a, d) => a + (d.battery || 0), 0) / list.length;
  const last = _bmTrendHistory[_bmTrendHistory.length - 1];
  if (last == null || Math.abs(last - avg) > 0.05) {
    _bmTrendHistory.push(avg);
    if (_bmTrendHistory.length > BM_TREND_MAX) _bmTrendHistory.shift();
  }

  const hist = _bmTrendHistory;
  if (hist.length < 2) {
    line.setAttribute('d', '');
    area.setAttribute('d', '');
    if (valEl) valEl.childNodes[0].nodeValue = `${Math.round(avg)}% · Δ `;
    if (dEl) { dEl.textContent = '0%'; dEl.className = ''; }
    return;
  }

  const W = 200, H = 56;
  const n = hist.length;
  const pts = hist.map((v, i) => {
    const x = (i / (n - 1)) * W;
    const y = H - (Math.max(0, Math.min(100, v)) / 100) * H;
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  });
  const linePath = 'M' + pts.join(' L');
  const areaPath = linePath + ` L${W},${H} L0,${H} Z`;
  line.setAttribute('d', linePath);
  area.setAttribute('d', areaPath);
  line.classList.toggle('warn', avg <= 50 && avg > 25);
  line.classList.toggle('crit', avg <= 25);

  const first = hist[0];
  const delta = avg - first;
  if (valEl) {
    valEl.childNodes[0].nodeValue = `${Math.round(avg)}% · Δ `;
  }
  if (dEl) {
    const sign = delta > 0 ? '+' : '';
    dEl.textContent = `${sign}${delta.toFixed(1)}%`;
    dEl.className = delta > 0.1 ? 'delta-pos' : delta < -0.1 ? 'delta-neg' : '';
  }
}

// ── Replacement Cycle Diagram: counts per stage + pulse on new events ──────
const _bmCycleCounts = { deploy: 0, low: 0, rtb: 0, base: 0, dispatch: 0 };
const _bmCycleSeen   = { log: 0 };

function _bmRenderCycle(drones, rescueLog) {
  const list = drones || [];
  // Snapshot counts from live drone status
  let low = 0, rtb = 0, base = 0, deployed = 0;
  for (const d of list) {
    const st = String(d.status || '').toUpperCase();
    deployed += 1;
    const b = Math.round(d.battery || 0);
    if (b <= 25) low += 1;
    if (st.includes('LOW_BATT') || st.includes('RECALL')) rtb += 1;
    if (st.includes('CHARG') || st === 'IDLE' && b < 80) base += 1;
  }
  _bmCycleCounts.deploy = deployed;
  _bmCycleCounts.low    = low;
  _bmCycleCounts.rtb    = rtb;
  _bmCycleCounts.base   = base;
  // Dispatch is cumulative across the mission (from rescue log)
  _bmCycleCounts.dispatch = _bmTotalDispatch;

  // Detect new events for pulse animation
  const log = rescueLog || [];
  const fresh = log.slice(_bmCycleSeen.log);
  _bmCycleSeen.log = log.length;
  let pulse = null;
  for (const e of fresh) {
    const t = (e.type || '');
    if (t === 'replacement_dispatch' || t === 'role_swap') pulse = 'dispatch';
    else if (t === 'cv_hold')                              pulse = 'low';
    else if (e.msg && /LOW_BATT|returning to base/i.test(e.msg)) pulse = 'rtb';
    else if (e.msg && /charg/i.test(e.msg))                pulse = 'base';
  }

  const apply = (id, value, pulseOn, crit) => {
    const node = document.getElementById(`bmc-${id}`);
    const val  = document.getElementById(`bmc-${id}-val`);
    if (val)  val.textContent = String(value);
    if (node) {
      node.classList.toggle('crit', !!crit);
      if (pulseOn) {
        node.classList.add('pulse');
        setTimeout(() => node.classList.remove('pulse'), 900);
      }
    }
  };
  apply('deploy',   _bmCycleCounts.deploy,   pulse === 'deploy',   false);
  apply('low',      _bmCycleCounts.low,      pulse === 'low',      _bmCycleCounts.low > 0);
  apply('rtb',      _bmCycleCounts.rtb,      pulse === 'rtb',      _bmCycleCounts.rtb > 0);
  apply('base',     _bmCycleCounts.base,     pulse === 'base',     false);
  apply('dispatch', _bmCycleCounts.dispatch, pulse === 'dispatch', false);
}

// ── Operations Doctrine: lights the canonical 7-stage cycle the fleet is in ───
// Every scan cycle should visually walk MOVE → THERMAL → CV HOLD → CONFIRM
// → (RESCUE) → ADVANCE. If thermal found nothing, the backend skips CV hold
// entirely, so we synthesize the post-thermal stages here from each drone's
// state transitions — firing a short staggered light-up sequence whenever a
// drone exits SCANNING, regardless of whether survivors were found.
const _opsDocSeen = { log: 0 };
const _opsDocTransient = { confirm: 0, rescue: 0, advance: 0, sweepHold: 0 };
const _opsDocPrev = {};   // droneId → { scanning, hold, target, status }

function _opsDoctrineRender(drones, rescueLog, missionStarted) {
  const list = drones || [];
  const log  = rescueLog || [];
  const now  = Date.now();

  // Baseline flags + per-drone transition detection
  let anyDeployed = false;
  let anyMoving   = false;
  let anyThermal  = false;
  let anyHold     = false;
  for (const d of list) {
    anyDeployed = true;
    const id    = d.drone_id || d.id || d.name || '';
    const st    = String(d.status || '').toUpperCase();
    const scanning  = (st === 'SCANNING' || (d.scan_timer && d.scan_timer > 0));
    const holding   = !!d.cv_hold;
    const hasTarget = !!d.target;

    if (holding)  anyHold    = true;
    if (scanning) anyThermal = true;
    if ((st.includes('MOVING') || (hasTarget && !holding))) anyMoving = true;

    // Transition: scan just finished on this drone → schedule the staggered
    // post-thermal walk even when backend found 0 contacts. Gives the UI its
    // guaranteed full cycle every waypoint.
    const prev = _opsDocPrev[id] || { scanning: false, hold: false };
    if (prev.scanning && !scanning) {
      // sweepHold stage lights immediately & holds 900ms
      _opsDocTransient.sweepHold = now + 900;
      // confirm lights 400ms in, holds 1300ms
      _opsDocTransient.confirm   = Math.max(_opsDocTransient.confirm, now + 1700);
      // advance lights 1100ms in, holds 1400ms — overlap with confirm fade
      _opsDocTransient.advance   = Math.max(_opsDocTransient.advance, now + 2500);
    }
    _opsDocPrev[id] = { scanning, hold: holding, target: hasTarget, status: st };
  }

  // Rescue-log transients (still honored — real cv_hold_release / rescue fire
  // these explicitly on contact waypoints and extend the latches).
  const fresh = log.slice(_opsDocSeen.log);
  _opsDocSeen.log = log.length;
  for (const e of fresh) {
    const t = String(e.type || '');
    const m = String(e.msg || '');
    if (t === 'cv_hold_release' || /confirm/i.test(m))  _opsDocTransient.confirm = Math.max(_opsDocTransient.confirm, now + 2200);
    if (t === 'rescue' || /rescued/i.test(m))           _opsDocTransient.rescue  = Math.max(_opsDocTransient.rescue,  now + 2200);
    if (t === 'advance_zone_waypoint' || /advanc/i.test(m)) _opsDocTransient.advance = Math.max(_opsDocTransient.advance, now + 2200);
    if (t === 'cv_hold')                                _opsDocTransient.sweepHold = Math.max(_opsDocTransient.sweepHold, now + 1200);
  }

  const stages = {
    0: missionStarted && anyDeployed,                                   // ASSIGN
    1: anyMoving && !anyHold && now >= _opsDocTransient.advance,        // MOVE (suppressed during advance latch so the two don't fight)
    2: anyThermal,                                                      // THERMAL
    3: anyHold || now < _opsDocTransient.sweepHold,                     // CV HOLD (real or synthesized sweep)
    4: now < _opsDocTransient.confirm,                                  // CONFIRM
    5: now < _opsDocTransient.rescue,                                   // RESCUE
    6: now < _opsDocTransient.advance,                                  // ADVANCE
  };

  for (let i = 0; i < 7; i++) {
    const el = document.getElementById(`ops-stage-${i}`);
    if (!el) continue;
    el.classList.toggle('active', !!stages[i]);
  }

  const sub = document.getElementById('ops-doctrine-sub');
  if (sub) {
    let label = 'standing by';
    if (!missionStarted)      label = 'standing by';
    else if (stages[5])       label = 'rescue in progress';
    else if (anyHold)         label = 'CV hold · zoom-confirm';
    else if (stages[4])       label = 'confirming sector';
    else if (stages[6])       label = 'advancing to next waypoint';
    else if (stages[3])       label = 'CV sweep verifying';
    else if (stages[2])       label = 'thermal sweep';
    else if (stages[1])       label = 'en route to waypoint';
    else if (stages[0])       label = 'fleet deployed';
    sub.textContent = label.toUpperCase();
  }
}

// Light re-paint between server polls so the staggered CV HOLD → CONFIRM →
// ADVANCE latches don't visually skip when the metrics refresh is slow.
let _opsDocLastSnap = { drones: [], log: [], started: false };
function _opsDoctrineTick() {
  _opsDoctrineRender(_opsDocLastSnap.drones, _opsDocLastSnap.log, _opsDocLastSnap.started);
}
setInterval(_opsDoctrineTick, 220);

function _bmRenderTicker() {
  const host = document.getElementById('bm-ticker');
  if (!host) return;
  if (!_bmDecisionLog.length) {
    host.innerHTML = '<div class="bm-empty">No battery plans evaluated yet.</div>';
    return;
  }
  let html = '';
  for (const e of _bmDecisionLog) {
    const rec = (e.recommendation || 'CONTINUE').toUpperCase();
    const cls = rec === 'CONTINUE' ? 'continue' : rec === 'RETURN_AFTER_WP' ? 'return-after' : 'return-now';
    const pill = rec === 'CONTINUE' ? 'CONTINUE' : rec === 'RETURN_AFTER_WP' ? 'SCAN → RTN' : 'RECALL';
    const now  = Math.round(e.current_battery_pct ?? 0);
    const afWp = e.battery_after_wp_pct;
    const afRt = e.battery_after_return_pct;
    const wpCls = afWp >= 50 ? 'ok' : afWp >= 25 ? 'warn' : 'crit';
    const rtCls = afRt >= 50 ? 'ok' : afRt >= 25 ? 'warn' : 'crit';
    const drone = (e.drone_id || '').replace('drone_', 'D-').toUpperCase();
    html += `
      <div class="bm-tk ${cls}">
        <div class="bm-tk-drone">${drone}</div>
        <div class="bm-tk-body">
          <b class="${_bmBatteryClass(now) || 'ok'}">${now}%</b>
          <span class="arrow">→wp</span>
          <b class="${wpCls}">${afWp ?? '—'}%</b>
          <span class="arrow">→rtn</span>
          <b class="${rtCls}">${afRt ?? '—'}%</b>
        </div>
        <div class="bm-tk-pill">${pill}</div>
      </div>`;
  }
  host.innerHTML = html;
}

function _bmIngestPlan(droneId, data) {
  const p = (data && data.plan) ? data.plan : null;
  if (!p || !droneId) return;
  _bmLastPlan[droneId] = p;

  // Capture fleet-wide calibration from plan fields
  if (typeof p.safe_reserve_pct === 'number') _bmReservePct = p.safe_reserve_pct;
  if (typeof p.drain_rate_pct_per_km === 'number') _bmDrainRate = p.drain_rate_pct_per_km;
  if (typeof p.max_range_km === 'number') _bmMaxRangeEst = p.max_range_km;

  _bmDecisionLog.unshift({
    drone_id: droneId,
    current_battery_pct:      p.current_battery_pct,
    battery_after_wp_pct:     p.battery_after_wp_pct,
    battery_after_return_pct: p.battery_after_return_pct,
    recommendation:           p.recommendation,
    ts: Date.now(),
  });
  if (_bmDecisionLog.length > BM_LOG_MAX) _bmDecisionLog.length = BM_LOG_MAX;
  _bmRenderTicker();
}

// ── Rescue Metrics panel ──────────────────────────────────────────────────────
const _rmPrev = {};                        // element id → last numeric value
const _rmRescueStamps = [];                // wall-clock ms per rescue event (client anchor)
const _rmCriticalFirstSeen = new Map();    // survivor key → ms when first observed critical+unrescued
let _rmPrevRescued = 0;
let _rmPrevDetected = 0;
let _rmDonutCirc = null;
let _rmPctFracShown = 0;                   // smoothed pct (0..1) for the donut fill

const _rmDeltaBuf = {
  rescued:  [],   // [{t, v}]
  detected: [],
  critical: [],
};
const RM_DELTA_WINDOW_MS = 60_000;

function _rmBatteryClass(pct) {
  if (pct > 50) return '';
  if (pct > 25) return 'warn';
  return 'crit';
}

function _rmFmtDuration(sec) {
  if (!isFinite(sec) || sec < 0) return '—';
  sec = Math.round(sec);
  const h = Math.floor(sec / 3600);
  const m = Math.floor((sec % 3600) / 60);
  const s = sec % 60;
  if (h) return `${h}h ${String(m).padStart(2,'0')}m`;
  if (m) return `${m}:${String(s).padStart(2,'0')}`;
  return `${s}s`;
}

function _rmSetVal(id, val, opts) {
  const el = document.getElementById(id);
  if (!el) return;
  const txt = (opts && opts.fmt) ? opts.fmt(val) : String(val);
  if (el.textContent === txt) return;
  el.textContent = txt;
  // Flash on numeric change
  el.classList.remove('odo-flash');
  void el.offsetWidth;
  el.classList.add('odo-flash');
  _rmPrev[id] = val;
}

function _rmPushDelta(key, value, nowMs) {
  const buf = _rmDeltaBuf[key];
  if (!buf) return;
  const last = buf[buf.length - 1];
  if (!last || last.v !== value) buf.push({ t: nowMs, v: value });
  const cutoff = nowMs - RM_DELTA_WINDOW_MS;
  while (buf.length > 1 && buf[0].t < cutoff) buf.shift();
}
function _rmDeltaOver(key, nowMs, windowMs) {
  const buf = _rmDeltaBuf[key];
  if (!buf || !buf.length) return 0;
  const cutoff = nowMs - windowMs;
  let base = buf[0].v;
  for (const p of buf) { if (p.t >= cutoff) break; base = p.v; }
  return (buf[buf.length - 1].v - base);
}

function _rmRenderDelta(id, delta, opts) {
  const el = document.getElementById(id);
  if (!el) return;
  const zero = delta === 0 || delta == null;
  el.className = 'metric-delta' + (zero ? ' zero' : (delta < 0 ? ' neg' : ''));
  if (zero) { el.textContent = (opts && opts.zeroText) || '·'; return; }
  const sign = delta > 0 ? '▲' : '▼';
  el.textContent = `${sign} ${Math.abs(delta)}`;
}

function _rmDonutCircumference() {
  if (_rmDonutCirc != null) return _rmDonutCirc;
  const r = 42;
  _rmDonutCirc = 2 * Math.PI * r;
  return _rmDonutCirc;
}
function _rmUpdateDonut(pctFrac, done) {
  const el = document.getElementById('rm-donut');
  if (!el) return;
  const C = _rmDonutCircumference();
  const p = Math.max(0, Math.min(1, pctFrac));
  el.setAttribute('stroke-dasharray', C.toFixed(2));
  el.setAttribute('stroke-dashoffset', (C * (1 - p)).toFixed(2));
  if (done) el.classList.add('done'); else el.classList.remove('done');
}

function updateRescueMetrics(s) {
  const $ = id => document.getElementById(id);
  if (!$('rm-rescued')) return;

  const nowMs = (s.server_ts ? s.server_ts * 1000 : Date.now());

  const total     = s.total || 0;
  const rescued   = s.rescued || 0;
  const detected  = s.survivors ? s.survivors.filter(sv => sv.detected).length : 0;
  const pct       = total ? (detected / total) : 0;
  const rescuedPct= total ? (rescued / total) : 0;
  const drones    = s.drones ? s.drones.length : 0;

  // Track rescue events (client-side, based on rescued-count jumps)
  if (rescued > _rmPrevRescued) {
    const jumps = rescued - _rmPrevRescued;
    for (let i = 0; i < jumps; i++) _rmRescueStamps.push(nowMs);
  }
  _rmPrevRescued = rescued;

  // Delta buffers
  _rmPushDelta('rescued',  rescued,  nowMs);
  _rmPushDelta('detected', detected, nowMs);

  // ── Hero donut + rescued lede ────────────────────────────────────────────
  _rmUpdateDonut(pct, !!s.mission_complete);
  _rmSetVal('rm-pct', Math.round(pct * 100) + '%');
  const pctBadge = $('rm-pct-badge');
  if (pctBadge) pctBadge.textContent = Math.round(pct * 100) + '%';
  _rmSetVal('rm-rescued', rescued);
  _rmSetVal('rm-total',   total);
  const rbar = $('rm-rescued-bar');
  if (rbar) rbar.style.width = (rescuedPct * 100).toFixed(1) + '%';
  _rmSetVal('rm-detected', detected);

  // Rescue rate per minute (last 60s; falls back to mission-long average)
  let ratePerMin = 0;
  const rescuesLast60s = _rmDeltaOver('rescued', nowMs, 60_000);
  if (rescuesLast60s > 0) {
    ratePerMin = rescuesLast60s;  // already per-minute window
  } else if (s.mission_start_ts) {
    const end = s.mission_end_ts || (s.server_ts || (Date.now() / 1000));
    const elapsedMin = Math.max((end - s.mission_start_ts) / 60, 1/60);
    ratePerMin = rescued / elapsedMin;
  }
  _rmSetVal('rm-rate', ratePerMin.toFixed(ratePerMin >= 10 ? 0 : 1) + '/min');

  // ── Tile: Critical ──────────────────────────────────────────────────────
  const criticalSurv = (s.survivors || []).filter(sv => sv.critical && !sv.rescued);
  const critical = criticalSurv.length;
  _rmSetVal('rm-critical', critical);
  _rmPushDelta('critical', critical, nowMs);
  _rmRenderDelta('rm-critical-delta', _rmDeltaOver('critical', nowMs, 60_000), { zeroText: '·' });

  const critCard = $('rm-card-critical');
  if (critCard) critCard.classList.toggle('critical-alert', critical > 0);

  // Track first-seen timestamp per critical survivor (key by rounded coords)
  const seenKeys = new Set();
  for (const sv of criticalSurv) {
    const key = `${sv.x.toFixed(4)},${sv.y.toFixed(4)}`;
    seenKeys.add(key);
    if (!_rmCriticalFirstSeen.has(key)) _rmCriticalFirstSeen.set(key, nowMs);
  }
  for (const k of Array.from(_rmCriticalFirstSeen.keys())) {
    if (!seenKeys.has(k)) _rmCriticalFirstSeen.delete(k);
  }
  const critSub = $('rm-critical-sub');
  if (critSub) {
    if (!critical) {
      critSub.innerHTML = 'none waiting';
    } else {
      let oldest = nowMs;
      for (const t of _rmCriticalFirstSeen.values()) if (t < oldest) oldest = t;
      const wait = _rmFmtDuration((nowMs - oldest) / 1000);
      critSub.innerHTML = `oldest waiting <b class="warn">${wait}</b>`;
    }
  }

  // ── Tile: Detected big ──────────────────────────────────────────────────
  _rmSetVal('rm-detected-big', detected);
  _rmRenderDelta('rm-detected-delta', _rmDeltaOver('detected', nowMs, 60_000), { zeroText: '·' });
  const detSub = $('rm-detected-sub');
  if (detSub) {
    const pending = Math.max(detected - rescued, 0);
    detSub.innerHTML = pending > 0
      ? `<span class="warn">${pending}</span> awaiting rescue`
      : 'all detected survivors rescued';
  }

  // ── Tile: Elapsed / ETA ─────────────────────────────────────────────────
  let elapsedSec = 0;
  if (s.mission_start_ts) {
    const endTs = s.mission_end_ts || (s.server_ts || (Date.now() / 1000));
    elapsedSec = Math.max(endTs - s.mission_start_ts, 0);
  }
  _rmSetVal('rm-elapsed', _rmFmtDuration(elapsedSec));
  const etaEl = $('rm-eta');
  if (etaEl) {
    let etaText = 'ETA —';
    if (s.mission_complete) {
      etaText = 'mission complete';
    } else if (total && ratePerMin > 0) {
      const remaining = Math.max(total - rescued, 0);
      if (remaining === 0) {
        etaText = 'ETA —';
      } else {
        const minsLeft = remaining / ratePerMin;
        etaText = `ETA ${_rmFmtDuration(minsLeft * 60)}`;
      }
    } else if (s.mission_started) {
      etaText = 'ETA calibrating…';
    }
    etaEl.textContent = etaText;
  }

  // ── Tile: Active Drones ─────────────────────────────────────────────────
  _rmSetVal('rm-drones', drones);
  const dronesSub = $('rm-drones-sub');
  if (dronesSub) {
    if (!drones) dronesSub.textContent = 'fleet idle';
    else {
      const recalling = (s.drones || []).filter(d => (d.status || '').toUpperCase().includes('RECALL')).length;
      dronesSub.textContent = recalling ? `${recalling} recalling` : 'all sweeping';
    }
  }

  // ── Replacement-cycle strip (Active › RTB › Charging › Replaced) ────────
  {
    const list = s.drones || [];
    let active = 0, rtb = 0, charging = 0, weakest = 100, weakId = '';
    for (const d of list) {
      const b = Math.round(d.battery || 0);
      const st = String(d.status || '').toUpperCase();
      if (b < weakest) { weakest = b; weakId = d.id || ''; }
      if (st.includes('CHARG'))                           charging += 1;
      else if (st.includes('LOW_BATT') || st.includes('RECALL')) rtb += 1;
      else active += 1;
    }
    const replaced = (s.rescue_log || []).filter(e => (e.type === 'replacement_dispatch' || e.type === 'role_swap')).length;

    const setNode = (id, value, stepIdx) => {
      const v = document.getElementById(`${id}-val`);
      if (v && v.textContent !== String(value)) {
        v.textContent = String(value);
        const node = document.getElementById(id);
        if (node) {
          node.classList.add('pulse');
          setTimeout(() => node.classList.remove('pulse'), 850);
        }
      }
    };
    setNode('rmc-active',   active);
    setNode('rmc-rtb',      rtb);
    setNode('rmc-charge',   charging);
    setNode('rmc-replaced', replaced);

    const totalIssues = rtb + (weakest <= 25 ? 1 : 0);
    const battEl = $('rm-battery');
    if (battEl) {
      battEl.className = 'metric-delta ' + (rtb ? 'neg' : replaced ? 'pos' : 'zero');
      battEl.textContent = list.length
        ? (rtb ? `${rtb} in RTB` : replaced ? `${replaced} swap` + (replaced === 1 ? '' : 's') : 'nominal')
        : '—';
    }
    const battSub = $('rm-battery-sub');
    if (battSub) {
      if (!list.length) {
        battSub.textContent = 'no drones online';
      } else {
        const label = weakId.replace('drone_', 'D-').toUpperCase();
        battSub.innerHTML =
          `weakest <b class="${weakest > 50 ? 'up' : weakest > 25 ? 'warn' : 'down'}">${label} ${weakest}%</b> · ` +
          `cycle: <b>${active}</b> flying → <b class="down">${rtb}</b> RTB → <b class="warn">${charging}</b> charging → <b class="up">${replaced}</b> replaced`;
      }
    }
  }

  // ── Battery Management: fleet gauge + per-drone roster ─────────────────
  _bmRenderFleetGauge(s.drones || []);
  _bmRenderRoster(s.drones || []);
  _bmRenderStateBars(s.drones || []);
  _bmRenderSparklines(s.drones || []);
  _bmUpdateKpis(s.rescue_log, s.tick);
  _bmRenderTrendChart(s.drones || []);
  _opsDocLastSnap = { drones: s.drones || [], log: s.rescue_log || [], started: !!s.mission_started };
  _opsDoctrineRender(s.drones || [], s.rescue_log, !!s.mission_started);

  // ── Footer status ───────────────────────────────────────────────────────
  _rmSetVal('rm-tick', s.tick ?? '—');
  const dot  = $('rm-status-dot');
  const txt  = $('rm-status-text');
  if (s.mission_complete) {
    txt.textContent = 'MISSION COMPLETE';
    dot.className = 'metrics-status-dot done';
  } else if (s.paused) {
    txt.textContent = 'PAUSED';
    dot.className = 'metrics-status-dot paused';
  } else if (s.mission_started) {
    txt.textContent = 'LIVE SWEEP';
    dot.className = 'metrics-status-dot live';
  } else {
    txt.textContent = 'STANDBY';
    dot.className = 'metrics-status-dot';
  }
}

// ── AI panel ──────────────────────────────────────────────────────────────────
const seenTs = new Set();
const aiFull = {}; 
const _droneMap = {}; 

// ── Drone Selector / Anti-Flash System ────────────────────────────────────────
let _xrayPinnedDrone = 'ALL';       // 'ALL' or a specific drone_id
let _xrayAutoRotateTimer = null;
let _xrayAutoRotateIdx = 0;
const _xrayDroneBuffer = {};        // drone_id → { phases: {phase→data}, lastUpdate: ms, round: N }
const _xrayDroneOrder = [];         // ordered list of drone_ids that have sent data
const _xrayTimeline = {};           // drone_id → [{type:'move'|'scan'|'recall', wp:'#3/12', ts}]
const XRAY_ROTATE_INTERVAL = 3500;  // ms between auto-rotation in ALL mode
let _xrayDebounceTimer = null;
const XRAY_DEBOUNCE_MS = 200;       // prevent DOM thrashing

function selectXrayDrone(droneId) {
  _xrayPinnedDrone = droneId;
  // Update badge UI
  document.querySelectorAll('#drone-selector .drone-badge').forEach(b => {
    b.classList.toggle('active', b.dataset.drone === droneId);
  });
  const hint = document.getElementById('drone-selector-hint');
  if (droneId === 'ALL') {
    if (hint) hint.textContent = 'Auto-rotating \u00b7 Click a drone to pin';
    _startAutoRotate();
  } else {
    if (hint) hint.textContent = `Pinned to ${droneId.replace('drone_','D-').toUpperCase()} \u00b7 Click ALL to unpin`;
    _stopAutoRotate();
    // Immediately render this drone's buffered data
    _renderDroneXray(droneId);
  }
}

function _startAutoRotate() {
  _stopAutoRotate();
  _xrayAutoRotateTimer = setInterval(() => {
    if (_xrayDroneOrder.length === 0) return;
    _xrayAutoRotateIdx = (_xrayAutoRotateIdx + 1) % _xrayDroneOrder.length;
    const droneId = _xrayDroneOrder[_xrayAutoRotateIdx];
    _renderDroneXray(droneId);
  }, XRAY_ROTATE_INTERVAL);
}

function _stopAutoRotate() {
  if (_xrayAutoRotateTimer) { clearInterval(_xrayAutoRotateTimer); _xrayAutoRotateTimer = null; }
}

// Start auto-rotate on load
setTimeout(_startAutoRotate, 2000);

function _renderDroneXray(droneId) {
  const buf = _xrayDroneBuffer[droneId];
  if (!buf) return;

  // Crossfade transition
  const textEl = document.getElementById('csb-reasoning-text');
  if (textEl) {
    textEl.classList.add('fading');
    setTimeout(() => {
      // Update label
      const label = document.getElementById('xray-drone-label');
      if (label) label.textContent = `${droneId.toUpperCase()} \u00bb CYCLE ${buf.round || '?'}`;
      document.getElementById('ai-cnt').textContent =
        droneId === 'CMD' ? 'CMD AGENT' : `ACT: ${droneId.split('_').pop()}`;

      // Replay buffered phases
      if (buf.phases.model)         _renderPhaseData('model', buf.phases.model);
      if (buf.phases.system_prompt) _renderPhaseData('system_prompt', buf.phases.system_prompt);
      if (buf.phases.state)         _renderPhaseData('state', buf.phases.state);
      if (buf.phases.reasoning)     _renderPhaseData('reasoning', buf.phases.reasoning);
      if (buf.phases.tool_calls)    _renderPhaseData('tool_calls', buf.phases.tool_calls);
      if (buf.phases.decision)      _renderPhaseData('decision', buf.phases.decision);
      if (buf.phases.summary)       _renderSummaryPhase(buf.phases.summary);

      // Set pipeline dots to the latest phase
      const phaseOrder = ['model','system_prompt','state','reasoning','tool_calls','decision'];
      let latestPhase = 'model';
      for (const p of phaseOrder) { if (buf.phases[p]) latestPhase = p; }
      _setXrayDots(latestPhase);

      // Render timeline
      _renderTimeline(droneId);

      textEl.classList.remove('fading');
    }, 150);
  }
}

function _renderTimeline(droneId) {
  const tl = document.getElementById('drone-timeline');
  if (!tl) return;
  const events = (_xrayTimeline[droneId] || []).slice(-15);
  if (!events.length) { tl.innerHTML = ''; return; }
  let html = events.map((e, i) => {
    const isLast = (i === events.length - 1);
    return `<div class="tl-dot ${e.type}${isLast ? ' active' : ''}" title="${e.type}: ${e.wp || ''}"></div>`;
  }).join('');
  const last = events[events.length - 1];
  html += `<span id="tl-label">${last.wp || ''}</span>`;
  tl.innerHTML = html;
}

function _enrichReasoningText(text) {
  if (!text) return '';
  // Escape HTML
  let s = text.replace(/</g, '&lt;').replace(/>/g, '&gt;');
  // Highlight rules
  s = s.replace(/(RULE \d+[^:\n]*:?)/g, '<span class="reason-rule">$1</span>');
  s = s.replace(/(TRIGGERED)/g, '<span class="reason-crit">$1</span>');
  // Highlight coordinates
  s = s.replace(/\((\d+\.\d{3,}),\s*(\d+\.\d{3,})\)/g, '(<span class="reason-coord">$1</span>, <span class="reason-coord">$2</span>)');
  // Highlight battery values
  s = s.replace(/(\d+\.?\d*)%/g, (match, num) => {
    const v = parseFloat(num);
    const cls = v > 50 ? 'reason-ok' : v > 25 ? 'reason-warn' : 'reason-crit';
    return `<span class="${cls}">${match}</span>`;
  });
  // Highlight section headers
  s = s.replace(/^(={3,}.*?={3,})$/gm, '<span class="reason-divider"></span>');
  s = s.replace(/^(\u250c|\u2502|\u2514|\u2500|─|│|┌|└)+.*$/gm, '<span style="color:var(--border-light);">$&</span>');
  // Highlight emojis section headers
  s = s.replace(/^(📍|📌|✅|❌|⚠️|🚫|⏸️|⏳|🔋|🧍|🎯|📡|🔍|✈️|📊)/gm, '<span style="font-size:12px;">$1</span>');
  return s;
}

function _renderPhaseData(phase, data) {
  const body = document.getElementById('xpb-' + phase);
  const textEl = document.getElementById('csb-reasoning-text');
  const box    = document.getElementById('xpb-reasoning');

  switch (phase) {
    case 'reasoning':
      if (data.status === 'complete' && textEl) {
        textEl.innerHTML = _enrichReasoningText(data.text || '\u2014');
        if (box) { box.dataset.streaming = '0'; box.scrollTop = box.scrollHeight; }
        _modalSources['reasoning'] = data.text || '';
      }
      break;
    case 'state':
      if (body) body.textContent = data.state_text || 'Injecting spatial context...';
      break;
    case 'system_prompt': {
      const promptEl  = document.getElementById('xpb-system_prompt');
      const promptTxt = data.prompt_text || '';
      if (promptEl) {
        const isFan = data.prompt_label === 'FAN_SPREAD';
        const borderColor = isFan ? 'var(--crimson)' : 'var(--accent)';
        const bg          = isFan ? 'rgba(255,107,53,0.04)' : 'rgba(0,136,255,0.02)';
        promptEl.style.borderLeft = `3px solid ${borderColor}`;
        promptEl.style.background = bg;
        promptEl.innerHTML = `<div class="orders-text">${promptTxt.replace(/</g,'&lt;').replace(/>/g,'&gt;')}</div>`;
      }
      _modalSources['orders'] = promptTxt;
      break;
    }
    case 'tool_calls':
      if (body && data.calls && data.calls.length) {
        const html = data.calls.map(c => _friendlyTool(c.tool, c.args, c.result)).join('');
        body.innerHTML = html;
        _modalSources['tools'] = html;
      }
      break;
    case 'decision':
      if (textEl && data.commands) {
        const cur = textEl.textContent || '';
        if (!cur.includes('─── DECISION ───')) {
          const summary = '\n\n─── DECISION ───\n' + (data.commands || []).join('\n');
          textEl.innerHTML += _enrichReasoningText(summary);
        }
        _modalSources['reasoning'] = (textEl.textContent || '');
        if (box) box.scrollTop = box.scrollHeight;
      }
      break;
  }
}


function getColId(d_id) {
    if (!d_id) return 1;
    if (_droneMap[d_id]) return _droneMap[d_id];

    const match = String(d_id).match(/drone_(\d+)/);
    if (match) {
        const num = parseInt(match[1]);
        _droneMap[d_id] = Math.min(num, 6);
    } else if (d_id.startsWith('R')) {
        const num = parseInt(d_id.substring(1));
        _droneMap[d_id] = Math.min(num, 5);
    } else {
        _droneMap[d_id] = 6;
    }

    const hdr = document.getElementById('aih-' + _droneMap[d_id]);
    if (hdr) hdr.textContent = d_id.toUpperCase();
    return _droneMap[d_id];
}

function _setXrayDots(activePhase) {
  const phases = ['model','system_prompt','state','reasoning','tool_calls','decision'];
  let seen = false;
  for (const p of phases) {
    const dot = document.getElementById('pdot-'+p);
    if (!dot) continue;
    if (p === activePhase) { 
        dot.className = 'step-dot active'; 
        seen = true; 
    } else if (!seen) { 
        dot.className = 'step-dot done'; 
    } else { 
        dot.className = 'step-dot'; 
    }
  }
}

// ── Friendly tool name translator ──────────────────────────────────────────
const _TOOL_ICONS = {
  // ── Composite Skills (high-level operations) ─────────────────────────────
  fleet_overview:         { icon: '🛰️', label: 'Full fleet situational awareness' },
  safe_navigate:          { icon: '✈️', label: 'Battery-safe navigation executed' },
  scan_waypoint:          { icon: '🔍', label: 'Full scan-at-waypoint cycle completed' },
  sweep_next:             { icon: '🗺️', label: 'Next sweep step executed' },
  battery_check_recall:   { icon: '🔋', label: 'Battery guard check performed' },
  mission_intel:          { icon: '📈', label: 'Full mission intelligence gathered' },
  rescue_dispatch:        { icon: '🚨', label: 'Rescue dispatch to nearest survivor' },
  sector_advance:         { icon: '⏭️', label: 'Sector progression check' },
  // ── Navigation / write ops (drone agents) ────────────────────────────────
  thermal_scan:           { icon: '🔍', label: 'Scanned area for survivors' },
  move_drone_to:          { icon: '✈️', label: 'Moved drone to new position' },
  recall_drone_to_base:   { icon: '🔋', label: 'Recalled drone to recharge at base' },
  override_drone_target:  { icon: '🎯', label: 'Redirected drone to priority target' },
  get_team_waypoint:      { icon: '🗺️', label: 'Retrieved next sweep waypoint' },
  advance_team_sector:    { icon: '⏭️', label: 'Advanced team to next sector' },
  advance_arc_waypoint:   { icon: '⏩', label: 'Advanced to next arc waypoint' },
  // ── Intelligence / read-only (Command Agent) ─────────────────────────────
  get_active_drones:      { icon: '🛰️', label: 'Identified active drones on network' },
  get_all_drones_status:  { icon: '🚁', label: 'Pulled full fleet status' },
  get_drone_info:         { icon: '📡', label: 'Pulled drone position & battery' },
  get_battery_status:     { icon: '🔋', label: 'Checked drone battery level' },
  get_mission_status:     { icon: '📈', label: 'Reviewed overall mission progress' },
  get_mapping_status:     { icon: '🗺️', label: 'Checked area coverage map' },
  get_known_survivors:    { icon: '🧍', label: 'Pulled thermal contact list' },
  get_sector_info:        { icon: '🧭', label: 'Retrieved sector coordinates' },
  get_scanned_areas_db:   { icon: '🗄️', label: 'Queried scanned-areas database' },
  get_team_sector_status: { icon: '📊', label: 'Checked active sweep sector progress' },
  get_arc_waypoints:      { icon: '📍', label: 'Retrieved drone waypoint queue' },
};
function _friendlyTool(name, args, resultStr) {
  const t = _TOOL_ICONS[name] || { icon: '⚙️', label: name };
  let detail = '';
  if (name === 'move_drone_to' && args) {
    detail = ` → (${Number(args.x||0).toFixed(3)}, ${Number(args.y||0).toFixed(3)})`;
  } else if (name === 'thermal_scan' || name === 'override_drone_target') {
    const droneNum = (args?.drone_id || '').replace('drone_','');
    if (droneNum) detail = ` · Drone ${droneNum}`;
  }
  let resHint = '';
  if (resultStr) {
    const rStr = String(resultStr).substring(0, 80).replace(/[{}"]/g,'');
    resHint = `<div class="tf-result">↳ ${rStr}${resultStr.length > 80 ? '…' : ''}</div>`;
  }
  return `<div class="tool-friendly">
    <span class="tf-icon">${t.icon}</span>
    <span class="tf-label">${t.label}</span>${detail}
    ${resHint}
  </div>`;
}

// ── Modal expand/close ──────────────────────────────────────────────────────
let _modalSources = {};
function openModal(key) {
  const modal   = document.getElementById('expand-modal');
  const content = document.getElementById('modal-content');
  const title   = document.getElementById('modal-title');
  const src     = _modalSources[key] || '';
  const labels  = {
    reasoning: '🧠 Full Reasoning Stream',
    tools:     '🌳 Mission Intelligence — All Actions',
    orders:    '📋 Mission Orders',
    summary:   '🧠 AI Chain of Thought',
  };
  title.textContent = labels[key] || key;
  if (key === 'tools') {
    content.innerHTML = _miBuildFullViewHTML();
    content.style.fontFamily = "'JetBrains Mono', monospace";
    content.style.color = 'var(--text-primary)';
  } else {
    content.textContent = src;
    content.style.color = key === 'reasoning' ? 'var(--emerald)' : 'var(--text-secondary)';
    content.style.fontFamily = "'JetBrains Mono', monospace";
  }
  modal.classList.add('open');
}
function closeModal() {
  document.getElementById('expand-modal').classList.remove('open');
}

function updateXrayPhase(droneId, round, phase, data) {
  // ── Role colour state machine (always runs, regardless of filter) ──────────
  if (droneId === 'CMD') {
    if (phase === 'decision' && round === 0) {
      cmdBriefed = true;
    } else if (phase === 'reasoning' && round > 0 && round < 100) {
      debriefActive = true;
    } else if (phase === 'decision' && round > 0 && round < 100) {
      debriefActive = false;
    }
  }

  // ── Buffer the event per-drone ─────────────────────────────────────────────
  if (!_xrayDroneBuffer[droneId]) {
    _xrayDroneBuffer[droneId] = { phases: {}, lastUpdate: Date.now(), round: round };
    _xrayDroneOrder.push(droneId);
    // Light up the badge for this drone
    const badge = document.querySelector(`#drone-selector .drone-badge[data-drone="${droneId}"]`);
    if (badge) badge.classList.add('has-data');
  }
  _xrayDroneBuffer[droneId].phases[phase] = data;
  _xrayDroneBuffer[droneId].lastUpdate = Date.now();
  _xrayDroneBuffer[droneId].round = round;

  // ── Build timeline from tool_calls ─────────────────────────────────────────
  if (phase === 'tool_calls' && data.calls && data.calls.length) {
    if (!_xrayTimeline[droneId]) _xrayTimeline[droneId] = [];
    for (const c of data.calls) {
      const type = (c.tool === 'thermal_scan') ? 'scan'
                 : (c.tool === 'recall_drone_to_base') ? 'recall'
                 : 'move';
      const wpInfo = data.calls.find(x => x.tool === 'move_drone_to');
      const wp = wpInfo ? `(${Number(wpInfo.args?.x||0).toFixed(3)}, ${Number(wpInfo.args?.y||0).toFixed(3)})` : '';
      _xrayTimeline[droneId].push({ type, wp, ts: Date.now() });
    }
    // Keep last 20 events
    if (_xrayTimeline[droneId].length > 20) _xrayTimeline[droneId] = _xrayTimeline[droneId].slice(-20);
  }

  // ── Special cases that always render immediately (battery_plan, summary) ──
  if (phase === 'strategy_alert') {
    return;  // formation-switch overlay removed — no popup alert
  }
  if (phase === 'battery_plan') {
    _renderBatteryPlan(data);
    _bmIngestPlan(droneId, data);
    return;
  }
  if (phase === 'reasoning' && data && data.status === 'complete' && (data.markdown_text || data.markdown_path)) {
    _renderSummaryPhase({
      status: 'complete',
      drone_id: droneId,
      round: round,
      model_name: 'ORCHESTRATOR',
      summary_text: data.text || _sumLastSummary || '',
      original_text: data.text || _sumLastOriginal || '',
      duration_ms: data.duration_ms || 0,
      markdown_text: data.markdown_text || '',
      markdown_path: data.markdown_path || '',
    });
  }
  if (phase === 'summary') {
    // Only render if this drone is currently selected (or in ALL mode & not rotating)
    const summaryVisible =
      (_xrayPinnedDrone === droneId) ||
      (_xrayPinnedDrone === 'ALL' && !_xrayAutoRotateTimer) ||
      (_xrayPinnedDrone === 'ALL' && _xrayDroneOrder[_xrayAutoRotateIdx] === droneId);
    if (summaryVisible) _renderSummaryPhase(data);
    // Buffered above — will be replayed by _renderDroneXray on drone switch
    return;
  }

  // ── Filter: only render to DOM if this drone is currently selected ─────────
  const shouldRender =
    (_xrayPinnedDrone === droneId) ||
    (_xrayPinnedDrone === 'ALL' && !_xrayAutoRotateTimer);  // ALL with no timer = render immediately

  if (!shouldRender && _xrayPinnedDrone !== 'ALL') return;

  // In ALL mode with auto-rotate active, just buffer — the timer will render
  if (_xrayPinnedDrone === 'ALL' && _xrayAutoRotateTimer) return;

  // ── Debounced render ───────────────────────────────────────────────────────
  if (_xrayDebounceTimer) clearTimeout(_xrayDebounceTimer);
  _xrayDebounceTimer = setTimeout(() => {
    _xrayDebounceTimer = null;

    // Update header label
    const label = document.getElementById('xray-drone-label');
    if (label) label.textContent = `${droneId.toUpperCase()} \u00bb CYCLE ${round}`;
    document.getElementById('ai-cnt').textContent =
      droneId === 'ORCH' ? 'CMD AGENT' : `ACT: ${droneId.split('_').pop()}`;

    // Update section titles
    const thinkingTitle = document.querySelector('#xpb-reasoning')?.previousElementSibling?.querySelector('.csb-sec-title');
    const actionsTitle  = document.querySelector('#xpb-tool_calls')?.previousElementSibling?.querySelector('.csb-sec-title');
    if (thinkingTitle) thinkingTitle.textContent = droneId === 'ORCH'
      ? '\ud83e\udde0 Intelligence Analysis'
      : '\ud83e\udde0 What the AI Commander is thinking';
    // Section title is now static "Mission Intelligence" — no per-drone override

    _setXrayDots(phase);
    _renderPhaseData(phase, data);
    _renderTimeline(droneId);
  }, XRAY_DEBOUNCE_MS);
}

// ── Strategy alert (always rendered immediately, not filtered) ────────────────
function _renderStrategyAlert(data) {
  const overlay = document.getElementById('strategy-alert-overlay');
  if (!overlay) return;

  const sectorEl    = document.getElementById('sa-sector');
  const reasonEl    = document.getElementById('sa-reason');
  const efficiencyEl= document.getElementById('sa-efficiency');
  const syslogEl    = document.getElementById('sa-syslog');
  if (sectorEl)     sectorEl.textContent     = `SECTOR ${data.sector_num} \u2014 ${(data.sector_name||'').toUpperCase()}`;
  if (reasonEl)     reasonEl.textContent     = data.reason || 'Tactical reanalysis in progress...';
  if (efficiencyEl) efficiencyEl.textContent = `\u25b2 +${data.efficiency_gain || '34%'} MID-SECTOR DETECTION EFFICIENCY`;
  if (syslogEl)     syslogEl.textContent     = '[SYS] Pausing all drone operations...';

  overlay.style.display = 'flex';

  setTimeout(() => {
    if (syslogEl) syslogEl.textContent =
      `[SYS] Analysing ${data.survivors_detected || 0} thermal contacts \u2014 mapping density distribution...`;
  }, 1500);
  setTimeout(() => {
    if (syslogEl) syslogEl.textContent =
      '[SYS] Recalculating optimal formation geometry for mid-sector survivor density...';
  }, 3000);
  setTimeout(() => {
    if (syslogEl) syslogEl.innerHTML =
      '[SYS] <span style="color:#00ff88;font-weight:700;">System prompts updated \u2014 FAN SPREAD formation loaded</span>';
    const badge     = document.getElementById('formation-badge');
    const badgeTxt  = document.getElementById('formation-badge-text');
    const badgeLbl  = document.getElementById('formation-badge-label');
    if (badge)    badge.classList.add('fan-spread');
    if (badgeTxt) { badgeTxt.textContent = 'FAN SPREAD'; badgeTxt.style.color = '#ff6b35'; }
    if (badgeLbl) badgeLbl.style.color = '#888';
    const dot = document.getElementById('pdot-system_prompt');
    if (dot) { dot.classList.add('active'); setTimeout(() => dot.classList.add('done'), 800); }
  }, 5000);
  setTimeout(() => {
    if (syslogEl) syslogEl.innerHTML =
      '[SYS] <span style="color:#00ff88;">\u25b6 All drones cleared \u2014 Fan Spread sweep resuming</span>';
  }, 7000);
  setTimeout(() => { overlay.style.display = 'none'; }, 8500);

  const logBody = document.getElementById('log-body');
  if (logBody) {
    const entry = document.createElement('div');
    entry.style.cssText = 'padding:6px 10px; border-left:3px solid #ff6b35; background:rgba(255,107,53,0.06); margin-bottom:4px; font-size:11px; border-radius:0 4px 4px 0;';
    entry.innerHTML = `<b style="color:#ff6b35;">\u26a1 STRATEGY SWITCH</b> <span style="color:#888;">Sector ${data.sector_num}</span> \u2014 <span style="color:#fff;">3-2 Arc Ring \u2192 Fan Spread</span>`;
    logBody.insertBefore(entry, logBody.firstChild);
  }
}

// ── Battery plan (always rendered immediately, not filtered) ──────────────────
function _renderBatteryPlan(data) {
  const bpBody = document.getElementById('xpb-tool_calls');
  const p      = data.plan || {};
  const rec    = (p.recommendation || 'CONTINUE').toUpperCase();
  const recClass = rec === 'CONTINUE' ? 'continue' : (rec === 'RETURN_AFTER_WP' ? 'return-after' : 'return-now');
  const recLabel = rec === 'CONTINUE' ? '\u2713 CONTINUE SWEEP' : (rec === 'RETURN_AFTER_WP' ? '\u26a0 SCAN THEN RETURN' : '\u2715 RETURN NOW');
  const bpct = p.current_battery_pct ?? '\u2014';
  const bClass = bpct >= 50 ? 'ok' : (bpct >= 30 ? 'warn' : 'danger');

  const html = `
    <div class="batt-plan-card">
      <div style="font-size:9px;color:#ff6b35;letter-spacing:0.1em;margin-bottom:6px;font-weight:700;">
        \ud83d\udd0b BATTERY MANAGEMENT \u2014 ${(data.context||'pre-move').toUpperCase()}
      </div>
      <div class="batt-plan-row">
        <span class="batt-plan-label">Current battery</span>
        <span class="batt-plan-val ${bClass}">${bpct}%</span>
      </div>
      <div class="batt-plan-row">
        <span class="batt-plan-label">Dist \u2192 WP</span>
        <span class="batt-plan-val">${p.dist_to_wp_km ?? '\u2014'} km</span>
      </div>
      <div class="batt-plan-row">
        <span class="batt-plan-label">WP \u2192 Base</span>
        <span class="batt-plan-val">${p.dist_wp_to_base_km ?? '\u2014'} km</span>
      </div>
      <div class="batt-plan-row">
        <span class="batt-plan-label">Cost to WP</span>
        <span class="batt-plan-val">\u2212${p.cost_to_wp_pct ?? '\u2014'}%</span>
      </div>
      <div class="batt-plan-row">
        <span class="batt-plan-label">After WP</span>
        <span class="batt-plan-val ${(p.battery_after_wp_pct>=15)?'ok':'danger'}">${p.battery_after_wp_pct ?? '\u2014'}%</span>
      </div>
      <div class="batt-plan-row">
        <span class="batt-plan-label">After return</span>
        <span class="batt-plan-val ${(p.battery_after_return_pct>=15)?'ok':'danger'}">${p.battery_after_return_pct ?? '\u2014'}%</span>
      </div>
      <div class="batt-plan-row">
        <span class="batt-plan-label">Max range</span>
        <span class="batt-plan-val">${p.max_range_km ?? '\u2014'} km</span>
      </div>
      <div class="batt-rec ${recClass}">${recLabel}</div>
    </div>`;
  if (bpBody) { bpBody.innerHTML = html; _modalSources['tools'] = html; }

  const tcDot = document.getElementById('pdot-tool_calls');
  if (tcDot) { tcDot.classList.add('active'); setTimeout(()=>tcDot.classList.remove('active'),600); }
}

// ── AI Chain of Thought Panel ─────────────────────────────────────────────────
let _sumLastOriginal = '';
let _sumLastSummary = '';
let _cotRawOpen = false;
let _cotMdText = '';
let _cotMdPath = '';

function _renderCotMarkdownVisualizer(markdownText, markdownPath) {
  const host = document.getElementById('cot-md-render');
  const meta = document.getElementById('cot-md-meta');
  if (!host || !meta) return;
  if (!markdownText) {
    host.innerHTML = '';
    meta.textContent = 'Markdown flowchart: waiting for AI artifact…';
    return;
  }
  _cotMdText = markdownText;
  _cotMdPath = markdownPath || '';
  meta.textContent = _cotMdPath
    ? `Markdown flowchart: ${_cotMdPath}`
    : 'Markdown flowchart: in-memory';

  const mm = markdownText.match(/```mermaid\s*([\s\S]*?)```/i);
  if (!mm || !mm[1]) {
    host.innerHTML = `<pre style="white-space:pre-wrap;color:var(--text-secondary);font-size:10px;">${_escHtml(markdownText.slice(0, 1800))}</pre>`;
    return;
  }
  host.innerHTML = `<div class="mermaid">${_escHtml(mm[1])}</div>`;
  try {
    if (window.mermaid && !window.__cotMermaidInit) {
      window.mermaid.initialize({ startOnLoad: false, theme: 'dark' });
      window.__cotMermaidInit = true;
    }
    if (window.mermaid) {
      window.mermaid.run({ nodes: host.querySelectorAll('.mermaid') });
    }
  } catch (e) {
    host.innerHTML = `<pre style="white-space:pre-wrap;color:var(--gold);font-size:10px;">Mermaid render failed.\n\n${_escHtml(mm[1])}</pre>`;
  }
}

function _escHtml(s) {
  return (s || '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

function _cotBatteryClass(pct) {
  const v = parseFloat(pct);
  if (isNaN(v)) return '';
  return v > 50 ? 'ok' : v > 25 ? 'warn' : 'crit';
}

// Parse the structured summary emitted by the summarizer prompt.
// Tolerant: missing sections fall through gracefully.
function _parseChainOfThought(text) {
  const out = { situation: '', obs: {}, thoughts: [], decision: '', next: '', fallback: '' };
  if (!text) return out;
  const lines = text.split(/\r?\n/);
  let section = null;
  for (let raw of lines) {
    const line = raw.replace(/\s+$/, '');
    if (!line.trim()) continue;
    const m = line.match(/^([A-Z][A-Z_ ]{2,20}):\s*(.*)$/);
    if (m) {
      const key = m[1].trim().toUpperCase();
      const val = m[2].trim();
      if (key === 'SITUATION')       { section = 'situation'; out.situation = val; continue; }
      if (key === 'OBSERVATION')     { section = 'obs'; continue; }
      if (key === 'THOUGHTS')        { section = 'thoughts'; continue; }
      if (key === 'DECISION')        { section = null; out.decision = val; continue; }
      if (key === 'NEXT')            { section = null; out.next = val; continue; }
    }
    if (section === 'situation') {
      out.situation += (out.situation ? ' ' : '') + line.trim();
    } else if (section === 'obs') {
      const om = line.match(/^\s*-\s*([a-zA-Z_][\w ]*?):\s*(.+)$/);
      if (om) out.obs[om[1].trim().toLowerCase()] = om[2].trim();
    } else if (section === 'thoughts') {
      const tm = line.match(/^\s*(\d+)\.\s*(.+)$/);
      if (tm) out.thoughts.push(tm[2].trim());
      else if (out.thoughts.length) out.thoughts[out.thoughts.length - 1] += ' ' + line.trim();
    } else {
      out.fallback += (out.fallback ? '\n' : '') + line;
    }
  }
  return out;
}

function _cotObsRow(key, val, cls) {
  const c = cls ? ' ' + cls : '';
  return `<div class="cot-obs-row"><span class="cot-obs-key">${_escHtml(key)}</span><span class="cot-obs-val${c}">${_escHtml(val)}</span></div>`;
}

function _renderChainOfThought(parsed) {
  const stream = document.getElementById('cot-stream');
  if (!stream) return;
  let html = '';

  if (parsed.situation) {
    html += `<div class="cot-situation">${_escHtml(parsed.situation)}</div>`;
  }

  const obs = parsed.obs || {};
  const hasObs = Object.keys(obs).length > 0;
  if (hasObs) {
    html += '<div class="cot-section-label">Observation</div>';
    html += '<div class="cot-obs-grid">';
    if (obs.battery != null) {
      const m = String(obs.battery).match(/(\d+\.?\d*)/);
      const pct = m ? m[1] : obs.battery;
      html += _cotObsRow('battery', pct + '%', _cotBatteryClass(pct));
    }
    if (obs.survivors != null) {
      const s = parseInt(obs.survivors, 10);
      html += _cotObsRow('survivors', String(obs.survivors), s > 0 ? 'ok' : '');
    }
    if (obs.location) html += _cotObsRow('location', obs.location);
    if (obs.notes)    html += _cotObsRow('notes', obs.notes);
    // Any extra observation keys we didn't predict
    Object.keys(obs).forEach(k => {
      if (!['battery','survivors','location','notes'].includes(k)) {
        html += _cotObsRow(k, obs[k]);
      }
    });
    html += '</div>';
  }

  if (parsed.thoughts && parsed.thoughts.length) {
    html += '<div class="cot-section-label">Thought process</div>';
    html += '<div class="cot-thoughts">';
    parsed.thoughts.forEach((t, i) => {
      const delay = (i * 220) + 'ms';
      html += `<div class="cot-thought" style="animation-delay:${delay}">`
           +    `<div class="cot-thought-num">${i + 1}</div>`
           +    `<div class="cot-thought-body">${_escHtml(t)}</div>`
           +  `</div>`;
    });
    html += '</div>';
  }

  if (parsed.decision) {
    html += `<div class="cot-decision">${_escHtml(parsed.decision)}</div>`;
  }
  if (parsed.next) {
    html += `<div class="cot-next">${_escHtml(parsed.next)}</div>`;
  }

  // If the model went fully off-format, show the raw text as a readable block
  if (!parsed.situation && !parsed.thoughts.length && !parsed.decision && parsed.fallback) {
    html = `<div class="cot-situation" style="font-family:'Inter',sans-serif;white-space:pre-wrap;">${_escHtml(parsed.fallback)}</div>`;
  }

  if (!html) {
    html = '<div class="cot-placeholder">AI returned an empty response. Retrying on next cycle.</div>';
  }

  stream.innerHTML = html;
}

function toggleCotRaw() {
  const raw    = document.getElementById('cot-raw');
  const toggle = document.getElementById('cot-raw-toggle');
  if (!raw || !toggle) return;
  _cotRawOpen = !_cotRawOpen;
  if (_cotRawOpen) {
    raw.innerHTML = _enrichReasoningText(_sumLastOriginal || '(no reasoning captured)');
    raw.style.display = 'block';
    toggle.textContent = '▾ Hide raw reasoning trace';
  } else {
    raw.style.display = 'none';
    toggle.textContent = '▸ Show raw reasoning trace';
  }
}

function _renderSummaryPhase(data) {
  const stream = document.getElementById('cot-stream');
  const badge  = document.getElementById('cot-model-badge');
  const drone  = document.getElementById('cot-drone');
  const round  = document.getElementById('cot-round');
  const tmeta  = document.getElementById('cot-time');
  const toggle = document.getElementById('cot-raw-toggle');

  if (drone) drone.textContent = (data.drone_id || '—').toUpperCase();
  if (round) round.textContent = 'R' + (data.round ?? '—');

  if (data.status === 'summarizing') {
    if (data.original_text) _sumLastOriginal = data.original_text;
    if (badge) badge.innerHTML = '<span class="cot-spinner"></span> ' + (data.model_name || 'AI').toUpperCase() + ' IS THINKING';
    if (tmeta) tmeta.textContent = 'live';
    if (stream) {
      stream.innerHTML = '<div class="cot-thinking"><span class="cot-spinner"></span><span>Watching ' +
        _escHtml(data.model_name || 'the summarizer') + ' think<span class="cot-dots"></span></span></div>';
    }
    if (toggle) toggle.style.display = _sumLastOriginal ? 'block' : 'none';
    _modalSources['summary'] = _sumLastOriginal || '';
    _renderCotMarkdownVisualizer(data.markdown_text || _cotMdText, data.markdown_path || _cotMdPath);
    return;
  }

  if (data.status === 'complete') {
    if (data.original_text) _sumLastOriginal = data.original_text;
    _sumLastSummary = data.summary_text || '';
    const parsed = _parseChainOfThought(_sumLastSummary);
    _renderChainOfThought(parsed);
    if (badge) badge.innerHTML = '✨ ' + (data.model_name || 'AI').toUpperCase();
    if (tmeta) tmeta.textContent = (data.duration_ms ? (data.duration_ms + 'ms') : '—');
    if (toggle) {
      toggle.style.display = 'block';
      if (_cotRawOpen) {
        const raw = document.getElementById('cot-raw');
        if (raw) raw.innerHTML = _enrichReasoningText(_sumLastOriginal);
      }
    }
    _modalSources['summary'] = _sumLastSummary || '';
    _renderCotMarkdownVisualizer(data.markdown_text || _cotMdText, data.markdown_path || _cotMdPath);
    return;
  }

  if (data.status === 'error') {
    if (badge) badge.innerHTML = '⚠ ' + (data.model_name || 'AI').toUpperCase() + ' ERROR';
    if (stream) stream.innerHTML = '<div class="cot-error">' + _escHtml(data.error || 'Summarization failed') + '</div>';
    if (toggle) toggle.style.display = _sumLastOriginal ? 'block' : 'none';
    _modalSources['summary'] = _sumLastOriginal || '';
    _renderCotMarkdownVisualizer(data.markdown_text || _cotMdText, data.markdown_path || _cotMdPath);
  }
}

function _addXrayHistory(droneId, round, text) {
  const hist = document.getElementById('xray-history');
  if (!hist) return;
  if (hist.querySelector('[data-placeholder]')) hist.innerHTML = '';
  const entry = document.createElement('div');
  entry.style.cssText = 'padding:4px 0; border-bottom:1px solid var(--border-light); font-size:10px;';
  entry.innerHTML = `<b style="color:var(--accent)">R${round}</b> ${droneId.toUpperCase()} — ${text.split('\n')[0].substring(0,60)}...`;
  hist.insertBefore(entry, hist.firstChild);
  while (hist.children.length > 30) hist.lastChild.remove();
}

function updateAI(events) {
  if (!events?.length) return;
  for (const ev of events) {
    if (seenTs.has(ev.ts)) continue;
    seenTs.add(ev.ts);
    updateXrayPhase(ev.drone_id, ev.round, 'decision', {text: ev.llm_response || ev.prompt || 'Legacy sync...'});
    _addXrayHistory(ev.drone_id, ev.round, ev.llm_response || ev.prompt || '—');
  }
}

function toggleAICard(k) {
  const el = document.getElementById(`aib-${k}`);
  if (el) el.style.display = el.style.display==='none' ? '' : 'none';
}
function showAITab(k, tab) {
  for (const t of ['cmd','out','in']) {
    document.getElementById(`tab-${t}-${k}`)?.classList.toggle('on', t===tab);
    document.getElementById(`ap-${t}-${k}`)?.classList.toggle('on', t===tab);
  }
  if (tab==='out'||tab==='in') {
    const pane = document.getElementById(`ap-${tab}-${k}`);
    if (pane && !pane.dataset.loaded) {
      pane.textContent = tab==='out' ? aiFull[k]?.llm_response||'—' : aiFull[k]?.prompt||'—';
      pane.dataset.loaded='1';
    }
  }
}

// ── Header stats ──────────────────────────────────────────────────────────────
function updateHeader(s) {
  document.getElementById('st-tick').textContent = s.tick;
  const detectedCount = s.survivors ? s.survivors.filter(sv => sv.detected).length : 0;
  document.getElementById('st-resc').textContent = `${detectedCount}/${s.total}`;
  document.getElementById('st-dist').textContent = Math.round(s.distance);
  // RTB / Charging count for header stat
  const rtbCount = (s.drones || []).filter(d => {
    const st = (d.status || '').toUpperCase();
    return st.includes('LOW_BATT') || st.includes('CHARG') || st.includes('RECALL');
  }).length;
  const stBattEl = document.getElementById('st-batt');
  if (stBattEl) stBattEl.textContent = rtbCount ? `${rtbCount} RTB` : '0 RTB';
  const pct = s.total ? Math.round(100*detectedCount/s.total) : 0;
  document.getElementById('st-pct').textContent   = pct;
  document.getElementById('prog-bar').style.width = pct+'%';
  // Live map overlay
  document.getElementById('ls-drones').textContent = s.drones.length;
  document.getElementById('ls-resc').textContent   = `${detectedCount}/${s.total}`;
  document.getElementById('ls-tick').textContent   = s.tick;
  // Header badge
  const badge = document.getElementById('hdr-badge');
  if (s.mission_complete) {
    badge.textContent = `✓ ${detectedCount}/${s.total} DETECTED`;
    badge.className   = 'done';
  } else if (s.paused) {
    badge.textContent = '⏸ PAUSED';
    badge.className   = 'paused';
  } else {
    badge.textContent = '● ACTIVE';
    badge.className   = 'active';
  }
}

function ctrlExport() { window.open('/api/export','_blank'); }

// ── WebSocket ─────────────────────────────────────────────────────────────────
function connect() {
  const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
  const ws = new WebSocket(protocol + '//' + location.host + '/ws');
  ws.onopen = () => { document.getElementById('loading').style.display='none'; };
  ws.onmessage = e => {
    const s = JSON.parse(e.data);
    
    if (s.type === 'ai_stream') {
        // Filter by selected drone
        if (_xrayPinnedDrone !== 'ALL' && s.drone_id !== _xrayPinnedDrone) return;
        const textEl = document.getElementById('csb-reasoning-text');
        const box    = document.getElementById('xpb-reasoning');
        if (textEl) {
            if (box && box.dataset.streaming !== '1') {
                textEl.textContent = '';
                textEl.style.color = '';
                textEl.style.fontFamily = '';
                if (box) box.dataset.streaming = '1';
            }
            textEl.textContent += s.chunk;
            if (box) box.scrollTop = box.scrollHeight;
        }
        return;
    }

    if (s.type === 'ai_phase') {
        updateXrayPhase(s.drone_id, s.round, s.phase, s.data);
        _aiPhaseToLog(s.drone_id, s.round, s.phase, s.data);
        return;
    }

    if (!s.ready) return;
    try {
      drawScannedAreas(s.mapped_cells);
      drawRescuedAreas(s.rescued_locations);
      updateDrones(s.drones);
      updateSurvivors(s.survivors);
      updateFleet(s.drones);
      _cvCheckDetections(s.survivors, s.drones);  // CV overlay: detect new survivors near focused drone
      updateRescueMetrics(s);
      updateLog(s.rescue_log);
      updateAI(s.ai_events);
      updateHeader(s);
      if (s.team_sector) updateActiveSector(s.team_sector);
    } catch(err) { console.error('[WS] render error:', err); }
  };
  ws.onclose = () => {
    document.getElementById('loading').style.display='flex';
    document.querySelector('#loading .pulse').textContent='Reconnecting…';
    setTimeout(connect, 2000);
  };
  ws.onerror = () => ws.close();
}

connect();

// Initialize button states
updateModeButtons();
</script>

<!-- ── Strategy Alert Overlay ─────────────────────────────────────────────── -->
<div id="strategy-alert-overlay">
  <div id="strategy-alert-box">
    <div id="sa-warning-header">⚠ TACTICAL ALERT</div>
    <div id="sa-title">Strategy Recalculation</div>
    <div id="sa-sector">SECTOR — ANALYSING THERMAL DATA</div>
    <div id="sa-reason">Initiating formation analysis...</div>
    <div class="sa-formation-cards">
      <div class="sa-card old">
        <div class="sa-card-label">Current Formation</div>
        <div class="sa-card-name" id="sa-old">3-2 ARC RING</div>
        <div class="sa-card-detail">R1/R2/R3 OUTER · R4/R5 INNER</div>
      </div>
      <div class="sa-arrow">→</div>
      <div class="sa-card new">
        <div class="sa-card-label">New Formation</div>
        <div class="sa-card-name" id="sa-new">FAN SPREAD</div>
        <div class="sa-card-detail">5 × 72° full-depth corridors</div>
      </div>
    </div>
    <div id="sa-efficiency">▲ +34% MID-SECTOR DETECTION EFFICIENCY</div>
    <div id="sa-hold-text">⏸ ALL DRONES HOLDING POSITION — RECALCULATING SWEEP VECTORS</div>
    <div id="sa-syslog">[SYS] Pausing all drone operations...</div>
  </div>
</div>

<!-- Hidden Three.js offscreen canvas — shared GLB renderer for all FPV tiles -->
<canvas id="glb-offscreen" width="256" height="256"></canvas>

<!-- ── FPV Full-Screen Computer Vision Focus Overlay ──────────────────────── -->
<div id="fpv-focus-overlay">
  <div id="fpv-focus-map-wrap">
    <div id="fpv-focus-map"></div>
    <canvas id="fpv-cv-canvas"></canvas>

    <!-- Top HUD -->
    <div id="fpv-focus-hud-top">
      <div class="cv-hud-left">
        <div class="cv-mode-badge"><div class="cv-mode-dot"></div>CV MODE ACTIVE</div>
        <span class="cv-drone-id" id="cv-drone-label">R1 D-21</span>
        <span class="cv-batt" id="cv-batt-label">85%</span>
        <span class="cv-coord" id="cv-coord-label">120.9800, 14.5900</span>
      </div>
      <div class="cv-hud-right">
        <span class="cv-frame-counter" id="cv-frame">FRM 0000</span>
        <span class="cv-ts" id="cv-ts">00:00:00</span>
      </div>
    </div>

    <!-- Bottom HUD -->
    <div id="fpv-focus-hud-bottom">
      <div class="cv-bottom-left">
        <div class="cv-threat-bar">
          <span class="cv-threat-label">THREAT</span>
          <div class="cv-threat-track"><div class="cv-threat-fill safe" id="cv-threat-fill"></div></div>
        </div>
        <div class="cv-confidence" id="cv-confidence">SURVIVOR CONFIDENCE: <span class="cv-confidence-val">—</span></div>
      </div>
      <div class="cv-bottom-right">
        <span id="cv-hdg">HDG 000°</span>
        <span id="cv-alt">ALT 120m</span>
      </div>
    </div>

    <!-- Streaming inference log (vision model narration) -->
    <div id="cv-infer-log"></div>

    <!-- Zone Verdict -->
    <div id="cv-verdict">
      <div id="cv-verdict-badge"></div>
      <div id="cv-verdict-sub"></div>
    </div>

    <!-- Scan Progress -->
    <div class="cv-scan-progress" id="cv-scan-progress">
      <span class="cv-scan-progress-label" id="cv-scan-label">SCANNING</span>
      <div class="cv-scan-progress-bar"><div class="cv-scan-progress-fill" id="cv-scan-fill"></div></div>
    </div>

    <button id="fpv-focus-close" onclick="closeFpvFocus()">&times;</button>
    <span class="cv-key-hint">SPACE = scan &middot; ESC = close</span>
    <button id="cv-demo-btn" onclick="triggerCvDemo()">▶ DEMO SCAN</button>
  </div>
</div>

</body>
</html>"""



# ── Routes ─────────────────────────────────────────────────────────────────────

@dashboard_app.get("/", response_class=HTMLResponse)
async def index():
    return _HTML


@dashboard_app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    await ws.accept()
    _connected_clients.add(ws)
    print("[WS] Client connected.", file=sys.stderr, flush=True)
    try:
        while True:
            # Run synchronous _get_state in a thread pool to avoid blocking the event loop
            state = await asyncio.to_thread(_get_state)
            try:
                await ws.send_text(json.dumps(state))
            except Exception:
                break
            await asyncio.sleep(0.4)
    except WebSocketDisconnect:
        pass
    except Exception as e:
        print(f"[WS] Error in ws_endpoint: {e}", file=sys.stderr, flush=True)
    finally:
        print("[WS] Client disconnected.", file=sys.stderr, flush=True)
        _connected_clients.discard(ws)


# ── Thread entry point ─────────────────────────────────────────────────────────

def start_dashboard(port: int = 8765) -> None:
    """
    Run the dashboard server (blocking). Call from a daemon thread.

    IMPORTANT: `uvicorn.run()` tries to install OS signal handlers which only
    work on the main thread in Python. Called from a daemon thread, it fails
    silently and breaks the entire event loop (WebSockets stop working).
    The fix: use uvicorn.Config + uvicorn.Server with a dedicated asyncio loop.
    """
    import os
    host = "0.0.0.0"
    port = int(os.environ.get("PORT", port))

    config = uvicorn.Config(
        dashboard_app,
        host=host,
        port=port,
        log_level="warning",
    )
    server = uvicorn.Server(config)

    # Give this thread its own event loop so uvicorn works cleanly outside the main thread
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    print(f"[VIZ] Dashboard starting on http://{host}:{port}", file=sys.stderr, flush=True)
    try:
        loop.run_until_complete(server.serve())
    finally:
        loop.close()
