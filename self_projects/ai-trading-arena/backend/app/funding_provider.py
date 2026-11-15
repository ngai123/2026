"""Perp positioning signals — funding rate + open interest (Bybit linear perps).

Funding rate reveals crowd positioning: strongly positive = longs crowded (pay
shorts), negative = shorts crowded. Open interest shows leverage build-up. These
are the perp signals nof1 fed its agents. Free, no key; best-effort + cached.
(Bybit chosen over Binance, which is geo-restricted in many regions.)
"""
from __future__ import annotations

import logging
import time

import requests

logger = logging.getLogger("arena.funding")

_CACHE: dict[str, tuple[dict, float]] = {}
_TTL_SECONDS = 600
_TIMEOUT = 8
_BASE = "https://api.bybit.com"


def _symbol(ticker: str) -> str:
    """BTC-USD -> BTCUSDT (Bybit linear perp symbol)."""
    return ticker.upper().split("-")[0] + "USDT"


def get_funding(ticker: str) -> dict:
    """Funding rate + open interest for one coin. {} on failure."""
    now = time.time()
    cached = _CACHE.get(ticker)
    if cached and now - cached[1] < _TTL_SECONDS:
        return cached[0]
    sym = _symbol(ticker)
    out: dict = {}
    try:
        r = requests.get(
            f"{_BASE}/v5/market/tickers?category=linear&symbol={sym}",
            timeout=_TIMEOUT,
            headers={"User-Agent": "ai-trading-arena"},
        )
        r.raise_for_status()
        rows = (r.json().get("result") or {}).get("list") or []
        if rows:
            d = rows[0]
            out["funding_rate"] = float(d.get("fundingRate", 0)) * 100  # percent / 8h
            out["open_interest"] = float(d.get("openInterest", 0))  # in coins
            out["mark_price"] = float(d.get("markPrice", 0) or 0)
    except Exception as exc:  # noqa: BLE001
        logger.warning("funding fetch failed for %s: %s", sym, exc)
    if out:
        _CACHE[ticker] = (out, now)
    return out


def format_funding_block(tickers: list[str]) -> tuple[str, dict]:
    """Per-coin funding + OI block for the prompt. Returns (text, raw)."""
    lines: list[str] = []
    raw: dict = {}
    for t in tickers:
        d = get_funding(t)
        if not d:
            continue
        raw[t] = d
        fr = d.get("funding_rate")
        oi = d.get("open_interest")
        tilt = ""
        if fr is not None:
            tilt = "longs crowded" if fr > 0.01 else "shorts crowded" if fr < -0.01 else "balanced"
        parts = []
        if fr is not None:
            parts.append(f"funding {fr:+.4f}%/8h ({tilt})")
        if oi is not None:
            parts.append(f"OI {oi:,.0f} {t.split('-')[0]}")
        if parts:
            lines.append(f"{t}: " + " | ".join(parts))
    return "\n".join(lines), raw
