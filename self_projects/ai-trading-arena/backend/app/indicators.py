"""Pure-function technical indicators.

Operate on plain lists of floats so they're easy to test and free of pandas at
call sites. Each returns the latest value (or None if not enough data).
"""
from __future__ import annotations

import math


def sma(closes: list[float], period: int) -> float | None:
    if len(closes) < period:
        return None
    return sum(closes[-period:]) / period


def ema(closes: list[float], period: int) -> float | None:
    if len(closes) < period:
        return None
    k = 2 / (period + 1)
    e = sum(closes[:period]) / period
    for price in closes[period:]:
        e = price * k + e * (1 - k)
    return e


def _ema_series(closes: list[float], period: int) -> list[float]:
    if len(closes) < period:
        return []
    k = 2 / (period + 1)
    e = sum(closes[:period]) / period
    out = [e]
    for price in closes[period:]:
        e = price * k + e * (1 - k)
        out.append(e)
    return out


def rsi(closes: list[float], period: int = 14) -> float | None:
    if len(closes) < period + 1:
        return None
    gains, losses = [], []
    for a, b in zip(closes[-period - 1 :], closes[-period:]):
        diff = b - a
        gains.append(max(diff, 0.0))
        losses.append(max(-diff, 0.0))
    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def macd(closes: list[float]) -> tuple[float, float, float] | None:
    """Return (macd, signal, histogram) using 12/26/9."""
    if len(closes) < 35:
        return None
    fast = _ema_series(closes, 12)
    slow = _ema_series(closes, 26)
    n = min(len(fast), len(slow))
    macd_line = [f - s for f, s in zip(fast[-n:], slow[-n:])]
    if len(macd_line) < 9:
        return None
    signal_series = _ema_series(macd_line, 9)
    macd_v = macd_line[-1]
    signal_v = signal_series[-1]
    return macd_v, signal_v, macd_v - signal_v


def bollinger_pctb(closes: list[float], period: int = 20, mult: float = 2.0) -> float | None:
    """%B: where price sits in the bands (0 = lower, 1 = upper)."""
    if len(closes) < period:
        return None
    window = closes[-period:]
    mid = sum(window) / period
    std = math.sqrt(sum((c - mid) ** 2 for c in window) / period)
    if std == 0:
        return 0.5
    upper, lower = mid + mult * std, mid - mult * std
    return (closes[-1] - lower) / (upper - lower)


def atr_pct(highs: list[float], lows: list[float], closes: list[float], period: int = 14) -> float | None:
    """Average True Range as a percent of price (volatility proxy)."""
    if len(closes) < period + 1:
        return None
    trs = []
    for i in range(1, len(closes)):
        tr = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i] - closes[i - 1]),
        )
        trs.append(tr)
    atr = sum(trs[-period:]) / period
    return atr / closes[-1] * 100 if closes[-1] else None


def pct_change(closes: list[float], lookback: int) -> float | None:
    if len(closes) <= lookback or closes[-lookback - 1] == 0:
        return None
    return (closes[-1] / closes[-lookback - 1] - 1) * 100


def realized_vol_pct(closes: list[float], lookback: int) -> float | None:
    """Stdev of recent simple returns, in percent."""
    if len(closes) < lookback + 1:
        return None
    rets = [
        closes[i] / closes[i - 1] - 1
        for i in range(len(closes) - lookback, len(closes))
        if closes[i - 1]
    ]
    if len(rets) < 2:
        return None
    mean = sum(rets) / len(rets)
    var = sum((r - mean) ** 2 for r in rets) / (len(rets) - 1)
    return math.sqrt(var) * 100
