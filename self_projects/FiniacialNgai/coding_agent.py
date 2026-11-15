"""
MiMo Coding Agent
-----------------
A MiMo-powered autonomous coding agent with real file system and bash tools.
Claude acts as tech lead — reviews output, gives commands.
MiMo does the actual implementation work.

Usage:
    python coding_agent.py "your task description"
    python coding_agent.py --task "fix the missing methods in repository.py"
    python coding_agent.py --interactive   # REPL mode
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path
from typing import Generator

from openai import OpenAI

# ── Config ────────────────────────────────────────────────────────────────────

PROJECT_ROOT = Path(__file__).parent
API_KEY  = os.getenv("XIAOMI_API_KEY", "")
BASE_URL = os.getenv("XIAOMI_BASE_URL", "https://token-plan-sgp.xiaomimimo.com/v1")
MODEL    = os.getenv("XIAOMI_MODEL",    "mimo-v2.5-pro")

MAX_TOOL_LOOPS = 30   # guard against infinite loops
MAX_FILE_CHARS = 40_000   # cap large file reads

# ── System prompt ─────────────────────────────────────────────────────────────

SYSTEM_PROMPT = f"""\
You are an expert Python developer working inside the FinancialNgai project.

Project root: {PROJECT_ROOT}

## Your role
You are the coding agent. You receive tasks from the tech lead (the user).
You use your tools to read files, write code, and run commands.
You ALWAYS:
1. Read the relevant file(s) before editing them
2. Make precise, minimal changes — don't rewrite what isn't broken
3. Verify your changes compile/run correctly using bash_exec
4. Report clearly what you changed and why

## Tools available
- read_file(path)           — read any file in the project
- write_file(path, content) — write/overwrite a file
- list_files(directory)     — list files in a directory
- bash_exec(command)        — run a shell command (from project root)
- search_code(pattern)      — grep for a pattern across .py files

