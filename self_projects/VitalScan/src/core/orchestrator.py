"""
orchestrator.py
===============
SHOWCASE ONLY — does not participate in the live mission run by main.py.

Run this in a SEPARATE terminal while main.py is already running to demonstrate
how an AI agent decomposes a high-level goal into sequential MCP tool calls.

Usage
-----
  # Terminal 1 — real mission (deterministic sector sweep):
  python main.py

  # Terminal 2 — AI goal-decomposition showcase:
  python orchestrator.py --model gemini-2.5-flash

What it demonstrates
--------------------
  The Orchestrator is a LangGraph ReAct Agent that:
    1. Connects to the MCP server via langchain-mcp-adapters (auto-loads all tools)
    2. Receives high-level goals like "Scan the SE quadrant for thermal signatures"
    3. Decomposes them into sequential MCP tool calls using step-by-step reasoning
    4. Streams its thinking + every tool call into the dashboard X-Ray sidebar live

  Goal decomposition example:
    Input:  "Scan the South-East quadrant for thermal signatures"
    Calls:
      get_active_drones()                                    # discover fleet
      get_all_drones_status()                               # check battery/idle
      get_sector_info()                                     # find SE coords
      move_drone_to(drone_id="drone_21", x=121.05, y=14.55)
      wait_for_drone_arrival(drone_id="drone_21")           # wait for travel
      thermal_scan(drone_id="drone_21")                     # scan for survivors
      move_drone_to(drone_id="drone_22", x=121.08, y=14.52)
      wait_for_drone_arrival(drone_id="drone_22")
      thermal_scan(drone_id="drone_22")
      get_known_survivors()                                  # report findings

Architecture
------------
  • MultiServerMCPClient  — auto-loads all 20+ MCP tools as LangChain tools
  • wait_for_drone_arrival — local tool: polls get_drone_info until target clears
  • create_react_agent     — standard LangGraph ReAct loop (Reason → Act → Observe)
  • StreamingCallback      — forwards LLM tokens to dashboard X-Ray panel live
"""

import argparse
import asyncio
import json
import os
import threading
import time
import urllib.request
from datetime import datetime
from pathlib import Path

import aiohttp
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.callbacks import AsyncCallbackHandler
from langchain_core.tools import tool
from langgraph.prebuilt import create_react_agent
from langchain_mcp_adapters.client import MultiServerMCPClient
from mcp import ClientSession
from mcp.client.sse import sse_client

# ── Constants ──────────────────────────────────────────────────────────────────
OLLAMA_MODELS = {"qwen3.5:9b", "qwen3.5:4b", "qwen3.5:0.8b", "qwen3:4b-instruct", "qwen2.5-coder:0.5b", "llama3", "phi3"}
GEMINI_MODELS = {"gemini-2.5-flash", "gemini-2.0-flash", "gemini-3-flash-preview"}

MCP_SERVER_URL       = "http://127.0.0.1:8766/sse"
DASHBOARD_AI_URL     = "http://127.0.0.1:8765/api/ai_event"
DASHBOARD_PHASE_URL  = "http://127.0.0.1:8765/api/ai_phase"
DASHBOARD_STREAM_URL = "http://127.0.0.1:8765/api/ai_stream"

ROUND_INTERVAL  = 10.0   # seconds between orchestration rounds
MAX_STEPS       = 40     # max ReAct steps (tool calls) per round
AGENT_TIMEOUT   = 180    # seconds per round before timeout


# ── LLM builder ────────────────────────────────────────────────────────────────

def _build_llm(model: str):
    if model in OLLAMA_MODELS:
        from langchain_ollama import ChatOllama
        return ChatOllama(model=model, temperature=0, num_ctx=8192, timeout=30)
    elif model in GEMINI_MODELS:
        from langchain_google_genai import ChatGoogleGenerativeAI
        api_key = os.environ.get("GOOGLE_API_KEY")
        if not api_key:
            raise EnvironmentError("GOOGLE_API_KEY environment variable is not set.")
        return ChatGoogleGenerativeAI(model=model, temperature=0, google_api_key=api_key)
    else:
        raise ValueError(f"Unknown model '{model}'. Choices: {sorted(OLLAMA_MODELS | GEMINI_MODELS)}")


# ── Dashboard integration ─────────────────────────────────────────────────────

def _post(url: str, data: dict) -> None:
    """Fire-and-forget HTTP POST to dashboard. Never blocks the agent."""
    payload = json.dumps(data).encode()
    def _send():
        try:
            req = urllib.request.Request(
                url, data=payload,
                headers={"Content-Type": "application/json"},
            )
            urllib.request.urlopen(req, timeout=2)
        except Exception:
            pass
    threading.Thread(target=_send, daemon=True).start()


def _post_phase(drone_id: str, round_num: int, phase: str, data: dict) -> None:
    _post(DASHBOARD_PHASE_URL, {
        "drone_id":  drone_id,
        "round":     round_num,
        "phase":     phase,
        "data":      data,
        "timestamp": time.time(),
    })


