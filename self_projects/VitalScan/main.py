"""
main.py
=======
Entry point for the Metro Manila Disaster Rescue System.

  AI Agent mode (command-line):
       export GOOGLE_API_KEY='your-gemini-key'
       python main.py

     → Spawns mcp_server.py which starts:
         • Mesa simulation (headless, background thread)
         • Live dashboard on http://localhost:8765
         • MCP SSE server on http://localhost:8766
     → Opens the dashboard in your browser automatically.
     → Launches the deterministic drone swarm (drone_agents.py / main_swarm).

SHOWCASE — Orchestrator AI (separate, does NOT control drones):
     python orchestrator.py --model gemini-2.5-flash
     → A standalone LangGraph ReAct agent that connects to the running MCP server,
       loads all tools via langchain-mcp-adapters, and demonstrates high-level goal
       decomposition (e.g. "Scan the SE quadrant") into sequential tool calls.
       Run this in a second terminal while main.py is already running.
"""

import argparse
import asyncio
import os
import subprocess
import sys
import time

# Load .env (zero-dep) so GOOGLE_API_KEY is available without `export`.
_env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
if os.path.isfile(_env_path):
    with open(_env_path) as _f:
        for _line in _f:
            _line = _line.strip()
            if not _line or _line.startswith("#") or "=" not in _line:
                continue
            _k, _v = _line.split("=", 1)
            os.environ.setdefault(_k.strip(), _v.strip().strip('"').strip("'"))
import urllib.request

from src.agents.drone_agents import main_swarm, OLLAMA_MODELS, GEMINI_MODELS

import os
MCP_SERVER_URL       = os.environ.get("MCP_SERVER_URL", "http://0.0.0.0:8766")
# In cloud envs like Hugging Face, PORT is set and should be used for the dashboard
DEFAULT_PORT         = os.environ.get("PORT", "8765")
SOLARA_URL           = os.environ.get("DASHBOARD_URL", f"http://0.0.0.0:{DEFAULT_PORT}")
SERVER_READY_TIMEOUT = 30
HEADLESS             = os.environ.get("HEADLESS", "false").lower() == "true"


def _make_banner(model: str) -> str:
    return f"""
╔══════════════════════════════════════════════════════════════╗
║      METRO MANILA DISASTER RESCUE SYSTEM                     ║
║      NDRRMC Drone Swarm — Deterministic Sweep                ║
╠══════════════════════════════════════════════════════════════╣
║  MCP Server   →  http://localhost:8766  (SSE)               ║
║  Live Map     →  http://localhost:8765  (Dashboard)         ║
║  Swarm AI     →  {model:<44}║
║  Navigation   →  Deterministic boustrophedon sector sweep   ║
║  Showcase     →  python orchestrator.py (separate terminal) ║
╚══════════════════════════════════════════════════════════════╝
"""


def _free_ports(*ports: int) -> None:
    """Kill any processes holding the given ports (macOS/Linux)."""
    import signal
    for port in ports:
        try:
            result = subprocess.run(
                ["lsof", "-ti", f":{port}"],
                capture_output=True, text=True,
            )
            pids = result.stdout.strip().split()
            for pid in pids:
                try:
                    os.kill(int(pid), signal.SIGTERM)
                except (ProcessLookupError, ValueError):
                    pass
        except FileNotFoundError:
            pass
    if ports:
        time.sleep(0.8)


def _wait_for_server(url: str, label: str, timeout: int = SERVER_READY_TIMEOUT) -> bool:
    """Poll url until it responds or timeout expires."""
    import urllib.error
    deadline = time.time() + timeout
    count = 0
    while time.time() < deadline:
        count += 1
        try:
            # We use a short 1s timeout to check if the port is responding
            urllib.request.urlopen(url, timeout=1)
            return True
        except urllib.error.HTTPError:
            # HTTP error still means the server is UP (e.g. 404/405 from FastMCP)
            return True
        except Exception:
            if count % 2 == 0:
                print(f"[SYSTEM] Still waiting for {label} at {url}...", flush=True)
            time.sleep(0.5)
    return False


def main():
    parser = argparse.ArgumentParser(description="Metro Manila Disaster Rescue System")
    parser.add_argument(
        "--models",
        default="gemini-2.5-flash",
        help="Comma-separated list of LLMs for base drone reasoning (e.g. qwen3:4b-instruct,gemini-2.5-flash)",
    )
    parser.add_argument(
        "--summarizer-model",
        default="gemini-2.0-flash-lite",
        help="Separate model for AI Reasoning Summarizer (e.g. gemini-2.0-flash-lite)",
    )
    args = parser.parse_args()

    print(_make_banner(args.models.split(",")[0].strip()), flush=True)

    # ── 1. Free ports ─────────────────────────────────────────────────────────
    print("[SYSTEM] Clearing ports 8765 and 8766...", flush=True)
    _free_ports(8765, 8766)

    # ── 2. Launch mcp_server.py subprocess ───────────────────────────────────
    print("[SYSTEM] Starting MCP server + simulation + dashboard...", flush=True)
    server_proc = subprocess.Popen(
        [sys.executable, "-m", "src.mcp.mcp_server"],
        stderr=sys.stderr,
        stdout=subprocess.DEVNULL,
    )

    # ── 3. Wait for MCP SSE server ────────────────────────────────────────────
    print(f"[SYSTEM] Waiting for MCP server at {MCP_SERVER_URL} ...", flush=True)
    if not _wait_for_server(MCP_SERVER_URL, "MCP"):
        print("[SYSTEM] MCP server did not start in time. Check mcp_server.py.", flush=True)
        server_proc.terminate()
        sys.exit(1)
    print("[SYSTEM] MCP server ready.", flush=True)

    if _wait_for_server(SOLARA_URL, "Dashboard"):
        print(f"\n[SYSTEM] Live rescue map → {SOLARA_URL}\n", flush=True)
        if not HEADLESS:
            try:
                import webbrowser
                webbrowser.open(SOLARA_URL)
            except Exception:
                pass
    else:
        print(f"[SYSTEM] Dashboard not ready — open {SOLARA_URL} manually.", flush=True)

    # ── 5. Run the deterministic drone swarm ──────────────────────────────────
    print(f"\n[SYSTEM] Starting Decentralized Swarm AI (models: {args.models})...\n", flush=True)
    print("[SYSTEM] TIP: Run 'python orchestrator.py' in a second terminal to see", flush=True)
    print("[SYSTEM]      the AI Orchestrator showcase (goal decomposition demo).\n", flush=True)
    try:
        asyncio.run(main_swarm(
            models=args.models.split(","),
            summarizer_model=args.summarizer_model
        ))
    except KeyboardInterrupt:
        print("\n[SYSTEM] Mission aborted by operator.", flush=True)
    finally:
        print("[SYSTEM] Shutting down MCP server.", flush=True)
        server_proc.terminate()
        try:
            server_proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            server_proc.kill()
        _free_ports(8765, 8766)


if __name__ == "__main__":
    main()
