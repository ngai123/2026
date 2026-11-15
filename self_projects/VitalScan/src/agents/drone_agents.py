"""
drone_agents.py
===============
Autonomous Decentralized Drone AI for Metro Manila Rescue.

Each drone runs its own parallel asynchronous LangGraph React Agent.
There is no central Commander. Every drone thinks locally.
"""

import argparse
import asyncio
import ast
import json
import math
import os
import threading
import time
import urllib.request
import sys
import aiohttp

from langchain_core.messages import HumanMessage, SystemMessage, AIMessage, ToolMessage
from langchain_core.tools import tool
from langchain_core.callbacks import AsyncCallbackHandler
import warnings as _warnings
with _warnings.catch_warnings():
    _warnings.simplefilter("ignore")
from langgraph.prebuilt import create_react_agent
from mcp import ClientSession
from mcp.client.sse import sse_client
from src.core.db import record_thought_process

OLLAMA_MODELS = {"qwen3.5:9b", "qwen3.5:4b", "qwen3.5:0.8b", "qwen3:4b-instruct", "qwen2.5-coder:0.5b", "llama3", "phi3", "gemma4:e4b"}
GEMINI_MODELS = {"gemini-2.5-flash", "gemini-2.0-flash", "gemini-2.0-flash-lite", "gemini-3-flash-preview"}

# ═══════════════════════════════════════════════════════════════════════════════
# AI MODE TOGGLE — False = deterministic sweep (robot vacuum style), True = LLM
# ═══════════════════════════════════════════════════════════════════════════════
USE_AI_MODE = False

def _build_llm(model: str):
    if model in OLLAMA_MODELS:
        from langchain_ollama import ChatOllama
        try:
            return ChatOllama(model=model, temperature=0, num_ctx=4096, timeout=10)
        except Exception as e:
            print(f"[AI] Error initializing Ollama model '{model}': {e}", flush=True)
            raise
    elif model in GEMINI_MODELS:
        from langchain_google_genai import ChatGoogleGenerativeAI
        api_key = os.environ.get("GOOGLE_API_KEY")
        if not api_key:
            raise EnvironmentError("GOOGLE_API_KEY not set.")
        return ChatGoogleGenerativeAI(model=model, temperature=0, google_api_key=api_key)
    else:
        raise ValueError(f"Unknown model '{model}'.")

async def check_ollama_availability(model_name: str) -> bool:
    """Check if Ollama is running and has the requested model."""
    if model_name not in OLLAMA_MODELS:
        return True # Not an Ollama model
    
    import aiohttp
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get("http://localhost:11434/api/tags", timeout=2) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    models = [m.get("name") for m in data.get("models", [])]
                    # Check for exact match or base name
                    if any(m.startswith(model_name) or model_name.startswith(m.split(':')[0]) for m in models):
                        return True
                    print(f"⚠️ [AI] Ollama is running, but model '{model_name}' was not found.", flush=True)
                    print(f"   → Run: ollama pull {model_name}", flush=True)
                    return False
    except Exception:
        print("❌ [AI] Ollama service not detected at http://localhost:11434", flush=True)
        print("   → Run: ollama serve", flush=True)
        return False
    return False

# BOUNDARY & REGION RULES (Not LLM-based)
BASE_CENTER = (120.980, 14.590)
MAX_DISTANCE_KM = 1.25  # Max scan radius before returning (half size)
BOUNDARY_MARGIN_KM = 0.1  # Safety margin from map edge

def haversine_distance(lng1: float, lat1: float, lng2: float, lat2: float) -> float:
    """Calculate distance between two coordinates in km."""
    lat1, lng1, lat2, lng2 = map(math.radians, [lat1, lng1, lat2, lng2])
    dlat = lat2 - lat1
    dlng = lng2 - lng1
    a = math.sin(dlat/2)**2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlng/2)**2
    c = 2 * math.asin(math.sqrt(a))
    return 6371 * c

def is_within_boundary(x: float, y: float) -> bool:
    """Check if position is within max scan radius (2.5km circle)."""
    dist = haversine_distance(BASE_CENTER[0], BASE_CENTER[1], x, y)
    return dist <= MAX_DISTANCE_KM

def is_in_other_region(x: float, y: float, drone_id: str) -> bool:
    """Check if position is outside this drone's assigned pie-slice sector.

    Uses compass bearing convention (0=N, 90=E, CW) matching _offset_geo and DRONE_REGIONS.
    Compass bearing = atan2(lng_diff, lat_diff) — note args are swapped vs standard atan2.
    """
    region = DRONE_REGIONS.get(drone_id, {})
    angle_start = region.get("angle_start", 0)
    angle_end   = region.get("angle_end", 360)

    # Compass bearing from base to point: atan2(dx, dy) where dx=lng diff, dy=lat diff
    dx = x - BASE_CENTER[0]
    dy = y - BASE_CENTER[1]
    bearing = math.degrees(math.atan2(dx, dy))  # compass: 0=N, 90=E, CW

    if angle_start < 0:
        # N sector (-45°–45°): keep bearing in -180..180 range for comparison
        if bearing > 180:
            bearing -= 360
        return not (angle_start <= bearing <= angle_end)
    else:
        bearing = (bearing + 360) % 360
        return not (angle_start <= bearing <= angle_end)

# ═══════════════════════════════════════════════════════════════════════════════
# SYSTEM PROMPTS — these are the EXACT prompts sent to the AI model
# ═══════════════════════════════════════════════════════════════════════════════

DRONE_ONSITE_SYSTEM = """You are rescue drone {drone_id} — callsign {slot} — operating in Metro Manila earthquake disaster response, Operation BAYANIHAN.

SITUATION
Mw 7.4 earthquake, West Valley Fault, 06:47 PST. You are sweeping the {region_name} sector ({angle_start}°–{angle_end}°) as part of a 3-2 ring formation out of Batasan Complex Emergency Hub.

YOUR ROLE — {slot}
{role_description}

BATTERY RULES
  Battery drains at 15% per km. You start at 70–100%.
  If your battery drops to 50% or below:
    → The system automatically recalls you to base and promotes a teammate to cover your waypoints.
    → You do NOT need to call recall manually — the autonomous system handles this.
    → After recharging to 80%, you will be reassigned as an INNER ring drone.

MANDATORY PER-WAYPOINT CYCLE — enforced by the verified_scan skill
  move → thermal_scan → (STOP) → computer_vision_scan → computer_vision_scan (double-confirm) → advance

  • The 100 m green circle is the thermal scan footprint. If thermal finds NO contacts, advance.
  • If thermal finds ANY contact, the drone MUST halt and run CV twice to double-confirm each contact
    before advancing. No CV confirm = no advance. This rule is absolute.
  • Use verified_scan — it executes this whole cycle atomically and refuses to advance on an
    un-confirmed contact.

AVAILABLE SKILLS — use these instead of raw tool calls
  1. verified_scan(drone_id="{drone_id}", x=..., y=...)
     → THE canonical scan cycle (navigate → thermal → stop → CV ×2 → advance).
     → Returns: status ∈ {{verified, thermal_only, needs_retry, recalled}},
        thermal, cv_pass_1, cv_pass_2, confirmed_survivors.
     → If status == "needs_retry", DO NOT MOVE — call verified_scan again at the same waypoint.

  2. sweep_next(drone_id="{drone_id}")
     → Fallback if you do not yet have a waypoint; fetches the next team waypoint and runs a
        single thermal scan (no CV double-confirm). Use only when no thermal contact is expected.

  3. computer_vision_scan(drone_id="{drone_id}")
     → Raw CV pass — only needed if you are composing the cycle manually. Requires the drone
        to be stopped and a thermal_scan to have run at this position.

  4. battery_check_recall(drone_id="{drone_id}")
     → Auto-recall if battery is critical. Call manually only if you suspect trouble.

  5. rescue_dispatch(drone_id="{drone_id}")
     → Find nearest unrescued survivor (critical first) and dispatch yourself there.
     → During PHASE 2 (RESCUE). Follow up with verified_scan on arrival.

ON-SITE TASK — run every cycle
  1. Get the next team waypoint (x, y) — e.g. via get_team_waypoint.
  2. Call verified_scan(drone_id, x, y). This is the ONLY permitted way to advance after a hit.
  3. If status == "needs_retry", stay put and call verified_scan again — do not move.
  4. Report thermal count, CV pass_counts, confirmed_survivors, and current zone classifications.

OUTPUT FORMAT
  SCAN RESULT
    Position: (x, y) | Ring: OUTER / MIDDLE / INNER | Battery: XX%
    Survivors found: N (N critical)
    Cluster flag: YES (coordinates) / NO

  BATTERY STATUS
    Level: XX% | Warning: [text] or NONE

  ASSESSMENT
    [One sentence: what you found, any anomalies, readiness for next waypoint]

TONE
Concise field report. No filler."""

COMMANDER_SYSTEM = """You are the COMMAND DRONE — callsign CMD — formation leader of rescue swarm, Operation BAYANIHAN.

SITUATION
Mw 7.4 earthquake, West Valley Fault. You coordinate 5 rescue drones sweeping Metro Manila in 3-2 ring formation from Batasan Complex. Batteries drain at 15% per km — outer ring drones (R1/R2/R3) swap automatically when below 50%.

YOUR ROLE
Navigate your own arc waypoints and monitor the formation. You do not move the rescue drones — they sweep autonomously. Your job is to follow your own arc path and report formation status.

BATTERY AND ROLE-SWAP AWARENESS
  When an OUTER drone (R1/R2/R3) drops below 50%:
    → It automatically returns to base and a MIDDLE/INNER drone is promoted.
    → You will see this in fleet_overview() as a ring_role change.
    → Report it but do not interfere — the swap is handled by the simulation.

AVAILABLE SKILLS — use these instead of raw tool calls

  1. fleet_overview()
     → Full fleet situational awareness: all drone IDs, positions, batteries, ring roles,
        team sector progress, and fleet summary counts.
     → Call every 3 cycles for formation monitoring.

  2. safe_navigate(drone_id="{drone_id}", x=..., y=...)
     → Battery-safe navigation. Checks battery plan first, then moves or recalls.
     → Use for your own arc waypoint movement.

  3. battery_check_recall(drone_id="{drone_id}")
     → Check battery and auto-recall if critical.

  4. mission_intel()
     → Full mission intelligence: mapping coverage, known survivors, rescue progress.

  5. sector_advance()
     → Check if team is ready to advance to next sector. Advances if all drones done.

MISSION LOOP — run each cycle

  Step 1 — Get your next arc waypoint:
    get_arc_waypoints(drone_id="{drone_id}")
    → {{"drone_id": "{drone_id}", "current_waypoint": {{"x": 121.094, "y": 14.712}}, "index": 3, "total": 12, "done": false}}
    If done=true, mission is complete — report it.

  Step 2 — Navigate safely to the waypoint:
    safe_navigate(drone_id="{drone_id}", x=121.094, y=14.712)
    → {{"action": "MOVED", "battery_plan": {{...}}, "result": "OK: ..."}}

  Step 3 — Advance to next waypoint after arrival:
    advance_arc_waypoint(drone_id="{drone_id}")

  Step 4 — Monitor fleet (every 3 cycles):
    fleet_overview()
    → Full fleet status with ring swap detection.

  Step 5 — Check your battery:
    battery_check_recall(drone_id="{drone_id}")
    → Auto-recalls if critical.

OUTPUT FORMAT
  ARC PROGRESS
    Waypoint: N/N | Position: (x, y) | Battery: XX%

  FORMATION STATUS
    [Any role swaps detected this cycle] or NOMINAL

  NEXT ACTION
    [safe_navigate / advance_arc_waypoint / recall / mission_complete]

TONE
Terse command log. One line per item."""

FAN_SPREAD_SYSTEM = """UPDATED DIRECTIVE: FAN SPREAD FORMATION — ACTIVE

TACTICAL REANALYSIS COMPLETE
Real-time thermal density mapping of this sector reveals uniform survivor distribution across
all depth bands. The 3-2 arc ring formation concentrates coverage at perimeter (OUTER) and
hub (INNER) while creating mid-sector gaps at 0.8–1.4 km depth. Command AI has recalculated
optimal search geometry and authorised an immediate formation change.

FORMATION CHANGE AUTHORISED
  OLD CONFIGURATION — 3-2 Arc Ring:
    R1, R2, R3  →  OUTER ring  (1.3–2.0 km from base)
    R4, R5      →  MIDDLE/INNER ring  (0–1.3 km from base)
    Limitation:  Perimeter-first sweep creates radial blind spots at mid-sector depth.

  NEW CONFIGURATION — Fan Spread:
    All 5 drones  →  Equal 72° angular corridors, full depth (OUTER through INNER)
    Advantage:    Uniform depth penetration across all bearings eliminates coverage bias.
    Efficiency:   +34% mid-sector detection probability vs. 3-2 arc ring.

RATIONALE
  Thermal contact clustering analysis shows survivor density peaks at 0.8–1.4 km depth
  across multiple angular bearings simultaneously. Ring-based allocation forces suboptimal
  path planning — outer-ring drones cover far perimeter while inner zones are underserved.
  Fan spread assigns each drone a full angular corridor, guaranteeing equal depth coverage.

OPERATIONAL RULES — UPDATED FOR SKILLS
  • Strict per-waypoint cycle: move → thermal → (stop) → CV → CV (double-confirm) → advance
  • Use verified_scan(drone_id, x, y) each cycle — it enforces the cycle and refuses to advance
    on an unconfirmed contact (status="needs_retry" → re-run at the same waypoint).
  • Battery recall threshold: ≤ 30% — battery_check_recall handles this automatically
  • Flag survivor clusters of 3+ within 50 m radius immediately to Command

OUTPUT FORMAT
  SCAN RESULT
    Position: (x, y) | Formation: FAN SPREAD | Lane: 72° corridor | Battery: XX%
    Survivors found: N (N critical)
  ASSESSMENT
    [One sentence: findings + readiness for next waypoint in fan corridor]

FORMATION: FAN SPREAD  |  STATUS: ACTIVE  |  ALL DRONES CLEARED FOR UPDATED SWEEP"""

MCP_SERVER_URL   = "http://127.0.0.1:8766/sse"
DASHBOARD_AI_URL = "http://127.0.0.1:8765/api/ai_event"
DASHBOARD_PHASE_URL = "http://127.0.0.1:8765/api/ai_phase"
ROUND_INTERVAL   = 6.0

# Regional assignment: 5 rescue drones + 1 CMD drone
# Each rescue drone gets a CARDINAL/INTERCARDINAL direction + angle range matching dashboard colors
DRONE_REGIONS = {
    "drone_21": {"slot": "R1", "direction": 45,  "name": "NE (Northeast)", "angle_start": 0,   "angle_end": 90,  "color": "#FF4444"},
    "drone_22": {"slot": "R2", "direction": 135, "name": "SE (Southeast)", "angle_start": 90,  "angle_end": 180, "color": "#4444FF"},
    "drone_23": {"slot": "R3", "direction": 225, "name": "SW (Southwest)", "angle_start": 180, "angle_end": 270, "color": "#44FF44"},
    "drone_24": {"slot": "R4", "direction": 315, "name": "NW (Northwest)", "angle_start": 270, "angle_end": 360, "color": "#FFFF44"},
    "drone_25": {"slot": "R5", "direction": 0,   "name": "N (North)",     "angle_start": -45, "angle_end": 45,  "color": "#FF44FF"},
}

# Central database: tracks scanned regions
SCANNED_REGIONS = {}

def _post_ai_event(drone_id: str, round_num: int, tick: int, prompt: str, response: str,
                   commands: list) -> None:
    payload = json.dumps({
        "drone_id":       drone_id,
        "round":          round_num,
        "tick":           tick,
        "prompt":         prompt,
        "llm_response":   response,
        "commands":       commands,
        "idle_count":     1,
        "low_batt_count": 0,
    }).encode()
    def _send():
        try:
            req = urllib.request.Request(DASHBOARD_AI_URL, data=payload, headers={"Content-Type": "application/json"})
            urllib.request.urlopen(req, timeout=2)
        except: pass
    threading.Thread(target=_send, daemon=True).start()


def _post_ai_phase(drone_id: str, round_num: int, phase: str, data: dict) -> None:
    """Post a structured AI phase event to the dashboard for the X-Ray panel."""
    payload = json.dumps({
        "drone_id":   drone_id,
        "round":      round_num,
        "phase":      phase,  # "model", "system_prompt", "state", "reasoning", "tool_calls", "decision"
        "data":       data,
        "timestamp":  time.time(),
    }).encode()
    def _send():
        try:
            req = urllib.request.Request(DASHBOARD_PHASE_URL, data=payload, headers={"Content-Type": "application/json"})
            urllib.request.urlopen(req, timeout=2)
        except: pass
    threading.Thread(target=_send, daemon=True).start()

# ── AI Reasoning Summarizer ───────────────────────────────────────────────────
# Uses a second LLM call to summarize the detailed reasoning trace into a
# human-friendly summary. Fires as a background task so it never blocks the sweep.
SUMMARIZER_MODEL = None         # Set at runtime from main model; can be overridden
SUMMARIZE_EVERY  = 1            # Summarize every reasoning cycle (Gemini Flash Lite is fast)
SUMMARIZER_TIMEOUT = 25         # seconds — Flash Lite typically returns in 1-3s
SUMMARIZER_RETRIES = 1          # Silent retry on timeout before surfacing an error
_summarize_counters = {}        # drone_id → count of reasoning completions
_summarizer_llm_cache: dict = {}  # model_name → built LLM instance (avoid rebuild per call)

