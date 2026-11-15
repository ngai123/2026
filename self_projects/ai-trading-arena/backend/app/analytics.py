"""Per-model analytics: risk-adjusted performance, cost/usage, and behavior.

All computed from what's already persisted (equity_snapshots + trade_logs), so
these stay correct as history grows.
"""
from __future__ import annotations

import math

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import EquitySnapshot, Model, TradeLog

# Keyword buckets for behavior analysis (matched against reasoning + thinking).
_KEYWORDS = {
    "on-chain": [
        "on-chain", "onchain", "hash rate", "hashrate", "active address",
        "mempool", "miner", "difficulty", "network", "whale",
    ],
    "technical": [
        "momentum", "resistance", "support", "trend", "moving average",
        "rsi", "macd", "volume", "breakout", "oversold", "overbought",
        "candle", "consolidat",
    ],
    "sentiment": [
        "fear", "greed", "sentiment", "fomo", "panic", "bullish", "bearish",
    ],
}


def _equity_series(db: Session, model_id: int) -> list[float]:
    snaps = db.scalars(
        select(EquitySnapshot)
        .where(EquitySnapshot.model_id == model_id)
        .order_by(EquitySnapshot.created_at)
    ).all()
    return [s.equity for s in snaps]


def _hourly_equity(db: Session, model_id: int) -> list[float]:
    """Last equity value per clock-hour — a sane base for Sharpe/vol instead of
    annualizing noisy 2-minute snapshots."""
    snaps = db.scalars(
        select(EquitySnapshot)
        .where(EquitySnapshot.model_id == model_id)
        .order_by(EquitySnapshot.created_at)
    ).all()
    by_hour: dict[str, float] = {}
    for s in snaps:
        by_hour[s.created_at.strftime("%Y-%m-%d %H")] = s.equity  # last wins
    return [by_hour[k] for k in sorted(by_hour)]


def quick_sharpe(db: Session, model_id: int) -> float | None:
    """Annualized Sharpe from hourly equity — for feeding a model its own score."""
    rets = _returns(_hourly_equity(db, model_id))
    if len(rets) < 2:
        return None
    mean = sum(rets) / len(rets)
    var = sum((r - mean) ** 2 for r in rets) / (len(rets) - 1)
    std = math.sqrt(var)
    if std == 0:
        return None
    return round((mean / std) * math.sqrt(24 * 365), 2)


def _returns(series: list[float]) -> list[float]:
    out = []
    for a, b in zip(series, series[1:]):
        if a > 0:
            out.append(b / a - 1.0)
    return out


def performance(db: Session, model: Model, benchmark_return_pct: float | None) -> dict:
    series = _equity_series(db, model.id)
    start = model.portfolio.starting_cash or 1.0
    equity = series[-1] if series else model.portfolio.cash
    total_return_pct = (equity - start) / start * 100

    # Sharpe / volatility from HOURLY returns (24/7 crypto → 8760 hrs/year).
    # Needs a few hours of history; until then they read as "—".
    rets = _returns(_hourly_equity(db, model.id))
    sharpe = None
    vol_pct = None
    if len(rets) >= 2:
        mean = sum(rets) / len(rets)
        var = sum((r - mean) ** 2 for r in rets) / (len(rets) - 1)
        std = math.sqrt(var)
        periods_per_year = 24 * 365  # hourly, 24/7
        if std > 0:
            sharpe = (mean / std) * math.sqrt(periods_per_year)
        vol_pct = std * math.sqrt(periods_per_year) * 100

    # Max drawdown on the equity curve.
    max_dd_pct = 0.0
    peak = -math.inf
    for v in series:
        peak = max(peak, v)
        if peak > 0:
            max_dd_pct = max(max_dd_pct, (peak - v) / peak * 100)

    # Trades + realized win rate over CLOSED positions (perp: a close can be a
    # BUY-to-cover or a SELL-to-close, both carry realized_pnl).
    trades = db.scalars(
        select(TradeLog).where(
            TradeLog.model_id == model.id, TradeLog.status == "executed"
        )
    ).all()
    n_trades = len(trades)
    closed = [t for t in trades if t.realized_pnl != 0]
    wins = [t for t in closed if t.realized_pnl > 0]
    win_rate_pct = (len(wins) / len(closed) * 100) if closed else None
    realized_pnl = sum(t.realized_pnl for t in trades)

    alpha_pct = (
        round(total_return_pct - benchmark_return_pct, 2)
        if benchmark_return_pct is not None
        else None
    )

    return {
        "total_return_pct": round(total_return_pct, 2),
        "sharpe": round(sharpe, 2) if sharpe is not None else None,
        "max_drawdown_pct": round(max_dd_pct, 2),
        "volatility_pct": round(vol_pct, 2) if vol_pct is not None else None,
        "alpha_vs_benchmark_pct": alpha_pct,
        "n_trades": n_trades,
        "win_rate_pct": round(win_rate_pct, 1) if win_rate_pct is not None else None,
        "realized_pnl": round(realized_pnl, 2),
    }