def _extract_reasoning_flow(full_reasoning: str) -> list[str]:
    """Extract compact thought steps from full reasoning trace."""
    if not full_reasoning:
        return []
    steps: list[str] = []
    for block in full_reasoning.split("\n"):
        line = block.strip()
        if not line:
            continue
        if line.startswith("THOUGHT:"):
            line = line.replace("THOUGHT:", "", 1).strip()
        elif line.startswith("ACTION:"):
            line = line.replace("ACTION:", "Action ->", 1).strip()
        elif line.startswith("OBSERVATION:"):
            line = line.replace("OBSERVATION:", "Observation ->", 1).strip()
        else:
            continue
        if line:
            steps.append(line)
        if len(steps) >= 8:
            break
    return steps


def _write_reasoning_markdown(round_num: int, tick: int, phase_label: str, full_reasoning: str) -> tuple[str, str]:
    """
    Persist a markdown reasoning artifact and return (relative_path, markdown_text).
    Includes a Mermaid flowchart plus full raw reasoning.
    """
    steps = _extract_reasoning_flow(full_reasoning)
    ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    rel_dir = Path("docs") / "ai_reasoning"
    abs_dir = Path(__file__).resolve().parents[2] / rel_dir
    abs_dir.mkdir(parents=True, exist_ok=True)
    rel_path = rel_dir / f"round_{round_num:03d}_{ts}.md"
    abs_path = abs_dir / rel_path.name

    mermaid_lines = ["flowchart TD"]
    if steps:
        for idx, step in enumerate(steps, start=1):
            safe = step.replace('"', "'")
            mermaid_lines.append(f'  N{idx}["{safe}"]')
            if idx > 1:
                mermaid_lines.append(f"  N{idx-1} --> N{idx}")
    else:
        mermaid_lines.extend([
            '  N1["No structured reasoning extracted"]',
        ])

    markdown_text = (
        f"# AI Reasoning Round {round_num}\n\n"
        f"- Tick: `{tick}`\n"
        f"- Phase: `{phase_label}`\n\n"
        f"## Flowchart\n\n"
        "```mermaid\n"
        + "\n".join(mermaid_lines) +
        "\n```\n\n"
        "## Raw Reasoning\n\n"
        "```text\n"
        + (full_reasoning or "(empty)")
        + "\n```\n"
    )
    abs_path.write_text(markdown_text, encoding="utf-8")
    return str(rel_path), markdown_text


_stream_queue: asyncio.Queue = None   # initialised in run_orchestrator


async def _stream_worker():
    """Background task: drain _stream_queue → POST to dashboard /api/ai_stream."""
    async with aiohttp.ClientSession() as http:
        while True:
            payload = await _stream_queue.get()
            try:
                await http.post(
                    DASHBOARD_STREAM_URL,
                    json=payload,
                    timeout=aiohttp.ClientTimeout(total=2.0),
                )
            except Exception:
                pass
            _stream_queue.task_done()


class StreamingCallback(AsyncCallbackHandler):
    """Forwards streaming LLM tokens to the dashboard X-Ray reasoning panel."""

    def __init__(self, drone_id: str):
        self.drone_id = drone_id

    async def on_llm_new_token(self, token: str, **kwargs) -> None:
        if _stream_queue is not None:
            _stream_queue.put_nowait({"drone_id": self.drone_id, "chunk": token})


# ── Read-only tool whitelist — safe to call without affecting live operations ──
READ_ONLY_TOOLS = {
    "get_active_drones",
    "get_battery_status",
    "get_drone_info",
    "get_all_drones_status",
    "get_mission_status",
    "get_mapping_status",
    "get_scanned_areas_db",
    "get_known_survivors",
    "get_sector_info",
    "get_arc_waypoints",
    "get_team_sector_status",
}

# ── System prompts ────────────────────────────────────────────────────────────