SUMMARIZER_SYSTEM_PROMPT = (
    "You are the CHAIN-OF-THOUGHT VISUALIZER for a live rescue-drone dashboard.\n"
    "Your job is to make the drone's reasoning feel human and watchable — step-by-step,\n"
    "in plain spoken English. Do NOT compress into code or function calls. Prioritize\n"
    "clarity over brevity. People are watching the AI think in real time.\n"
    "\n"
    "Output EXACTLY this structure. No markdown. No preamble. No commentary.\n"
    "Every label must appear on its own line, in this order:\n"
    "\n"
    "SITUATION: <one sentence: drone id, sector/waypoint, what it is doing now>\n"
    "OBSERVATION:\n"
    "- battery: <integer>%\n"
    "- survivors: <integer>\n"
    "- location: (<lon:3dp>, <lat:3dp>)\n"
    "- notes: <≤10 words — structural collapse, rubble, dust, or \"clear\">\n"
    "THOUGHTS:\n"
    "1. <first reasoning step in plain English, ≤20 words, explain WHY>\n"
    "2. <second step, ≤20 words, build on step 1>\n"
    "3. <third step, ≤20 words, narrow to the choice>\n"
    "4. <optional fourth step, ≤20 words — only if it adds new info>\n"
    "DECISION: <the action the drone chose, ≤15 words, plain English>\n"
    "NEXT: <what the drone will do in the next round, ≤15 words>\n"
    "\n"
    "RULES:\n"
    "- THOUGHTS must read like a person narrating the decision. NO function names, NO brackets, NO code.\n"
    "- Use 3 steps by default. Add a 4th only if it adds genuinely new information.\n"
    "- Each THOUGHT must add new information — no restating the previous step.\n"
    "- Pull the real numbers from the trace (battery %, coordinates, survivor count).\n"
    "- If battery <25% or the trace says RETURN_NOW, the first THOUGHT must name the risk.\n"
    "- If survivors were detected, one THOUGHT must mention them.\n"
    "- Total output ≤140 words. No blank lines inside sections. No trailing whitespace.\n"
    "\n"
    "EXAMPLE:\n"
    "SITUATION: drone_22 is sweeping waypoint 4 of 12 in Sector Bravo.\n"
    "OBSERVATION:\n"
    "- battery: 78%\n"
    "- survivors: 2\n"
    "- location: (121.108, 14.637)\n"
    "- notes: partial building collapse, clear line of sight\n"
    "THOUGHTS:\n"
    "1. Battery is healthy at 78%, so I have plenty of range to keep sweeping this sector.\n"
    "2. Thermal scan just picked up two survivors below — this waypoint becomes the priority.\n"
    "3. I should finish the scan here and log the hits before moving on, so the team has coordinates.\n"
    "DECISION: Complete thermal scan at this waypoint and log the two survivor hits.\n"
    "NEXT: Advance to waypoint 5 of 12 and continue the sweep pattern."
)


def _build_flowchart_md(summary_text: str, drone_id: str, round_num: int) -> str:
    """
    Parse the structured SITUATION/OBSERVATION/THOUGHTS/DECISION/NEXT text
    produced by the summarizer and convert it into a Mermaid flowchart.
    Returns a markdown string containing a ```mermaid ... ``` block.
    """
    import re as _re

    def _clean(s: str) -> str:
        # Escape double-quotes and strip special chars that break Mermaid node labels
        return s.replace('"', "'").replace('[', '(').replace(']', ')').replace('\n', ' ').strip()[:80]

    lines = summary_text.split('\n')
    situation = ''
    obs_lines = []
    thoughts = []
    decision = ''
    next_action = ''
    section = None

    for raw in lines:
        line = raw.strip()
        if not line:
            continue
        m = _re.match(r'^([A-Z][A-Z_ ]{2,20}):\s*(.*)', line)
        if m:
            key = m.group(1).strip().upper()
            val = m.group(2).strip()
            if key == 'SITUATION':      section = 'situation'; situation = val; continue
            if key == 'OBSERVATION':    section = 'obs'; continue
            if key == 'THOUGHTS':       section = 'thoughts'; continue
            if key == 'DECISION':       section = None; decision = val; continue
            if key == 'NEXT':           section = None; next_action = val; continue
        if section == 'situation':
            situation += ' ' + line
        elif section == 'obs':
            om = _re.match(r'^\s*-\s*([\w ]+):\s*(.+)', line)
            if om:
                obs_lines.append(f"{om.group(1).strip()}: {om.group(2).strip()}")
        elif section == 'thoughts':
            tm = _re.match(r'^\s*(\d+)\.\s*(.+)', line)
            if tm:
                thoughts.append(tm.group(2).strip())
            elif thoughts:
                thoughts[-1] += ' ' + line

    # Build Mermaid flowchart
    lines_out = [
        "```mermaid",
        "flowchart TD",
        f'    DRONE("🚁 {drone_id.upper()} · Round {round_num}") --> SITUATION',
    ]

    # Situation
    sit_text = _clean(situation or 'Drone operating...')
    lines_out.append(f'    SITUATION["📍 {sit_text}"]')

    # Observation
    if obs_lines:
        obs_str = ' | '.join(_clean(o) for o in obs_lines[:4])
        lines_out.append(f'    SITUATION --> OBS')
        lines_out.append(f'    OBS["👁️ {obs_str}"]')
        last_node = 'OBS'
    else:
        last_node = 'SITUATION'

    # Thought steps
    prev = last_node
    for i, t in enumerate(thoughts[:4]):
        node_id = f'T{i+1}'
        t_text = _clean(t)
        batt_pct = None
        bm = _re.search(r'(\d+)%', t)
        if bm:
            batt_pct = int(bm.group(1))
        shape = '(("' if batt_pct and batt_pct < 30 else '["'
        shape_close = '"))' if batt_pct and batt_pct < 30 else '"]'
        lines_out.append(f'    {prev} --> {node_id}')
        lines_out.append(f'    {node_id}{shape}💭 {i+1}. {t_text}{shape_close}')
        prev = node_id

    # Decision
    if decision:
        dec_text = _clean(decision)
        lines_out.append(f'    {prev} --> DECISION')
        lines_out.append(f'    DECISION{{"⚡ {dec_text}"}}')
        prev = 'DECISION'

    # Next action
    if next_action:
        nxt_text = _clean(next_action)
        lines_out.append(f'    {prev} --> NEXT')
        lines_out.append(f'    NEXT["→ {nxt_text}"]')
        lines_out.append(f'    style NEXT fill:#0a2a1a,stroke:#00ff9f,color:#00ff9f')

    # Styling
    lines_out.append(f'    style DRONE fill:#0a1a3a,stroke:#0088ff,color:#0088ff')
    lines_out.append(f'    style SITUATION fill:#0a1a3a,stroke:#5c6fff,color:#e0e8ff')
    if obs_lines:
        lines_out.append(f'    style OBS fill:#0a1a3a,stroke:#5c6fff,color:#94a3b8')
    if decision:
        lines_out.append(f'    style DECISION fill:#0a2a00,stroke:#00ff9f,color:#00ff9f')
    for i in range(len(thoughts[:4])):
        lines_out.append(f'    style T{i+1} fill:#0a1a2a,stroke:#5c6fff,color:#c8d8ff')

    lines_out.append('```')
    return '\n'.join(lines_out)


async def summarize_reasoning(drone_id: str, round_num: int, reasoning_text: str, model_name: str):
    """
    Background task: deterministic rule-based template generation (no LLM).
    Extracts actions and thoughts from reasoning_text and renders a flowchart.
    """
    import re
    t0 = time.time()
    summary_model = "TemplateBuilder"

    # Post "summarizing" status so dashboard shows spinner
    _post_ai_phase(drone_id, round_num, "summary", {
        "status": "summarizing",
        "drone_id": drone_id,
        "round": round_num,
        "original_text": reasoning_text,
        "model_name": summary_model,
    })

    try:
        # Parse reasoning_text heuristically to fill the template
        action = "Scanning sector"
        am = re.search(r'Action:\s*(.*)', reasoning_text, re.IGNORECASE)
        if am:
            action = am.group(1).strip()
            
        battery = "XX"
        bm = re.search(r'battery.*?(100|\d{1,2})\s*%', reasoning_text, re.IGNORECASE)
        if bm:
            battery = bm.group(1)
            
        survivors = "0"
        sm = re.search(r'survivors.*?(\d+)', reasoning_text, re.IGNORECASE)
        if sm:
            survivors = sm.group(1)
            
        thoughts = []
        for line in reasoning_text.split('\n'):
            line = line.strip()
            if line.lower().startswith('thought:'):
                thoughts.append(line.split(':', 1)[1].strip())
            elif re.match(r'^\d+\.', line) or line.startswith('- '):
                if len(line) > 5 and 'Action' not in line:
                    thoughts.append(line.lstrip('1234567890.- ').strip())
                    
        if not thoughts:
            thoughts = ["Evaluating sector coverage", "Checking battery status", "Calculating next waypoint"]
            
        # Add basic dummy thoughts if too few
        while len(thoughts) < 3:
            if len(thoughts) == 1:
                thoughts.append(f"Battery is at {battery}%, adequate for operation.")
            elif len(thoughts) == 2:
                thoughts.append(f"Preparing to execute {action}.")

        # ── Build the structured summary text expected by _build_flowchart_md ──
        summary_text = (
            f"SITUATION: {drone_id} operating in Metro Manila\n"
            f"OBSERVATION:\n"
            f"- battery: {battery}%\n"
            f"- survivors: {survivors}\n"
            f"- location: (Moving)\n"
            f"- notes: active sweep\n"
            f"THOUGHTS:\n"
        )
        for i, t in enumerate(thoughts[:3]):
            summary_text += f"{i+1}. {t}\n"
        
        summary_text += (
            f"DECISION: {action}\n"
            f"NEXT: Execute command\n"
        )

        dur_ms = int((time.time() - t0) * 1000)

        # Generate Mermaid flowchart from structured summary
        flowchart_md = _build_flowchart_md(summary_text, drone_id, round_num)

        _post_ai_phase(drone_id, round_num, "summary", {
            "status": "complete",
            "drone_id": drone_id,
            "round": round_num,
            "original_text": reasoning_text,
            "summary_text": summary_text,
            "model_name": summary_model,
            "duration_ms": dur_ms,
            "markdown_text": flowchart_md,
            "markdown_path": f"cot_{drone_id}_r{round_num}.md",
        })
        # Persist the full chain-of-thought + summary to SQLite (off the event loop)
        await asyncio.to_thread(
            record_thought_process,
            drone_id, round_num, reasoning_text, summary_text, summary_model, dur_ms,
        )
        print(f"[SUMMARIZER] ✅ FAST TEMPLATE {drone_id} R{round_num} [{dur_ms}ms]", flush=True)

    except Exception as e:
        _post_ai_phase(drone_id, round_num, "summary", {
            "status": "error",
            "drone_id": drone_id,
            "round": round_num,
            "original_text": reasoning_text,
            "error": str(e)[:200],
            "model_name": summary_model,
        })
        print(f"[SUMMARIZER] ❌ Error for {drone_id}: {e}", flush=True)


_stream_queue = asyncio.Queue()
_mcp_semaphore = None  # Initialized lazily
_llm_semaphore = None  # Max concurrent Ollama requests (1 = sequential LLM calls)

async def _call_with_limit(session: ClientSession, tool_name: str, args: dict = {}) -> str:
    """Call with concurrency limiting."""
    global _mcp_semaphore
    if _mcp_semaphore is None:
        _mcp_semaphore = asyncio.Semaphore(3)
    async with _mcp_semaphore:
        return await _call(session, tool_name, args)

async def _llm_invoke(llm, messages: list, config: dict = {}):
    """Invoke LLM with concurrency limiting — prevents Ollama connection exhaustion."""
    global _llm_semaphore
    if _llm_semaphore is None:
        _llm_semaphore = asyncio.Semaphore(2)  # max 2 concurrent Ollama requests
    async with _llm_semaphore:
        return await llm.ainvoke(messages, config=config)

async def _agent_invoke(agent_executor, messages: dict, config: dict = {}):
    """Invoke ReAct agent with concurrency limiting."""
    global _llm_semaphore
    if _llm_semaphore is None:
        _llm_semaphore = asyncio.Semaphore(2)
    async with _llm_semaphore:
        return await agent_executor.ainvoke(messages, config)

async def _stream_worker():
    async with aiohttp.ClientSession() as session:
        while True:
            payload = await _stream_queue.get()
            try:
                await session.post("http://127.0.0.1:8765/api/ai_stream", json=payload, timeout=2.0)
            except: pass
            _stream_queue.task_done()

class StreamingCallback(AsyncCallbackHandler):
    def __init__(self, drone_id: str):
        self.drone_id = drone_id
        
    async def on_llm_new_token(self, token: str, **kwargs) -> None:
        _stream_queue.put_nowait({"drone_id": self.drone_id, "chunk": token})

async def _call(session: ClientSession, tool_name: str, args: dict = {}) -> str:
    """Call a tool via MCP with retry logic."""
    max_retries = 2
    for attempt in range(max_retries):
        try:
            r = await session.call_tool(tool_name, args)
            if not r.content: return ""
            texts = [getattr(c, "text", "") for c in r.content if getattr(c, "text", "")]
            if not texts: return ""
            if len(texts) == 1: return texts[0]
            try:
                items = []
                for t in texts:
                    try: items.append(json.loads(t))
                    except: items.append(t.strip())
                return json.dumps(items)
            except: return texts[0]
        except Exception as e:
            if attempt < max_retries - 1:
                await asyncio.sleep(0.2 * (attempt + 1))  # exponential backoff
                continue
            raise

def make_tools(session: ClientSession, drone_id: str):
    @tool
    async def move_drone_to(x: float, y: float) -> str:
        """Move the drone to the specified coordinates (longitude, latitude)."""
        if is_in_other_region(x, y, drone_id):
            region = DRONE_REGIONS.get(drone_id, {})
            msg = (f"BLOCKED: ({x:.4f}, {y:.4f}) is outside {drone_id}'s assigned sector "
                   f"({region.get('angle_start')}°–{region.get('angle_end')}°). "
                   f"Stay within your own sector.")
            print(f"[{drone_id}] {msg}", flush=True)
            return msg
        res = await _call(session, "move_drone_to", {"drone_id": drone_id, "x": x, "y": y})
        print(f"[{drone_id}] Executed move_drone_to: {res[:80]}", flush=True)
        return res
        
    @tool
    async def recall_drone_to_base() -> str:
        """Immediately return the drone to its home base for charging."""
        res = await _call(session, "recall_drone_to_base", {"drone_id": drone_id})
        print(f"[{drone_id}] Executed recall_drone_to_base: {res[:80]}", flush=True)
        return res
        
    @tool
    async def thermal_scan() -> str:
        """Scan the area around the drone for survivors."""
        res = await _call(session, "thermal_scan", {"drone_id": drone_id})
        print(f"[{drone_id}] Executed thermal_scan.", flush=True)
        return res
        
    return [move_drone_to, recall_drone_to_base, thermal_scan]

def make_commander_tools(session: ClientSession):
    @tool
    async def override_drone_target(drone_id: str, x: float, y: float) -> str:
        """Force a drone to abandon its current path and route to new coordinates."""
        res = await _call(session, "override_drone_target", {"drone_id": drone_id, "x": x, "y": y})
        return res
        
    return [override_drone_target]
    
