"""Database schema.

Tables
------
Model          : one AI competitor (display name + OpenRouter slug).
Portfolio      : 1:1 with Model — cash balance + bookkeeping.
Position       : an open holding (shares of a ticker) inside a portfolio.
TradeLog       : every decision an agent makes, including HOLDs and rejects,
                 with the raw reasoning text and execution outcome.
EquitySnapshot : periodic mark-to-market of each portfolio for equity curves.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Model(Base):
    __tablename__ = "models"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)
    slug: Mapped[str] = mapped_column(String(150))  # OpenRouter model id
    # The model's own evolving memory — notes it writes to its future self each
    # round (strategy, lessons, what to watch) and reads back next round.
    memory: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)

    portfolio: Mapped["Portfolio"] = relationship(
        back_populates="model", uselist=False, cascade="all, delete-orphan"
    )
    trades: Mapped[list["TradeLog"]] = relationship(
        back_populates="model", cascade="all, delete-orphan"
    )


class Portfolio(Base):
    __tablename__ = "portfolios"

    id: Mapped[int] = mapped_column(primary_key=True)
    model_id: Mapped[int] = mapped_column(ForeignKey("models.id"), unique=True)
    cash: Mapped[float] = mapped_column(Float)
    starting_cash: Mapped[float] = mapped_column(Float)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=_utcnow, onupdate=_utcnow
    )

    model: Mapped["Model"] = relationship(back_populates="portfolio")
    positions: Mapped[list["Position"]] = relationship(
        back_populates="portfolio", cascade="all, delete-orphan"
    )


class Position(Base):
    __tablename__ = "positions"
    __table_args__ = (UniqueConstraint("portfolio_id", "ticker"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    portfolio_id: Mapped[int] = mapped_column(ForeignKey("portfolios.id"))
    ticker: Mapped[str] = mapped_column(String(10))
    shares: Mapped[float] = mapped_column(Float, default=0.0)  # signed: +long / -short
    avg_price: Mapped[float] = mapped_column(Float, default=0.0)  # entry price
    leverage: Mapped[float] = mapped_column(Float, default=1.0)
    margin: Mapped[float] = mapped_column(Float, default=0.0)  # collateral posted (USD)
    # Pre-registered exit plan; the engine auto-closes when TP/SL is hit.
    # 0 = unset. invalidation_condition is the model's own text, shown back to it.
    take_profit: Mapped[float] = mapped_column(Float, default=0.0)
    stop_loss: Mapped[float] = mapped_column(Float, default=0.0)
    invalidation_condition: Mapped[str] = mapped_column(Text, default="")

    portfolio: Mapped["Portfolio"] = relationship(back_populates="positions")


class TradeLog(Base):
    __tablename__ = "trade_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    model_id: Mapped[int] = mapped_column(ForeignKey("models.id"))
    ticker: Mapped[str] = mapped_column(String(10))
    action: Mapped[str] = mapped_column(String(10))  # BUY / SELL / HOLD
    allocation_pct: Mapped[float] = mapped_column(Float, default=0.0)
    shares: Mapped[float] = mapped_column(Float, default=0.0)  # shares transacted
    price: Mapped[float] = mapped_column(Float, default=0.0)  # exec price/share
    take_profit: Mapped[float] = mapped_column(Float, default=0.0)  # exit plan
    stop_loss: Mapped[float] = mapped_column(Float, default=0.0)
    leverage: Mapped[float] = mapped_column(Float, default=1.0)  # leverage used
    reasoning: Mapped[str] = mapped_column(Text, default="")  # parsed JSON field
    confidence: Mapped[float] = mapped_column(Float, default=0.0)  # model's 0-100
    # Full model output before parsing, any chain-of-thought, and the EXACT
    # prompt sent — captured so the harness is fully auditable.
    raw_response: Mapped[str] = mapped_column(Text, default="")
    thinking: Mapped[str] = mapped_column(Text, default="")
    prompt: Mapped[str] = mapped_column(Text, default="")
    # Chinese translations for display (models still reason in English).
    reasoning_zh: Mapped[str] = mapped_column(Text, default="")
    thinking_zh: Mapped[str] = mapped_column(Text, default="")
    # "executed" | "rejected" | "hold" | "error" — see engine.py
    status: Mapped[str] = mapped_column(String(20), default="executed")
    note: Mapped[str] = mapped_column(Text, default="")  # rejection/error detail
    # Realized P&L booked on SELLs (sell price - cost basis) * shares.
    realized_pnl: Mapped[float] = mapped_column(Float, default=0.0)
    # Token usage + cost for this model call (0 for benchmark / non-LLM).
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0)
    total_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)

    model: Mapped["Model"] = relationship(back_populates="trades")


class EquitySnapshot(Base):
    __tablename__ = "equity_snapshots"

    id: Mapped[int] = mapped_column(primary_key=True)
    model_id: Mapped[int] = mapped_column(ForeignKey("models.id"), index=True)
    equity: Mapped[float] = mapped_column(Float)
    cash: Mapped[float] = mapped_column(Float)
    positions_value: Mapped[float] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, index=True)


class OnChainSnapshot(Base):
    """Historical record of the on-chain metrics fed to the models each tick."""

    __tablename__ = "onchain_snapshots"

    id: Mapped[int] = mapped_column(primary_key=True)
    ticker: Mapped[str] = mapped_column(String(10), default="BTC-USD")
    metrics: Mapped[str] = mapped_column(Text, default="")  # JSON blob
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, index=True)