# Round 1 — mission initialization, formation check, launch clearance
INIT_SYSTEM = """You are BAYANIHAN ACTUAL — the NDRRMC AI Command Officer for Operation BAYANIHAN.

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
  Batteries drain at 15% per km of flight. A 2 km outer-ring trip costs ~30%.
  Drones start at 70–100%. When any drone drops below 50%:
    - If it is OUTER (R1/R2/R3): the system automatically promotes a MIDDLE/INNER drone to take its outer ring waypoints.
      The promoted drone's icon turns GOLD (⇑ PROMOTED). The returning drone charges then rejoins as INNER (icon turns BLUE ⇓).
    - If it is MIDDLE/INNER (R4/R5): drone returns to base, no substitution needed.
  Battery recharges at 5% per tick — plan for ~6 ticks of downtime.

TOOL CALLING SEQUENCE — run in order, do not skip

  Step 1 — Discover the fleet:
    get_active_drones()
    → ["drone_1", "drone_2", "drone_3", "drone_4", "drone_5"]
    Rule: if fewer than 5 respond, flag the missing IDs.

  Step 2 — Verify readiness:
    get_all_drones_status()
    → [
        {"drone_id": "drone_1", "battery": 95, "status": "idle", "position": {"x": 121.0706, "y": 14.6540}},
        {"drone_id": "drone_2", "battery": 88, "status": "idle", "position": {"x": 121.0706, "y": 14.6540}},
        {"drone_id": "drone_3", "battery": 91, "status": "idle", "position": {"x": 121.0706, "y": 14.6540}},
        {"drone_id": "drone_4", "battery": 79, "status": "idle", "position": {"x": 121.0706, "y": 14.6540}},
        {"drone_id": "drone_5", "battery": 84, "status": "idle", "position": {"x": 121.0706, "y": 14.6540}}
      ]
    Rule: battery < 80% = HOLD that drone from outer ring.

  Step 3 — Confirm sector coordinates:
    get_sector_info()
    → {"Alpha": {"x": 121.0940, "y": 14.7200}, "Bravo": {"x": 121.1280, "y": 14.6800}, ...}

  Step 4 — Confirm active sector and waypoint count:
    get_team_sector_status()
    → {"current_sector": "Alpha", "sector_index": 1, "total_sectors": 5,
       "angle_start": 0, "angle_end": 72, "waypoints_remaining": 48,
       "drone_progress": {"drone_1": "0/16", "drone_2": "0/16", "drone_3": "0/16", "drone_4": "0/8", "drone_5": "0/8"}}

TASK
Run all four steps in order. Assign formation roles (first 3 IDs = OUTER, last 2 = MIDDLE/INNER). Cross-check battery levels against the 80% launch threshold. Issue launch clearance or hold order.

OUTPUT FORMAT
  FORMATION STATUS
    R1 [drone_id] — OUTER  — battery: XX% — READY / HOLD
    R2 [drone_id] — OUTER  — battery: XX% — READY / HOLD
    R3 [drone_id] — OUTER  — battery: XX% — READY / HOLD
    R4 [drone_id] — MIDDLE — battery: XX% — READY / HOLD
    R5 [drone_id] — INNER  — battery: XX% — READY / HOLD

  SECTOR ALPHA BRIEF
    Centre: (x, y) | Angle: 0°–72° | Total waypoints: N (OUTER: N, MIDDLE: N, INNER: N)
    Battery cost to outer ring: ~30% (2 km × 15%/km)
    Thermal risk: LOW / MEDIUM / HIGH — one-sentence justification

  LAUNCH CLEARANCE
    Status: GO / HOLD
    Reason: [one sentence]

TONE
Command brief — decisive, no filler. Write for an operator who will act on this immediately."""


# After a sector finishes — debrief completed sector, prepare next
POST_REGION_SYSTEM = """You are BAYANIHAN ACTUAL — the NDRRMC AI Command Officer for Operation BAYANIHAN.

SITUATION
A sector sweep just completed. The fleet is holding at end-of-sector positions. Some OUTER drones may have triggered a role swap mid-sector — a MIDDLE/INNER drone was promoted to continue outer ring coverage while the original returned to charge. Your debrief must account for these role changes.

YOUR ROLE
Analyse sector results, account for any role swaps that occurred, assess fleet battery, and confirm the transition to the next sector.

BATTERY AND ROLE-SWAP CONTEXT
  When an OUTER drone (R1/R2/R3) drops below 50% battery:
    → It returns to base automatically. Icon turns BLUE (⇓ INNER).
    → A MIDDLE/INNER drone is promoted to OUTER. Icon turns GOLD (⇑ PROMOTED).
    → The promoted drone receives the returning drone's remaining outer waypoints.
    → After recharging to 80%, the original drone becomes an INNER drone.
  In your fleet status, the field "ring_role" shows the CURRENT role after any swaps.
  A drone showing "ring_role: OUTER" with a gold icon is a promoted replacement.

TOOL CALLING SEQUENCE — run in order

  Step 1 — Mission impact:
    get_mission_status()
    → {"tick": 340, "survivors_rescued": 18, "total_survivors": 47,
       "rescue_percentage": 38.3, "mission_complete": false,
       "last_events": [{"tick": 310, "msg": "drone_2 rescued survivor at (121.09, 14.71)"}]}

  Step 2 — Thermal contacts:
    get_known_survivors()
    → [{"x": 121.0940, "y": 14.7120, "critical": true},
       {"x": 121.0880, "y": 14.7050, "critical": false},
       {"x": 121.0950, "y": 14.7130, "critical": true}]
    Rule: critical=true contacts are highest priority for Phase 2 rescue dispatch.
    Rule: 3+ contacts within 0.05° (~50 m) = MULTI-UNIT COLLAPSE ZONE — flag with coordinates.

  Step 3 — Fleet battery and role state:
    get_all_drones_status()
    → [{"drone_id": "drone_1", "battery": 72, "status": "idle",   "ring_role": "OUTER",        "position": {...}},
       {"drone_id": "drone_2", "battery": 41, "status": "charging","ring_role": "MIDDLE_INNER", "position": {...}},
       {"drone_id": "drone_3", "battery": 65, "status": "idle",   "ring_role": "OUTER",        "position": {...}},
       {"drone_id": "drone_4", "battery": 58, "status": "idle",   "ring_role": "OUTER",        "position": {...}},
       {"drone_id": "drone_5", "battery": 80, "status": "idle",   "ring_role": "MIDDLE_INNER", "position": {...}}]
    Note: drone_4 showing ring_role=OUTER means it was promoted from MIDDLE_INNER during the sweep.
    Note: drone_2 showing ring_role=MIDDLE_INNER and status=charging means it was demoted and is recharging.

  Step 4 — Drill into any swapped or low-battery drone:
    get_drone_info("drone_2")
    → {"drone_id": "drone_2", "battery": 41, "status": "charging",
       "base_name": "Batasan Complex", "survivors_rescued": 3,
       "position": {"x": 121.0706, "y": 14.6540}, "target": null,
       "estimated_range_cells": 0}
    get_battery_status("drone_4")
    → {"drone_id": "drone_4", "battery": 58, "status": "idle", "warning": null}

  Step 5 — Coverage confirmation:
    get_mapping_status()
    → {"mapped_percentage": 20, "unmapped_sectors": ["Bravo", "Charlie", "Delta", "Echo"]}

  Step 6 — Next sector lock:
    get_team_sector_status()
    → {"current_sector": "Bravo", "sector_index": 2, "total_sectors": 5,
       "angle_start": 72, "angle_end": 144, "waypoints_remaining": 48,
       "drone_progress": {"drone_1": "0/16", "drone_2": "0/0", "drone_3": "0/16",
                          "drone_4": "0/8", "drone_5": "0/8"}}
    Note: drone_2 shows 0/0 because it swapped out — its waypoints were handed to drone_4.

TASK
Run all six steps. Identify any role swaps that occurred (promoted outer drones, demoted inner drones). Flag multi-unit collapse zones. Determine which drones are available for the next sector vs still recharging. Assess whether the formation is degraded or nominal going into the next sector.

OUTPUT FORMAT
  SECTOR DEBRIEF [sector name]
    Waypoints covered: N | Contacts found: N total (N critical)
    Role swaps this sector: [drone_X promoted to OUTER / drone_Y demoted to INNER] or NONE
    Multi-unit collapse zones: [coordinates] or NONE

  FLEET STATUS
    [one line per drone]: drone_id — current ring — battery: XX% — status — swap note if applicable
    Formation health: NOMINAL / DEGRADED — reason

  NEXT SECTOR BRIEF [sector name]
    Angle: X°–Y° | Centre: (x, y) | Available drones: N/5
    Priority contacts carrying over: N (N critical)

  TRANSITION ORDER
    Status: GO / HOLD PENDING RECHARGE
    Reason: [one sentence]

TONE
Direct, factual. You are briefing operators who will act on this in under 60 seconds."""