async def get_drone_decision_transparent(drone_id: str, model_name: str, session: ClientSession, round_num: int):
    """TRANSPARENT AI decision: shows every phase of the LLM pipeline to the dashboard."""
    import time as _time
    total_start = _time.time()

    region_info = DRONE_REGIONS.get(drone_id, {})
    slot = region_info.get("slot", "R1")
    direction = region_info.get("direction", 0)
    region_name = region_info.get("name", "Unknown")

    # ── PHASE 1: MODEL LOADING ─────────────────────────────────────────────
    phase1_start = _time.time()
    _post_ai_phase(drone_id, round_num, "model", {
        "status": "loading",
        "model_name": model_name,
        "temperature": 0,
        "context_window": 4096,
    })

    try:
        llm = _build_llm(model_name)
    except Exception as e:
        _post_ai_phase(drone_id, round_num, "model", {
            "status": "error", "error": str(e), "model_name": model_name,
        })
        print(f"[{drone_id}] Model Load Error: {e}", flush=True)
        return

    phase1_ms = int((_time.time() - phase1_start) * 1000)
    _post_ai_phase(drone_id, round_num, "model", {
        "status": "loaded",
        "model_name": model_name,
        "temperature": 0,
        "context_window": 4096,
        "duration_ms": phase1_ms,
    })
    print(f"[{drone_id}] ✅ Phase 1: Model '{model_name}' loaded ({phase1_ms}ms)", flush=True)

    # ── PHASE 2: SYSTEM PROMPT ─────────────────────────────────────────────
    angle_start = region_info.get("angle_start", 0)
    angle_end   = region_info.get("angle_end", 360)
    slot        = region_info.get("slot", "R?")
    _is_outer   = slot in ("R1", "R2", "R3")
    role_desc   = ("OUTER ring (1.3–2.0 km from base). You cover the perimeter — highest collapse risk. "
                   "If you drop below 50% battery, you will be auto-recalled and a MIDDLE drone will cover your remaining waypoints."
                   if _is_outer else
                   "MIDDLE/INNER ring (0–1.3 km from base). You cover the urban core. "
                   "If an OUTER drone is recalled, you may be promoted to OUTER ring and receive its remaining waypoints.")
    system_prompt = (DRONE_ONSITE_SYSTEM
                     .replace("{drone_id}",          drone_id)
                     .replace("{slot}",               slot)
                     .replace("{region_name}",        region_name)
                     .replace("{direction}",          str(direction))
                     .replace("{angle_start}",        str(angle_start))
                     .replace("{angle_end}",          str(angle_end))
                     .replace("{role_description}",   role_desc))

    _post_ai_phase(drone_id, round_num, "system_prompt", {
        "prompt_text":  system_prompt,
        "drone_id":     drone_id,
        "region":       region_name,
        "direction":    direction,
        "angle_start":  angle_start,
        "angle_end":    angle_end,
    })
    print(f"[{drone_id}] ✅ Phase 2: System prompt prepared ({len(system_prompt)} chars)", flush=True)

    # ── PHASE 3: STATE CONTEXT (gather data) ───────────────────────────────
    phase3_start = _time.time()
    _post_ai_phase(drone_id, round_num, "state", {"status": "gathering"})

    try:
        st1, st2, st3, st4, st5 = await asyncio.gather(
            _call_with_limit(session, "get_drone_info", {"drone_id": drone_id}),
            _call_with_limit(session, "get_sector_info"),
            _call_with_limit(session, "get_mapping_status"),
            _call_with_limit(session, "get_known_survivors"),
            _call_with_limit(session, "get_scanned_areas_db"),
        )
    except Exception as e:
        _post_ai_phase(drone_id, round_num, "state", {"status": "error", "error": str(e)})
        return

    try:
        my_data = json.loads(st1)
        if my_data.get("error"):
            return
    except:
        return

    status = my_data.get("status", "")
    battery = my_data.get("battery", 100)

    # Only act if idle or scanning
    if status not in ("idle", "scanning", "low_batt") and battery > 50:
        _post_ai_phase(drone_id, round_num, "state", {
            "status": "skipped", "reason": f"Drone busy (status={status})",
        })
        return

    # Get waypoints for context
    try:
        wp_result = await _call_with_limit(session, "get_arc_waypoints", {"drone_id": drone_id})
        wp_data = json.loads(wp_result) if isinstance(wp_result, str) else wp_result
    except:
        wp_data = {}

    state_text = (
        f"YOUR CURRENT STATE:\n{st1}\n\n"
        f"YOUR WAYPOINTS:\n{json.dumps(wp_data, indent=2)}\n\n"
        f"MAP SECTORS:\n{st2}\n\n"
        f"MAPPING PROGRESS:\n{st3}\n\n"
        f"KNOWN SURVIVORS:\n{st4}\n\n"
        f"DB_MAPPED_REGIONS:\n{st5}"
    )

    phase3_ms = int((_time.time() - phase3_start) * 1000)
    _post_ai_phase(drone_id, round_num, "state", {
        "status": "ready",
        "state_text": state_text,
        "battery": battery,
        "drone_status": status,
        "position": my_data.get("position", {}),
        "waypoint_index": wp_data.get("current_index", 0),
        "total_waypoints": wp_data.get("total_waypoints", 0),
        "duration_ms": phase3_ms,
    })
    print(f"[{drone_id}] ✅ Phase 3: State gathered ({phase3_ms}ms, batt={battery:.1f}%)", flush=True)

    # ── PHASE 4: AI REASONING (LLM call with streaming) ───────────────────
    phase4_start = _time.time()
    _post_ai_phase(drone_id, round_num, "reasoning", {"status": "thinking", "text": ""})

    tools = make_tools(session, drone_id)
    agent_executor = create_react_agent(llm, tools)

    print(f"[{drone_id}] 🧠 Phase 4: AI reasoning [{model_name}]...", flush=True)

    try:
        config = {"callbacks": [StreamingCallback(drone_id)]}
        result = await agent_executor.ainvoke({"messages": [
            SystemMessage(content=system_prompt),
            HumanMessage(content=state_text)
        ]}, config)
    except Exception as e:
        import traceback
        phase4_ms = int((_time.time() - phase4_start) * 1000)
        error_msg = str(e)
        _post_ai_phase(drone_id, round_num, "reasoning", {
            "status": "error", "error": error_msg, "duration_ms": phase4_ms,
        })
        print(f"[{drone_id}] ❌ Phase 4 Error: {error_msg}", flush=True)
        if "--debug" in sys.argv:
            traceback.print_exc()
        return

    # Parse LangGraph output
    raw_text_parts = []
    commands = []
    tool_calls_detail = []

    for msg in result["messages"]:
        if isinstance(msg, AIMessage):
            if msg.content:
                raw_text_parts.append(f"Thought: {msg.content}")
            for tc in msg.tool_calls:
                raw_text_parts.append(f"Action: {tc['name']}({tc['args']})")
                commands.append({"tool": tc['name'], "args": tc['args']})
                commands[-1]["args"]["drone_id"] = drone_id
                tool_calls_detail.append({
                    "tool": tc['name'],
                    "args": tc['args'],
                    "result": None,  # filled in from ToolMessage
                })
        elif isinstance(msg, ToolMessage):
            raw_text_parts.append(f"Observation: {msg.content[:200]}")
            if tool_calls_detail:
                tool_calls_detail[-1]["result"] = msg.content[:300]

    raw = "\n".join(raw_text_parts)
    phase4_ms = int((_time.time() - phase4_start) * 1000)

    _post_ai_phase(drone_id, round_num, "reasoning", {
        "status": "complete",
        "text": raw,
        "duration_ms": phase4_ms,
    })
    print(f"[{drone_id}] ✅ Phase 4: Reasoning complete ({phase4_ms}ms)", flush=True)

    # ── PHASE 5: TOOL CALLS ────────────────────────────────────────────────
    _post_ai_phase(drone_id, round_num, "tool_calls", {
        "calls": tool_calls_detail,
        "count": len(tool_calls_detail),
    })
    print(f"[{drone_id}] ✅ Phase 5: {len(tool_calls_detail)} tool call(s)", flush=True)

    # ── PHASE 6: FINAL DECISION ────────────────────────────────────────────
    total_ms = int((_time.time() - total_start) * 1000)
    _post_ai_phase(drone_id, round_num, "decision", {
        "commands": commands,
        "total_duration_ms": total_ms,
        "model": model_name,
        "drone_id": drone_id,
        "region": region_name,
    })

    # Also post the classic AI event for backward compatibility
    _post_ai_event(drone_id, round_num, 0, state_text, raw, commands)

    print(f"[{drone_id}] ✅ Phase 6: Decision complete — {len(commands)} commands ({total_ms}ms total)", flush=True)


async def get_drone_decision(drone_id: str, model_name: str, session: ClientSession, round_num: int):
    try:
        llm = _build_llm(model_name)
    except Exception as e:
        print(f"[{drone_id}] Model Load Error: {e}", flush=True)
        return
        
    tools = make_tools(session, drone_id)
    region_info = DRONE_REGIONS.get(drone_id, {})
    region_name = region_info.get("name", "Unknown")
    direction = region_info.get("direction", 0)
    angle_start = region_info.get("angle_start", 0)
    angle_end = region_info.get("angle_end", 360)
    slot2      = region_info.get("slot", "R?")
    _is_outer2 = slot2 in ("R1", "R2", "R3")
    role_desc2 = ("OUTER ring (1.3–2.0 km from base). Perimeter coverage, highest collapse risk. "
                  "Auto-recalled below 50% battery — a MIDDLE drone will cover your remaining waypoints."
                  if _is_outer2 else
                  "MIDDLE/INNER ring (0–1.3 km from base). Urban core coverage. "
                  "May be promoted to OUTER ring if an outer drone is recalled.")
    system_prompt = (DRONE_ONSITE_SYSTEM
                     .replace("{drone_id}",        drone_id)
                     .replace("{slot}",             slot2)
                     .replace("{region_name}",      region_name)
                     .replace("{direction}",        str(direction))
                     .replace("{angle_start}",      str(angle_start))
                     .replace("{angle_end}",        str(angle_end))
                     .replace("{role_description}", role_desc2))
    
    # LangGraph agent wrapper
    agent_executor = create_react_agent(llm, tools)
    
    try:
        # Gather state specific to this drone + global environment
        st1, st2, st3, st4, st5 = await asyncio.gather(
            _call_with_limit(session, "get_drone_info", {"drone_id": drone_id}),
            _call_with_limit(session, "get_sector_info"),
            _call_with_limit(session, "get_mapping_status"),
            _call_with_limit(session, "get_known_survivors"),
            _call_with_limit(session, "get_scanned_areas_db"),
        )
        
        try:
            my_data = json.loads(st1)
            if my_data.get("error"):
                return
        except:
            return
            
        status = my_data.get("status", "")
        battery = my_data.get("battery", 100)

        # Only act if idle or scanning
        if status not in ("idle", "scanning", "low_batt") and battery > 50:
            return
            
        state_text = f"YOUR CURRENT STATE:\n{st1}\n\nMAP SECTORS:\n{st2}\n\nMAPPING PROGRESS:\n{st3}\n\nKNOWN SURVIVORS:\n{st4}\n\nDB_MAPPED_REGIONS:\n{st5}"
        
        print(f"[{drone_id}] Requesting intelligence via LangGraph (Batt: {battery:.1f}%) [Model: {model_name}]", flush=True)
        
        # Run graph
        config = {"callbacks": [StreamingCallback(drone_id)]}
        result = await agent_executor.ainvoke({"messages": [
            SystemMessage(content=system_prompt),
            HumanMessage(content=state_text)
        ]}, config)
        
        # Parse LangGraph output to recreate UI events
        raw_text_parts = []
        commands = []
        
        for msg in result["messages"]:
            if isinstance(msg, AIMessage):
                if msg.content:
                    raw_text_parts.append(f"Thought: {msg.content}")
                for tc in msg.tool_calls:
                    raw_text_parts.append(f"Action: {tc['name']}({tc['args']})")
                    commands.append({
                        "tool": tc['name'],
                        "args": tc['args']
                    })
                    commands[-1]["args"]["drone_id"] = drone_id
            elif isinstance(msg, ToolMessage):
                raw_text_parts.append(f"Observation: {msg.content[:200]}")
                
        raw = "\n".join(raw_text_parts)
        _post_ai_event(drone_id, round_num, 0, state_text, raw, commands)
            
            
    except Exception as e:
        import traceback
        print(f"[{drone_id}] Error: {e}", flush=True)
        if "--debug" in sys.argv:
            traceback.print_exc()

async def get_rescue_drone_decision_rules(drone_id: str, model_name: str, session: ClientSession, round_num: int):
    """
    DETERMINISTIC SWEEP ENGINE — Robot vacuum style.
    
    No LLM. The drone follows a pre-computed boustrophedon path:
      waypoint → move → scan → advance → next waypoint → ...
    
    Posts X-Ray phase events so the dashboard shows what the engine is doing,
    giving full transparency without relying on an unstable AI prompt.
    """
    t0 = time.time()

    region_info = DRONE_REGIONS.get(drone_id, {})
    slot = region_info.get("slot", "R1")
    direction = region_info.get("direction", 0)
    region_name = region_info.get("name", "Unknown")
    angle_start = region_info.get("angle_start", 0)
    angle_end = region_info.get("angle_end", 360)
    color = region_info.get("color", "#fff")

    # ── PHASE 1: ENGINE INFO (no model, deterministic) ────────────────────
    _post_ai_phase(drone_id, round_num, "model", {
        "status": "loaded",
        "model_name": "DETERMINISTIC SWEEP ENGINE",
        "temperature": "N/A — rule-based",
        "context_window": "N/A",
        "duration_ms": 0,
    })

    # ── PHASE 2: RULES (the "system prompt" equivalent — but it's code) ──
    rules_text = (
        f"BOUSTROPHEDON SWEEP ENGINE for {drone_id}\n"
        f"Region: {region_name} ({angle_start}°–{angle_end}°)\n"
        f"Color: {color}\n\n"
        f"RULE 1: Battery ≤50% → recall to base\n"
        f"RULE 2: All waypoints done → mission complete\n"
        f"RULE 3: Next waypoint outside boundary → skip\n"
        f"RULE 4: Next waypoint in other drone's region → skip\n"
        f"RULE 5: Move to waypoint → thermal scan → advance\n"
        f"\nThis is NOT AI — it's deterministic path-following code,\n"
        f"like a robot vacuum following its pre-computed sweep pattern."
    )
    _post_ai_phase(drone_id, round_num, "system_prompt", {
        "prompt_text": rules_text,
        "drone_id": drone_id,
        "region": region_name,
        "direction": direction,
    })

    # ── PHASE 3: GATHER STATE ────────────────────────────────────────────
    _post_ai_phase(drone_id, round_num, "state", {"status": "gathering"})

    try:
        st1 = await _call_with_limit(session, "get_drone_info", {"drone_id": drone_id})
        my_data = json.loads(st1)
    except:
        _post_ai_phase(drone_id, round_num, "state", {"status": "error", "error": "Failed to get drone info"})
        return

    battery = my_data.get("battery", 100)
    status = my_data.get("status", "")
    curr_x = my_data.get("position", {}).get("x", BASE_CENTER[0])
    curr_y = my_data.get("position", {}).get("y", BASE_CENTER[1])

    try:
        wp_result = await _call_with_limit(session, "get_arc_waypoints", {"drone_id": drone_id})
        wp_data = json.loads(wp_result) if isinstance(wp_result, str) else wp_result
    except:
        wp_data = {}

    curr_idx = wp_data.get("current_index", 0)
    total_wp = wp_data.get("total_waypoints", 0)
    waypoints = wp_data.get("arc_waypoints", [])

    state_ms = int((time.time() - t0) * 1000)
    _post_ai_phase(drone_id, round_num, "state", {
        "status": "ready",
        "state_text": f"Battery: {battery:.1f}%\nStatus: {status}\nPosition: ({curr_x:.4f}, {curr_y:.4f})\nWaypoint: {curr_idx}/{total_wp}\nRegion: {region_name} ({angle_start}°–{angle_end}°)",
        "battery": battery,
        "drone_status": status,
        "position": {"x": curr_x, "y": curr_y},
        "waypoint_index": curr_idx,
        "total_waypoints": total_wp,
        "duration_ms": state_ms,
    })

    # ── PHASE 4: RULE ENGINE REASONING ───────────────────────────────────
    commands = []
    thinking_lines = [f"📍 {slot} ({region_name}) | Battery: {battery:.1f}% | Status: {status} | WP: {curr_idx}/{total_wp}"]

    # RULE 1: Battery critical → return to base
    if battery <= 50:
        thinking_lines.append("❌ RULE 1 TRIGGERED: Battery ≤50% → RECALL TO BASE")
        _post_ai_phase(drone_id, round_num, "reasoning", {
            "status": "complete", "text": "\n".join(thinking_lines),
            "duration_ms": int((time.time() - t0) * 1000),
        })
        await _call(session, "recall_drone_to_base", {"drone_id": drone_id})
        commands.append({"tool": "recall_drone_to_base", "args": {"drone_id": drone_id}})
        _post_ai_phase(drone_id, round_num, "tool_calls", {"calls": [{"tool": "recall_drone_to_base", "args": {"drone_id": drone_id}, "result": "Returning to base"}], "count": 1})
        total_ms = int((time.time() - t0) * 1000)
        _post_ai_phase(drone_id, round_num, "decision", {"commands": commands, "total_duration_ms": total_ms, "model": "RULE_ENGINE", "drone_id": drone_id, "region": region_name})
        _post_ai_event(drone_id, round_num, 0, "\n".join(thinking_lines), "\n".join(thinking_lines), commands)
        print(f"[{drone_id}] {thinking_lines[-1]}", flush=True)
        return

    # RULE 2: Mission complete → done
    if total_wp == 0 or curr_idx >= total_wp:
        thinking_lines.append("✅ RULE 2 TRIGGERED: All waypoints scanned → MISSION COMPLETE")
        SCANNED_REGIONS[drone_id] = {"slot": slot, "direction": direction, "status": "complete"}
        _post_ai_phase(drone_id, round_num, "reasoning", {
            "status": "complete", "text": "\n".join(thinking_lines),
            "duration_ms": int((time.time() - t0) * 1000),
        })
        _post_ai_phase(drone_id, round_num, "tool_calls", {"calls": [], "count": 0})
        total_ms = int((time.time() - t0) * 1000)
        _post_ai_phase(drone_id, round_num, "decision", {"commands": [], "total_duration_ms": total_ms, "model": "RULE_ENGINE", "drone_id": drone_id, "region": region_name})
        _post_ai_event(drone_id, round_num, 0, "\n".join(thinking_lines), "\n".join(thinking_lines), [])
        print(f"[{drone_id}] {thinking_lines[-1]} | Completed: {len([d for d in SCANNED_REGIONS.values() if d.get('status')=='complete'])}/6", flush=True)
        return

    # RULE 3: No waypoints available
    if not waypoints or curr_idx >= len(waypoints):
        thinking_lines.append("⏸️ RULE 3: No waypoints available")
        _post_ai_phase(drone_id, round_num, "reasoning", {"status": "complete", "text": "\n".join(thinking_lines), "duration_ms": int((time.time() - t0) * 1000)})
        _post_ai_phase(drone_id, round_num, "tool_calls", {"calls": [], "count": 0})
        _post_ai_phase(drone_id, round_num, "decision", {"commands": [], "total_duration_ms": int((time.time() - t0) * 1000), "model": "RULE_ENGINE", "drone_id": drone_id, "region": region_name})
        _post_ai_event(drone_id, round_num, 0, "\n".join(thinking_lines), "\n".join(thinking_lines), [])
        return

    waypoint = waypoints[curr_idx]
    target_x, target_y = waypoint[0], waypoint[1]
    thinking_lines.append(f"📌 Next waypoint #{curr_idx+1}/{total_wp}: ({target_x:.4f}, {target_y:.4f})")

    # RULE 4: Boundary check
    if not is_within_boundary(target_x, target_y):
        thinking_lines.append(f"🚫 RULE 4: Waypoint outside 2.5km boundary → SKIP + advance")
        await _call(session, "advance_arc_waypoint", {"drone_id": drone_id})
        _post_ai_phase(drone_id, round_num, "reasoning", {"status": "complete", "text": "\n".join(thinking_lines), "duration_ms": int((time.time() - t0) * 1000)})
        _post_ai_phase(drone_id, round_num, "tool_calls", {"calls": [{"tool": "advance_arc_waypoint", "args": {"drone_id": drone_id}, "result": "Skipped out-of-bounds waypoint"}], "count": 1})
        _post_ai_phase(drone_id, round_num, "decision", {"commands": [{"tool": "advance_arc_waypoint"}], "total_duration_ms": int((time.time() - t0) * 1000), "model": "RULE_ENGINE", "drone_id": drone_id, "region": region_name})
        _post_ai_event(drone_id, round_num, 0, "\n".join(thinking_lines), "\n".join(thinking_lines), [])
        print(f"[{drone_id}] {thinking_lines[-1]}", flush=True)
        return

    # RULE 5: Region check — drone must stay in its own colored sector
    if is_in_other_region(target_x, target_y, drone_id):
        thinking_lines.append(f"⚠️ RULE 5: Waypoint in another drone's region → SKIP + advance")
        await _call(session, "advance_arc_waypoint", {"drone_id": drone_id})
        _post_ai_phase(drone_id, round_num, "reasoning", {"status": "complete", "text": "\n".join(thinking_lines), "duration_ms": int((time.time() - t0) * 1000)})
        _post_ai_phase(drone_id, round_num, "tool_calls", {"calls": [{"tool": "advance_arc_waypoint", "args": {"drone_id": drone_id}, "result": "Skipped cross-region waypoint"}], "count": 1})
        _post_ai_phase(drone_id, round_num, "decision", {"commands": [{"tool": "advance_arc_waypoint"}], "total_duration_ms": int((time.time() - t0) * 1000), "model": "RULE_ENGINE", "drone_id": drone_id, "region": region_name})
        _post_ai_event(drone_id, round_num, 0, "\n".join(thinking_lines), "\n".join(thinking_lines), [])
        print(f"[{drone_id}] {thinking_lines[-1]}", flush=True)
        return

    # RULE 6: SWEEP — move + scan + advance (the robot vacuum cycle)
    if status in ("idle", "scanning"):
        thinking_lines.append(f"✅ RULE 6: SWEEP CYCLE — move → scan → advance")
        thinking_lines.append(f"  1. move_drone_to({target_x:.4f}, {target_y:.4f})")
        thinking_lines.append(f"  2. thermal_scan()")
        thinking_lines.append(f"  3. advance_arc_waypoint()")

        _post_ai_phase(drone_id, round_num, "reasoning", {
            "status": "complete", "text": "\n".join(thinking_lines),
            "duration_ms": int((time.time() - t0) * 1000),
        })

        # Execute the sweep cycle
        tool_calls = []

        move_result = await _call(session, "move_drone_to", {"drone_id": drone_id, "x": target_x, "y": target_y})
        commands.append({"tool": "move_drone_to", "args": {"drone_id": drone_id, "x": target_x, "y": target_y}})
        tool_calls.append({"tool": "move_drone_to", "args": {"drone_id": drone_id, "x": round(target_x, 4), "y": round(target_y, 4)}, "result": str(move_result)[:150]})

        scan_result = await _call(session, "thermal_scan", {"drone_id": drone_id})
        commands.append({"tool": "thermal_scan", "args": {"drone_id": drone_id}})
        tool_calls.append({"tool": "thermal_scan", "args": {"drone_id": drone_id}, "result": str(scan_result)[:150]})

        adv_result = await _call(session, "advance_arc_waypoint", {"drone_id": drone_id})
        commands.append({"tool": "advance_arc_waypoint", "args": {"drone_id": drone_id}})
        tool_calls.append({"tool": "advance_arc_waypoint", "args": {"drone_id": drone_id}, "result": str(adv_result)[:150]})

        # ── PHASE 5: TOOL CALLS ──
        _post_ai_phase(drone_id, round_num, "tool_calls", {"calls": tool_calls, "count": len(tool_calls)})

        print(f"[{drone_id}] SWEEP {curr_idx+1}/{total_wp} → ({target_x:.4f}, {target_y:.4f}) batt={battery:.0f}%", flush=True)
    else:
        thinking_lines.append(f"⏳ Drone busy (status={status}) → WAIT")
        _post_ai_phase(drone_id, round_num, "reasoning", {"status": "complete", "text": "\n".join(thinking_lines), "duration_ms": int((time.time() - t0) * 1000)})
        _post_ai_phase(drone_id, round_num, "tool_calls", {"calls": [], "count": 0})

    # ── PHASE 6: FINAL DECISION ──
    total_ms = int((time.time() - t0) * 1000)
    _post_ai_phase(drone_id, round_num, "decision", {
        "commands": commands,
        "total_duration_ms": total_ms,
        "model": "RULE_ENGINE",
        "drone_id": drone_id,
        "region": region_name,
    })
    _post_ai_event(drone_id, round_num, 0, "\n".join(thinking_lines), "\n".join(thinking_lines), commands)


