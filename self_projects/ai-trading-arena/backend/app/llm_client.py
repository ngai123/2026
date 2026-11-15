"""OpenRouter integration + bullet-proof JSON parsing.

Models *frequently* wrap JSON in prose, markdown fences, or trailing commentary,
so `parse_decision` is layered: try strict json -> strip code fences -> extract
the first balanced {...} block -> validate against the AgentDecision schema.

`run_agents` fans out the identical prompt to every model concurrently.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
from dataclasses import dataclass

from openai import AsyncOpenAI

from . import tools as _tools
from .config import AgentSpec, get_settings
from .schemas import AgentTurn, CoinDecision

logger = logging.getLogger("arena.llm")
settings = get_settings()

_client = AsyncOpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=settings.openrouter_api_key,
    default_headers={
        # OpenRouter uses these for attribution / rankings (optional).
        "HTTP-Referer": settings.openrouter_app_url,
        "X-Title": settings.openrouter_app_title,
    },
)

_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL)


@dataclass
class AgentResult:
    """Outcome of one model's turn — either a decision or an error string."""

    spec: AgentSpec
    turn: AgentTurn | None
    raw: str
    error: str | None = None
    thinking: str = ""  # provider chain-of-thought, when exposed
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    cost: float = 0.0  # USD, from OpenRouter usage accounting


def _extract_first_json_object(text: str) -> str | None:
    """Return the first balanced {...} substring, respecting strings/escapes."""
    start = text.find("{")
    if start == -1:
        return None
    depth = 0
    in_str = False
    escape = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_str:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_str = False
        else:
            if ch == '"':
                in_str = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    return text[start : i + 1]
    return None


def _extract_first_json_array(text: str) -> str | None:
    """First balanced [...] substring (mirror of the object extractor)."""
    start = text.find("[")
    if start == -1:
        return None
    depth = 0
    in_str = False
    escape = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_str:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_str = False
        else:
            if ch == '"':
                in_str = True
            elif ch == "[":
                depth += 1
            elif ch == "]":
                depth -= 1
                if depth == 0:
                    return text[start : i + 1]
    return None


def _coerce_turn(data) -> tuple[AgentTurn | None, str | None]:
    """Coerce parsed JSON into an AgentTurn, tolerating several shapes:
    {"memory","decisions":[...]} | a bare [decision,...] | a single decision dict.
    """
    try:
        if isinstance(data, list):
            ds = [CoinDecision.model_validate(x) for x in data if isinstance(x, dict)]
            return AgentTurn(decisions=ds), None
        if isinstance(data, dict):
            if isinstance(data.get("decisions"), list):
                return AgentTurn.model_validate(data), None
            if "signal" in data or "coin" in data:  # a single decision
                d = CoinDecision.model_validate(data)
                return AgentTurn(memory=str(data.get("memory", "")), decisions=[d]), None
            return None, "JSON object missing 'decisions'"
        return None, "JSON was not an object or array"
    except Exception as exc:  # pydantic ValidationError
        return None, f"schema validation failed: {exc}"


def parse_turn(raw: str) -> tuple[AgentTurn | None, str | None]:
    """Best-effort parse of a model response into an AgentTurn (list of decisions)."""
    if not raw or not raw.strip():
        return None, "empty response"

    candidates: list[str] = [raw.strip()]
    for m in _FENCE_RE.findall(raw):
        candidates.append(m.strip())
    obj = _extract_first_json_object(raw)
    if obj:
        candidates.append(obj)
    arr = _extract_first_json_array(raw)
    if arr:
        candidates.append(arr)

    last_err = "no parseable JSON found"
    for cand in candidates:
        try:
            data = json.loads(cand)
        except json.JSONDecodeError as exc:
            last_err = f"json decode error: {exc.msg}"
            continue
        turn, err = _coerce_turn(data)
        if turn is not None:
            return turn, None
        last_err = err or last_err

    return None, last_err


_TIMEOUT_SECONDS = 240  # heavy reasoners (Kimi) need longer


