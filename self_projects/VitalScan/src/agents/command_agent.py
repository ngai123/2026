"""
command_agent.py
================
Autonomous Search-and-Rescue Commander for Metro Manila.

Architecture: direct planner loop (no LangGraph ReAct).
  Each round:
    1. Gather full fleet + mission state via MCP tool calls.
    2. Send state to LLM → ask for a JSON array of commands.
    3. Parse JSON and execute each command directly via MCP.
    4. Sleep briefly so drones can move, then repeat.

This avoids the ReAct loop-on-discovery-tools problem that small local
models exhibit when wrapped in LangGraph's agent framework.
"""

import argparse
import asyncio
import ast
import json
import os
import re
import threading
import urllib.request

from langchain_core.messages import HumanMessage, SystemMessage
from mcp import ClientSession
from mcp.client.sse import sse_client

OLLAMA_MODELS = {"qwen3.5:9b", "qwen3.5:4b", "qwen3.5:0.8b", "qwen3:4b-instruct", "qwen2.5-coder:0.5b"}
GEMINI_MODELS = {"gemini-2.5-flash", "gemini-2.0-flash","gemini-3-flash-preview"}


def _build_llm(model: str):
    if model in OLLAMA_MODELS:
        from langchain_ollama import ChatOllama
        return ChatOllama(
            model=model,
            temperature=0,
            num_ctx=8192,
        )
    elif model in GEMINI_MODELS:
        from langchain_google_genai import ChatGoogleGenerativeAI
        api_key = os.environ.get("GOOGLE_API_KEY")
        if not api_key:
            raise EnvironmentError(
                "GOOGLE_API_KEY environment variable is not set.\n"
                "       export GOOGLE_API_KEY='your-gemini-api-key'"
            )
        return ChatGoogleGenerativeAI(model=model, temperature=0, google_api_key=api_key)
    else:
        raise ValueError(
            f"Unknown model '{model}'. "
            f"Choose from: {sorted(OLLAMA_MODELS | GEMINI_MODELS)}"
        )


# ─────────────────────────────────────────────────────────────────────────────
# PLANNER PROMPT
# One-shot: feed state → get JSON command list back.
# Kept deliberately short so small models can follow it reliably.
# ─────────────────────────────────────────────────────────────────────────────

PLANNER_SYSTEM = """You are the NDRRMC COMMAND AI for Operation BAYANIHAN (7.4-magnitude earthquake, West Valley Fault).

OBJECTIVE:
Coordinate 5 autonomous UAVs (R1-R5) to locate and scan survivors in Metro Manila.

RING STRATEGY:
- R1, R2, R3: OUTER ring (1.3 - 2.0 km from base). High-density collapse zones.
- R4, R5: MIDDLE (0.6 - 1.3 km) and INNER (< 0.6 km) rings. Command district.

PRIORITY:
1. RECALL: All drones with battery <= 50% or status 'low_batt'. Use battery_check_recall.
2. ASSIGN: All IDLE/SCANNING drones. Use sweep_next for systematic sweep.
3. PHASE 1 (MAPPING): Use sweep_next to follow team sector waypoints.
4. PHASE 2 (RESCUE): Use rescue_dispatch to route drones to nearest unrescued survivors.

SKILLS (use these instead of raw tools):
- fleet_overview(): Full fleet status + sector progress in one call. Call FIRST.
- sweep_next(drone_id): Execute next sweep step (waypoint + scan + advance).
- safe_navigate(drone_id, x, y): Battery-safe movement with auto-recall.
- battery_check_recall(drone_id): Check battery, auto-recall if critical.
- mission_intel(): Full mission intelligence snapshot.
- rescue_dispatch(drone_id): Find and dispatch to nearest unrescued survivor.
- sector_advance(): Advance team to next sector when ready.
- scan_waypoint(drone_id, x, y): Navigate + scan + advance for manual targets.

FORMAT:
Write logic reasoning, then a JSON array in a markdown `json` code block:
```json
[{"tool": "SKILL_NAME", "args": {ARGS}}, ...]
```"""

MCP_SERVER_URL      = os.environ.get("MCP_SERVER_URL", "http://0.0.0.0:8766/sse")
DASHBOARD_AI_URL    = os.environ.get("DASHBOARD_AI_URL", "http://0.0.0.0:8765/api/ai_event")