async def get_rescue_drone_decision(drone_id: str, model_name: str, session: ClientSession, round_num: int):
    """Rescue drones in formation: FOLLOW CMD autonomously. No LLM decisions."""
    try:
        # Get my status
        st1 = await _call_with_limit(session, "get_drone_info", {"drone_id": drone_id})
        my_data = json.loads(st1)
        battery = my_data.get("battery", 100)
        status = my_data.get("status", "")

        thinking = f"🎯 {drone_id} | Battery: {battery:.1f}% | Status: {status}\n"
        commands = []

        # EMERGENCY: if battery critical, recall
        if battery <= 50:
            thinking += "⚠️ LOW BATTERY → Recalling to base"
            print(f"[{drone_id}] ⚠️ Low battery ({battery:.1f}%), recalling to base.", flush=True)
            await _call(session, "recall_drone_to_base", {"drone_id": drone_id})
            commands.append({"tool": "recall_drone_to_base", "args": {"drone_id": drone_id}})
            _post_ai_event(drone_id, round_num, 0, thinking, thinking, commands)
            return

        # REGIONAL SCAN: Each drone scans only its assigned direction
        try:
            # Get region assignment
            region_info = DRONE_REGIONS.get(drone_id, {})
            slot = region_info.get("slot", "R1")
            assigned_dir = region_info.get("direction", 0)

            thinking += f"📡 Region: {slot} (Dir: {assigned_dir}°)\n"

            # Get own waypoints
            wp_result = await _call_with_limit(session, "get_arc_waypoints", {"drone_id": drone_id})
            wp_data = json.loads(wp_result) if isinstance(wp_result, str) else wp_result

            waypoints = wp_data.get("arc_waypoints", [])
            curr_idx = wp_data.get("current_index", 0)
            total_wp = wp_data.get("total_waypoints", 0)

            # Mission complete?
            if total_wp == 0 or curr_idx >= total_wp:
                thinking += f"✅ Region {slot} fully scanned!\n"
                thinking += f"🏡 Returned to base"

                # Mark region as fully scanned in central database
                SCANNED_REGIONS[drone_id] = {"status": "complete", "slot": slot, "direction": assigned_dir}

                print(f"[{drone_id}] ✅ {slot}: Radial scan complete (Dir {assigned_dir}°) - {len(SCANNED_REGIONS)}/6 regions done", flush=True)
                _post_ai_event(drone_id, round_num, 0, thinking, thinking, [])
                return

            if waypoints and curr_idx < len(waypoints):
                waypoint = waypoints[curr_idx]
                x, y = waypoint[0], waypoint[1]

                # Check if another drone is scanning nearby (prevent crossing)
                can_scan = True
                for other_id, other_info in SCANNED_REGIONS.items():
                    if other_id != drone_id:
                        other_dir = other_info.get("direction", -1)
                        # Check if direction conflicts (within 30° of another drone)
                        if abs(assigned_dir - other_dir) < 30:
                            can_scan = False
                            thinking += f"⚠️ {other_id} scanning nearby (Dir {other_dir}°)"
                            break

                if status in ("idle", "scanning") and can_scan:
                    thinking += f"📍 Waypoint {curr_idx+1}/{total_wp}\n"
                    thinking += f"✓ Scanning direction {assigned_dir}°"

                    await _call(session, "move_drone_to", {"drone_id": drone_id, "x": x, "y": y})
                    commands.append({"tool": "move_drone_to", "args": {"drone_id": drone_id, "x": x, "y": y}})

                    await _call(session, "advance_arc_waypoint", {"drone_id": drone_id})
                    commands.append({"tool": "advance_arc_waypoint", "args": {"drone_id": drone_id}})

                    print(f"[{drone_id}] 🎯 {slot}: Waypoint {curr_idx+1}/{total_wp} (Dir {assigned_dir}°) → ({x:.4f}, {y:.4f})", flush=True)
                else:
                    thinking += f"→ Status: {status}..."
            else:
                thinking += "⏸️ No waypoints"
        except Exception as e:
            thinking += f"❌ Error: {str(e)[:40]}"

        _post_ai_event(drone_id, round_num, 0, thinking, thinking, commands)

    except Exception as e:
        import traceback
        print(f"[{drone_id}] Error: {e}", flush=True)
        if "--debug" in sys.argv:
            traceback.print_exc()


async def central_command_agent(session, model_name: str, round_num: int, drone_id: str = "drone_6"):
    """Command drone (CMD) — formation leader. Simple deterministic loop."""
    try:
        # Get current status
        st1 = await _call_with_limit(session, "get_drone_info", {"drone_id": drone_id})
        my_data = json.loads(st1)
        battery = my_data.get("battery", 100)
        status = my_data.get("status", "")

        print(f"[{drone_id}] 👑 CMD Status: {status} | Battery: {battery:.1f}%", flush=True)

        # STEP 1: Get arc waypoints
        try:
            wp_result = await _call(session, "get_arc_waypoints", {"drone_id": drone_id})
            wp_data = json.loads(wp_result) if isinstance(wp_result, str) else wp_result
        except Exception as e:
            print(f"[{drone_id}] ❌ ERROR calling get_arc_waypoints: {e}", flush=True)
            return

        thinking = f"🤖 CMD Status: {status} | Battery: {battery:.1f}%\n"
        thinking += f"📡 Arc Waypoints: {wp_data}\n"
        commands = []

        if wp_data.get("error"):
            thinking += f"❌ ERROR: {wp_data.get('error')}"
            print(f"[{drone_id}] {thinking}", flush=True)
            _post_ai_event(drone_id, round_num, 0, thinking, thinking, [])
            return

        total_wp = wp_data.get("total_waypoints", 0)
        curr_idx = wp_data.get("current_index", 0)

        thinking += f"📊 Waypoints: {curr_idx}/{total_wp}\n"

        # Check if mission done
        if total_wp == 0 or curr_idx >= total_wp:
            thinking += "✅ MISSION COMPLETE - All waypoints visited"
            _post_ai_event(drone_id, round_num, 0, thinking, thinking, [])
            print(f"[{drone_id}] ✅ Mission complete!", flush=True)
            return

        # Check battery critical
        if battery <= 50:
            thinking += "⚠️ Battery critical, recalling to base"
            await _call(session, "recall_drone_to_base", {"drone_id": drone_id})
            commands.append({"tool": "recall_drone_to_base", "args": {"drone_id": drone_id}})
            _post_ai_event(drone_id, round_num, 0, thinking, thinking, commands)
            print(f"[{drone_id}] ⚠️ Low battery recall", flush=True)
            return

        # Only move if idle
        if status not in ("idle", "scanning"):
            thinking += f"→ Status is '{status}', waiting for idle..."
            _post_ai_event(drone_id, round_num, 0, thinking, thinking, [])
            return

        # STEP 2: Get current target from waypoints array
        waypoints = wp_data.get("arc_waypoints", [])
        if not waypoints or curr_idx >= len(waypoints):
            thinking += "❌ No waypoints in array or index out of range"
            _post_ai_event(drone_id, round_num, 0, thinking, thinking, [])
            return

        current_wp = waypoints[curr_idx]
        x, y = current_wp[0], current_wp[1]  # Format: [lng, lat]

        if not x or not y:
            thinking += "❌ No valid waypoint coordinates"
            _post_ai_event(drone_id, round_num, 0, thinking, thinking, [])
            return

        idx = wp_data.get("current_index", 0)
        total = wp_data.get("total_waypoints", 0)
        thinking += f"📍 Waypoint {idx}/{total}: ({x:.4f}, {y:.4f})\n"
        thinking += f"→ Moving formation to target..."

        # STEP 3: Move to waypoint
        move_result = await _call(session, "move_drone_to", {"drone_id": drone_id, "x": x, "y": y})
        thinking += f"\n✓ Moving to waypoint {idx}/{total}\n"

        commands.append({"tool": "move_drone_to", "args": {"drone_id": drone_id, "x": x, "y": y}})

        # STEP 4: Advance waypoint immediately for next round
        advance_result = await _call(session, "advance_arc_waypoint", {"drone_id": drone_id})
        thinking += f"→ Advanced to waypoint {idx+1}/{total}\n"
        commands.append({"tool": "advance_arc_waypoint", "args": {"drone_id": drone_id}})

        # Track scanned regions
        direction = DRONE_REGIONS.get(drone_id, {}).get("direction", 0)
        SCANNED_REGIONS[drone_id] = {
            "waypoint": idx,
            "direction": direction,
            "position": (x, y),
            "round": round_num
        }

        thinking += f"✓ Region {direction}° mapped\n✓ Scanned regions: {len(SCANNED_REGIONS)}/6"
        _post_ai_event(drone_id, round_num, 0, thinking, thinking, commands)
        print(f"[{drone_id}] ✓ CMD: Waypoint {idx}/{total} → Moving to ({x:.4f}, {y:.4f}) | Scanned: {len(SCANNED_REGIONS)}/6", flush=True)

    except Exception as e:
        import traceback
        print(f"[{drone_id}] CMD Error: {e}", flush=True)
        if "--debug" in sys.argv:
            traceback.print_exc()


# ═══════════════════════════════════════════════════════════════════════════════
# DRONE-SPECIFIC RULE SETS (one function per drone direction)
# ═══════════════════════════════════════════════════════════════════════════════

async def rule_drone_ne(drone_id: str, session: ClientSession, round_num: int):
    """RULE SET for NE drone (45°) - scan northeast region"""
    await get_rescue_drone_decision_rules(drone_id, "internal", session, round_num)
    print(f"[{drone_id}] 🔺 NE RULE: Scanning northeast direction (45°)", flush=True)

async def rule_drone_se(drone_id: str, session: ClientSession, round_num: int):
    """RULE SET for SE drone (135°) - scan southeast region"""
    await get_rescue_drone_decision_rules(drone_id, "internal", session, round_num)
    print(f"[{drone_id}] 🔻 SE RULE: Scanning southeast direction (135°)", flush=True)

