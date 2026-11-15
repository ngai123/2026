"""Crypto Fear & Greed Index — free, no key (alternative.me).

A widely-watched 0-100 sentiment gauge (0 = extreme fear, 100 = extreme greed).
Updates daily, so we cache aggressively. Best-effort: returns {} on failure.
"""
from __future__ import annotations

import logging
import time

import requests

logger = logging.getLogger("arena.sentiment")

_CACHE: dict[str, tuple[dict, float]] = {}
_TTL_SECONDS = 3600  # updates ~daily
_TIMEOUT = 8


def get_fear_greed() -> dict:
    cached = _CACHE.get("fng")
    if cached and time.time() - cached[1] < _TTL_SECONDS:
        return cached[0]
    try:
        r = requests.get(
            "https://api.alternative.me/fng/?limit=1",
            timeout=_TIMEOUT,
            headers={"User-Agent": "ai-trading-arena"},
        )
        r.raise_for_status()
        d = r.json()["data"][0]
        out = {
            "value": int(d["value"]),
            "classification": d["value_classification"],
        }
        _CACHE["fng"] = (out, time.time())
        return out
    except Exception as exc:  # noqa: BLE001
        logger.warning("fear & greed fetch failed: %s", exc)
        return {}


def format_sentiment_block() -> tuple[str, dict]:
    d = get_fear_greed()
    if not d:
        return "", {}
    return (
        f"Crypto Fear & Greed Index: {d['value']}/100 ({d['classification']})",
        d,
    )
