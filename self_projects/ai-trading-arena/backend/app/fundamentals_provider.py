"""Per-coin market fundamentals (CoinGecko, free, no key).

Covers ALL coins (BTC on-chain only covers BTC), giving market cap, 24h/7d
moves, volume, supply, and distance from all-time high. Cached; best-effort.
"""
from __future__ import annotations

import logging
import time

import requests

logger = logging.getLogger("arena.fundamentals")

# Our ticker -> CoinGecko id.
_IDS = {
    "BTC-USD": "bitcoin",
    "ETH-USD": "ethereum",
    "SOL-USD": "solana",
    "XRP-USD": "ripple",
    "DOGE-USD": "dogecoin",
    "BNB-USD": "binancecoin",
    "ADA-USD": "cardano",
}

_CACHE: dict[str, tuple[dict, float]] = {}
_TTL_SECONDS = 600
_TIMEOUT = 10


def get_fundamentals(tickers: list[str]) -> dict[str, dict]:
    """Market data per ticker: {ticker: {...}}. {} on failure."""
    key = ",".join(sorted(tickers))
    now = time.time()
    cached = _CACHE.get(key)
    if cached and now - cached[1] < _TTL_SECONDS:
        return cached[0]
    ids = [_IDS[t] for t in tickers if t in _IDS]
    if not ids:
        return {}
    try:
        r = requests.get(
            "https://api.coingecko.com/api/v3/coins/markets",
            params={
                "vs_currency": "usd",
                "ids": ",".join(ids),
                "price_change_percentage": "24h,7d,30d",
            },
            timeout=_TIMEOUT,
            headers={"User-Agent": "ai-trading-arena"},
        )
        r.raise_for_status()
        id_to_ticker = {v: k for k, v in _IDS.items()}
        out: dict[str, dict] = {}
        for row in r.json():
            tk = id_to_ticker.get(row.get("id"))
            if not tk:
                continue
            out[tk] = {
                "market_cap": row.get("market_cap"),
                "volume_24h": row.get("total_volume"),
                "change_24h": row.get("price_change_percentage_24h_in_currency"),
                "change_7d": row.get("price_change_percentage_7d_in_currency"),
                "change_30d": row.get("price_change_percentage_30d_in_currency"),
                "ath_change_pct": row.get("ath_change_percentage"),
                "circulating_supply": row.get("circulating_supply"),
            }
        if out:
            _CACHE[key] = (out, now)
        return out
    except Exception as exc:  # noqa: BLE001
        logger.warning("fundamentals fetch failed: %s", exc)
        return {}