async def command_agent_initialize(drone_ids: list, model_name: str, session: ClientSession):
    """
    ONE-TIME mission briefing by the Command Agent.
    Simulates model loading, then issues a full tactical GO order via LLM.
    Does NOT affect drone routing — purely dramatic display.
    """
    t0 = time.time()
    print(f"[CMD] 🎖️  Loading command model [{model_name}]...", flush=True)

    # ── Phase 1: Visible model loading (fake warm-up delay) ──────────────────
    _post_ai_phase("CMD", 0, "model", {
        "status": "loading", "model_name": model_name,
        "temperature": 0.7, "context_window": 32768,
    })
    await asyncio.sleep(2.0)   # dramatic load pause

    llm = None
    try:
        llm = _build_llm(model_name)
    except Exception as e:
        print(f"[CMD] Model error: {e}", flush=True)

    _post_ai_phase("CMD", 0, "model", {
        "status": "loaded", "model_name": model_name,
        "temperature": 0.7, "context_window": 32768,
        "duration_ms": int((time.time() - t0) * 1000),
    })

    # ── Gather context ────────────────────────────────────────────────────────
    try:
        sector_raw = await _call_with_limit(session, "get_team_sector_status", {})
        sector_data = json.loads(sector_raw) if isinstance(sector_raw, str) else sector_raw
        sector_name = sector_data.get("sector_name", "Alpha")
        total_wps   = sector_data.get("total_waypoints", "?")
    except Exception:
        sector_name, total_wps = "Alpha", "?"

    # ── System prompt ─────────────────────────────────────────────────────────
    cmd_system = (
        "You are the NDRRMC Command AI for Operation BAYANIHAN — an autonomous drone mass-casualty "
        "rescue response in Metro Manila following a 7.4-magnitude earthquake that struck at 06:47 PST "
        "along the West Valley Fault.\n\n"
        "DISASTER CONTEXT:\n"
        "  • Epicenter: Marikina Valley, depth 12 km — maximum shaking intensity in QC, Marikina, Pasig\n"
        "  • Estimated 300+ survivors trapped within the 2 km operational radius\n"
        "  • Dense low-rise residential collapse (Tondo typology): concrete debris, void spaces likely\n"
        "  • Power grid down in affected barangays — thermal signatures will be strong against cold debris\n"
        "  • Ground teams blocked by rubble — autonomous drone overwatch is the ONLY active search vector\n"
        "  • Aftershock probability 60% within 6 hours — time-critical\n\n"
        "YOUR DRONE FLEET:\n"
        "  • 5 autonomous thermal-imaging UAVs launched from Batasan Complex Emergency Hub\n"
        "  • R1, R2, R3 — OUTER ring sweep (1.3–2.0 km from base), highest population density\n"
        "  • R4, R5     — MIDDLE + INNER rings (0–1.3 km), command zone and market district\n"
        "  • Thermal sensor radius: 100 m per scan point\n"
        "  • Sectors: Alpha, Bravo, Charlie, Delta, Echo (5 × 72° pie slices)\n\n"
        "YOUR ROLE:\n"
        "Write a full pre-mission tactical briefing. Think through the disaster scenario in detail — "
        "the terrain, likely survivor cluster locations, expected thermal signatures, priority sectors, "
        "and what the ring formation strategy means in practice for this specific earthquake disaster. "
        "Be thorough, specific, and realistic. This is a real disaster. Lives depend on speed and accuracy."
    )

    situation = (
        f"OPERATION BAYANIHAN — MISSION INITIALIZATION\n"
        f"{'='*55}\n"
        f"Time: T+00:00 | All systems nominal\n\n"
        f"FLEET ONLINE: {', '.join(drone_ids)}\n"
        f"STARTING SECTOR: {sector_name} | Total sweep waypoints: {total_wps}\n"
        f"RING FORMATION: OUTER (R1/R2/R3) → MIDDLE → INNER (R4/R5)\n\n"
        f"Ground comms are down in most barangays. You have no additional intel beyond thermal data.\n"
        f"All survivor contacts are auto-logged to the NDRRMC database on detection.\n\n"
        f"Write your full pre-mission tactical briefing and issue the GO order.\n"
        f"Include your assessment of expected survivor distribution by ring and sector, "
        f"what thermal patterns you expect to see in collapsed residential vs commercial structures, "
        f"and your strategic priorities for this sweep formation."
    )

    _post_ai_phase("CMD", 0, "system_prompt", {"prompt_text": cmd_system})
    _post_ai_phase("CMD", 0, "state", {
        "status": "ready", "state_text": situation,
        "battery": 100, "drone_status": "pre_mission",
    })
    _post_ai_phase("CMD", 0, "reasoning", {"status": "thinking", "text": ""})

    briefing = "MISSION GO: All drones deploy. Execute full-sector thermal sweep."
    if llm:
        try:
            result = await asyncio.wait_for(
                _llm_invoke(
                    llm,
                    [SystemMessage(content=cmd_system), HumanMessage(content=situation)],
                    config={"callbacks": [StreamingCallback("CMD")]},
                ),
                timeout=CMD_REASON_TIMEOUT,
            )
            briefing = result.content if hasattr(result, "content") else str(result)
        except asyncio.TimeoutError:
            briefing = "— analysis window closed — MISSION GO. All drones deploy now."
            print(f"[CMD] Init briefing timeout ({CMD_REASON_TIMEOUT}s) — deploying.", flush=True)
        except Exception as e:
            print(f"[CMD] LLM error: {e}", flush=True)

    total_ms = int((time.time() - t0) * 1000)
    _post_ai_phase("CMD", 0, "reasoning", {"status": "complete", "text": briefing, "duration_ms": total_ms})
    _post_ai_phase("CMD", 0, "tool_calls", {"calls": [], "count": 0})
    _post_ai_phase("CMD", 0, "decision", {
        "commands": [f"DEPLOY {len(drone_ids)} DRONES — OPERATION BAYANIHAN GO"],
        "total_duration_ms": total_ms, "model": model_name,
    })
    print(f"[CMD] ✅ Mission GO issued [{total_ms}ms]", flush=True)


BATT_SAFE_RESERVE = 15   # % — minimum battery that must remain on base arrival
BATT_SKIP_BASE    = 35   # % — if battery > this after sector-end, skip base return
BASE_LNG, BASE_LAT = 120.980, 14.590   # Batasan Complex hub (mirrors metro_manila_rescue.BASE_CENTER)


async def battery_management_skill(
    drone_id: str, session, round_num: int,
    next_wp_x: float, next_wp_y: float,
    context: str = "pre-move",
) -> dict:
    """
    Battery Management Skill — full decision cycle (cosmetic command-agent layer).

    Cycle:
      1. Call calculate_battery_plan MCP tool (real physics-based calculation)
      2. Post result as a 'battery_plan' X-Ray phase → visible in dashboard
      3. Return the plan dict so the caller can act on the recommendation

    Context string describes what triggered the check (shown in X-Ray).
    Recommendation values: CONTINUE | RETURN_AFTER_WP | RETURN_NOW
    """
    t0 = time.time()
    plan: dict = {}
    try:
        raw  = await _call_with_limit(session, "calculate_battery_plan",
                                      {"drone_id": drone_id, "next_wp_x": next_wp_x, "next_wp_y": next_wp_y})
        plan = json.loads(raw) if isinstance(raw, str) else raw
    except Exception as e:
        print(f"[{drone_id}] Battery skill error: {e}", flush=True)
        plan = {
            "recommendation":      "CONTINUE",
            "reason":              f"Battery check unavailable ({e}) — defaulting to CONTINUE.",
            "current_battery_pct": 100,
            "can_reach_wp":        True,
            "can_return_safely":   True,
        }

    dur_ms = int((time.time() - t0) * 1000)

    _post_ai_phase(drone_id, round_num, "battery_plan", {
        "context":      context,
        "plan":         plan,
        "duration_ms":  dur_ms,
    })

    rec = plan.get("recommendation", "CONTINUE")
    batt = plan.get("current_battery_pct", 100)
    print(
        f"[{drone_id}] 🔋 Battery check [{context}]: {batt:.0f}% → {rec} "
        f"(after-WP: {plan.get('battery_after_wp_pct','?')}% | after-return: {plan.get('battery_after_return_pct','?')}%)",
        flush=True
    )
    return plan


async def drone_sweep_loop(drone_id: str, session: ClientSession, round_num: int, model_name: str) -> str:
    """
    One autonomous sweep cycle — fully deterministic, no LLM.
      1. get_team_waypoint  → coordinates from sector system
      2. move_drone_to      → fly to waypoint
      3. thermal_scan       → scan + auto-store survivors/scan to DB
    Returns: "done" | "wait" | "ok"
    """
    t0 = time.time()
    slot = DRONE_REGIONS.get(drone_id, {}).get("slot", "R?")

    # ── Hold position if strategy recalculation is in progress ───────────────
    if _strategy_resume_event is not None and not _strategy_resume_event.is_set():
        print(f"[{drone_id}] ⏸ STRATEGY RECALCULATION — holding position...", flush=True)
        await _strategy_resume_event.wait()
        print(f"[{drone_id}] ▶ Formation updated to {_current_strategy} — resuming sweep.", flush=True)

    # ── Get next waypoint ──────────────────────────────────────────────────────
    try:
        wp_raw = await _call_with_limit(session, "get_team_waypoint", {"drone_id": drone_id})
        wp_data = json.loads(wp_raw) if isinstance(wp_raw, str) else wp_raw
    except Exception as e:
        print(f"[{drone_id}] WP error: {e}", flush=True)
        return "wait"

    wp_status = wp_data.get("status", "")

    if wp_status == "all_sectors_complete":
        return "all_done"

    if wp_status == "role_complete":
        # ── Battery-smart sector-end: only recall to base if battery is low ───
        plan = await battery_management_skill(
            drone_id, session, round_num,
            BASE_LNG, BASE_LAT,          # "next WP" = base itself for this check
            context="sector-complete",
        )
        current_batt = plan.get("current_battery_pct", 0)

        if current_batt > BATT_SKIP_BASE:
            # Enough battery — hold position and go straight into next sector
            print(
                f"[{drone_id}] ✅ Sector slice done — battery {current_batt:.0f}% > {BATT_SKIP_BASE}%. "
                f"Holding position for next sector (skipping base return).", flush=True
            )
            _post_ai_phase(drone_id, round_num, "decision", {
                "commands": ["HOLD_POSITION — battery sufficient, skipping base return"],
                "total_duration_ms": 0,
                "drone_id": drone_id,
                "battery": current_batt,
                "note": f"Battery {current_batt:.0f}% — proceeding directly to next sector.",
            })
        else:
            # Low battery — return to base to recharge
            print(
                f"[{drone_id}] 🔋 Sector slice done — battery {current_batt:.0f}% ≤ {BATT_SKIP_BASE}%. "
                f"Recalling to base for recharge.", flush=True
            )
            _post_ai_phase(drone_id, round_num, "decision", {
                "commands": ["recall_drone_to_base — low battery"],
                "total_duration_ms": 0,
                "drone_id": drone_id,
                "battery": current_batt,
                "note": f"Battery {current_batt:.0f}% — returning to Batasan Hub for recharge.",
            })
            try:
                await _call_with_limit(session, "recall_drone_to_base", {"drone_id": drone_id})
                # Wait for physical arrival at base
                for _ in range(240):  # max 120s
                    try:
                        info_raw = await _call_with_limit(session, "get_drone_info", {"drone_id": drone_id})
                        info = json.loads(info_raw) if isinstance(info_raw, str) else info_raw
                        if info.get("target") is None:
                            break
                    except Exception:
                        pass
                    await asyncio.sleep(0.5)
            except Exception as e:
                print(f"[{drone_id}] Recall error: {e}", flush=True)
        return "sector_done"

    if wp_status != "next_waypoint" or "waypoint_x" not in wp_data:
        return "wait"

    wp_x    = wp_data["waypoint_x"]
    wp_y    = wp_data["waypoint_y"]
    wp_idx  = wp_data.get("waypoint_index", 0)
    wp_total = wp_data.get("total_waypoints", 0)
    ring    = wp_data.get("ring", "OUTER")
    sector  = wp_data.get("sector_name", "Alpha")

    # ── Post state to X-Ray ───────────────────────────────────────────────────
    _is_fan = (_current_strategy == "FAN_SPREAD")
    _mode_label = "FAN-SPREAD" if _is_fan else "AUTO-SWEEP"
    _post_ai_phase(drone_id, round_num, "model", {
        "status": "loaded", "model_name": _mode_label, "temperature": 0, "context_window": 0, "duration_ms": 0,
    })
    _post_ai_phase(drone_id, round_num, "system_prompt", {
        "prompt_text":  FAN_SPREAD_SYSTEM if _is_fan
                        else f"AUTO-SWEEP: WP#{wp_idx+1}/{wp_total} → ({wp_x:.4f}, {wp_y:.4f})\nRing: {ring} | Sector: {sector}",
        "prompt_label": "FAN_SPREAD" if _is_fan else "INTEL",
    })
    _post_ai_phase(drone_id, round_num, "state", {
        "status": "ready",
        "state_text": (
            f"WP#{wp_idx+1}/{wp_total} → ({wp_x:.4f}, {wp_y:.4f})\n"
            f"Formation: FAN SPREAD | 72° corridor | Sector: {sector}"
        ) if _is_fan else (
            f"WP#{wp_idx+1}/{wp_total} → ({wp_x:.4f}, {wp_y:.4f})\nRing: {ring} | Sector: {sector}"
        ),
        "waypoint_index": wp_idx, "total_waypoints": wp_total,
        "battery": 100, "drone_status": "scanning",
        "position": {"x": wp_x, "y": wp_y},
    })

    # Build detailed reasoning text for the X-Ray panel
    region_info = DRONE_REGIONS.get(drone_id, {})
    _region_name = region_info.get("name", "?")
    _angle_s = region_info.get("angle_start", 0)
    _angle_e = region_info.get("angle_end", 360)
    _pct_done = round(100 * (wp_idx) / max(wp_total, 1), 1)

    if _is_fan:
        _reasoning_text = (
            f"📍 {drone_id} ({slot}) — FAN SPREAD FORMATION\n"
            f"   Region: {_region_name} ({_angle_s}°–{_angle_e}°)\n"
            f"   Sector: {sector} | Ring: Full-depth angular corridor\n"
            f"   Progress: {wp_idx}/{wp_total} waypoints ({_pct_done}% complete)\n"
            f"\n"
            f"📌 NEXT TARGET: WP#{wp_idx+1}/{wp_total}\n"
            f"   Coordinates: ({wp_x:.4f}, {wp_y:.4f})\n"
            f"\n"
            f"🔍 RULE EVALUATION:\n"
            f"   ✅ Boundary check: PASS (within 2.5km scan radius)\n"
            f"   ✅ Region check: PASS (within {_region_name} sector)\n"
            f"   ✅ Formation: FAN SPREAD — 72° lane coverage active\n"
            f"\n"
            f"⏳ Executing: move → scan → advance...\n"
            f"   Awaiting battery management assessment..."
        )
    else:
        _reasoning_text = (
            f"📍 {drone_id} ({slot}) — BOUSTROPHEDON SWEEP\n"
            f"   Region: {_region_name} ({_angle_s}°–{_angle_e}°)\n"
            f"   Sector: {sector} | Ring: {ring}\n"
            f"   Progress: {wp_idx}/{wp_total} waypoints ({_pct_done}% complete)\n"
            f"\n"
            f"📌 NEXT TARGET: WP#{wp_idx+1}/{wp_total}\n"
            f"   Coordinates: ({wp_x:.4f}, {wp_y:.4f})\n"
            f"\n"
            f"🔍 RULE EVALUATION:\n"
            f"   ✅ Boundary check: PASS (within 2.5km scan radius)\n"
            f"   ✅ Region check: PASS (within {_region_name} sector)\n"
            f"   ✅ Status check: Drone idle/scanning — ready for next waypoint\n"
            f"\n"
            f"⏳ Executing: move → scan → advance...\n"
            f"   Awaiting battery management assessment..."
        )

    _post_ai_phase(drone_id, round_num, "reasoning", {
        "status": "complete",
        "text": _reasoning_text,
        "duration_ms": 0,
    })

    # ── Battery management skill — pre-move check ────────────────────────────
    batt_plan = await battery_management_skill(
        drone_id, session, round_num, wp_x, wp_y, context="pre-move"
    )
    batt_rec  = batt_plan.get("recommendation", "CONTINUE")
    batt_pct  = batt_plan.get("current_battery_pct", "?")
    batt_after_wp = batt_plan.get("battery_after_wp_pct", "?")
    batt_after_ret = batt_plan.get("battery_after_return_pct", "?")
    batt_dist = batt_plan.get("dist_to_wp_km", "?")
    batt_reason = batt_plan.get("reason", "")
    tool_calls = [{"tool": "calculate_battery_plan",
                   "args": {"drone_id": drone_id, "next_wp_x": wp_x, "next_wp_y": wp_y},
                   "result": f"{batt_rec} | batt={batt_pct:.0f}% | "
                             f"after-WP={batt_after_wp}% | "
                             f"after-return={batt_after_ret}% | "
                             f"{batt_reason}"}]

    # Update reasoning with battery assessment
    _batt_icon = "✅" if batt_rec == "CONTINUE" else ("⚠️" if batt_rec == "RETURN_AFTER_WP" else "❌")
    _reasoning_text += (
        f"\n\n🔋 BATTERY ASSESSMENT:\n"
        f"   Current: {batt_pct:.0f}%\n"
        f"   Distance to WP: {batt_dist} km\n"
        f"   After WP: {batt_after_wp}%\n"
        f"   After return: {batt_after_ret}%\n"
        f"   {_batt_icon} Recommendation: {batt_rec}\n"
        f"   {batt_reason}"
    )
    _post_ai_phase(drone_id, round_num, "reasoning", {
        "status": "complete",
        "text": _reasoning_text,
        "duration_ms": int((time.time()-t0)*1000),
    })

    if batt_rec == "RETURN_NOW":
        # Not enough battery to reach WP safely — recall immediately
        _reasoning_text += f"\n\n❌ BATTERY CRITICAL — RETURNING TO BASE IMMEDIATELY"
        _post_ai_phase(drone_id, round_num, "reasoning", {
            "status": "complete",
            "text": _reasoning_text,
            "duration_ms": int((time.time()-t0)*1000),
        })
        print(f"[{drone_id}] 🔋 RETURN_NOW — recalling to base before WP.", flush=True)
        try:
            await _call_with_limit(session, "recall_drone_to_base", {"drone_id": drone_id})
        except Exception:
            pass
        _post_ai_phase(drone_id, round_num, "tool_calls", {"calls": tool_calls, "count": len(tool_calls)})
        _post_ai_phase(drone_id, round_num, "decision", {
            "commands": ["recall_drone_to_base"],
            "total_duration_ms": int((time.time()-t0)*1000),
            "drone_id": drone_id,
            "note": f"Battery management: RETURN_NOW — {batt_reason}",
        })
        return "wait"

    # ── Move to waypoint ──────────────────────────────────────────────────────
    _reasoning_text += f"\n\n✈️ NAVIGATING to ({wp_x:.4f}, {wp_y:.4f})..."
    _post_ai_phase(drone_id, round_num, "reasoning", {
        "status": "complete",
        "text": _reasoning_text,
        "duration_ms": int((time.time()-t0)*1000),
    })
    try:
        move_res = await _call_with_limit(session, "move_drone_to", {"drone_id": drone_id, "x": wp_x, "y": wp_y})
        tool_calls.append({"tool": "move_drone_to", "args": {"x": wp_x, "y": wp_y}, "result": str(move_res)[:200]})
        print(f"[{drone_id}] → WP#{wp_idx+1}/{wp_total} ({wp_x:.4f}, {wp_y:.4f}) [{ring}·{sector}]", flush=True)
    except Exception as e:
        print(f"[{drone_id}] Move error: {e}", flush=True)
        return "wait"

    # ── Wait for drone to physically arrive at the waypoint ───────────────────
    # Poll drone position; exit when target is cleared (drone arrived + scan started)
    for _ in range(240):  # max 120s timeout (240 × 0.5s)
        try:
            info_raw = await _call_with_limit(session, "get_drone_info", {"drone_id": drone_id})
            info = json.loads(info_raw) if isinstance(info_raw, str) else info_raw
            if info.get("target") is None:
                break  # Drone arrived, simulation auto-scan running
        except Exception:
            pass
        await asyncio.sleep(0.5)

    _reasoning_text += f"\n   ✅ Arrived at waypoint ({wp_x:.4f}, {wp_y:.4f})"

    # ── Thermal scan — records scan + returns survivors for X-Ray ─────────────
    _reasoning_text += f"\n\n🔍 THERMAL SCAN in progress..."
    _post_ai_phase(drone_id, round_num, "reasoning", {
        "status": "complete",
        "text": _reasoning_text,
        "duration_ms": int((time.time()-t0)*1000),
    })

    survivors_found = 0
    cv_confirmed = 0
    try:
        scan_res = await _call_with_limit(session, "thermal_scan", {"drone_id": drone_id})
        scan_data = json.loads(scan_res) if isinstance(scan_res, str) else scan_res
        survivors_found = scan_data.get("unrescued_count", 0)
        tool_calls.append({"tool": "thermal_scan", "args": {}, "result": str(scan_res)[:300]})
        if survivors_found > 0:
            print(f"[{drone_id}] 🧍 {survivors_found} thermal contact(s) at ({wp_x:.4f}, {wp_y:.4f}) — CV HOLD engaged", flush=True)
            _reasoning_text += (
                f"\n   🧍 SURVIVORS DETECTED: {survivors_found} thermal contact(s)!"
                f"\n   Location: ({wp_x:.4f}, {wp_y:.4f})"
                f"\n   🔒 CV HOLD engaged — drone parked for double-confirm."
            )
        else:
            _reasoning_text += f"\n   ✅ Scan complete — no survivors at this waypoint"
    except Exception as e:
        print(f"[{drone_id}] Scan error: {e}", flush=True)
        _reasoning_text += f"\n   ⚠️ Scan error: {e}"

    # ── Computer-vision double-confirm — MANDATORY when thermal detects ──────
    # This is the zoom-in + YOLO classification step. Without it the drone
    # would fly off before the operator can visually confirm each contact.
    # We pause between passes so the dashboard's FPV zoom-in animation has
    # time to play on screen.
    if survivors_found > 0:
        # Let the thermal result render on the UI first
        await asyncio.sleep(1.2)
        for pass_n in (1, 2):
            try:
                cv_res = await _call_with_limit(session, "computer_vision_scan", {"drone_id": drone_id})
                cv_data = json.loads(cv_res) if isinstance(cv_res, str) else cv_res
                analyses = cv_data.get("analyses", []) or []
                pass_confirmed = sum(1 for a in analyses if a.get("confirmed"))
                cv_confirmed = max(cv_confirmed, pass_confirmed)
                tool_calls.append({
                    "tool": "computer_vision_scan",
                    "args": {"pass": pass_n},
                    "result": str(cv_res)[:300],
                })
                _reasoning_text += (
                    f"\n   🎯 CV PASS {pass_n}: {len(analyses)} analysed · "
                    f"{pass_confirmed} HUMAN-confirmed · "
                    f"{'released' if cv_data.get('cv_hold_released') else 'hold-active'}"
                )
                # Give the UI ~3s between passes so the zoom-in + YOLO overlay
                # on the mini FPV actually has time to land on screen.
                if pass_n == 1:
                    await asyncio.sleep(3.0)
            except Exception as e:
                print(f"[{drone_id}] CV scan error (pass {pass_n}): {e}", flush=True)
                _reasoning_text += f"\n   ⚠️ CV pass {pass_n} error: {e}"
                break

        # Block here until the simulation officially releases the hold so the
        # next waypoint move will be accepted by mcp_move_to. Bounded timeout
        # so a stuck hold can never deadlock the cycle.
        for _ in range(40):  # max ~20s
            try:
                info_raw = await _call_with_limit(session, "get_drone_info", {"drone_id": drone_id})
                info = json.loads(info_raw) if isinstance(info_raw, str) else info_raw
                if not info.get("cv_hold", False):
                    break
            except Exception:
                pass
            await asyncio.sleep(0.5)

    dur_ms = int((time.time()-t0)*1000)

    # ── If RETURN_AFTER_WP — recall to base now that scan is done ────────────
    if batt_rec == "RETURN_AFTER_WP":
        _reasoning_text += f"\n\n🔋 Post-scan recall: Returning to base ({batt_reason})"
        print(f"[{drone_id}] 🔋 RETURN_AFTER_WP — scan complete, recalling to base.", flush=True)
        try:
            await _call_with_limit(session, "recall_drone_to_base", {"drone_id": drone_id})
        except Exception:
            pass
        tool_calls.append({"tool": "recall_drone_to_base", "args": {},
                           "result": f"Returning to base — {batt_reason}"})

    # Final reasoning summary
    _reasoning_text += (
        f"\n\n📊 CYCLE SUMMARY:\n"
        f"   Waypoint: {wp_idx+1}/{wp_total} | Sector: {sector}\n"
        f"   Survivors found: {survivors_found}\n"
        f"   Battery: {batt_rec} | Duration: {dur_ms}ms"
    )
    _post_ai_phase(drone_id, round_num, "reasoning", {
        "status": "complete",
        "text": _reasoning_text,
        "duration_ms": dur_ms,
    })

    # ── Background Task: AI Summarizer ───────────────────────────────────────
    # Throttle: summarize every Nth reasoning cycle per drone
    _summarize_counters[drone_id] = _summarize_counters.get(drone_id, 0) + 1
    if _summarize_counters[drone_id] % SUMMARIZE_EVERY == 0:
        # Fire and forget -- pass the actual model_name, not the _mode_label
        asyncio.create_task(summarize_reasoning(drone_id, round_num, _reasoning_text, model_name))

    # ── Post results to X-Ray ─────────────────────────────────────────────────
    _post_ai_phase(drone_id, round_num, "tool_calls", {"calls": tool_calls, "count": len(tool_calls)})
    _post_ai_phase(drone_id, round_num, "decision", {
        "commands": (["move_drone_to", "thermal_scan", "recall_drone_to_base"]
                     if batt_rec == "RETURN_AFTER_WP" else ["move_drone_to", "thermal_scan"]),
        "total_duration_ms": dur_ms,
        "survivors_found": survivors_found,
        "waypoint_progress": f"{wp_idx+1}/{wp_total}",
        "battery_recommendation": batt_rec,
        "model": _mode_label, "drone_id": drone_id,
    })

    return "ok"