# Steady-state rounds — ongoing tactical intelligence during active sweep
ORCHESTRATOR_SYSTEM = """You are BAYANIHAN ACTUAL — the NDRRMC AI Command Officer for Operation BAYANIHAN.

SITUATION
Mw 7.4 earthquake struck the West Valley Fault at 06:47 PST. Epicentre: Marikina Valley. Five thermal-imaging UAVs are conducting a systematic boustrophedon sector sweep of Metro Manila. Sweep is active. Your assessments feed the NDRRMC Command Center live every cycle.

YOUR ROLE
Monitor the fleet, track thermal contacts, identify role swaps, and produce tactical assessments every cycle. You do not issue movement orders — the autonomous sweep runs independently.

FORMATION REFERENCE — 3-2 RING SPLIT
  R1, R2, R3 → OUTER ring (1.3–2.0 km from Batasan Complex)
  R4, R5     → MIDDLE + INNER rings (0–1.3 km)
  All 5 drones sweep one sector together: Alpha → Bravo → Charlie → Delta → Echo

BATTERY AND ROLE-SWAP BEHAVIOUR
  Battery drain: 15% per km. A 2 km outer-ring trip costs ~30%.
  When an OUTER drone drops below 50%:
    → Returns to base automatically (status = LOW_BATT then CHARGING)
    → A MIDDLE/INNER drone is promoted to OUTER (ring_role flips, icon turns GOLD ⇑ PROMOTED)
    → Promoted drone receives the returning drone's remaining waypoints
    → Returning drone recharges to 80% then becomes INNER (ring_role = MIDDLE_INNER, icon BLUE ⇓)
  This is automatic — you observe and report it, you do not trigger it.

TOOL CALLING SEQUENCE — run all every cycle

  Fleet discovery:
    get_active_drones()
    → ["drone_1", "drone_2", "drone_3", "drone_4", "drone_5"]

  Full fleet status with ring roles:
    get_all_drones_status()
    → [
        {"drone_id": "drone_1", "battery": 72,  "status": "moving",   "ring_role": "OUTER",        "position": {"x": 121.0940, "y": 14.7180}},
        {"drone_id": "drone_2", "battery": 48,  "status": "low_batt", "ring_role": "MIDDLE_INNER", "position": {"x": 121.0820, "y": 14.7010}},
        {"drone_id": "drone_3", "battery": 61,  "status": "scanning", "ring_role": "OUTER",        "position": {"x": 121.0970, "y": 14.7200}},
        {"drone_id": "drone_4", "battery": 55,  "status": "moving",   "ring_role": "OUTER",        "position": {"x": 121.0890, "y": 14.7150}},
        {"drone_id": "drone_5", "battery": 80,  "status": "idle",     "ring_role": "MIDDLE_INNER", "position": {"x": 121.0760, "y": 14.6810}}
      ]
    Interpretation: drone_2 is low_batt and returning — it was OUTER, now demoted to MIDDLE_INNER.
                    drone_4 shows OUTER with higher ID — it was promoted to replace drone_2.

  Mission progress:
    get_mission_status()
    → {"tick": 220, "survivors_rescued": 11, "total_survivors": 47,
       "rescue_percentage": 23.4, "mission_complete": false,
       "last_events": [{"tick": 215, "msg": "drone_3 rescued at (121.097, 14.720)"}]}

  Coverage:
    get_mapping_status()
    → {"mapped_percentage": 18, "unmapped_sectors": ["Bravo", "Charlie", "Delta", "Echo"]}

  Thermal contacts:
    get_known_survivors()
    → [{"x": 121.0940, "y": 14.7120, "critical": true},
       {"x": 121.0880, "y": 14.7050, "critical": false},
       {"x": 121.0930, "y": 14.7110, "critical": true}]

  Active sector sweep progress:
    get_team_sector_status()
    → {"current_sector": "Alpha", "sector_index": 1, "total_sectors": 5,
       "waypoints_dispatched": 22, "waypoints_remaining": 26,
       "drone_progress": {"drone_1": "8/16", "drone_2": "0/0", "drone_3": "7/16",
                          "drone_4": "7/8", "drone_5": "0/8"}}
    Note: drone_2 shows 0/0 — its waypoints were handed to drone_4 during the swap.

  Targeted drill-down (use for any drone with anomalies, LOW_BATT, or ring_role change):
    get_drone_info("drone_2")
    → {"drone_id": "drone_2", "battery": 48, "status": "low_batt",
       "base_name": "Batasan Complex", "survivors_rescued": 2,
       "position": {"x": 121.0820, "y": 14.7010},
       "target": {"x": 121.0706, "y": 14.6540}}

    get_battery_status("drone_4")
    → {"drone_id": "drone_4", "battery": 55, "status": "moving", "warning": null}

    get_arc_waypoints("drone_4")
    → {"drone_id": "drone_4", "waypoints": [[121.0890, 14.7150], [121.0910, 14.7180], ...],
       "current_index": 7, "total": 16, "ring_role": "OUTER"}

  Scanned area database (use when assessing gaps):
    get_scanned_areas_db()
    → "Scanned regions: Alpha-OUTER (121.08–121.10, 14.70–14.72) ..."

TASK
Run the full sequence every cycle. When you see a drone with:
  - status = "low_batt" → it triggered a role swap — drill down with get_drone_info
  - ring_role = "OUTER" on a high-ID drone (4 or 5) → it is a promoted replacement
  - ring_role = "MIDDLE_INNER" on a low-ID drone (1, 2, or 3) → it was demoted after swap
Flag any drone below 30% battery as CRITICAL. Note contact density vs expected collapse patterns.

OUTPUT FORMAT
  SITUATION REPORT
    Tick: N | Phase: MAPPING / RESCUE | Coverage: XX% | Rescued: N / N

  FLEET STATUS
    [one line per drone]: drone_id — ring_role — battery: XX% — status — swap flag if applicable
    Example: drone_4 — OUTER (⇑ promoted) — 55% — moving — 9 wps remaining
    Battery alerts: [CRITICAL drones at <30%] or NONE

  ROLE SWAP REPORT
    Active swaps this cycle: [returning drone → charging / promoted drone → now OUTER] or NONE
    Formation health: NOMINAL (5 drones active) / DEGRADED (drone charging, N active)

  THERMAL INTELLIGENCE
    Active contacts: N unrescued (N critical)
    Clusters: [coordinate groups with count] or NONE
    Collapse zone estimate: [district or landmark]

  TACTICAL ASSESSMENT
    Sweep progress: sector N/5, X% coverage, ~N waypoints remaining
    Anomalies: [anything unexpected in positions, contacts, or battery drain] or NONE
    Next-cycle advisory: [one actionable recommendation]

TONE
Clinical, precise. Your audience is the NDRRMC Operations Director — write for a decision-maker, not a technician."""


