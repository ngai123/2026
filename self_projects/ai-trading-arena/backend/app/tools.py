"""Tools the trading models can call to investigate before deciding.

All tools are local, deterministic, read-only and FREE (no extra LLM cost) — they
just surface data we already fetch/compute. This is how the harness lets a model
use its intelligence: pull deeper history, compute indicators, check key levels,
funding, fundamentals, news, cross-asset strength, or do sizing math on demand.
"""
from __future__ import annotations

import json
import logging

from . import (
    data_provider,
    fundamentals_provider,
    funding_provider,
    indicators,
    news_provider,
    onchain_provider,
)
from .config import get_settings

logger = logging.getLogger("arena.tools")
settings = get_settings()


def _norm(coin: str) -> str:
    t = (coin or "").strip().upper().replace("/", "-")
    if ":" in t:
        t = t.split(":")[-1]
    if t in settings.ticker_list:
        return t
    if f"{t}-USD" in settings.ticker_list:
        return f"{t}-USD"
    for u in settings.ticker_list:
        if u.split("-")[0] == t.split("-")[0]:
            return u
    return t


# --------------------------------------------------------------------------
# Tool implementations (return concise strings)
# --------------------------------------------------------------------------
def _get_price_history(coin: str, interval: str = "1h", bars: int = 48) -> str:
    coin = _norm(coin)
    bars = max(5, min(int(bars or 48), 200))
    if interval == "1d":
        rows = data_provider.get_recent_ohlcv(coin, days=bars)
        series = [f"{b.date} C:{b.close} V:{b.volume}" for b in rows]
    else:
        arr = data_provider.get_ohlc_arrays(coin, period="30d", interval="1h")
        closes = (arr.get("closes") or [])[-bars:]
        series = [f"{c:,.4f}" for c in closes]
    if not series:
        return f"No history for {coin}."
    return f"{coin} {interval} (oldest->newest):\n" + " | ".join(series)


def _get_indicators(coin: str) -> str:
    coin = _norm(coin)
    arr = data_provider.get_ohlc_arrays(coin, period="30d", interval="1h")
    c = arr.get("closes") or []
    if len(c) < 30:
        return f"Not enough data for {coin}."
    h, l = arr.get("highs", []), arr.get("lows", [])
    out = {
        "price": round(c[-1], 4),
        "sma20": round(indicators.sma(c, 20) or 0, 4),
        "sma50": round(indicators.sma(c, 50) or 0, 4),
        "rsi14": round(indicators.rsi(c, 14) or 0, 1),
        "bollinger_pctb": round(indicators.bollinger_pctb(c, 20) or 0, 2),
        "atr_pct": round(indicators.atr_pct(h, l, c, 14) or 0, 2),
        "ret_24h_pct": round(indicators.pct_change(c, 24) or 0, 2),
        "ret_7d_pct": round(indicators.pct_change(c, 168) or 0, 2),
        "realized_vol_24h_pct": round(indicators.realized_vol_pct(c, 24) or 0, 2),
    }
    m = indicators.macd(c)
    out["macd_hist"] = round(m[2], 3) if m else None
    return f"{coin} indicators: {json.dumps(out)}"


def _get_key_levels(coin: str) -> str:
    coin = _norm(coin)
    rows = data_provider.get_recent_ohlcv(coin, days=60)
    if not rows:
        return f"No data for {coin}."
    price = rows[-1].close
    highs = [b.high for b in rows]
    lows = [b.low for b in rows]
    hi60, lo60 = max(highs), min(lows)
    hi20, lo20 = max(highs[-20:]), min(lows[-20:])
    return (
        f"{coin} key levels (price {price:,.4f}): "
        f"60d high {hi60:,.4f} ({(price/hi60-1)*100:+.1f}%), "
        f"60d low {lo60:,.4f} ({(price/lo60-1)*100:+.1f}%), "
        f"20d high {hi20:,.4f}, 20d low {lo20:,.4f}"
    )


def _get_funding(coin: str) -> str:
    blk, _ = funding_provider.format_funding_block([_norm(coin)])
    return blk or f"No funding data for {coin}."


def _get_fundamentals(coin: str = "") -> str:
    tickers = [_norm(coin)] if coin else settings.ticker_list
    data = fundamentals_provider.get_fundamentals(tickers)
    if not data:
        return "No fundamentals available."
    lines = []
    for tk, d in data.items():
        lines.append(
            f"{tk}: mcap ${(d.get('market_cap') or 0)/1e9:.1f}B | "
            f"vol24h ${(d.get('volume_24h') or 0)/1e9:.2f}B | "
            f"24h {d.get('change_24h') or 0:+.1f}% | 7d {d.get('change_7d') or 0:+.1f}% | "
            f"from ATH {d.get('ath_change_pct') or 0:+.0f}%"
        )
    return "\n".join(lines)