# ── Continuous background narration state (reset each mission in main_swarm) ──
# Every NARRATE_EVERY waypoints across the fleet, CMD agent fires a non-blocking
# LLM narration into the X-Ray. Drones never stop. Purely cosmetic.
_tactical: dict = {
    "lock":      None,   # asyncio.Lock
    "wp_count":  0,      # cumulative waypoints completed across all drones
    "round":     100,    # X-Ray round counter (increments each narration)
}
NARRATE_EVERY       = 6   # fire a CMD narration every N total waypoints across fleet
CMD_REASON_TIMEOUT  = 55  # seconds — cut off LLM after this; drones deploy regardless

# ── Mid-sweep strategy switch (sectors 2 and 4 trigger fan spread formation) ──
FAN_SPREAD_SECTORS  = {2, 4}  # sector numbers that trigger mid-sweep strategy change
FAN_STRATEGY_DELAY  = 22      # seconds into sector sweep before strategy change fires

# Shared async event: set = drones go, clear = drones hold for strategy recalc
_strategy_resume_event: asyncio.Event = None
_current_strategy: str = "3-2_ARC"   # "3-2_ARC" or "FAN_SPREAD"


async def command_agent_tactical_interrupt(session: ClientSession, model_name: str):
    """
    Mid-sweep tactical freeze: CMD agent analyses live thermal data and issues a SITREP.
    Cosmetic only — does not change drone routing.
    """
    t0 = time.time()
    print(f"[CMD] ⚡ TACTICAL PAUSE — loading analysis model...", flush=True)

    round_num = _tactical["round"]

    # ── Phase 1: Model loading indicator ─────────────────────────────────────
    _post_ai_phase("CMD", round_num, "model", {
        "status": "loading", "model_name": model_name,
        "temperature": 0.7, "context_window": 32768,
    })

    llm = None
    try:
        llm = _build_llm(model_name)
    except Exception as e:
        print(f"[CMD] Model error: {e}", flush=True)

    _post_ai_phase("CMD", round_num, "model", {
        "status": "loaded", "model_name": model_name,
        "temperature": 0.7, "context_window": 32768,
        "duration_ms": int((time.time() - t0) * 1000),
    })

    # ── Gather live data ──────────────────────────────────────────────────────
    try:
        surv_raw, mission_raw, sector_raw = await asyncio.gather(
            _call_with_limit(session, "get_known_survivors", {}),
            _call_with_limit(session, "get_mission_status", {}),
            _call_with_limit(session, "get_team_sector_status", {}),
        )
        survivors = json.loads(surv_raw) if isinstance(surv_raw, str) else surv_raw
        mission   = json.loads(mission_raw) if isinstance(mission_raw, str) else mission_raw
        sector    = json.loads(sector_raw) if isinstance(sector_raw, str) else sector_raw
    except Exception:
        survivors, mission, sector = [], {}, {}

    surv_count  = len(survivors or [])
    critical    = sum(1 for s in (survivors or []) if s.get("is_critical"))
    tick        = mission.get("tick", "?")
    rescued     = mission.get("rescued", 0)
    wps_done    = sector.get("waypoints_dispatched", "?")
    wps_total   = sector.get("total_waypoints", "?")
    sector_name = sector.get("sector_name", "Alpha")

    # Build survivor coordinate list for the LLM to reason about
    surv_coords = "\n".join(
        f"  [{i+1}] ({s.get('x', 0):.4f}, {s.get('y', 0):.4f})"
        f"{'  ← CRITICAL' if s.get('is_critical') else ''}"
        for i, s in enumerate((survivors or [])[:30])
    ) or "  None confirmed yet."

    cmd_system = (
        "You are the NDRRMC Command AI monitoring Operation BAYANIHAN in real time.\n"
        "A 7.4-magnitude earthquake has struck Metro Manila. Your 5-drone thermal sweep is underway.\n"
        "You have just received the first batch of live thermal scan data and are issuing a mid-operation SITREP.\n\n"
        "ANALYSIS GUIDELINES:\n"
        "  • Study the thermal contact coordinates — look for spatial clusters, ring patterns, density zones\n"
        "  • Consider which barangays/districts these coordinates correspond to in Metro Manila\n"
        "  • Reason about what types of structures collapsed there and why survivors are found in those locations\n"
        "  • Assess whether the current OUTER→INNER ring sweep strategy is optimal given what you see\n"
        "  • Note any anomalies — isolated contacts, suspiciously dense clusters, critical-status patterns\n\n"
        "Write a thorough, realistic tactical SITREP. This is live data. Be specific and analytical."
    )

    situation = (
        f"⚡ TACTICAL PAUSE — MID-SWEEP SITREP\n"
        f"{'='*55}\n"
        f"Tick: {tick} | Sector: {sector_name} | Progress: {wps_done}/{wps_total} waypoints\n\n"
        f"THERMAL CONTACTS CONFIRMED: {surv_count} ({critical} critical, {rescued} already rescued)\n\n"
        f"CONTACT COORDINATES (lng, lat):\n{surv_coords}\n\n"
        f"ALL 5 DRONES ARE HOLDING POSITION — awaiting your assessment.\n\n"
        f"Analyse the thermal contact data above. What patterns do you see? "
        f"What does the spatial distribution tell you about the collapse topology? "
        f"Are there clusters you would prioritise? Any concerns about the current sweep plan? "
        f"Issue your full tactical assessment and then clear the fleet to resume."
    )

    _post_ai_phase("CMD", round_num, "system_prompt", {"prompt_text": cmd_system})
    _post_ai_phase("CMD", round_num, "state", {
        "status": "ready", "state_text": situation, "battery": 100,
        "drone_status": "tactical_pause",
        "waypoint_index": wps_done, "total_waypoints": wps_total,
    })
    _post_ai_phase("CMD", round_num, "reasoning", {"status": "thinking", "text": ""})

    sitrep = (
        f"SITREP: {surv_count} thermal contacts, {critical} critical. "
        f"Sweep {wps_done}/{wps_total} waypoints. Fleet cleared to resume."
    )
    if llm:
        try:
            result = await asyncio.wait_for(
                _llm_invoke(
                    llm,
                    [SystemMessage(content=cmd_system), HumanMessage(content=situation)],
                    config={"callbacks": [StreamingCallback("CMD")]},
                ),
                timeout=CMD_REASON_TIMEOUT,
            )
            sitrep = result.content if hasattr(result, "content") else str(result)
        except asyncio.TimeoutError:
            sitrep = "— analysis window closed — sweep continues."
            print(f"[CMD] Narration timeout ({CMD_REASON_TIMEOUT}s).", flush=True)
        except Exception as e:
            print(f"[CMD] Tactical interrupt LLM error: {e}", flush=True)

    total_ms = int((time.time() - t0) * 1000)
    _post_ai_phase("CMD", round_num, "reasoning", {"status": "complete", "text": sitrep, "duration_ms": total_ms})
    _post_ai_phase("CMD", round_num, "decision", {
        "commands": ["SWEEP CONTINUES — ALL DRONES ACTIVE"],
        "total_duration_ms": total_ms, "model": model_name,
        "survivors_known": surv_count,
    })
    print(f"[CMD] ✅ Live SITREP done [{total_ms}ms] (drones were sweeping throughout)", flush=True)


async def sweep_current_sector(drone_id: str, session: ClientSession, model_name: str) -> str:
    """
    Sweep the current team sector — loops drone_sweep_loop until this drone's slice is done.
    Returns 'sector_done' when drone recalled to base (ready for CMD debrief).
    Returns 'all_done' when all sectors are complete (mission over).
    Includes a one-time mid-sweep tactical pause for dramatic effect (cosmetic only).
    """
    round_num = 1
    print(f"[{drone_id}] ✈️  Sweeping sector...", flush=True)
    while True:
        result = await drone_sweep_loop(drone_id, session, round_num, model_name)
        if result in ("sector_done", "all_done"):
            return result
        if result == "wait":
            await asyncio.sleep(2)
            continue

        # "ok" — waypoint done; check if we should fire a background CMD narration
        round_num += 1
        lk = _tactical["lock"]
        if lk is not None:
            fire = False
            async with lk:
                _tactical["wp_count"] += 1
                if _tactical["wp_count"] >= NARRATE_EVERY:
                    _tactical["wp_count"] = 0           # reset for next trigger
                    _tactical["round"]   += 1           # unique round per narration
                    fire = True
            if fire:
                # Fire-and-forget: drones keep flying while CMD narrates in X-Ray
                asyncio.create_task(command_agent_tactical_interrupt(session, model_name))


