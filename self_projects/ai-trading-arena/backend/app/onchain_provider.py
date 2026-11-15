"""Free BTC on-chain data — blockchain.com + mempool.space (no API key).

Gives the models network-activity context beyond price: hash rate, active
addresses, transaction volume, miner revenue, mempool congestion and fees.
Everything is best-effort and cached (these metrics move slowly); on any failure
we simply omit the data so the models still get OHLCV.
"""
from __future__ import annotations

import logging
import time

import requests

logger = logging.getLogger("arena.onchain")

_CACHE: dict[str, tuple[dict, float]] = {}
_TTL_SECONDS = 600  # 10 min — on-chain stats update slowly
_TIMEOUT = 8


def _get_json(url: str):
    r = requests.get(url, timeout=_TIMEOUT, headers={"User-Agent": "ai-trading-arena"})
    r.raise_for_status()
    return r.json()


def get_btc_onchain() -> dict:
    """Current BTC on-chain metrics. Returns {} if everything fails."""
    cached = _CACHE.get("btc")
    if cached and time.time() - cached[1] < _TTL_SECONDS:
        return cached[0]

    data: dict = {}
    # --- blockchain.com aggregate stats ---
    try:
        s = _get_json("https://api.blockchain.info/stats?format=json")
        data["hash_rate_ehs"] = round(s.get("hash_rate", 0) / 1e9, 1)  # GH/s -> EH/s
        data["difficulty"] = s.get("difficulty")
        data["tx_count_24h"] = s.get("n_tx")
        data["volume_usd_24h"] = s.get("estimated_transaction_volume_usd")
        data["minutes_between_blocks"] = round(s.get("minutes_between_blocks", 0), 1)
        # These /stats fields are unreliable (can come back 0 or negative) — only
        # keep them when they're sane, so we never feed garbage to the models.
        rev = s.get("miners_revenue_usd")
        if isinstance(rev, (int, float)) and rev > 0:
            data["miners_revenue_usd_24h"] = rev
    except Exception as exc:  # noqa: BLE001
        logger.warning("blockchain.info stats failed: %s", exc)

    # --- active addresses (latest point of the chart) ---
    try:
        c = _get_json(
            "https://api.blockchain.info/charts/n-unique-addresses"
            "?timespan=5days&format=json&sampled=true"
        )
        vals = c.get("values") or []
        if vals:
            data["active_addresses"] = int(vals[-1]["y"])
    except Exception as exc:  # noqa: BLE001
        logger.warning("active-addresses chart failed: %s", exc)

    # --- mempool congestion + fees ---
    try:
        mp = _get_json("https://mempool.space/api/mempool")
        data["mempool_tx_count"] = mp.get("count")
    except Exception as exc:  # noqa: BLE001
        logger.warning("mempool size failed: %s", exc)
    try:
        fees = _get_json("https://mempool.space/api/v1/fees/recommended")
        data["fee_fast_satvb"] = fees.get("fastestFee")
        data["fee_hour_satvb"] = fees.get("hourFee")
    except Exception as exc:  # noqa: BLE001
        logger.warning("recommended fees failed: %s", exc)

    if data:
        _CACHE["btc"] = (data, time.time())
    return data


def _fmt(n) -> str:
    if n is None:
        return "n/a"
    if isinstance(n, (int, float)):
        if abs(n) >= 1e9:
            return f"{n/1e9:.2f}B"
        if abs(n) >= 1e6:
            return f"{n/1e6:.2f}M"
        if abs(n) >= 1e3:
            return f"{n:,.0f}"
        return f"{n:g}"
    return str(n)


def format_onchain_block(tickers: list[str]) -> tuple[str, dict]:
    """Build the prompt's on-chain block (BTC only). Returns (text, raw_dict)."""
    if not any(t.upper().startswith("BTC") for t in tickers):
        return "", {}
    d = get_btc_onchain()
    if not d:
        return "", {}
    lines = [
        f"Hash rate: {_fmt(d.get('hash_rate_ehs'))} EH/s | "
        f"Difficulty: {_fmt(d.get('difficulty'))} | "
        f"Avg block time: {d.get('minutes_between_blocks', 'n/a')} min",
        f"Active addresses (24h): {_fmt(d.get('active_addresses'))} | "
        f"Tx count (24h): {_fmt(d.get('tx_count_24h'))} | "
        f"On-chain volume (24h): ${_fmt(d.get('volume_usd_24h'))}",
    ]
    if "miners_revenue_usd_24h" in d:
        lines.append(f"Miner revenue (24h): ${_fmt(d['miners_revenue_usd_24h'])}")
    if d.get("mempool_tx_count") or d.get("fee_fast_satvb"):
        lines.append(
            f"Mempool: {_fmt(d.get('mempool_tx_count'))} txs | "
            f"Fees: {d.get('fee_fast_satvb', 'n/a')} sat/vB (fast), "
            f"{d.get('fee_hour_satvb', 'n/a')} (1h)"
        )
    return "\n".join(lines), d