def _get_onchain() -> str:
    blk, _ = onchain_provider.format_onchain_block(settings.ticker_list)
    return blk or "No on-chain data (BTC only)."


def _get_news() -> str:
    return news_provider.format_news_block() or "No fresh news."


def _compare_universe() -> str:
    """Relative strength: 24h/7d return + RSI for every coin, to spot leaders."""
    lines = []
    for t in settings.ticker_list:
        arr = data_provider.get_ohlc_arrays(t, period="30d", interval="1h")
        c = arr.get("closes") or []
        if len(c) < 30:
            continue
        lines.append(
            f"{t}: 24h {indicators.pct_change(c,24) or 0:+.2f}% | "
            f"7d {indicators.pct_change(c,168) or 0:+.2f}% | RSI {indicators.rsi(c,14) or 0:.0f}"
        )
    return "Cross-asset relative strength:\n" + "\n".join(lines)


def _calc(expression: str) -> str:
    """Safe arithmetic for sizing/risk math (digits and + - * / ( ) . % only)."""
    import re

    expr = (expression or "").strip()
    if not re.fullmatch(r"[0-9eE+\-*/(). %]+", expr):
        return "calc error: only numbers and + - * / ( ) % allowed."
    try:
        val = eval(expr, {"__builtins__": {}}, {})  # noqa: S307 - sanitized above
        return f"{expr} = {val}"
    except Exception as exc:  # noqa: BLE001
        return f"calc error: {exc}"


_DISPATCH = {
    "get_price_history": _get_price_history,
    "get_indicators": _get_indicators,
    "get_key_levels": _get_key_levels,
    "get_funding": _get_funding,
    "get_fundamentals": _get_fundamentals,
    "get_onchain": _get_onchain,
    "get_news": _get_news,
    "compare_universe": _compare_universe,
    "calc": _calc,
}


def dispatch(name: str, args: dict) -> str:
    fn = _DISPATCH.get(name)
    if fn is None:
        return f"unknown tool: {name}"
    try:
        return str(fn(**(args or {})))[:6000]
    except TypeError as exc:
        return f"bad arguments for {name}: {exc}"
    except Exception as exc:  # noqa: BLE001
        logger.warning("tool %s failed: %s", name, exc)
        return f"{name} failed: {exc}"


_C = {"type": "string"}
TOOL_SCHEMAS = [
    {"type": "function", "function": {
        "name": "get_price_history",
        "description": "Recent OHLCV/closes for a coin. interval '1h' or '1d'.",
        "parameters": {"type": "object", "properties": {
            "coin": _C, "interval": {"type": "string", "enum": ["1h", "1d"]},
            "bars": {"type": "integer"}}, "required": ["coin"]}}},
    {"type": "function", "function": {
        "name": "get_indicators",
        "description": "Computed technical indicators (SMA/RSI/MACD/Bollinger/ATR, returns) for a coin.",
        "parameters": {"type": "object", "properties": {"coin": _C}, "required": ["coin"]}}},
    {"type": "function", "function": {
        "name": "get_key_levels",
        "description": "Support/resistance: 60d & 20d high/low and distance from price.",
        "parameters": {"type": "object", "properties": {"coin": _C}, "required": ["coin"]}}},
    {"type": "function", "function": {
        "name": "get_funding",
        "description": "Perp funding rate + open interest (crowd positioning) for a coin.",
        "parameters": {"type": "object", "properties": {"coin": _C}, "required": ["coin"]}}},
    {"type": "function", "function": {
        "name": "get_fundamentals",
        "description": "Market fundamentals (mcap, volume, 24h/7d change, ATH distance). Omit coin for all.",
        "parameters": {"type": "object", "properties": {"coin": _C}}}},
    {"type": "function", "function": {
        "name": "get_onchain",
        "description": "BTC on-chain network fundamentals (hash rate, active addresses, tx volume).",
        "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {
        "name": "get_news",
        "description": "Recent crypto news headlines.",
        "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {
        "name": "compare_universe",
        "description": "Cross-asset relative strength (24h/7d return + RSI for every coin).",
        "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {
        "name": "calc",
        "description": "Evaluate an arithmetic expression for sizing/risk math.",
        "parameters": {"type": "object", "properties": {"expression": _C}, "required": ["expression"]}}},
]