def _extra_body() -> dict:
    """Per-call options sent to OpenRouter:
    - usage.include → return real USD cost
    - reasoning.effort → throttle chain-of-thought (the bulk of output tokens)
    """
    body: dict = {"usage": {"include": True}}
    effort = (settings.reasoning_effort or "").strip().lower()
    if effort in {"none", "off", "disabled", "false"}:
        body["reasoning"] = {"enabled": False}
    # OpenRouter allows EITHER max_tokens OR effort, not both. Prefer the hard
    # token cap when set (it bounds output cost for pure reasoners directly);
    # otherwise fall back to effort level.
    elif settings.reasoning_max_tokens > 0:
        body["reasoning"] = {"max_tokens": settings.reasoning_max_tokens}
    elif effort in {"minimal", "low", "medium", "high"}:
        body["reasoning"] = {"effort": effort}
    return body


def _content_of(resp) -> str:
    """Pull the text out of a completion, tolerating reasoning-only models.

    Some models (esp. previews / reasoning models) leave `content` empty and put
    everything in a non-standard `reasoning` field; fall back to it so we can
    still try to recover a JSON object.
    """
    if not getattr(resp, "choices", None):
        return ""
    msg = resp.choices[0].message
    content = (msg.content or "").strip()
    if content:
        return content
    # OpenRouter exposes reasoning traces here for some providers.
    for attr in ("reasoning", "reasoning_content"):
        val = getattr(msg, attr, None)
        if val:
            return str(val).strip()
    extra = getattr(msg, "model_extra", None) or {}
    return str(extra.get("reasoning") or extra.get("reasoning_content") or "").strip()


def _thinking_of(resp) -> str:
    """Pull the chain-of-thought trace some providers expose, separate from the
    final content. Empty when the model doesn't return one."""
    if not getattr(resp, "choices", None):
        return ""
    msg = resp.choices[0].message
    for attr in ("reasoning", "reasoning_content"):
        val = getattr(msg, attr, None)
        if val:
            return str(val).strip()
    extra = getattr(msg, "model_extra", None) or {}
    return str(extra.get("reasoning") or extra.get("reasoning_content") or "").strip()


async def _create(spec: AgentSpec, system_prompt: str, user_prompt: str, json_mode: bool):
    kwargs = dict(
        model=spec.model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.4,
        max_tokens=settings.max_output_tokens,
    )
    if json_mode:
        # Harmless for models that honor it; we run the defensive parser anyway.
        kwargs["response_format"] = {"type": "json_object"}
    kwargs["extra_body"] = _extra_body()
    return await asyncio.wait_for(
        _client.chat.completions.create(**kwargs), timeout=_TIMEOUT_SECONDS
    )


def _usage_of(resp) -> tuple[int, int, int, float]:
    """(prompt_tokens, completion_tokens, total_tokens, cost_usd) from a response."""
    u = getattr(resp, "usage", None)
    if u is None:
        return 0, 0, 0, 0.0
    pt = getattr(u, "prompt_tokens", 0) or 0
    ct = getattr(u, "completion_tokens", 0) or 0
    tt = getattr(u, "total_tokens", 0) or (pt + ct)
    cost = getattr(u, "cost", None)
    if cost is None:
        extra = getattr(u, "model_extra", None) or {}
        cost = extra.get("cost", 0.0)
    return pt, ct, tt, float(cost or 0.0)


async def _attempt_once(
    spec: AgentSpec, system_prompt: str, user_prompt: str
) -> AgentResult:
    """One model call with timeout + parse, never raises."""
    try:
        resp = await _create(spec, system_prompt, user_prompt, json_mode=True)
        raw = _content_of(resp)
        thinking = _thinking_of(resp)
    except asyncio.TimeoutError:
        return AgentResult(spec, None, "", error=f"timeout after {_TIMEOUT_SECONDS}s")
    except Exception as exc:  # noqa: BLE001 - surface any API error per-agent
        # Some models reject response_format; retry once without it.
        if "response_format" in str(exc).lower():
            try:
                resp = await _create(spec, system_prompt, user_prompt, json_mode=False)
                raw = _content_of(resp)
                thinking = _thinking_of(resp)
            except asyncio.TimeoutError:
                return AgentResult(
                    spec, None, "", error=f"timeout after {_TIMEOUT_SECONDS}s"
                )
            except Exception as exc2:  # noqa: BLE001
                return AgentResult(spec, None, "", error=f"api error: {exc2}")
        else:
            return AgentResult(spec, None, "", error=f"api error: {exc}")

    pt, ct, tt, cost = _usage_of(resp)
    turn, err = parse_turn(raw)
    # If parsing failed AND the model was cut off at the token cap, say so
    # clearly — it means reasoning crowded out the answer (raise MAX_OUTPUT_TOKENS).
    if turn is None:
        try:
            finish = resp.choices[0].finish_reason
        except Exception:  # noqa: BLE001
            finish = None
        if finish == "length":
            err = f"output truncated at {ct} tokens (raise MAX_OUTPUT_TOKENS)"
    return AgentResult(
        spec,
        turn,
        raw,
        error=err,
        thinking=thinking,
        prompt_tokens=pt,
        completion_tokens=ct,
        total_tokens=tt,
        cost=cost,
    )