def _post_ai_event(round_num: int, tick: int, prompt: str, response: str,
                   commands: list, idle_count: int, low_batt_count: int) -> None:
    """Fire-and-forget POST to dashboard /api/ai_event. Never blocks the agent."""
    payload = json.dumps({
        "round":          round_num,
        "tick":           tick,
        "prompt":         prompt[:800],
        "llm_response":   response[:1000],
        "commands":       commands,
        "idle_count":     idle_count,
        "low_batt_count": low_batt_count,
    }).encode()

    def _send():
        try:
            req = urllib.request.Request(
                DASHBOARD_AI_URL, data=payload,
                headers={"Content-Type": "application/json"},
            )
            urllib.request.urlopen(req, timeout=2)
        except Exception:
            pass   # dashboard may not be up; silently ignore

    threading.Thread(target=_send, daemon=True).start()

# Seconds to wait between rounds so drones have time to move.
# Simulation ticks every 0.35s; a drone crossing 10 cells takes ~3.5s.
# 8s gives enough time for most drones to reach their sector and go idle.
ROUND_INTERVAL = 8.0


# ─────────────────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────────────────

async def _call(session: ClientSession, tool: str, args: dict = {}) -> str:
    """Call an MCP tool and return the text content.

    FastMCP with json_response=True may encode a list return value as multiple
    TextContent blocks (one per element).  Collect all blocks and re-join them
    into a JSON array so downstream json.loads() always works correctly.
    """
    r = await session.call_tool(tool, args)
    if not r.content:
        return ""
    texts = [getattr(c, "text", "") for c in r.content if getattr(c, "text", "")]
    if not texts:
        return ""
    if len(texts) == 1:
        return texts[0]
    # Multiple blocks — try to reassemble as a JSON array
    try:
        items = []
        for t in texts:
            try:
                items.append(json.loads(t))
            except json.JSONDecodeError:
                # If FastMCP returns a plain string without quotes, use it as is
                items.append(t.strip())
        return json.dumps(items)
    except Exception:
        return texts[0]


async def _gather_state(session: ClientSession) -> dict[str, str]:
    """Fetch all state tools in parallel."""
    results = await asyncio.gather(
        _call(session, "get_active_drones"),
        _call(session, "get_all_drones_status"),
        _call(session, "get_sector_info"),
        _call(session, "get_mission_status"),
        _call(session, "get_mapping_status"),
        _call(session, "get_known_survivors"),
    )
    return {
        "drones":    results[0],
        "status":    results[1],
        "sectors":   results[2],
        "mission":   results[3],
        "map_state": results[4],
        "survivors": results[5],
    }


def _extract_text(content) -> str:
    """Normalise LLM response content to a plain string.

    ChatGoogleGenerativeAI returns a list of content blocks when the response
    is multi-part; ChatOllama returns a plain string.  Both cases are handled
    here so downstream code always works with str.
    """
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict):
                parts.append(block.get("text", ""))
            elif isinstance(block, str):
                parts.append(block)
        return " ".join(parts)
    return str(content)


def _extract_commands(text: str) -> list[dict] | None:
    """Pull the JSON array out of the LLM response.
    Supports chain-of-thought where the JSON is wrapped in a markdown code block,
    or just as the final part of the text.
    """
    # First, try to find a JSON block in markdown backticks
    m_code = re.search(r"```(?:json)?\s*(\[.*?\])\s*```", text, re.DOTALL)
    if m_code:
        try:
            return json.loads(m_code.group(1))
        except json.JSONDecodeError:
            pass
            
    # Fallback to finding the first/last square bracket pair that parses
    start_idx = text.find('[')
    end_idx = text.rfind(']')
    if start_idx != -1 and end_idx != -1 and end_idx >= start_idx:
        try:
            return json.loads(text[start_idx:end_idx+1])
        except json.JSONDecodeError:
            pass
    return None


# ─────────────────────────────────────────────────────────────────────────────
# ROUND EXECUTION
# ─────────────────────────────────────────────────────────────────────────────

