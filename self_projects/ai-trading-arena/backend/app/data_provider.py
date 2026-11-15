"""Market data via yfinance.

Two responsibilities:
  - latest close prices (used to mark portfolios and execute trades)
  - a short recent OHLCV history per ticker (fed to the LLMs as context)

yfinance hits Yahoo's public endpoints, which are flaky, so everything here is
defensive and cached briefly to avoid hammering the API inside one loop pass.
"""
from __future__ import annotations

import logging
import math
import time
from dataclasses import dataclass

import yfinance as yf

logger = logging.getLogger("arena.data")

# (price_cache, ts) keyed by ticker — short TTL so one loop pass is consistent.
_PRICE_CACHE: dict[str, tuple[float, float]] = {}
_PRICE_TTL_SECONDS = 60


@dataclass
class OHLCVBar:
    date: str
    open: float
    high: float
    low: float
    close: float
    volume: int


def get_latest_price(ticker: str) -> float | None:
    """Most recent available close. None if it can't be fetched."""
    now = time.time()
    cached = _PRICE_CACHE.get(ticker)
    if cached and now - cached[1] < _PRICE_TTL_SECONDS:
        return cached[0]

    try:
        hist = yf.Ticker(ticker).history(period="5d", interval="1d")
        if hist.empty:
            logger.warning("No price history for %s", ticker)
            return None
        price = float(hist["Close"].iloc[-1])
        # Guard against NaN/inf — a bad print would corrupt all equity math.
        if not math.isfinite(price) or price <= 0:
            logger.warning("Non-finite/zero price for %s: %r", ticker, price)
            return None
        _PRICE_CACHE[ticker] = (price, now)
        return price
    except Exception as exc:  # noqa: BLE001
        logger.warning("Price fetch failed for %s: %s", ticker, exc)
        return None


def get_latest_prices(tickers: list[str]) -> dict[str, float]:
    """Best-effort price map; tickers that fail are simply omitted."""
    out: dict[str, float] = {}
    for t in tickers:
        p = get_latest_price(t)
        if p is not None:
            out[t] = p
    return out


_HIST_CACHE: dict[str, tuple[dict, float]] = {}
_HIST_TTL_SECONDS = 300


def get_ohlc_arrays(ticker: str, period: str = "30d", interval: str = "1h") -> dict:
    """Intraday OHLC arrays (highs/lows/closes/volumes) for indicator math.

    Cached briefly so one tick's indicator computation hits the network once.
    Returns {} on failure.
    """
    key = f"{ticker}:{period}:{interval}"
    now = time.time()
    cached = _HIST_CACHE.get(key)
    if cached and now - cached[1] < _HIST_TTL_SECONDS:
        return cached[0]
    try:
        hist = yf.Ticker(ticker).history(period=period, interval=interval)
        if hist.empty:
            return {}
        out = {
            "closes": [float(x) for x in hist["Close"].tolist()],
            "highs": [float(x) for x in hist["High"].tolist()],
            "lows": [float(x) for x in hist["Low"].tolist()],
            "volumes": [float(x) for x in hist["Volume"].tolist()],
        }
        _HIST_CACHE[key] = (out, now)
        return out
    except Exception as exc:  # noqa: BLE001
        logger.warning("OHLC arrays fetch failed for %s: %s", ticker, exc)
        return {}


def get_recent_ohlcv(ticker: str, days: int = 10) -> list[OHLCVBar]:
    """Daily OHLCV bars for the last `days` sessions."""
    try:
        hist = yf.Ticker(ticker).history(period=f"{days + 5}d", interval="1d")
        if hist.empty:
            return []
        hist = hist.tail(days)
        bars: list[OHLCVBar] = []
        for idx, row in hist.iterrows():
            bars.append(
                OHLCVBar(
                    date=idx.strftime("%Y-%m-%d"),
                    open=round(float(row["Open"]), 2),
                    high=round(float(row["High"]), 2),
                    low=round(float(row["Low"]), 2),
                    close=round(float(row["Close"]), 2),
                    volume=int(row["Volume"]),
                )
            )
        return bars
    except Exception as exc:  # noqa: BLE001
        logger.warning("OHLCV fetch failed for %s: %s", ticker, exc)
        return []
