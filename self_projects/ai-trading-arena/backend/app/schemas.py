"""Pydantic models for API responses and the strict LLM decision schema."""
from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Annotated, Literal

from pydantic import BaseModel, Field, PlainSerializer, field_validator


def _iso_utc(dt: datetime | None) -> str | None:
    """Serialize datetimes as unambiguous UTC ISO (with offset).

    DB timestamps come back naive (SQLite drops tzinfo); we store UTC, so assume
    UTC and emit an explicit offset — no more naive strings that clients misread
    as local time.
    """
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat()


# A datetime that always serializes to UTC ISO with an explicit offset.
UtcDateTime = Annotated[
    datetime, PlainSerializer(_iso_utc, return_type=str, when_used="json")
]


# --- The contract we force the LLMs into ----------------------------------
class CoinDecision(BaseModel):
    """One per-coin decision in a model's turn (Hyperliquid/perp style)."""

    coin: str
    signal: Literal["buy_to_enter", "sell_to_enter", "close", "hold"]
    quantity: float = 0.0          # absolute coin quantity
    leverage: float = 1.0          # 1x .. max_leverage
    confidence: float = 0.5        # 0..1
    profit_target: float = 0.0     # price; 0 = none
    stop_loss: float = 0.0         # price; 0 = none
    invalidation_condition: str = ""
    is_add: bool = False           # pyramiding onto an existing position
    risk_usd: float = 0.0          # the model's stated $ risk (informational)
    justification: str = ""

    @field_validator("coin")
    @classmethod
    def upper_coin(cls, v: str) -> str:
        return str(v).strip().upper()

    @field_validator("signal", mode="before")
    @classmethod
    def norm_signal(cls, v) -> str:
        return str(v).strip().lower().replace(" ", "_").replace("-", "_")

    @field_validator("quantity", "leverage", "profit_target", "stop_loss", "risk_usd", mode="before")
    @classmethod
    def nonneg(cls, v) -> float:
        try:
            f = float(v)
        except (TypeError, ValueError):
            return 0.0
        return f if math.isfinite(f) and f > 0 else 0.0

    @field_validator("confidence", mode="before")
    @classmethod
    def clamp_conf(cls, v) -> float:
        try:
            f = float(v)
        except (TypeError, ValueError):
            return 0.5
        # Accept either 0-1 or 0-100; normalize to 0-1.
        if f > 1.0:
            f = f / 100.0
        return max(0.0, min(1.0, f))


class AgentTurn(BaseModel):
    """A model's full turn: notes to itself + a list of per-coin decisions."""

    memory: str = ""
    decisions: list[CoinDecision] = []


# --- API output shapes ----------------------------------------------------
class PositionOut(BaseModel):
    ticker: str
    side: str = "LONG"
    shares: float
    avg_price: float
    last_price: float
    leverage: float = 1.0
    margin: float = 0.0
    notional: float = 0.0
    market_value: float
    unrealized_pnl: float
    liquidation_price: float = 0.0


class LeaderboardEntry(BaseModel):
    model_id: int
    name: str
    slug: str
    cash: float
    positions_value: float
    equity: float
    starting_cash: float
    total_return_pct: float
    alpha_vs_benchmark_pct: float = 0.0
    is_benchmark: bool = False
    rank: int
    memory: str = ""


class TradeOut(BaseModel):
    id: int
    model_id: int
    model_name: str
    ticker: str
    action: str
    allocation_pct: float
    confidence: float = 0.0
    shares: float
    price: float
    leverage: float = 1.0
    take_profit: float = 0.0
    stop_loss: float = 0.0
    reasoning: str
    reasoning_zh: str = ""
    thinking_zh: str = ""
    raw_response: str = ""
    thinking: str = ""
    status: str
    note: str
    created_at: UtcDateTime


class PortfolioOut(BaseModel):
    model_id: int
    name: str
    cash: float
    equity: float
    positions_value: float
    total_return_pct: float
    positions: list[PositionOut]


class EquityPoint(BaseModel):
    t: UtcDateTime
    equity: float


class EquitySeries(BaseModel):
    model_id: int
    name: str
    points: list[EquityPoint]


class HoldingCell(BaseModel):
    shares: float
    value: float
    side: str = "FLAT"
    leverage: float = 1.0
    notional: float = 0.0
    unrealized_pnl: float = 0.0
    liquidation_price: float = 0.0


class HoldingsRow(BaseModel):
    model_id: int
    name: str
    cash: float
    equity: float
    # ticker -> holding; every configured ticker is present (0 if not held).
    cells: dict[str, HoldingCell]


class HoldingsOut(BaseModel):
    tickers: list[str]
    rows: list[HoldingsRow]


class StatusOut(BaseModel):
    market_open: bool
    allow_after_hours: bool
    tickers: list[str]
    loop_interval_minutes: int
    last_run: UtcDateTime | None
    next_run: UtcDateTime | None
    today_cost_usd: float = 0.0
    total_cost_usd: float = 0.0
    daily_cost_cap_usd: float = 0.0
    timezone: str = "UTC"