async def _run_round(llm, session: ClientSession, round_num: int) -> bool:
    """
    One planning + execution round.
    Returns True when the mission is complete.
    """
    state = await _gather_state(session)

    # Parse mission status for progress display
    try:
        mission_data = state.get("mission", "{}")
        if not mission_data or not mission_data.strip():
            mission_data = "{}"
        mission = json.loads(mission_data)
        if isinstance(mission, str):       # double-encoded edge case
            mission = json.loads(mission)
        if not isinstance(mission, dict):
            mission = {}
    except Exception as e:
        print(f"  [mission parse error: {e}]", flush=True)
        mission = {}

    tick    = mission.get("tick", 0)
    rescued = mission.get("survivors_rescued", 0)
    total   = mission.get("total_survivors", 1)
    pct     = mission.get("rescue_percentage", 0)

    print(
        f"[COMMANDER] Round {round_num:3d} | Tick {tick:4d} | "
        f"Rescued {rescued:2d}/{total} ({pct}%)",
        flush=True,
    )

    if mission.get("mission_complete", False):
        print(
            f"\n[COMMANDER] MISSION COMPLETE at tick {tick}! "
            f"{rescued}/{total} survivors rescued.",
            flush=True,
        )
        return True

    # Compute idle drones explicitly so the model knows exactly who needs assignment
    try:
        status_data = state.get("status", "[]")
        if not status_data or not status_data.strip():
            status_data = "[]"
        fleet = json.loads(status_data)
        if isinstance(fleet, str):         # double-encoded edge case
            fleet = json.loads(fleet)
        # Normalise: each element must be a dict (FastMCP can double-encode)
        norm = []
        for d in fleet:
            if isinstance(d, str):
                try:
                    d = json.loads(d)
                except Exception:
                    continue
            if isinstance(d, dict):
                norm.append(d)
        fleet = norm

        idle_ids = [
            d["drone_id"] for d in fleet
            if d.get("status") in ("idle", "scanning")
        ]
        low_ids = [
            d["drone_id"] for d in fleet
            if d.get("battery", 100) <= 20 or d.get("status") == "low_batt"
        ]
    except Exception as parse_exc:
        print(f"  [fleet parse error: {type(parse_exc).__name__}: {parse_exc}]", flush=True)
        print(f"  [raw status snippet: {state.get('status', '')[:200]}]", flush=True)
        idle_ids, low_ids = [], []

    # Nothing to do — skip LLM call entirely
    if not idle_ids and not low_ids:
        print("  [all drones busy — waiting]", flush=True)
        return False

    # Parse sector centers so we can tell the LLM where each idle drone already is
    try:
        sectors_str = state.get("sectors", "{}")
        if not sectors_str or not sectors_str.strip():
            sectors_str = "{}"
        sectors_data = json.loads(sectors_str)
        coord_to_sector = {
            (v["center_x"], v["center_y"]): name
            for name, v in sectors_data.items()
        }
    except Exception as e:
        print(f"  [sectors parse error: {e}]", flush=True)
        coord_to_sector = {}

    # Build a per-drone line with current position and "already at sector" warning
    drone_lines = []
    for d in fleet:
        drone_id = d.get("drone_id", "")
        status   = d.get("status", "")
        pos      = d.get("position", {})
        x, y     = pos.get("x", 0), pos.get("y", 0)
        battery  = d.get("battery", 100)

        if battery <= 20 or status == "low_batt":
            drone_lines.append(
                f"  {drone_id}: RECALL NOW — battery={battery}%"
            )
        elif status in ("idle", "scanning"):
            at_sector = coord_to_sector.get((x, y))
            location  = f"({x},{y})"
            if at_sector:
                location += f" = already at {at_sector} — MUST send to a DIFFERENT sector"
            drone_lines.append(
                f"  {drone_id}: needs assignment — currently at {location}, battery={battery}%"
            )

    assignment_hint = (
        f"DRONE ASSIGNMENTS NEEDED ({len(idle_ids)} idle, {len(low_ids)} low-battery):\n"
        + "\n".join(drone_lines) + "\n\n"
        f"RULES:\n"
        f"- Output exactly {len(idle_ids)} move_drone_to command(s) for the idle drones.\n"
        f"- Do NOT send a drone to coordinates it is ALREADY AT.\n"
        f"- Recall low-battery drones first, then assign idle drones to unmapped sectors (Phase 1) or known survivors (Phase 2).\n"
    )

    # Build state message for the LLM
    state_text = (
        f"{assignment_hint}\n"
        f"Fleet status:\n{state['status']}\n\n"
        f"Sector coordinates:\n{state['sectors']}\n\n"
        f"Mapping Status:\n{state['map_state']}\n\n"
        f"Known unrescued survivors:\n{state['survivors']}\n\n"
        f"Mission status:\n{state['mission']}"
    )

    # Ask the LLM for a command plan
    try:
        print("  [COMMANDER AI]: ", end="", flush=True)
        raw_parts = []
        async for chunk in llm.astream([
            SystemMessage(content=PLANNER_SYSTEM),
            HumanMessage(content=state_text),
        ]):
            text_chunk = _extract_text(chunk.content)
            print(text_chunk, end="", flush=True)
            raw_parts.append(text_chunk)
        print("\n", flush=True)
        raw = "".join(raw_parts)
    except Exception as exc:
        print(f"\n  [LLM error: {type(exc).__name__}: {exc}]", flush=True)
        return False

    commands = _extract_commands(raw)
    if not commands:
        print(f"  [no valid JSON returned — skipping round]", flush=True)
        print(f"  LLM said: {raw[:300]}", flush=True)
        _post_ai_event(round_num, tick, state_text, raw, [], len(idle_ids), len(low_ids))
        return False

    print(f"  Executing {len(commands)} command(s):", flush=True)
    for cmd in commands:
        tool = cmd.get("tool", "")
        args = cmd.get("args", {})
        if not tool:
            continue
        try:
            result_text = await _call(session, tool, args)
            print(f"    ✓ {tool}({args}) → {result_text[:120]}", flush=True)
        except Exception as exc:
            print(f"    ✗ {tool}({args}) → ERROR: {exc}", flush=True)

    _post_ai_event(round_num, tick, state_text, raw, commands, len(idle_ids), len(low_ids))
    return False


