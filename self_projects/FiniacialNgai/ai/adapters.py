"""
Stream adapters — thin HTTP-layer wrappers for LLM providers.

* ``GeminiAdapter``  — Google Gemini (google-genai SDK)
* ``OpenAIAdapter``  — Any OpenAI-compatible API (Ollama, MiMo, etc.)

Each adapter exposes a single ``complete()`` method that returns a
standardised ``(text_content, reasoning_content, tool_calls)`` tuple.
"""

from __future__ import annotations

import json
import re
from typing import Protocol

from ai.registry import build_gemini_tools


# ─ Protocol ──────────────────────────────────────────────────────────────────

class StreamAdapter(Protocol):
    """Minimal contract every adapter must satisfy."""

    def complete(
        self, messages: list[dict], tools: list[dict]
    ) -> tuple[str, str, list[dict]]:
        """Make one non-streaming LLM call.

        Parameters
        ----------
        messages : list[dict]
            Full conversation history (OpenAI message format, including
            a leading ``{"role": "system", ...}`` dict).
        tools : list[dict]
            Tool definitions in OpenAI function-calling format.

        Returns
        -------
        tuple[str, str, list[dict]]
            ``(text_content, reasoning_content, tool_calls)`` where each
            tool-call dict is ``{"id": str, "type": "function",
            "function": {"name": str, "arguments": str}}``.
        """
        ...


# ─ Helpers ───────────────────────────────────────────────────────────────────

_THINK_RE = re.compile(r"(.*?)</think>", re.DOTALL)


def _extract_think(text: str) -> tuple[str, str]:
    """Strip ``...</think>`` blocks from *text*.

    Returns ``(clean_text, reasoning_content)``.
    """
    match = _THINK_RE.search(text)
    if match:
        reasoning = match.group(1).strip()
        clean = (text[: match.start()] + text[match.end() :]).strip()
        return clean, reasoning
    return text, ""


def _to_python(val):
    """Recursively convert Gemini proto objects to plain Python."""
    if hasattr(val, "items"):
        return {k: _to_python(v) for k, v in val.items()}
    if hasattr(val, "__iter__") and not isinstance(val, (str, bytes)):
        return [_to_python(v) for v in val]
    return val


# ─ Gemini adapter ────────────────────────────────────────────────────────────