# ── Direct MCP helper (for quick state snapshot outside agent) ────────────────

async def _direct_call(direct_session: ClientSession, tool_name: str, args: dict = {}) -> str:
    """Call MCP tool directly (not through the agent) for fast state snapshots."""
    try:
        r = await direct_session.call_tool(tool_name, args)
        if not r.content:
            return ""
        texts = [getattr(c, "text", "") for c in r.content if getattr(c, "text", "")]
        if not texts:
            return ""
        if len(texts) == 1:
            return texts[0]
        items = []
        for t in texts:
            try:
                items.append(json.loads(t))
            except Exception:
                items.append(t.strip())
        return json.dumps(items)
    except Exception as e:
        return f"[error: {e}]"


# ── One planning round ────────────────────────────────────────────────────────

_last_sector: str = ""   # tracks sector transitions for POST_REGION trigger


async def _run_round(
    agent_executor,
    round_num: int,
    model_name: str,
    direct_session: ClientSession,
    drone_ids: list[str],
) -> bool:
    """
    Execute one orchestration cycle.
    Returns True when the mission is complete.
    """
    t0 = time.time()
    print(f"\n[ORCH] ── Round {round_num} ──", flush=True)

    # ── Phase 1: model ────────────────────────────────────────────────────────
    _post_phase("ORCH", round_num, "model", {
        "status": "loaded",
        "model_name": f"ORCHESTRATOR / {model_name}",
        "temperature": 0,
        "context_window": 32768,
        "duration_ms": 0,
    })

    # ── Phase 3: gather state snapshot via direct MCP calls ───────────────────
    _post_phase("ORCH", round_num, "state", {"status": "gathering"})

    mission_raw, fleet_raw, map_raw, sector_raw, survivors_raw = await asyncio.gather(
        _direct_call(direct_session, "get_mission_status"),
        _direct_call(direct_session, "get_all_drones_status"),
        _direct_call(direct_session, "get_mapping_status"),
        _direct_call(direct_session, "get_team_sector_status"),
        _direct_call(direct_session, "get_known_survivors"),
    )

    # Check mission complete
    try:
        mission_data = json.loads(mission_raw) if mission_raw.startswith("{") else {}
        if mission_data.get("mission_complete"):
            print(f"[ORCH] Mission complete!", flush=True)
            _post_phase("ORCH", round_num, "decision", {
                "commands": ["MISSION COMPLETE — all survivors rescued"],
                "total_duration_ms": int((time.time() - t0) * 1000),
                "model": model_name,
            })
            return True
    except Exception:
        mission_data = {}

    # Determine mission phase
    try:
        map_data = json.loads(map_raw) if map_raw.startswith("{") else {}
        pct_mapped = map_data.get("mapped_percentage", 0)
        unmapped = map_data.get("unmapped_sectors", [])
    except Exception:
        pct_mapped, unmapped = 0, []

    try:
        rescued  = mission_data.get("survivors_rescued", 0)
        total_sv = mission_data.get("total_survivors", "?")
        tick     = mission_data.get("tick", 0)
    except Exception:
        rescued, total_sv, tick = 0, "?", 0

    state_text = (
        f"TICK: {tick} | RESCUED: {rescued}/{total_sv} | MAPPED: {pct_mapped:.0f}%\n\n"
        f"FLEET STATUS:\n{fleet_raw}\n\n"
        f"MAPPING:\n{map_raw}\n\n"
        f"ACTIVE SECTOR:\n{sector_raw}\n\n"
        f"KNOWN UNRESCUED SURVIVORS:\n{survivors_raw}"
    )

    _post_phase("ORCH", round_num, "state", {
        "status": "ready",
        "state_text": state_text,
        "battery": 100,
        "drone_status": "orchestrating",
        "duration_ms": int((time.time() - t0) * 1000),
    })

    # ── Select system prompt based on round / sector transition ──────────────
    global _last_sector
    try:
        sector_data  = json.loads(sector_raw) if sector_raw.startswith("{") else {}
        active_sector = sector_data.get("current_sector") or sector_data.get("sector_name", "")
    except Exception:
        active_sector = ""

    sector_changed = active_sector and active_sector != _last_sector and _last_sector != ""

    if round_num == 1:
        active_system = INIT_SYSTEM
        prompt_label  = "INIT"
    elif sector_changed:
        active_system = POST_REGION_SYSTEM
        prompt_label  = f"POST-REGION ({_last_sector} → {active_sector})"
    else:
        active_system = ORCHESTRATOR_SYSTEM
        prompt_label  = "INTEL"

    if active_sector:
        _last_sector = active_sector

    # ── Phase 2: system prompt (posted after selection so label is correct) ───
    _post_phase("ORCH", round_num, "system_prompt", {
        "prompt_text": active_system,
        "prompt_label": prompt_label,
    })

    # ── Build dynamic state brief ─────────────────────────────────────────────
    if unmapped:
        phase_label = f"PHASE 1 — MAPPING ({len(unmapped)} sectors remaining: {', '.join(unmapped[:3])})"
    else:
        phase_label = f"PHASE 2 — RESCUE ({rescued}/{total_sv} survivors recovered)"

    if round_num == 1:
        mission_goal = (
            f"ROUND {round_num} — INITIALIZATION\n"
            f"Drones on network: {drone_ids}\n"
            f"Current state:\n{state_text}\n\n"
            f"Run the initialization procedure and issue launch clearance."
        )
    elif sector_changed:
        mission_goal = (
            f"ROUND {round_num} — SECTOR TRANSITION ({_last_sector})\n"
            f"Phase: {phase_label} | Tick: {tick}\n"
            f"Current state:\n{state_text}\n\n"
            f"Run the debrief procedure for the completed sector and brief the next sector."
        )
    else:
        mission_goal = (
            f"ROUND {round_num} — ACTIVE SWEEP\n"
            f"Phase: {phase_label} | Tick: {tick} | Sector: {active_sector or 'unknown'}\n"
            f"Drones: {drone_ids}\n"
            f"Current state:\n{state_text}\n\n"
            f"Run your full intelligence assessment."
        )

    print(f"[ORCH] Round {round_num} [{prompt_label}] | {phase_label} | Tick={tick}", flush=True)

    # ── Phase 4: reasoning — invoke the ReAct agent ───────────────────────────
    _post_phase("ORCH", round_num, "reasoning", {"status": "thinking", "text": ""})

    try:
        config = {
            "callbacks": [StreamingCallback("ORCH")],
            "recursion_limit": MAX_STEPS,
        }
        result = await asyncio.wait_for(
            agent_executor.ainvoke(
                {"messages": [
                    SystemMessage(content=active_system),
                    HumanMessage(content=mission_goal),
                ]},
                config,
            ),
            timeout=AGENT_TIMEOUT,
        )
    except asyncio.TimeoutError:
        _post_phase("ORCH", round_num, "reasoning", {
            "status": "complete",
            "text": f"— analysis window closed ({AGENT_TIMEOUT}s) — round continues.",
            "duration_ms": AGENT_TIMEOUT * 1000,
        })
        print(f"[ORCH] Round {round_num} timed out after {AGENT_TIMEOUT}s.", flush=True)
        return False
    except Exception as exc:
        print(f"[ORCH] Round {round_num} error: {type(exc).__name__}: {exc}", flush=True)
        return False

    # ── Parse agent output ────────────────────────────────────────────────────
    reasoning_parts = []
    tool_calls      = []
    commands        = []
    mission_complete_seen = False

    for msg in result.get("messages", []):
        if isinstance(msg, AIMessage):
            if msg.content:
                reasoning_parts.append(f"THOUGHT:\n{msg.content}")
            for tc in msg.tool_calls:
                arg_str = json.dumps(tc["args"])
                reasoning_parts.append(f"\nACTION: {tc['name']}({arg_str})")
                commands.append(f"{tc['name']}({arg_str})")
                tool_calls.append({"tool": tc["name"], "args": tc["args"], "result": None})
        elif isinstance(msg, ToolMessage):
            short = str(msg.content)[:300]
            reasoning_parts.append(f"OBSERVATION: {short}\n")
            if tool_calls:
                tool_calls[-1]["result"] = str(msg.content)[:400]
            try:
                r = json.loads(msg.content) if isinstance(msg.content, str) else {}
                if isinstance(r, dict) and r.get("mission_complete"):
                    mission_complete_seen = True
            except Exception:
                pass

    full_reasoning = "\n".join(reasoning_parts)
    dur_ms = int((time.time() - t0) * 1000)

    # ── Phase 4 complete ──────────────────────────────────────────────────────
    md_path, md_text = _write_reasoning_markdown(round_num, tick, phase_label, full_reasoning)
    _post_phase("ORCH", round_num, "reasoning", {
        "status": "complete",
        "text": full_reasoning,
        "duration_ms": dur_ms,
        "markdown_path": md_path,
        "markdown_text": md_text,
    })

    # ── Phase 5: tool calls ───────────────────────────────────────────────────
    _post_phase("ORCH", round_num, "tool_calls", {
        "calls": tool_calls,
        "count": len(tool_calls),
    })

    # ── Phase 6: decision ─────────────────────────────────────────────────────
    _post_phase("ORCH", round_num, "decision", {
        "commands": commands,
        "total_duration_ms": dur_ms,
        "model": model_name,
        "drone_id": "ORCH",
    })

    # Classic AI event for backward compat
    _post(DASHBOARD_AI_URL, {
        "drone_id":       "ORCH",
        "round":          round_num,
        "tick":           tick,
        "prompt":         mission_goal[:800],
        "llm_response":   full_reasoning[:1000],
        "commands":       commands,
        "idle_count":     0,
        "low_batt_count": 0,
    })

    print(f"[ORCH] Round {round_num} done — {len(tool_calls)} tool calls [{dur_ms}ms]", flush=True)
    return mission_complete_seen