# ─────────────────────────────────────────────────────────────────────────────
# MAIN ENTRY POINT
# ─────────────────────────────────────────────────────────────────────────────

async def run_command_agent(model: str = "gemini-2.5-flash"):
    try:
        llm = _build_llm(model)
    except (EnvironmentError, ValueError) as err:
        print(f"ERROR: {err}", flush=True)
        return

    print(f"[COMMANDER] Using model: {model}", flush=True)

    try:
        async with sse_client(MCP_SERVER_URL) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                print("[COMMANDER] MCP connected.", flush=True)
                print("[COMMANDER] Waiting for simulation to initialize with drones...", flush=True)

                # Wait for drones to be placed and simulation to start
                max_wait = 120  # 2 minutes
                waited = 0
                drone_list = []
                while not drone_list and waited < max_wait:
                    try:
                        drones = await _call(session, "get_active_drones")
                        if drones and drones.strip():
                            try:
                                drone_list = json.loads(drones)
                            except json.JSONDecodeError:
                                try:
                                    # Fallback incase drones is a Python string rep like "['drone_12']"
                                    drone_list = ast.literal_eval(drones)
                                except Exception:
                                    # Fallback if it's just a raw single drone string
                                    drone_list = [drones.strip()]
                    except Exception as e:
                        print(f"[DEBUG Init] e: {e}. Raw drones: {drones!r}", flush=True)
                        pass  # Ignore parse errors, model not ready yet

                    if not drone_list:
                        await asyncio.sleep(2)
                        waited += 2

                if not drone_list:
                    print("[COMMANDER] ERROR: No drones detected after 2 minutes. Did you place drones and click START?", flush=True)
                    return

                print("\n" + "═" * 62, flush=True)
                print("  COMMANDER AI — MISSION LAUNCH", flush=True)
                print("═" * 62 + "\n", flush=True)
                print(f"[COMMANDER] Ready! {len(drone_list)} drones detected.\n", flush=True)

                round_num = 1
                while True:
                    done = await _run_round(llm, session, round_num)
                    if done:
                        break
                    round_num += 1
                    await asyncio.sleep(ROUND_INTERVAL)

    except BaseException as err:
        def _leaves(exc):
            if isinstance(exc, BaseExceptionGroup):
                for sub in exc.exceptions:
                    yield from _leaves(sub)
            else:
                yield exc

        for i, exc in enumerate(list(_leaves(err)), 1):
            print(f"\n[COMMANDER] Error [{i}]: {type(exc).__name__}: {exc}", flush=True)

        print("\n[COMMANDER] Common causes:", flush=True)
        if model in OLLAMA_MODELS:
            print("  • Ollama not running  →  ollama serve", flush=True)
            print(f"  • Model not pulled    →  ollama pull {model}", flush=True)
        else:
            print("  • Quota exceeded      →  wait or upgrade plan", flush=True)
            print("  • No API access       →  check GOOGLE_API_KEY", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="COMMANDER AI — Rescue Drone Controller")
    parser.add_argument(
        "--model",
        default="gemini-2.5-flash",
        choices=sorted(OLLAMA_MODELS | GEMINI_MODELS),
        help="LLM backend to use (default: gemini-2.5-flash)",
    )
    args = parser.parse_args()
    asyncio.run(run_command_agent(model=args.model))