class GeminiAdapter:
    """Google Gemini adapter using the ``google-genai`` SDK."""

    def __init__(self, api_key: str, model: str) -> None:
        import config
        from google import genai

        api_key = api_key or config.GOOGLE_API_KEY or config.GEMINI_API_KEY
        self._client = genai.Client(api_key=api_key)
        self._model = model
        self._gemini_tools = build_gemini_tools()

    # -- content conversion --------------------------------------------

    @staticmethod
    def _build_contents(messages: list[dict]) -> list:
        """Convert OpenAI-format messages → Gemini ``Content`` objects."""
        from google.genai import types

        # Map tool_call_id → tool name (needed for Gemini responses)
        tc_id_to_name: dict[str, str] = {}
        for m in messages:
            if m["role"] == "assistant" and m.get("tool_calls"):
                for tc in m["tool_calls"]:
                    tc_id_to_name[tc["id"]] = tc["function"]["name"]

        contents: list = []
        tool_resp_parts: list = []

        for m in messages:
            role = m["role"]
            if role == "system":
                continue  # handled via system_instruction

            # ─ tool result messages ─
            if role == "tool":
                name = tc_id_to_name.get(m.get("tool_call_id", ""), "unknown")
                tool_resp_parts.append(
                    types.Part.from_function_response(
                        name=name,
                        response={"result": m["content"]},
                    )
                )
                continue

            # flush collected tool-response parts before non-tool msg
            if tool_resp_parts:
                contents.append(types.Content(role="user", parts=tool_resp_parts))
                tool_resp_parts = []

            # ─ assistant messages (text + function calls) ─
            if role == "assistant":
                parts: list = []
                if m.get("content"):
                    parts.append(types.Part.from_text(text=m["content"]))
                for tc in m.get("tool_calls", []):
                    fn = tc["function"]
                    args = fn["arguments"]
                    if isinstance(args, str):
                        try:
                            args = json.loads(args)
                        except (json.JSONDecodeError, TypeError):
                            args = {}
                    parts.append(
                        types.Part.from_function_call(
                            name=fn["name"], args=_to_python(args)
                        )
                    )
                if parts:
                    contents.append(types.Content(role="model", parts=parts))

            # ─ user messages ─
            elif role == "user":
                contents.append(
                    types.Content(
                        role="user",
                        parts=[types.Part.from_text(text=m.get("content", ""))],
                    )
                )

        # flush any trailing tool responses
        if tool_resp_parts:
            contents.append(types.Content(role="user", parts=tool_resp_parts))

        return contents

    # -- complete ------------------------------------------------------

    def complete(
        self, messages: list[dict], tools: list[dict]
    ) -> tuple[str, str, list[dict]]:
        from google.genai import types

        # Extract system prompt (Gemini handles it separately)
        system_prompt = ""
        for m in messages:
            if m["role"] == "system":
                system_prompt = m["content"]
                break

        gen_config = types.GenerateContentConfig(
            system_instruction=system_prompt or None,
            tools=self._gemini_tools,
            automatic_function_calling=types.AutomaticFunctionCallingConfig(
                disable=True
            ),
        )

        contents = self._build_contents(messages)

        try:
            response = self._client.models.generate_content(
                model=self._model,
                contents=contents,
                config=gen_config,
            )
        except Exception as e:
            raise RuntimeError(f"Gemini API error: {e}") from e

        # Extract text and tool calls from response
        text = ""
        tool_calls: list[dict] = []
        seen: set[str] = set()

        try:
            if response.candidates:
                for candidate in response.candidates:
                    for part in candidate.content.parts or []:
                        try:
                            if part.text:
                                text += part.text
                        except Exception:
                            pass
                        try:
                            if part.function_call and part.function_call.name:
                                name = part.function_call.name
                                if name not in seen:
                                    args = _to_python(part.function_call.args)
                                    tool_calls.append(
                                        {
                                            "id": f"gemini_{name}",
                                            "type": "function",
                                            "function": {
                                                "name": name,
                                                "arguments": json.dumps(args),
                                            },
                                        }
                                    )
                                    seen.add(name)
                        except AttributeError:
                            pass
        except Exception:
            pass

        # Gemini doesn't use  blocks
        return (text, "", tool_calls)


# ─ OpenAI-compatible adapter ─────────────────────────────────────────────────

class OpenAIAdapter:
    """OpenAI-compatible adapter — works for MiMo, Ollama, etc."""

    def __init__(
        self,
        api_key: str,
        base_url: str,
        model: str,
        temperature: float = 0.3,
    ) -> None:
        from openai import OpenAI

        self._client = OpenAI(api_key=api_key, base_url=base_url)
        self._model = model
        self._temperature = temperature

    def complete(
        self, messages: list[dict], tools: list[dict]
    ) -> tuple[str, str, list[dict]]:
        try:
            response = self._client.chat.completions.create(
                model=self._model,
                messages=messages,
                tools=tools,
                tool_choice="auto",
                temperature=self._temperature,
            )
        except Exception as e:
            raise RuntimeError(f"OpenAI-compatible API error: {e}") from e

        if not response.choices:
            return ("", "", [])

        msg = response.choices[0].message
        raw_text = msg.content or ""

        # Extract reasoning from  blocks (Ollama / MiMo)
        text, reasoning = _extract_think(raw_text)

        # Normalise tool calls
        tool_calls: list[dict] = []
        if msg.tool_calls:
            for tc in msg.tool_calls:
                args = tc.function.arguments or "{}"
                if isinstance(args, dict):
                    args = json.dumps(args)
                tool_calls.append(
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.function.name,
                            "arguments": args,
                        },
                    }
                )

        return (text, reasoning, tool_calls)
