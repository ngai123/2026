"""FastAPI app: REST endpoints + the APScheduler-driven 24/7 loop.

Run:  uvicorn app.main:app --reload --port 8000
"""
from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import datetime

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from . import analytics, engine
from .config import get_settings, is_benchmark
from .data_provider import get_latest_prices
from .database import get_db, init_db
from .market_hours import is_market_open
from .models import EquitySnapshot, Model, TradeLog
from .schemas import (
    EquityPoint,
    EquitySeries,
    HoldingCell,
    HoldingsOut,
    HoldingsRow,
    LeaderboardEntry,
    PortfolioOut,
    PositionOut,
    StatusOut,
    TradeOut,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
logger = logging.getLogger("arena.api")
settings = get_settings()

scheduler = AsyncIOScheduler()


async def _scheduled_tick() -> None:
    try:
        await engine.run_loop_once()
    except Exception:  # noqa: BLE001
        logger.exception("Scheduled tick raised")


async def _snapshot_tick() -> None:
    # Free, frequent mark-to-market so the equity curve tracks live positions.
    try:
        await asyncio.to_thread(engine.mark_to_market)
    except Exception:  # noqa: BLE001
        logger.exception("Snapshot tick raised")


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    scheduler.add_job(
        _scheduled_tick,
        trigger="interval",
        minutes=settings.loop_interval_minutes,
        id="trading_loop",
        next_run_time=datetime.now(),  # fire once on startup
        max_instances=1,
        coalesce=True,
    )
    scheduler.add_job(
        _snapshot_tick,
        trigger="interval",
        minutes=2,
        id="mark_to_market",
        max_instances=1,
        coalesce=True,
    )
    scheduler.start()
    logger.info(
        "Scheduler started: trade loop every %d min + mark-to-market every 2 min, tickers=%s",
        settings.loop_interval_minutes,
        settings.ticker_list,
    )
    yield
    scheduler.shutdown(wait=False)


app = FastAPI(title="AI Trading Arena", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # tighten for production
    allow_methods=["*"],
    allow_headers=["*"],
)


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------
def _portfolio_value(model: Model, prices: dict[str, float]) -> tuple[float, float]:
    """Return (positions_value, equity/NAV) — isolated-margin perp model:
    positions_value = sum(posted margin + unrealized PnL)."""
    pv = engine.marked_positions_value(model.portfolio, prices)
    return pv, model.portfolio.cash + pv


# --------------------------------------------------------------------------
# Endpoints
# --------------------------------------------------------------------------
@app.get("/api/status", response_model=StatusOut)
def get_status(db: Session = Depends(get_db)) -> StatusOut:
    job = scheduler.get_job("trading_loop")
    from sqlalchemy import func
    from .models import TradeLog

    off = f"{settings.timezone_offset_hours:+d} hours"
    today = float(
        db.scalar(
            select(func.coalesce(func.sum(TradeLog.cost_usd), 0.0)).where(
                func.date(TradeLog.created_at, off) == func.date("now", off)
            )
        )
        or 0.0
    )
    total = float(
        db.scalar(select(func.coalesce(func.sum(TradeLog.cost_usd), 0.0))) or 0.0
    )
    return StatusOut(
        market_open=is_market_open(),
        allow_after_hours=settings.allow_after_hours,
        tickers=settings.ticker_list,
        loop_interval_minutes=settings.loop_interval_minutes,
        last_run=engine.LAST_RUN,
        next_run=job.next_run_time if job else None,
        today_cost_usd=round(today, 4),
        total_cost_usd=round(total, 4),
        daily_cost_cap_usd=settings.daily_cost_cap_usd,
        timezone=settings.timezone,
    )


@app.get("/api/leaderboard", response_model=list[LeaderboardEntry])
def leaderboard(db: Session = Depends(get_db)) -> list[LeaderboardEntry]:
    models = db.scalars(select(Model)).all()
    prices = get_latest_prices(settings.ticker_list)

    # Benchmark return first, so we can rank everyone by ALPHA (excess over it).
    bench_return = None
    for m in models:
        if is_benchmark(m.slug):
            _, beq = _portfolio_value(m, prices)
            bstart = m.portfolio.starting_cash or 1.0
            bench_return = (beq - bstart) / bstart * 100
            break

    rows: list[LeaderboardEntry] = []
    for m in models:
        pv, equity = _portfolio_value(m, prices)
        start = m.portfolio.starting_cash or 1.0
        ret = (equity - start) / start * 100
        alpha = ret - bench_return if bench_return is not None else 0.0
        rows.append(
            LeaderboardEntry(
                model_id=m.id,
                name=m.name,
                slug=m.slug,
                cash=round(m.portfolio.cash, 2),
                positions_value=round(pv, 2),
                equity=round(equity, 2),
                starting_cash=start,
                total_return_pct=round(ret, 2),
                alpha_vs_benchmark_pct=round(alpha, 2),
                is_benchmark=is_benchmark(m.slug),
                rank=0,
                memory=m.memory,
            )
        )

    # Rank by ALPHA — the arena is now explicitly a contest to beat Buy & Hold.
    rows.sort(key=lambda r: r.alpha_vs_benchmark_pct, reverse=True)
    for i, r in enumerate(rows, start=1):
        r.rank = i
    return rows


@app.get("/api/portfolio/{model_id}", response_model=PortfolioOut)
def portfolio(model_id: int, db: Session = Depends(get_db)) -> PortfolioOut:
    m = db.get(Model, model_id)
    if not m:
        raise HTTPException(404, "model not found")
    prices = get_latest_prices(settings.ticker_list)

    positions: list[PositionOut] = []
    for pos in m.portfolio.positions:
        if pos.shares == 0:
            continue
        last = prices.get(pos.ticker, pos.avg_price)
        upnl = engine.position_upnl(pos, last)
        positions.append(
            PositionOut(
                ticker=pos.ticker,
                side="SHORT" if pos.shares < 0 else "LONG",
                shares=round(pos.shares, 4),
                avg_price=round(pos.avg_price, 2),
                last_price=round(last, 2),
                leverage=round(pos.leverage, 1),
                margin=round(pos.margin, 2),
                notional=round(abs(pos.shares) * last, 2),
                market_value=round(pos.margin + upnl, 2),
                unrealized_pnl=round(upnl, 2),
                liquidation_price=round(engine.liquidation_price(pos), 2),
            )
        )

    pv, equity = _portfolio_value(m, prices)
    start = m.portfolio.starting_cash or 1.0
    return PortfolioOut(
        model_id=m.id,
        name=m.name,
        cash=round(m.portfolio.cash, 2),
        equity=round(equity, 2),
        positions_value=round(pv, 2),
        total_return_pct=round((equity - start) / start * 100, 2),
        positions=positions,
    )


@app.get("/api/positions", response_model=HoldingsOut)
def positions(db: Session = Depends(get_db)) -> HoldingsOut:
    """Holdings matrix: every model's shares (and value) per configured ticker."""
    tickers = settings.ticker_list
    models = db.scalars(select(Model)).all()
    prices = get_latest_prices(tickers)

    rows: list[HoldingsRow] = []
    for m in models:
        held = {p.ticker: p for p in m.portfolio.positions if p.shares != 0}
        cells: dict[str, HoldingCell] = {}
        for tk in tickers:
            p = held.get(tk)
            if p:
                price = prices.get(tk, p.avg_price)
                cells[tk] = HoldingCell(
                    shares=round(p.shares, 4),
                    value=round(p.margin + engine.position_upnl(p, price), 2),
                    side="SHORT" if p.shares < 0 else "LONG",
                    leverage=round(p.leverage, 1),
                    notional=round(abs(p.shares) * price, 2),
                    unrealized_pnl=round(engine.position_upnl(p, price), 2),
                    liquidation_price=round(engine.liquidation_price(p), 2),
                )
            else:
                cells[tk] = HoldingCell(shares=0.0, value=0.0)
        _pv, equity = _portfolio_value(m, prices)
        rows.append(
            HoldingsRow(
                model_id=m.id,
                name=m.name,
                cash=round(m.portfolio.cash, 2),
                equity=round(equity, 2),
                cells=cells,
            )
        )

    rows.sort(key=lambda r: r.equity, reverse=True)
    return HoldingsOut(tickers=tickers, rows=rows)


@app.get("/api/trades", response_model=list[TradeOut])
def trades(
    limit: int = 50,
    model_id: int | None = None,
    db: Session = Depends(get_db),
) -> list[TradeOut]:
    stmt = select(TradeLog).order_by(desc(TradeLog.created_at)).limit(min(limit, 500))
    if model_id is not None:
        stmt = (
            select(TradeLog)
            .where(TradeLog.model_id == model_id)
            .order_by(desc(TradeLog.created_at))
            .limit(min(limit, 500))
        )
    logs = db.scalars(stmt).all()
    name_by_id = {m.id: m.name for m in db.scalars(select(Model)).all()}
    return [
        TradeOut(
            id=t.id,
            model_id=t.model_id,
            model_name=name_by_id.get(t.model_id, "?"),
            ticker=t.ticker,
            action=t.action,
            allocation_pct=t.allocation_pct,
            confidence=t.confidence,
            shares=round(t.shares, 4),
            price=round(t.price, 2),
            leverage=round(t.leverage, 1),
            take_profit=round(t.take_profit, 2),
            stop_loss=round(t.stop_loss, 2),
            reasoning=t.reasoning,
            reasoning_zh=t.reasoning_zh,
            thinking_zh=t.thinking_zh,
            raw_response=t.raw_response,
            thinking=t.thinking,
            status=t.status,
            note=t.note,
            created_at=t.created_at,
        )
        for t in logs
    ]


@app.get("/api/equity-curves", response_model=list[EquitySeries])
def equity_curves(limit: int = 200, db: Session = Depends(get_db)) -> list[EquitySeries]:
    """Equity snapshots per model for the dashboard charts."""
    series: list[EquitySeries] = []
    for m in db.scalars(select(Model)).all():
        snaps = db.scalars(
            select(EquitySnapshot)
            .where(EquitySnapshot.model_id == m.id)
            .order_by(desc(EquitySnapshot.created_at))
            .limit(min(limit, 1000))
        ).all()
        snaps = list(reversed(snaps))
        series.append(
            EquitySeries(
                model_id=m.id,
                name=m.name,
                points=[EquityPoint(t=s.created_at, equity=round(s.equity, 2)) for s in snaps],
            )
        )
    return series


# Analytics scans all history per model; cache briefly since the dashboard polls
# every 30s but the underlying data only changes on ticks (15 min) / snapshots.
_ANALYTICS_CACHE: dict[str, object] = {"at": 0.0, "data": None}
_ANALYTICS_TTL = 60.0


@app.get("/api/analytics")
def get_analytics(db: Session = Depends(get_db)) -> dict:
    """Per-model performance metrics, usage/cost, and behavior aggregates."""
    import time

    now = time.time()
    if _ANALYTICS_CACHE["data"] is not None and now - float(_ANALYTICS_CACHE["at"]) < _ANALYTICS_TTL:
        return _ANALYTICS_CACHE["data"]  # type: ignore[return-value]

    models = db.scalars(select(Model)).all()
    prices = get_latest_prices(settings.ticker_list)

    # Benchmark return for alpha.
    bench_return = None
    for m in models:
        if is_benchmark(m.slug):
            bench_return = analytics.performance(db, m, None)["total_return_pct"]
            break

    rows = []
    for m in models:
        perf = analytics.performance(db, m, bench_return)
        # Current exposure / unrealized, marked at live prices.
        gross_notional = sum(
            abs(p.shares) * prices.get(p.ticker, p.avg_price)
            for p in m.portfolio.positions
            if p.shares != 0
        )
        upnl = sum(
            engine.position_upnl(p, prices.get(p.ticker, p.avg_price))
            for p in m.portfolio.positions
            if p.shares != 0
        )
        _pv, equity = _portfolio_value(m, prices)
        risk = analytics.risk(db, m)
        risk["gross_exposure_x"] = round(gross_notional / equity, 2) if equity > 0 else 0.0
        risk["unrealized_pnl"] = round(upnl, 2)
        risk["open_positions"] = sum(1 for p in m.portfolio.positions if p.shares != 0)
        rows.append(
            {
                "model_id": m.id,
                "name": m.name,
                "is_benchmark": is_benchmark(m.slug),
                "performance": perf,
                "usage": analytics.usage(db, m),
                "behavior": analytics.behavior(db, m),
                "risk": risk,
            }
        )
    rows.sort(key=lambda r: r["performance"]["total_return_pct"], reverse=True)
    result = {"models": rows}
    _ANALYTICS_CACHE["at"] = now
    _ANALYTICS_CACHE["data"] = result
    return result


@app.post("/api/run-now")
async def run_now() -> dict:
    """Manually trigger one loop tick (ignores market hours). Handy for demos."""
    return await engine.run_loop_once(force=True)