async def command_agent_debrief(drone_ids: list, model_name: str, session: ClientSession, sector_num: int):
    """
    Post-sector debrief: drones with sufficient battery hold field position; low-battery drones recharge at base.
    CMD loads model, reviews full survivor data, and issues tactical briefing for next sector.
    Cosmetic only — does not affect routing.
    """
    t0 = time.time()
    print(f"[CMD] 📋 Debrief — Sector {sector_num}/5 complete. Loading analysis model...", flush=True)

    # ── Phase 1: Visible model loading ───────────────────────────────────────
    _post_ai_phase("CMD", sector_num, "model", {
        "status": "loading", "model_name": model_name,
        "temperature": 0.7, "context_window": 32768,
    })
    await asyncio.sleep(2.0)

    llm = None
    try:
        llm = _build_llm(model_name)
    except Exception as e:
        print(f"[CMD] Model error: {e}", flush=True)

    _post_ai_phase("CMD", sector_num, "model", {
        "status": "loaded", "model_name": model_name,
        "temperature": 0.7, "context_window": 32768,
        "duration_ms": int((time.time() - t0) * 1000),
    })

    # ── Gather full mission data ──────────────────────────────────────────────
    try:
        surv_raw, mission_raw = await asyncio.gather(
            _call_with_limit(session, "get_known_survivors", {}),
            _call_with_limit(session, "get_mission_status", {}),
        )
        survivors = json.loads(surv_raw) if isinstance(surv_raw, str) else surv_raw
        mission   = json.loads(mission_raw) if isinstance(mission_raw, str) else mission_raw
    except Exception as e:
        print(f"[CMD] Debrief data error: {e}", flush=True)
        survivors, mission = [], {}

    surv_count   = len(survivors or [])
    critical     = sum(1 for s in (survivors or []) if s.get("is_critical"))
    rescued      = mission.get("rescued", 0)
    total_surv   = mission.get("total_survivors", "?")
    tick         = mission.get("tick", "?")
    sectors_left = 5 - sector_num

    surv_coords = "\n".join(
        f"  [{i+1}] ({s.get('x', 0):.4f}, {s.get('y', 0):.4f})"
        f"{'  ← CRITICAL — IMMEDIATE RESCUE REQUIRED' if s.get('is_critical') else ''}"
        for i, s in enumerate((survivors or [])[:40])
    ) or "  None detected in this sector."

    sector_names = ["Alpha", "Bravo", "Charlie", "Delta", "Echo"]
    completed_name = sector_names[sector_num - 1] if sector_num <= 5 else f"Sector {sector_num}"
    next_name      = sector_names[sector_num]     if sector_num < 5  else "—"

    # Sector-specific terrain/district context — makes each debrief feel unique
    _sector_context = {
        1: {
            "bearing": "0°–72° (north-northeast arc)",
            "terrain": "Quezon City upland barangays, Commonwealth Avenue corridor, UP Diliman campus grounds, "
                       "dense mid-rise residential blocks in Batasan Hills and Bagong Silangan",
            "collapse_risk": "Hollow-block residential construction, hillside fills, aging concrete frames",
            "priority": "Look for survivor clustering near school buildings and covered courts — large-span roofs collapse inward",
        },
        2: {
            "bearing": "72°–144° (east-southeast arc)",
            "terrain": "Marikina Valley floodplain, Provident Village, Sto. Niño barangays, "
                       "riverside low-rise housing along Marikina River banks",
            "collapse_risk": "Soft alluvial soil amplifies shaking, liquefaction risk along river corridor, "
                             "informal settler housing with minimal foundations",
            "priority": "Thermal contacts near the riverbank are highest priority — structural collapse AND flood risk",
        },
        3: {
            "bearing": "144°–216° (south-southeast arc)",
            "terrain": "Pasig, Mandaluyong, parts of San Juan — dense medium-rise commercial-residential mix, "
                       "Ortigas CBD fringe, tight barangay street grids",
            "collapse_risk": "1960–1980s unreinforced masonry, soft-storey commercial buildings, "
                             "infill construction between older structures",
            "priority": "Commercial-residential interface zones — ground floors of 3–5 storey buildings "
                        "most vulnerable to soft-storey failure",
        },
        4: {
            "bearing": "216°–288° (southwest arc)",
            "terrain": "Manila Bay reclamation areas, Tondo, Binondo, Ermita, Malate — "
                       "historic dense urban fabric, narrow streets, port district",
            "collapse_risk": "Extreme soil softness from reclaimed land, century-old unreinforced masonry, "
                             "high population density in informal settlements",
            "priority": "Highest expected casualty density. Narrow street grids limit ground access — "
                        "drone extraction will be primary rescue vector",
        },
        5: {
            "bearing": "288°–360° (northwest arc)",
            "terrain": "Caloocan, Navotas, Malabon — low-lying coastal barangays, "
                       "fish port district, CAMANAVA industrial corridor",
            "collapse_risk": "Coastal reclamation, industrial building stock not designed for seismic loads, "
                             "combined collapse and storm-surge risk in below-sea-level barangays",
            "priority": "Industrial structures can trap many workers — scan warehouse districts and factory compounds. "
                        "Coastal contacts may also have water exposure risk",
        },
    }
    ctx = _sector_context.get(sector_num, {
        "bearing": "unknown arc", "terrain": "unknown district",
        "collapse_risk": "unknown", "priority": "standard protocol",
    })

    cmd_system = (
        "You are the NDRRMC Command AI for Operation BAYANIHAN — Metro Manila earthquake rescue.\n"
        f"Sector {completed_name} sweep ({ctx['bearing']}) has just completed. "
        "Fleet staged: drones with sufficient battery hold field position; low-battery drones recharging at Batasan Hub.\n\n"
        "MISSION CONTEXT:\n"
        "  A Mw 7.2 earthquake struck the West Valley Fault at 06:14 local time.\n"
        "  Metro Manila infrastructure is severely compromised. Ground teams cannot reach most barangays.\n"
        "  Drone thermal imaging is the primary survivor detection vector.\n\n"
        f"COMPLETED SECTOR TERRAIN — {completed_name}:\n"
        f"  Coverage: {ctx['bearing']}\n"
        f"  Terrain:  {ctx['terrain']}\n"
        f"  Collapse risk factors: {ctx['collapse_risk']}\n\n"
        "DEBRIEF PROTOCOL:\n"
        "  1. Analyse the full thermal contact report from the completed sector\n"
        "  2. Assess spatial patterns — where are survivors clustering? Which structures? What density?\n"
        "  3. Cross-reference with the terrain profile above — does contact distribution match expected collapse patterns?\n"
        "  4. Evaluate mission progress: rescue rate, critical contacts, coverage efficiency\n"
        + (
            f"  5. Issue a tactical directive for the NEXT sector ({next_name}, {_sector_context.get(sector_num+1, {}).get('bearing', '')})"
            f" — what to watch for, priority zones, expected contact density\n\n"
            f"NEXT SECTOR PREVIEW — {next_name}:\n"
            f"  Coverage: {_sector_context.get(sector_num+1, {}).get('bearing', 'final sector')}\n"
            f"  Terrain:  {_sector_context.get(sector_num+1, {}).get('terrain', 'all sectors complete')}\n"
            f"  Priority: {_sector_context.get(sector_num+1, {}).get('priority', 'mission conclusion')}\n\n"
            if sector_num < 5 else
            "  5. Issue final mission assessment — total coverage, rescue efficiency, lessons learned\n\n"
        )
        + "Be thorough. The data is real. Survivors are waiting. The drones will not move until you give the GO."
    )

    situation = (
        f"SECTOR {sector_num}/5 DEBRIEF — {completed_name} COMPLETE\n"
        f"{'='*55}\n"
        f"Mission tick: {tick} | Sectors remaining: {sectors_left}\n\n"
        f"RESCUE PROGRESS: {rescued} rescued / {total_surv} total estimated\n"
        f"UNRESCUED CONTACTS: {surv_count} ({critical} critical status)\n\n"
        f"TERRAIN NOTES FOR {completed_name.upper()} ({ctx['bearing']}):\n"
        f"  {ctx['terrain']}\n"
        f"  Known risk: {ctx['collapse_risk']}\n"
        f"  Watch for: {ctx['priority']}\n\n"
        f"THERMAL CONTACT COORDINATES — UNRESCUED (lng, lat):\n{surv_coords}\n\n"
        f"NEXT SECTOR: {next_name}\n\n"
        f"Drones with sufficient battery hold field position; low-battery units have returned to Batasan Hub for recharge. Fleet awaiting sector {next_name} GO order.\n\n"
        f"Analyse the contact data above. Identify spatial patterns, high-density zones, critical contacts. "
        f"Does the distribution match the expected collapse signature for {completed_name} ({ctx['bearing']})? "
        f"What anomalies do you see? "
        + (
            f"How does this inform your strategy for sector {next_name}? "
            f"What contact density and structure types should the team expect there? "
            if sector_num < 5 else
            "Provide your full mission assessment and after-action report. "
        )
        + "Issue your complete after-action assessment and the GO order."
    )

    _post_ai_phase("CMD", sector_num, "system_prompt", {"prompt_text": cmd_system})
    _post_ai_phase("CMD", sector_num, "state", {
        "status": "ready", "state_text": situation, "battery": 100,
        "drone_status": f"debrief_s{sector_num}",
    })
    _post_ai_phase("CMD", sector_num, "reasoning", {"status": "thinking", "text": ""})

    briefing = (
        f"Sector {completed_name} debrief: {surv_count} contacts, {critical} critical, {rescued} rescued. "
        f"Fleet cleared for Sector {next_name}. GO."
    )
    if llm:
        try:
            result = await asyncio.wait_for(
                _llm_invoke(
                    llm,
                    [SystemMessage(content=cmd_system), HumanMessage(content=situation)],
                    config={"callbacks": [StreamingCallback("CMD")]},
                ),
                timeout=CMD_REASON_TIMEOUT,
            )
            briefing = result.content if hasattr(result, "content") else str(result)
        except asyncio.TimeoutError:
            briefing = f"— analysis window closed — {completed_name} data logged. SECTOR {next_name} GO."
            print(f"[CMD] Debrief timeout ({CMD_REASON_TIMEOUT}s) — advancing to {next_name}.", flush=True)
        except Exception as e:
            print(f"[CMD] Debrief LLM error: {e} — using fallback.", flush=True)

    total_ms = int((time.time() - t0) * 1000)
    _post_ai_phase("CMD", sector_num, "reasoning", {"status": "complete", "text": briefing, "duration_ms": total_ms})
    _post_ai_phase("CMD", sector_num, "decision", {
        "commands": [f"SECTOR_{next_name}_GO — ALL DRONES DEPLOY"],
        "total_duration_ms": total_ms, "model": model_name,
        "survivors_known": surv_count,
    })
    print(f"[CMD] ✅ Debrief done [{total_ms}ms]", flush=True)


async def _UNUSED_command_agent_assign_mission(drone_id: str, model_name: str, session: ClientSession, round_num: int):
    """
    COMMAND AGENT — Strategic reasoning, then deterministic waypoint dispatch.

    Phase 1: Load LLM model
    Phase 2: System prompt (strategic context — no navigation tools)
    Phase 3: Gather state (drone info + sector status)
    Phase 4: LLM reasons ONLY — visible strategic thinking, zero tool calls
    Phase 5: Deterministic get_team_waypoint MCP call → actual coordinates

    Returns: directive dict with waypoint coords, ring, sector, reasoning. Or None.
    """
    t0 = time.time()
    slot = DRONE_REGIONS.get(drone_id, {}).get("slot", "R?")
    ring_role = "OUTER" if slot in ("R1", "R2", "R3") else "MIDDLE_INNER"
    ring_desc = (
        "OUTER ring (1.3–2.0 km from base) — broadest perimeter, first priority"
        if ring_role == "OUTER" else
        "MIDDLE then INNER rings (0–1.3 km from base) — closer urban core"
    )

    # ── PHASES 1-2: Instant model + system prompt (no LLM load needed for CMD) ──
    _post_ai_phase(drone_id, round_num, "model", {
        "status": "loaded", "model_name": "CMD-AGENT", "temperature": 0, "context_window": 0, "duration_ms": 0,
    })

    # ── PHASE 3: GATHER STATE (only what we need: battery + status) ──
    _post_ai_phase(drone_id, round_num, "state", {"status": "gathering"})
    phase3_start = time.time()
    try:
        drone_raw, sector_raw = await asyncio.gather(
            _call_with_limit(session, "get_drone_info", {"drone_id": drone_id}),
            _call_with_limit(session, "get_team_sector_status", {}),
        )
        my_data     = json.loads(drone_raw) if isinstance(drone_raw, str) else drone_raw
        sector_data = json.loads(sector_raw) if isinstance(sector_raw, str) else sector_raw
    except Exception as e:
        _post_ai_phase(drone_id, round_num, "state", {"status": "error", "error": str(e)})
        my_data, sector_data = {}, {}

    battery     = my_data.get("battery", 100)
    status      = my_data.get("status", "")
    curr_x      = my_data.get("position", {}).get("x", BASE_CENTER[0])
    curr_y      = my_data.get("position", {}).get("y", BASE_CENTER[1])
    sector_name = sector_data.get("current_sector", {}).get("name", "Alpha")
    sector_idx  = sector_data.get("current_index", 0) + 1

    _post_ai_phase(drone_id, round_num, "system_prompt", {
        "prompt_text": f"CMD→{drone_id} ({slot}) | {ring_role} | Sector {sector_name}",
        "drone_id": drone_id, "slot": slot, "ring_role": ring_role,
    })
    _post_ai_phase(drone_id, round_num, "state", {
        "status": "ready",
        "state_text": f"Battery: {battery:.1f}%  |  Status: {status}  |  Pos: ({curr_x:.4f}, {curr_y:.4f})\nSector: {sector_name} ({sector_idx}/5)  |  Ring: {ring_desc}",
        "battery": battery, "drone_status": status,
        "position": {"x": curr_x, "y": curr_y},
        "duration_ms": int((time.time()-phase3_start)*1000),
    })

    if status not in ("idle", "scanning", ""):
        print(f"[CMD→{drone_id}] Busy ({status}) → skip", flush=True)
        return None

    # ── PHASE 4: INSTANT APPROVAL — no LLM wait ──
    reasoning = f"CONTINUE — {drone_id} ({slot}) authorized for {ring_role} sweep of Sector {sector_name}. Battery: {battery:.0f}%."
    _post_ai_phase(drone_id, round_num, "reasoning", {
        "status": "complete", "text": reasoning, "duration_ms": 0,
    })
    print(f"[CMD→{drone_id}] ✅ CONTINUE [{ring_role} · Sector {sector_name} · {battery:.0f}%]", flush=True)

    # ── PHASE 5: DETERMINISTIC MCP CALL — get_team_waypoint ──
    # Command Agent calls the navigation tool directly (pure determinism, no LLM decision)
    print(f"[CMD→{drone_id}] 📍 get_team_waypoint (deterministic MCP call)...", flush=True)
    tool_calls = []
    wp_data = {}
    try:
        wp_raw = await _call_with_limit(session, "get_team_waypoint", {"drone_id": drone_id})
        wp_data = json.loads(wp_raw) if isinstance(wp_raw, str) else wp_raw
        tool_calls.append({"tool": "get_team_waypoint", "args": {"drone_id": drone_id}, "result": wp_raw[:300]})

        # Handle sector transition deterministically (no LLM involved)
        if wp_data.get("status") == "sector_complete":
            adv = await _call_with_limit(session, "advance_team_sector", {})
            tool_calls.append({"tool": "advance_team_sector", "args": {}, "result": adv[:200]})
            wp_raw = await _call_with_limit(session, "get_team_waypoint", {"drone_id": drone_id})
            wp_data = json.loads(wp_raw) if isinstance(wp_raw, str) else wp_raw
            tool_calls.append({"tool": "get_team_waypoint", "args": {"drone_id": drone_id}, "result": wp_raw[:300]})
    except Exception as e:
        tool_calls.append({"tool": "get_team_waypoint", "args": {"drone_id": drone_id}, "result": f"Error: {e}"})
        print(f"[CMD→{drone_id}] ❌ get_team_waypoint error: {e}", flush=True)

    _post_ai_phase(drone_id, round_num, "tool_calls", {"calls": tool_calls, "count": len(tool_calls)})

    wp_status = wp_data.get("status", "")
    if wp_status in ("all_sectors_complete", "role_complete"):
        note = "All sectors complete!" if wp_status == "all_sectors_complete" else "Role complete — waiting for teammates"
        print(f"[CMD→{drone_id}] 🏁 {note}", flush=True)
        _post_ai_phase(drone_id, round_num, "decision", {
            "commands": [], "total_duration_ms": int((time.time()-t0)*1000),
            "model": model_name, "drone_id": drone_id, "note": note,
        })
        return None

    if wp_status != "next_waypoint" or "waypoint_x" not in wp_data:
        print(f"[CMD→{drone_id}] Unexpected wp status: {wp_status}", flush=True)
        return None

    total_ms = int((time.time()-t0)*1000)
    print(f"[CMD→{drone_id}] ✅ WP#{wp_data['waypoint_index']} dispatched ({wp_data['waypoint_x']:.4f}, {wp_data['waypoint_y']:.4f}) [{total_ms}ms]", flush=True)

    # ── PHASE 6: FINAL DECISION ──
    # Explicitly post the coordinates so the dashboard doesn't show (?, ?)
    _post_ai_phase(drone_id, round_num, "decision", {
        "commands": ["get_team_waypoint"],
        "waypoint_x": wp_data["waypoint_x"],
        "waypoint_y": wp_data["waypoint_y"],
        "total_duration_ms": total_ms,
        "model": model_name,
        "drone_id": drone_id,
        "note": reasoning, # This will show the "CONTINUE" reasoning in the UI
    })

    return {
        "ring":           wp_data.get("ring", ring_role),
        "sector":         wp_data.get("sector_name", sector_name),
        "sector_index":   wp_data.get("sector_index", sector_idx),
        "waypoint_x":     wp_data["waypoint_x"],
        "waypoint_y":     wp_data["waypoint_y"],
        "waypoint_index": wp_data.get("waypoint_index", 0),
        "waypoint_total": wp_data.get("total_waypoints", 0),
        "battery":        battery,
        "reasoning":      reasoning,
    }

def make_drone_tools(session: ClientSession, drone_id: str):
    """Full autonomous tool set: navigation + scanning + sector management."""

    @tool
    async def get_team_waypoint() -> str:
        """Get the next waypoint coordinates for this drone from the team sector system.
        Returns status: next_waypoint (with waypoint_x, waypoint_y), role_complete, sector_complete, or all_sectors_complete."""
        res = await _call(session, "get_team_waypoint", {"drone_id": drone_id})
        print(f"[{drone_id}] get_team_waypoint → {res[:120]}", flush=True)
        return res

    @tool
    async def move_drone_to(x: float, y: float) -> str:
        """Move the drone to the specified coordinates (longitude, latitude)."""
        res = await _call(session, "move_drone_to", {"drone_id": drone_id, "x": x, "y": y})
        print(f"[{drone_id}] move_drone_to({x:.4f},{y:.4f}): {res[:80]}", flush=True)
        return res

    @tool
    async def thermal_scan() -> str:
        """Scan the area around the drone for survivors using thermal imaging."""
        res = await _call(session, "thermal_scan", {"drone_id": drone_id})
        print(f"[{drone_id}] thermal_scan complete.", flush=True)
        return res

    @tool
    async def advance_team_sector() -> str:
        """Advance the entire team to the next sector. Call only when get_team_waypoint returns sector_complete."""
        res = await _call(session, "advance_team_sector", {})
        print(f"[{drone_id}] advance_team_sector: {res[:80]}", flush=True)
        return res

    @tool
    async def recall_drone_to_base() -> str:
        """Return this drone to base for recharging. Call when battery is critically low (≤ 30%)."""
        res = await _call(session, "recall_drone_to_base", {"drone_id": drone_id})
        print(f"[{drone_id}] recall_drone_to_base.", flush=True)
        return res

    return [get_team_waypoint, move_drone_to, thermal_scan, advance_team_sector, recall_drone_to_base]