def _is_transient(res: AgentResult) -> bool:
    """Worth one retry: timeout, rate limit / 5xx, or unparseable output."""
    if res.turn is not None:
        return False
    err = (res.error or "").lower()
    return (
        "timeout" in err
        or "429" in err
        or "rate" in err
        or "502" in err
        or "503" in err
        or "no parseable" in err
        or "json decode" in err
        or "empty response" in err
    )


_REPAIR_SYS = (
    "You reformat text into valid JSON and output NOTHING else."
)
_REPAIR_USER = (
    "The text below was supposed to be trading decisions but isn't valid JSON. "
    'Return ONLY a JSON object: {"memory": "...", "decisions": [{"coin": "...", '
    '"signal": "buy_to_enter|sell_to_enter|close|hold", "quantity": <num>, '
    '"leverage": <num>, "confidence": <0-1>, "profit_target": <num>, '
    '"stop_loss": <num>, "invalidation_condition": "...", "is_add": false, '
    '"justification": "..."}]}. Text:\n\n{raw}'
)


async def _repair(spec: AgentSpec, raw: str) -> AgentResult:
    """Targeted re-ask: hand the malformed output back and request clean JSON."""
    try:
        resp = await asyncio.wait_for(
            _client.chat.completions.create(
                model=spec.model,
                messages=[
                    {"role": "system", "content": _REPAIR_SYS},
                    {"role": "user", "content": _REPAIR_USER.format(raw=raw[:4000])},
                ],
                temperature=0.0,
                max_tokens=800,
                # Repair needs no reasoning — force it off to save output tokens.
                extra_body={"usage": {"include": True}, "reasoning": {"enabled": False}},
            ),
            timeout=_TIMEOUT_SECONDS,
        )
    except Exception as exc:  # noqa: BLE001
        return AgentResult(spec, None, raw, error=f"repair failed: {exc}")
    fixed = _content_of(resp)
    pt, ct, tt, cost = _usage_of(resp)
    turn, err = parse_turn(fixed)
    return AgentResult(
        spec, turn, raw, error=err, prompt_tokens=pt,
        completion_tokens=ct, total_tokens=tt, cost=cost,
    )


def _accumulate(into: AgentResult, *extra: AgentResult) -> AgentResult:
    for e in extra:
        into.cost += e.cost
        into.prompt_tokens += e.prompt_tokens
        into.completion_tokens += e.completion_tokens
        into.total_tokens += e.total_tokens
    return into


