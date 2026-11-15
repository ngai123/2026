"""
Single Consultant class — owns the agentic loop.

External interface is identical to the old consultant modules::

    stream_chat(messages, snapshot_id) -> Generator[str, None, None]

Internally it delegates to:

* ``ToolExecutor``  (ai/executor.py) — pure tool execution
* ``StreamAdapter``  (ai/adapters.py) — HTTP layer to the LLM
"""

from __future__ import annotations

import json
from typing import Generator, Optional

from ai.adapters import StreamAdapter
from ai.executor import ToolExecutor
from ai.registry import TOOLS, SYSTEM_PROMPT

# Separator inserted after a reasoning block so ai_chat.py can split
# the "thinking" display from the actual response content.
_REASON_SEP = "\n\n---\n\n"


class Consultant:
    """Unified financial-consultant backed by a pluggable adapter."""

    def __init__(
        self,
        adapter: StreamAdapter,
        system_prompt: str = SYSTEM_PROMPT,
    ) -> None:
        self._adapter = adapter
        self._system_prompt = system_prompt
        self._executor = ToolExecutor()

    # ── Public interface ──────────────────────────────────────────────

    def stream_chat(
        self,
        messages: list[dict],
        snapshot_id: Optional[int] = None,
    ) -> Generator[str, None, None]:
        """Stream response chunks identical to the old consultants.

        Parameters
        ----------
        messages : list[dict]
            Conversation so far (each dict has ``role`` and ``content``).
        snapshot_id : int, optional
            Accepted for interface compatibility; not used (the executor
            always queries the latest snapshot).
        """
        # Build provider-format history starting with the system message
        history: list[dict] = [
            {"role": "system", "content": self._system_prompt},
        ]
        # Copy caller's messages (don't mutate the original list)
        history += [
            {"role": m["role"], "content": m["content"]} for m in messages
        ]

        while True:
            # ── Call the LLM ──────────────────────────────────────────
            try:
                text, reasoning, tool_calls = self._adapter.complete(
                    history, TOOLS
                )
            except Exception as e:
                yield f"\n\n**Error:** {e}\n"
                return

            # ── Yield reasoning (if any) ──────────────────────────────
            if reasoning:
                formatted = (
                    "> **Reasoning**\n> "
                    + reasoning.strip().replace("\n", "\n> ")
                )
                yield formatted
                yield _REASON_SEP

            # ── Yield main text ───────────────────────────────────────
            if text:
                yield text

            # ── No tool calls → done ──────────────────────────────────
            if not tool_calls:
                break

            # ── Append assistant turn (with tool calls) to history ────
            history.append(
                {
                    "role": "assistant",
                    "content": text or None,
                    "tool_calls": tool_calls,
                }
            )

            # ── Execute each tool ─────────────────────────────────────
            for tc in tool_calls:
                fn = tc["function"]
                name: str = fn["name"]
                try:
                    args = (
                        json.loads(fn["arguments"])
                        if isinstance(fn["arguments"], str)
                        else fn["arguments"]
                    )
                except (json.JSONDecodeError, TypeError):
                    args = {}

                yield (
                    f"\n\n*\\[Fetching: "
                    f"{name.replace('_', ' ').title()}...]*\n\n"
                )

                result = self._executor.execute(name, args)

                history.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc["id"],
                        "content": result,
                    }
                )

    def chat_sync(self, messages: list[dict]) -> str:
        """Non-streaming convenience wrapper."""
        return "".join(self.stream_chat(messages))