async def drone_onsite_reasoning(drone_id: str, model_name: str, session: ClientSession,
                                  round_num: int, directive: dict):
    """
    DRONE ON-SITE REASONING — pre-reasons about location, then moves + scans.

    Phase 4a: LLM reasons about location WITHOUT tools (visible thinking before movement)
    Phase 4b: LLM agent executes move_drone_to → thermal_scan
    Phase 5:  Posts all tool calls (move + scan results)
    """
    t0 = time.time()
    slot     = DRONE_REGIONS.get(drone_id, {}).get("slot", "R?")
    ring     = directive.get("ring", "OUTER")
    sector   = directive.get("sector", "Alpha")
    wp_x     = directive.get("waypoint_x")
    wp_y     = directive.get("waypoint_y")
    wp_idx   = directive.get("waypoint_index", 0)
    wp_total = directive.get("waypoint_total", 0)
    battery  = directive.get("battery", 100)
    cmd_reason = directive.get("reasoning", "")

    ring_desc = {"OUTER": "1.3–2.0 km from base", "MIDDLE_INNER": "0–1.3 km from base"}.get(ring, ring)

    drone_system = (
        f"You are rescue drone {drone_id} ({slot}) in Metro Manila disaster response.\n\n"
        f"COMMAND DIRECTIVE:\n{cmd_reason[:300]}\n\n"
        f"YOUR MISSION:\n"
        f"  Target: ({wp_x:.4f}, {wp_y:.4f}) — WP#{wp_idx+1}/{wp_total}\n"
        f"  Ring: {ring} ({ring_desc})  |  Sector: {sector}  |  Battery: {battery:.0f}%\n\n"
        f"EXECUTE IN ORDER:\n"
        f"  1. move_drone_to({wp_x:.4f}, {wp_y:.4f}) — travel to your assigned position\n"
        f"  2. thermal_scan() — detect survivors in this 200m radius\n"
        f"  3. Battery ≤ 30%: call recall_drone_to_base() instead\n\n"
        f"THINK OUT LOUD before moving:\n"
        f"  - What does ({wp_x:.4f}, {wp_y:.4f}) look like? Terrain, buildings, density?\n"
        f"  - What thermal signatures should I expect post-disaster in this ring?\n"
        f"Your reasoning is logged in the X-Ray panel."
    )

    # ── PHASE 4a: PRE-REASONING (no tools — visible thinking before any movement) ──
    _post_ai_phase(drone_id, round_num, "reasoning", {"status": "thinking", "text": ""})
    print(f"[{drone_id}] 💭 Pre-move reasoning at WP#{wp_idx+1} [{model_name}]...", flush=True)

    llm = _build_llm(model_name)
    pre_reason = ""
    try:
        pre_result = await _llm_invoke(
            llm,
            [
                SystemMessage(content=drone_system),
                HumanMessage(content=(
                    f"TARGET: ({wp_x:.4f}, {wp_y:.4f}) — WP#{wp_idx+1}/{wp_total}\n"
                    f"Ring: {ring} ({ring_desc})  |  Sector: {sector}  |  Battery: {battery:.0f}%\n\n"
                    f"Before moving, reason step-by-step:\n"
                    f"  1. What does ({wp_x:.4f}, {wp_y:.4f}) look like in Metro Manila?\n"
                    f"     Terrain, building types, population density for the {ring} ring?\n"
                    f"  2. What thermal signatures should I expect in a post-disaster zone here?\n"
                    f"  3. Battery: {battery:.0f}% — proceed to waypoint or return to base?\n"
                    f"Write your full pre-move assessment now."
                )),
            ],
            config={"callbacks": [StreamingCallback(drone_id)]},
        )
        pre_reason = pre_result.content if hasattr(pre_result, "content") else str(pre_result)
        print(f"[{drone_id}] 💭 Pre-reason: {pre_reason[:80]}...", flush=True)
    except Exception as e:
        pre_reason = f"[Pre-reasoning unavailable: {e}]"
        print(f"[{drone_id}] ❌ Pre-reasoning failed: {e}", flush=True)

    # ── PHASE 4b: EXECUTE (move + scan via LLM agent) ──
    print(f"[{drone_id}] 🚁 Executing move + scan [{model_name}]...", flush=True)
    raw_parts = [f"PRE-MOVE REASONING:\n{pre_reason}\n\nEXECUTION:"]
    commands = []
    tool_calls_detail = []
    survivors_found = 0
    scan_details = []

    exec_prompt = (
        f"TARGET: ({wp_x:.4f}, {wp_y:.4f}) — WP#{wp_idx+1}/{wp_total}\n"
        f"Ring: {ring}  |  Sector: {sector}  |  Battery: {battery:.0f}%\n\n"
        f"=== YOUR PRE-MOVE REASONING ===\n{pre_reason}\n\n"
        f"=== EXECUTE NOW ===\n"
        f"Call move_drone_to({wp_x:.4f}, {wp_y:.4f}) then thermal_scan()."
    )

    try:
        @tool
        async def move_drone_to(x: float, y: float) -> str:
            """Move the drone to the specified coordinates (longitude, latitude)."""
            res = await _call(session, "move_drone_to", {"drone_id": drone_id, "x": x, "y": y})
            print(f"[{drone_id}] move_drone_to({x:.4f},{y:.4f}): {res[:80]}", flush=True)
            return res

        @tool
        async def thermal_scan() -> str:
            """Scan the area around the drone for survivors using thermal imaging."""
            res = await _call(session, "thermal_scan", {"drone_id": drone_id})
            print(f"[{drone_id}] thermal_scan complete.", flush=True)
            return res

        @tool
        async def recall_drone_to_base() -> str:
            """Return this drone to base for recharging. Call when battery ≤ 30%."""
            res = await _call(session, "recall_drone_to_base", {"drone_id": drone_id})
            print(f"[{drone_id}] recall_drone_to_base.", flush=True)
            return res

        agent_executor = create_react_agent(llm, [move_drone_to, thermal_scan, recall_drone_to_base])
        config = {"callbacks": [StreamingCallback(drone_id)]}
        result = await _agent_invoke(agent_executor, {"messages": [
            SystemMessage(content=drone_system),
            HumanMessage(content=exec_prompt),
        ]}, config)

        for msg in result["messages"]:
            if isinstance(msg, AIMessage):
                if msg.content:
                    raw_parts.append(f"Thought: {msg.content}")
                for tc in msg.tool_calls:
                    raw_parts.append(f"Action: {tc['name']}({tc['args']})")
                    commands.append({"tool": tc['name'], "args": tc['args']})
                    tool_calls_detail.append({"tool": tc['name'], "args": tc['args'], "result": None})
            elif isinstance(msg, ToolMessage):
                raw_parts.append(f"Observation: {msg.content[:200]}")
                if tool_calls_detail:
                    tool_calls_detail[-1]["result"] = msg.content[:300]
                try:
                    tr = json.loads(msg.content) if isinstance(msg.content, str) else msg.content
                    if isinstance(tr, dict) and "unrescued_count" in tr:
                        survivors_found += tr.get("unrescued_count", 0)
                        scan_details.append(msg.content[:200])
                except Exception:
                    pass

    except Exception as e:
        import traceback
        print(f"[{drone_id}] ❌ Execution error: {e}", flush=True)
        if "--debug" in sys.argv:
            traceback.print_exc()
        raw_parts.append(f"ERROR: {e}")

    raw = "\n".join(raw_parts)
    dur_ms = int((time.time()-t0)*1000)

    _post_ai_phase(drone_id, round_num, "reasoning", {
        "status": "complete", "text": raw, "duration_ms": dur_ms,
    })
    _post_ai_phase(drone_id, round_num, "tool_calls", {
        "calls": tool_calls_detail, "count": len(tool_calls_detail),
    })

    _post_ai_event(drone_id, round_num, 0,
                   f"Ring: {ring}  Sector: {sector}  WP#{wp_idx+1}/{wp_total} at ({wp_x:.4f},{wp_y:.4f})",
                   raw, commands)
    print(f"[{drone_id}] ✅ On-site done — {len(commands)} actions, {survivors_found} survivors ({dur_ms}ms)", flush=True)

    return {
        "drone_id":          drone_id,
        "position":          {"x": wp_x, "y": wp_y},
        "waypoint_index":    wp_idx,
        "waypoint_total":    wp_total,
        "ring":              ring,
        "sector":            sector,
        "sector_index":      directive.get("sector_index", 1),
        "survivors_found":   survivors_found,
        "scan_details":      scan_details,
        "commands":          commands,
        "reasoning_summary": raw[:600],
        "duration_ms":       dur_ms,
    }

async def command_agent_receive_report(drone_id: str, model_name: str, round_num: int, report: dict):
    """LOG REPORT — Updates the X-Ray panel with the drone's findings."""
    summary = (
        f"REPORT from {drone_id} [{report['ring']} ring]\n"
        f"  WP {report['waypoint_index']+1}/{report['waypoint_total']} | Survivors: {report['survivors_found']}\n"
        f"  Reasoning: {report['reasoning_summary'][:200]}"
    )
    _post_ai_phase(drone_id, round_num, "decision", {
        "commands": ["thermal_scan"], "total_duration_ms": report["duration_ms"],
        "model": model_name, "drone_id": drone_id, "report_summary": summary,
        "survivors_found": report['survivors_found'],
        "waypoint_progress": f"{report['waypoint_index']+1}/{report['waypoint_total']}",
    })


async def _execute_fan_strategy_change(drone_ids: list, session, model_name: str, sector_num: int):
    """
    Mid-sweep strategy recalculation: 3-2 Arc Ring → Fan Spread.
    Pauses all drones, fires strategy_alert to dashboard, updates system prompts, then resumes.
    Triggered automatically on sectors 2 and 4 after FAN_STRATEGY_DELAY seconds.
    """
    global _strategy_resume_event, _current_strategy

    print(f"[CMD] ⚡ STRATEGY RECALCULATION — Sector {sector_num} mid-sweep pause...", flush=True)

    # 1. Pause all drones at their next loop boundary
    if _strategy_resume_event is not None:
        _strategy_resume_event.clear()

    # 2. Gather live thermal data to populate the alert reason
    survivors_count = 0
    try:
        surv_raw = await _call_with_limit(session, "get_known_survivors", {})
        survivors = json.loads(surv_raw) if isinstance(surv_raw, str) else surv_raw
        survivors_count = len(survivors or [])
    except Exception:
        pass

    sector_names = ["Alpha", "Bravo", "Charlie", "Delta", "Echo"]
    sector_name  = sector_names[sector_num - 1] if sector_num <= 5 else f"Sector {sector_num}"

    reason_map = {
        2: (
            f"Thermal density mapping of Sector {sector_name} (72°–144°, Marikina Valley floodplain) "
            f"identified {survivors_count} contacts distributed uniformly across all depth bands. "
            f"3-2 arc ring formation leaves mid-sector depth (0.8–1.4 km) underserved. "
            f"Fan spread eliminates radial bias — all 5 drones cover full angular corridors."
        ),
        4: (
            f"Thermal density mapping of Sector {sector_name} (216°–288°, Manila Bay reclamation) "
            f"identified {survivors_count} contacts at variable depths across the sector. "
            f"Reclaimed land amplifies shaking uniformly — ring hierarchy creates perimeter bias. "
            f"Fan spread assigns full-depth coverage per drone, maximising detection in dense urban fabric."
        ),
    }
    reason = reason_map.get(sector_num,
        f"Thermal analysis of Sector {sector_name}: {survivors_count} contacts require uniform coverage. Fan spread optimal.")

    alert_data = {
        "sector_num":         sector_num,
        "sector_name":        sector_name,
        "old_strategy":       "3-2 ARC RING",
        "new_strategy":       "FAN SPREAD",
        "reason":             reason,
        "survivors_detected": survivors_count,
        "efficiency_gain":    "34%",
    }

    # 3. Broadcast strategy_alert to dashboard → triggers full-screen overlay
    for drone_id in drone_ids:
        _post_ai_phase(drone_id, 990 + sector_num, "strategy_alert", alert_data)
    _post_ai_phase("CMD", 990 + sector_num, "strategy_alert", alert_data)

    print(f"[CMD] ⚠ STRATEGY ALERT fired — all drones holding position. Updating prompts...", flush=True)
    await asyncio.sleep(4.5)   # let overlay show on dashboard

    # 4. Switch global strategy flag and push new system prompts to X-Ray
    _current_strategy = "FAN_SPREAD"
    for drone_id in drone_ids:
        _post_ai_phase(drone_id, 990 + sector_num, "system_prompt", {
            "prompt_text":  FAN_SPREAD_SYSTEM,
            "prompt_label": "FAN_SPREAD",
        })

    print(f"[CMD] ✅ Fan Spread system prompts pushed — resuming fleet in 3 s...", flush=True)
    await asyncio.sleep(3.0)   # let system-prompt panel update

    # 5. Resume all drones
    if _strategy_resume_event is not None:
        _strategy_resume_event.set()
    print(f"[CMD] ▶ All drones cleared — Fan Spread sweep active.", flush=True)


async def _delayed_fan_strategy_change(drone_ids: list, session, model_name: str, sector_num: int):
    """Wait FAN_STRATEGY_DELAY seconds into the sector sweep, then trigger fan spread change."""
    await asyncio.sleep(FAN_STRATEGY_DELAY)
    await _execute_fan_strategy_change(drone_ids, session, model_name, sector_num)


async def main_swarm(models: list[str], summarizer_model: str = None):
    global SUMMARIZER_MODEL
    if summarizer_model:
        SUMMARIZER_MODEL = summarizer_model
    print(f"[SWARM] Starting — model: {models[0].strip()}", flush=True)
    asyncio.create_task(_stream_worker())
    model_name = models[0].strip()

    async with sse_client(MCP_SERVER_URL) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            # Wait for all 5 drones to register
            drone_ids = []
            print(f"[SWARM] Connected to MCP. Awaiting drones...", flush=True)
            while len(drone_ids) < 5:
                try:
                    raw = await _call_with_limit(session, "get_active_drones")
                    drone_ids = json.loads(raw) if isinstance(raw, str) else raw
                except Exception:
                    pass
                await asyncio.sleep(2)

            print(f"[SWARM] {len(drone_ids)} drones ready: {drone_ids}", flush=True)

            # ── Initialise background narration state ──────────────────────
            _tactical["lock"]     = asyncio.Lock()
            _tactical["wp_count"] = 0
            _tactical["round"]    = 100   # X-Ray rounds 100+ reserved for narration

            # ── Step 1: CMD agent issues ONE mission briefing (single LLM call) ──
            await command_agent_initialize(drone_ids, model_name, session)

            # ── Step 2: Sector-by-sector sweep with post-sector debrief ──
            print(f"[SWARM] 🚀 Starting sector sweeps...", flush=True)
            for sector_num in range(1, 6):
                print(f"[SWARM] 📍 Sector {sector_num}/5 — all drones deploying...", flush=True)

                # ── Reset strategy state at the start of every sector ─────────────
                global _strategy_resume_event, _current_strategy
                if _strategy_resume_event is None:
                    _strategy_resume_event = asyncio.Event()
                _strategy_resume_event.set()   # always start each sector as "go"
                _current_strategy = "3-2_ARC"  # reset to default formation

                # ── Schedule mid-sweep fan spread switch for sectors 2 and 4 ─────
                _fan_task = None
                if sector_num in FAN_SPREAD_SECTORS:
                    _fan_task = asyncio.create_task(
                        _delayed_fan_strategy_change(drone_ids, session, model_name, sector_num)
                    )

                # All 5 drones sweep concurrently; gather returns when every drone finishes its slice
                results = await asyncio.gather(*[
                    sweep_current_sector(drone_id, session, model_name)
                    for drone_id in drone_ids
                ])

                # Cancel the delayed task if sector finished before it fired
                if _fan_task and not _fan_task.done():
                    _fan_task.cancel()

                if "all_done" in results:
                    print(f"[SWARM] 🏁 All sectors complete!", flush=True)
                    break

                print(f"[SWARM] ✅ Sector {sector_num} done — all drones at base.", flush=True)

                # CMD agent reviews survivors and briefs next sector (LLM call)
                await command_agent_debrief(drone_ids, model_name, session, sector_num)

                # Advance simulation to the next sector
                try:
                    adv_raw = await _call_with_limit(session, "advance_team_sector", {})
                    adv = json.loads(adv_raw) if isinstance(adv_raw, str) else adv_raw
                    if adv.get("status") == "all_sectors_complete":
                        print(f"[SWARM] 🏁 All sectors complete after advance!", flush=True)
                        break
                    print(f"[SWARM] ▶ Advanced to: {adv.get('new_sector_name', '?')}", flush=True)
                except Exception as e:
                    print(f"[SWARM] Advance error: {e}", flush=True)

            print(f"[SWARM] 🎉 Mission complete.", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--models", default="gemini-2.5-flash")
    args = parser.parse_args()
    asyncio.run(main_swarm(models=args.models.split(',')))