async def _attempt_with_tools(
    spec: AgentSpec, system_prompt: str, user_prompt: str
) -> AgentResult:
    """Agentic loop: let the model CALL tools to investigate, then answer.

    Bounded by max_tool_rounds. Tools are local/free. Usage/cost accumulate
    across rounds. Falls back to forcing a final JSON answer if the model keeps
    calling tools. Never raises.
    """
    messages: list[dict] = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]
    pt = ct = tt = 0
    cost = 0.0
    thinking = ""
    try:
        for _round in range(max(1, settings.max_tool_rounds)):
            resp = await asyncio.wait_for(
                _client.chat.completions.create(
                    model=spec.model,
                    messages=messages,
                    temperature=0.4,
                    max_tokens=settings.max_output_tokens,
                    tools=_tools.TOOL_SCHEMAS,
                    tool_choice="auto",
                    extra_body=_extra_body(),
                ),
                timeout=_TIMEOUT_SECONDS,
            )
            p, c, t, k = _usage_of(resp)
            pt += p; ct += c; tt += t; cost += k
            if not getattr(resp, "choices", None):
                break  # provider returned no choices — fall through to forced answer
            msg = resp.choices[0].message
            calls = getattr(msg, "tool_calls", None)
            if not calls:
                # Model answered — parse it.
                thinking = _thinking_of(resp)
                turn, err = parse_turn(_content_of(resp))
                if turn is not None:
                    return AgentResult(spec, turn, _content_of(resp), error=err,
                        thinking=thinking, prompt_tokens=pt, completion_tokens=ct,
                        total_tokens=tt, cost=cost)
                break  # got content but unparseable -> fall through to forced answer
            # Execute each requested tool and feed results back.
            messages.append({
                "role": "assistant",
                "content": msg.content or "",
                "tool_calls": [
                    {"id": tc.id, "type": "function",
                     "function": {"name": tc.function.name, "arguments": tc.function.arguments}}
                    for tc in calls
                ],
            })
            for tc in calls:
                try:
                    args = json.loads(tc.function.arguments or "{}")
                except json.JSONDecodeError:
                    args = {}
                result = _tools.dispatch(tc.function.name, args)
                messages.append({"role": "tool", "tool_call_id": tc.id, "content": result})

        # Out of rounds (or unparseable) — force a final JSON answer, no tools.
        messages.append({
            "role": "user",
            "content": "Stop using tools. Output your final decision now as the JSON object only.",
        })
        resp = await asyncio.wait_for(
            _client.chat.completions.create(
                model=spec.model, messages=messages, temperature=0.4,
                max_tokens=settings.max_output_tokens,
                response_format={"type": "json_object"},
                extra_body=_extra_body(),
            ),
            timeout=_TIMEOUT_SECONDS,
        )
        p, c, t, k = _usage_of(resp)
        pt += p; ct += c; tt += t; cost += k
        thinking = thinking or _thinking_of(resp)
        turn, err = parse_turn(_content_of(resp))
        return AgentResult(spec, turn, _content_of(resp), error=err, thinking=thinking,
            prompt_tokens=pt, completion_tokens=ct, total_tokens=tt, cost=cost)
    except asyncio.TimeoutError:
        return AgentResult(spec, None, "", error=f"timeout after {_TIMEOUT_SECONDS}s",
            prompt_tokens=pt, completion_tokens=ct, total_tokens=tt, cost=cost)
    except Exception as exc:  # noqa: BLE001 - tools unsupported / API error
        return AgentResult(spec, None, "", error=f"tool loop error: {exc}",
            prompt_tokens=pt, completion_tokens=ct, total_tokens=tt, cost=cost)


async def _call_one(spec: AgentSpec, system_prompt: str, user_prompt: str) -> AgentResult:
    """Call a model with layered robustness so a flaky API hiccup or malformed
    JSON doesn't unfairly force a HOLD. All attempts are billed honestly."""
    if settings.enable_tools:
        res = await _attempt_with_tools(spec, system_prompt, user_prompt)
        # If tools failed outright (model can't use them), fall back to direct.
        if res.turn is None and res.error and "tool loop error" in res.error:
            res = await _attempt_once(spec, system_prompt, user_prompt)
    else:
        res = await _attempt_once(spec, system_prompt, user_prompt)
    spent = [res]

    # 1) Retry once on a transient failure (timeout / rate-limit / 5xx / no parse).
    if _is_transient(res):
        retry = await _attempt_once(spec, system_prompt, user_prompt)
        spent.append(retry)
        res = retry

    # 2) If the model responded with text we still couldn't parse, try a repair.
    if res.turn is None and res.raw and res.raw.strip():
        fixed = await _repair(spec, res.raw)
        spent.append(fixed)
        if fixed.turn is not None:
            fixed.thinking = res.thinking
            res = fixed

    return _accumulate(res, *[s for s in spent if s is not res])


async def run_agents(
    specs: list[AgentSpec], system_prompt: str, user_prompt: str
) -> list[AgentResult]:
    """Fan the identical prompt out to all models concurrently."""
    return await asyncio.gather(
        *(_call_one(s, system_prompt, user_prompt) for s in specs)
    )