## Rules
- All paths are relative to the project root unless absolute
- Never delete files — only edit or create
- Confirm each task is done before stopping
- If something is unclear, ask before writing code
"""

# ── Tool definitions ──────────────────────────────────────────────────────────

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read the full content of a file in the project.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "File path relative to project root (or absolute)"}
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "Write (create or overwrite) a file with given content.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path":    {"type": "string", "description": "File path relative to project root"},
                    "content": {"type": "string", "description": "Full file content to write"},
                },
                "required": ["path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_files",
            "description": "List all files in a directory (non-recursive by default).",
            "parameters": {
                "type": "object",
                "properties": {
                    "directory": {"type": "string", "description": "Directory path relative to project root"},
                    "recursive": {"type": "boolean", "description": "List recursively (default false)"},
                },
                "required": ["directory"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "bash_exec",
            "description": "Run a shell command from the project root. Use to run tests, check syntax, grep, etc.",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "Shell command to run"},
                    "timeout": {"type": "integer", "description": "Timeout in seconds (default 30)"},
                },
                "required": ["command"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_code",
            "description": "Search for a pattern across all Python files in the project.",
            "parameters": {
                "type": "object",
                "properties": {
                    "pattern": {"type": "string", "description": "grep-compatible pattern to search for"},
                    "path":    {"type": "string", "description": "Subdirectory to search in (default: whole project)"},
                },
                "required": ["pattern"],
            },
        },
    },
]

# ── Tool executor ─────────────────────────────────────────────────────────────

def _resolve(path: str) -> Path:
    p = Path(path)
    return p if p.is_absolute() else PROJECT_ROOT / p


def execute_tool(name: str, args: dict) -> str:
    try:
        if name == "read_file":
            p = _resolve(args["path"])
            if not p.exists():
                return json.dumps({"error": f"File not found: {p}"})
            content = p.read_text(errors="replace")
            if len(content) > MAX_FILE_CHARS:
                content = content[:MAX_FILE_CHARS] + f"\n... [truncated at {MAX_FILE_CHARS} chars]"
            return json.dumps({"path": str(p), "content": content})

        elif name == "write_file":
            p = _resolve(args["path"])
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(args["content"])
            return json.dumps({"status": "written", "path": str(p), "bytes": len(args["content"])})

        elif name == "list_files":
            d = _resolve(args.get("directory", "."))
            recursive = args.get("recursive", False)
            if not d.exists():
                return json.dumps({"error": f"Directory not found: {d}"})
            if recursive:
                files = [str(f.relative_to(PROJECT_ROOT)) for f in d.rglob("*")
                         if f.is_file() and ".venv" not in f.parts and "__pycache__" not in f.parts]
            else:
                files = [str(f.relative_to(PROJECT_ROOT)) for f in d.iterdir()
                         if ".venv" not in str(f)]
            return json.dumps({"directory": str(d), "files": sorted(files)})

        elif name == "bash_exec":
            timeout = args.get("timeout", 30)
            result = subprocess.run(
                args["command"],
                shell=True,
                capture_output=True,
                text=True,
                cwd=PROJECT_ROOT,
                timeout=timeout,
            )
            output = (result.stdout or "") + (result.stderr or "")
            if len(output) > 8000:
                output = output[:8000] + "\n... [truncated]"
            return json.dumps({
                "returncode": result.returncode,
                "output": output,
            })

        elif name == "search_code":
            pattern = args["pattern"]
            search_path = args.get("path", ".")
            result = subprocess.run(
                f'grep -rn --include="*.py" {json.dumps(pattern)} {search_path}',
                shell=True,
                capture_output=True,
                text=True,
                cwd=PROJECT_ROOT,
            )
            output = result.stdout or "(no matches)"
            if len(output) > 6000:
                output = output[:6000] + "\n... [truncated]"
            return json.dumps({"matches": output})

        else:
            return json.dumps({"error": f"Unknown tool: {name}"})

    except subprocess.TimeoutExpired:
        return json.dumps({"error": "Command timed out"})
    except Exception as e:
        return json.dumps({"error": str(e)})


# ── Agent loop ────────────────────────────────────────────────────────────────

class MiMoCodingAgent:
    def __init__(self):
        self.client = OpenAI(api_key=API_KEY, base_url=BASE_URL)
        self.history: list[dict] = [{"role": "system", "content": SYSTEM_PROMPT}]

    def run(self, task: str) -> Generator[str, None, None]:
        """Run a task. Yields streamed output lines."""
        self.history.append({"role": "user", "content": task})
        yield f"\n🤖 MiMo working on: {task}\n{'─'*60}\n"

        for loop in range(MAX_TOOL_LOOPS):
            # ── Stream one completion ──────────────────────────────────────
            accumulated = ""
            tool_calls_map: dict[int, dict] = {}
            in_think = False
            think_buf = ""

            try:
                # Use non-streaming for tool-call turns so reasoning_content
                # is cleanly captured and passed back (MiMo thinking-mode requirement).
                response = self.client.chat.completions.create(
                    model=MODEL,
                    messages=self.history,
                    tools=TOOLS,
                    tool_choice="auto",
                    stream=False,
                    temperature=0.2,
                )
                choice  = response.choices[0]
                message = choice.message

                # Capture reasoning_content if present (thinking mode)
                reasoning_content = getattr(message, "reasoning_content", None)
                if reasoning_content:
                    yield f"\n💭 [reasoning — {len(reasoning_content)} chars]\n"

                accumulated = message.content or ""
                if accumulated.strip():
                    yield accumulated

                raw_tool_calls = message.tool_calls or []
                for tc in raw_tool_calls:
                    idx = len(tool_calls_map)
                    tool_calls_map[idx] = {
                        "id":   tc.id or f"call_{idx}",
                        "type": "function",
                        "function": {
                            "name":      tc.function.name,
                            "arguments": tc.function.arguments,
                        },
                    }

            except Exception as e:
                yield f"\n❌ API error: {e}\n"
                return

            # ── No tool calls → done ───────────────────────────────────────
            if not tool_calls_map:
                # Build assistant dict including reasoning_content if present
                asst_msg: dict = {"role": "assistant", "content": accumulated}
                if reasoning_content:
                    asst_msg["reasoning_content"] = reasoning_content
                self.history.append(asst_msg)
                yield f"\n\n{'─'*60}\n✅ Task complete.\n"
                break

            tool_calls = list(tool_calls_map.values())
            asst_msg = {
                "role":       "assistant",
                "content":    accumulated or None,
                "tool_calls": tool_calls,
            }
            if reasoning_content:
                asst_msg["reasoning_content"] = reasoning_content
            self.history.append(asst_msg)

            # ── Execute tools ──────────────────────────────────────────────
            for tc in tool_calls:
                fn   = tc["function"]
                name = fn["name"]
                try:
                    args = json.loads(fn["arguments"] or "{}")
                except json.JSONDecodeError:
                    args = {}

                yield f"\n\n🔧 [{name}] {_tool_summary(name, args)}\n"
                result = execute_tool(name, args)

                # Show brief result preview
                try:
                    parsed = json.loads(result)
                    if "error" in parsed:
                        yield f"   ❌ {parsed['error']}\n"
                    elif name == "write_file":
                        yield f"   ✅ Written {parsed.get('bytes',0)} bytes → {parsed.get('path','')}\n"
                    elif name == "bash_exec":
                        rc = parsed.get("returncode", 0)
                        icon = "✅" if rc == 0 else "⚠️"
                        out = parsed.get("output", "").strip()
                        preview = out[:300] + ("…" if len(out) > 300 else "")
                        yield f"   {icon} exit={rc}\n{textwrap.indent(preview, '   ')}\n"
                    elif name == "read_file":
                        lines = parsed.get("content", "").count("\n")
                        yield f"   📄 {lines} lines read\n"
                    elif name == "search_code":
                        hits = parsed.get("matches", "").strip()
                        preview = hits[:400] + ("…" if len(hits) > 400 else "")
                        yield f"   🔍 {textwrap.indent(preview, '   ')}\n"
                    else:
                        yield f"   ↩ {result[:200]}\n"
                except Exception:
                    yield f"   ↩ {result[:200]}\n"

                self.history.append({
                    "role": "tool",
                    "tool_call_id": tc["id"],
                    "content": result,
                })

        else:
            yield f"\n⚠️  Hit max loops ({MAX_TOOL_LOOPS}). Stopping.\n"

    def chat(self, message: str) -> Generator[str, None, None]:
        """Follow-up message in the same session."""
        yield from self.run(message)


def _tool_summary(name: str, args: dict) -> str:
    if name == "read_file":
        return args.get("path", "")
    if name == "write_file":
        return args.get("path", "")
    if name == "bash_exec":
        return args.get("command", "")[:80]
    if name == "search_code":
        return f'"{args.get("pattern","")}"'
    if name == "list_files":
        return args.get("directory", ".")
    return str(args)[:80]


# ── CLI ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="MiMo Coding Agent for FinancialNgai")
    parser.add_argument("task", nargs="?", help="Task to perform")
    parser.add_argument("--task", "-t", dest="task_flag", help="Task to perform")
    parser.add_argument("--interactive", "-i", action="store_true", help="Interactive REPL mode")
    args = parser.parse_args()

    task = args.task or args.task_flag
    agent = MiMoCodingAgent()

    if args.interactive or not task:
        print(f"\n🤖 MiMo Coding Agent — {MODEL}")
        print(f"   Project: {PROJECT_ROOT}")
        print("   Type your task. 'quit' to exit.\n")
        while True:
            try:
                user_input = input("▶ ").strip()
            except (EOFError, KeyboardInterrupt):
                print("\nBye.")
                break
            if user_input.lower() in ("quit", "exit", "q"):
                break
            if not user_input:
                continue
            for chunk in agent.chat(user_input):
                print(chunk, end="", flush=True)
            print()
    else:
        for chunk in agent.run(task):
            print(chunk, end="", flush=True)
        print()


if __name__ == "__main__":
    main()