def _pearson(xs: list[float], ys: list[float]) -> float | None:
    n = len(xs)
    if n < 3:
        return None
    mx, my = sum(xs) / n, sum(ys) / n
    cov = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    vx = sum((x - mx) ** 2 for x in xs)
    vy = sum((y - my) ** 2 for y in ys)
    if vx <= 0 or vy <= 0:
        return None
    return cov / math.sqrt(vx * vy)


def risk(db: Session, model: Model) -> dict:
    """Leverage usage, liquidations, reliability, and confidence calibration."""
    rows = db.scalars(select(TradeLog).where(TradeLog.model_id == model.id)).all()
    # Opens carry the leverage used (realized_pnl == 0 on entry).
    opens = [
        t for t in rows
        if t.status == "executed" and t.action in ("BUY", "SELL")
        and t.shares > 0 and abs(t.realized_pnl) < 1e-9
    ]
    levs = [t.leverage for t in opens if t.leverage]
    avg_leverage = round(sum(levs) / len(levs), 2) if levs else 0.0

    n_liquidations = sum(1 for t in rows if t.status == "liquidated")

    # Reliability: failed LLM turns / total LLM turns.
    errors = sum(1 for t in rows if t.status == "error")
    turns = sum(1 for t in rows if t.total_tokens > 0) + errors
    error_rate_pct = round(errors / turns * 100, 1) if turns else 0.0

    # Calibration: does higher confidence on closed trades predict more P&L?
    closed = [t for t in rows if abs(t.realized_pnl) > 1e-9 and t.confidence > 0]
    corr = _pearson([t.confidence for t in closed], [t.realized_pnl for t in closed])

    return {
        "avg_leverage": avg_leverage,
        "n_liquidations": n_liquidations,
        "error_rate_pct": error_rate_pct,
        "confidence_pnl_corr": round(corr, 2) if corr is not None else None,
    }


def usage(db: Session, model: Model) -> dict:
    rows = db.scalars(
        select(TradeLog).where(TradeLog.model_id == model.id)
    ).all()
    calls = [r for r in rows if r.total_tokens > 0 or r.cost_usd > 0]
    total_cost = sum(r.cost_usd for r in rows)
    total_tokens = sum(r.total_tokens for r in rows)
    n_calls = len(calls)
    return {
        "prompt_tokens": sum(r.prompt_tokens for r in rows),
        "completion_tokens": sum(r.completion_tokens for r in rows),
        "total_tokens": total_tokens,
        "total_cost_usd": round(total_cost, 4),
        "n_calls": n_calls,
        "avg_cost_per_call_usd": round(total_cost / n_calls, 5) if n_calls else 0.0,
    }


def behavior(db: Session, model: Model) -> dict:
    rows = db.scalars(
        select(TradeLog).where(TradeLog.model_id == model.id)
    ).all()
    buy = sum(1 for r in rows if r.action == "BUY")
    sell = sum(1 for r in rows if r.action == "SELL")
    hold = sum(1 for r in rows if r.action == "HOLD")
    execed = [r for r in rows if r.status == "executed" and r.action in ("BUY", "SELL")]
    avg_conviction = (
        round(sum(r.allocation_pct for r in execed) / len(execed), 1)
        if execed
        else 0.0
    )
    focus = {k: 0 for k in _KEYWORDS}
    for r in rows:
        text = f"{r.reasoning}\n{r.thinking}".lower()
        for cat, words in _KEYWORDS.items():
            if any(w in text for w in words):
                focus[cat] += 1
    return {
        "buy": buy,
        "sell": sell,
        "hold": hold,
        "avg_conviction_pct": avg_conviction,
        "focus": focus,
    }