# ── Main entry point ──────────────────────────────────────────────────────────

async def run_orchestrator(model: str = "gemini-2.5-flash"):
    """
    Start the Orchestrator agent.
    Connects to both MCP server (for agent tools) and a direct MCP session (for quick state calls).
    """
    global _stream_queue
    _stream_queue = asyncio.Queue()
    asyncio.create_task(_stream_worker())

    try:
        llm = _build_llm(model)
    except (EnvironmentError, ValueError) as err:
        print(f"[ORCH] ERROR: {err}", flush=True)
        return

    print(f"[ORCH] Orchestrator initialising — model: {model}", flush=True)

    # ── Wait for the MCP server to be reachable ───────────────────────────────
    print(f"[ORCH] Checking MCP server at {MCP_SERVER_URL} ...", flush=True)
    import urllib.error as _ue
    server_ready = False
    for attempt in range(1, 16):   # up to 30 s
        try:
            urllib.request.urlopen(MCP_SERVER_URL, timeout=1)
            server_ready = True
            break
        except _ue.HTTPError:
            server_ready = True    # HTTP error = server IS up
            break
        except Exception:
            if attempt == 1:
                print(
                    f"[ORCH] MCP server not reachable yet — is main.py running?\n"
                    f"       Start it with:  python main.py\n"
                    f"       Retrying",
                    end="", flush=True,
                )
            print(".", end="", flush=True)
            await asyncio.sleep(2)

    if not server_ready:
        print(
            f"\n[ORCH] ERROR: Could not connect to MCP server at {MCP_SERVER_URL}\n"
            f"       Make sure main.py is running in another terminal first.",
            flush=True,
        )
        return

    print(f"\n[ORCH] MCP server ready. Loading tools...", flush=True)

    # ── Open direct MCP session for state snapshots ───────────────────────────
    try:
        async with sse_client(MCP_SERVER_URL) as (read, write):
            async with ClientSession(read, write) as direct_session:
                await direct_session.initialize()

                # ── Load MCP tools via langchain-mcp-adapters ─────────────────
                mcp_client = MultiServerMCPClient({
                    "drone_fleet": {
                        "url": MCP_SERVER_URL,
                        "transport": "sse",
                    }
                })
                mcp_tools = await mcp_client.get_tools()

                # ── Filter to read-only tools only ────────────────────────────
                # Prevents the agent from accidentally issuing move/scan orders
                # that would interfere with the live autonomous sweep in main.py.
                agent_tools = [t for t in mcp_tools if t.name in READ_ONLY_TOOLS]
                excluded = [t.name for t in mcp_tools if t.name not in READ_ONLY_TOOLS]
                print(
                    f"[ORCH] {len(agent_tools)} intelligence tools available: "
                    f"{[t.name for t in agent_tools]}",
                    flush=True,
                )
                if excluded:
                    print(f"[ORCH] Excluded (write/state-changing): {excluded}", flush=True)

                agent_executor = create_react_agent(llm, agent_tools)

                # ── Wait for drones to register ───────────────────────────────
                print(f"[ORCH] Waiting for drones...", flush=True)
                drone_ids: list[str] = []
                while not drone_ids:
                    raw = await _direct_call(direct_session, "get_active_drones")
                    try:
                        d = json.loads(raw)
                        if isinstance(d, list) and d:
                            drone_ids = d
                    except Exception:
                        pass
                    if not drone_ids:
                        await asyncio.sleep(2)

                print(f"[ORCH] {len(drone_ids)} drones detected: {drone_ids}", flush=True)
                print(f"\n{'='*62}", flush=True)
                print(f"  COMMAND AGENT — INTELLIGENCE SHOWCASE", flush=True)
                print(f"  Model:        {model}", flush=True)
                print(f"  Drones:       {drone_ids}", flush=True)
                print(f"  Intel tools:  {len(agent_tools)} (read-only)", flush=True)
                print(f"  Operations:   LIVE (autonomous sweep running in main.py)", flush=True)
                print(f"{'='*62}\n", flush=True)

                # ── Main orchestration loop ───────────────────────────────────
                round_num = 1
                while True:
                    done = await _run_round(
                        agent_executor,
                        round_num,
                        model,
                        direct_session,
                        drone_ids,
                    )
                    if done:
                        print(f"[ORCH] Mission complete after {round_num} rounds!", flush=True)
                        break
                    round_num += 1
                    print(f"[ORCH] Waiting {ROUND_INTERVAL}s...", flush=True)
                    await asyncio.sleep(ROUND_INTERVAL)

    except BaseException as err:
        import sys, traceback

        def _leaves(exc):
            if isinstance(exc, BaseExceptionGroup):
                for sub in exc.exceptions:
                    yield from _leaves(sub)
            else:
                yield exc

        leaf_errors = list(_leaves(err))
        for exc in leaf_errors:
            print(f"\n[ORCH] Error: {type(exc).__name__}: {exc}", flush=True)
        if "--debug" in sys.argv:
            traceback.print_exc()

        # Determine what kind of error this is
        err_str = " ".join(str(e) for e in leaf_errors).lower()
        print("\n[ORCH] Possible causes:", flush=True)
        if "connect" in err_str or "connection" in err_str:
            print(f"  * MCP server not running → start main.py first", flush=True)
            print(f"  * Wrong port             → MCP should be at {MCP_SERVER_URL}", flush=True)
        elif model in OLLAMA_MODELS:
            print(f"  * Ollama not running  → ollama serve", flush=True)
            print(f"  * Model not pulled    → ollama pull {model}", flush=True)
        else:
            print(f"  * No API key          → export GOOGLE_API_KEY='...'", flush=True)
            print(f"  * Quota exceeded      → wait or upgrade plan", flush=True)


if __name__ == "__main__":
    import asyncio

    parser = argparse.ArgumentParser(description="NDRRMC Orchestrator — Rescue Drone Fleet Manager")
    parser.add_argument(
        "--model",
        default="gemini-2.5-flash",
        choices=sorted(OLLAMA_MODELS | GEMINI_MODELS),
        help="LLM backend (default: gemini-2.5-flash)",
    )
    args = parser.parse_args()
    asyncio.run(run_orchestrator(model=args.model))
