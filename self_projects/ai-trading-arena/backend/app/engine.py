"""The trading engine: prompt building, execution, and the loop tick.

One "tick" (`run_loop_once`):
  1. Fetch latest prices + OHLCV, technical signals, on-chain & sentiment context.
  2. For each agent, build a prompt with its own portfolio + track record.
  3. Call all configured models concurrently via OpenRouter.
  4. Parse each JSON decision and execute the paper trade against that agent's
     own cash/positions (with slippage + fees).
  5. Snapshot every portfolio's mark-to-market equity.

All money/position math is paper-only and lives entirely in SQLite.
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import (
    analytics,
    data_provider,
    desk_analyst,
    funding_provider,
    indicators,
    news_provider,
    onchain_provider,
    sentiment_provider,
    translator,
)
from .config import AGENTS, AgentSpec, get_settings, is_benchmark
from .database import SessionLocal
from .llm_client import AgentResult, run_agents
from .market_hours import is_market_open
from .models import (
    EquitySnapshot,
    Model,
    OnChainSnapshot,
    Portfolio,
    Position,
    TradeLog,
)
from .schemas import AgentTurn  # noqa: F401

logger = logging.getLogger("arena.engine")
settings = get_settings()

# Tracks loop activity for the /api/status endpoint.
LAST_RUN: datetime | None = None


# --------------------------------------------------------------------------
# Prompt construction
# --------------------------------------------------------------------------
# Bump when the prompt/context contract changes, so behavior shifts are traceable.
PROMPT_VERSION = "v13"

SYSTEM_PROMPT = f"""You are an alpha-seeking autonomous crypto trader (prompt \
{PROMPT_VERSION}) competing live against other AI models with REAL money.

THIS IS REAL CAPITAL
You have been entrusted with REAL funds in a live market — every trade executes
with real money, real fees, and real counterparties. Gains and losses are real
and permanent. Trade with the discipline and accountability that demands.

OBJECTIVE — GENERATE ALPHA
Your ONLY score is ALPHA: your return MINUS a passive 100% Buy & Hold of the
same market. Matching Buy & Hold = 0 alpha = FAILURE. You earn nothing for
simply being long like everyone else — a passive holder already does that for
free. Your job is to BEAT it. If you cannot beat it, you are losing.

WHY MOST AGENTS FAIL (do not be one of them)
- CASH DRAG: sitting at a partial allocation (e.g. ~50% BTC) while the market
  rises GUARANTEES you trail Buy & Hold. Closet-indexing is the worst outcome.
- Go long with conviction before up-moves; capture the dips the passive holder
  eats by raising cash or SHORTING before pullbacks, then re-entering lower.

LONG, SHORT & LEVERAGE
- You trade perpetual-style across the coin universe and may hold MULTIPLE
  positions at once. Go LONG (buy_to_enter) to profit when price rises, or SHORT
  (sell_to_enter) to profit when it FALLS — shorting is your tool for down-moves.
- Each position uses LEVERAGE (1x..{int(settings.max_leverage)}x) and posts
  margin = quantity*price/leverage from your cash. More leverage = more exposure
  per dollar AND faster liquidation: a position is force-closed if its equity
  drops below the maintenance margin. Use leverage deliberately, not reflexively.

WHAT YOU RECEIVE EACH ROUND
- A shared DESK BRIEFING from the desk analyst: risk regime, a per-asset
  dashboard (structure, key levels, RSI/MACD/ATR, on-chain), narrative vs
  reality from the news, a catalyst horizon, a menu of ALPHA SETUPS, and an
  edge-quality matrix. It is a MENU — you choose and size your own trade.
- YOUR ACCOUNT: available capital, NAV, current prices, and live positions
  (with any active exit plan).
- YOUR MEMORY & TRACK RECORD: your notes from last round, your standing vs the
  benchmark, your Sharpe, and your recent decisions.
- The briefing is shared by all traders — your EDGE is choosing and sizing
  better than they do, not just following the most obvious setup.

TOOLS — INVESTIGATE BEFORE YOU DECIDE
You can CALL tools to pull data on demand before committing. Use them to test
your thesis, not reflexively. Available: get_price_history, get_indicators,
get_key_levels (support/resistance), get_funding (positioning), get_fundamentals
(mcap/volume/ATH distance, all coins), get_onchain (BTC), get_news,
compare_universe (cross-asset relative strength), and calc (sizing/risk math).
Call what genuinely sharpens your edge, then return your final decision JSON.

TRADE YOUR OWN CONVICTION
- Back YOUR read of the market. Do NOT play it safe, do NOT default to the
  consensus, and do NOT mimic what a "reasonable" agent would do. Your alpha
  comes from a DIFFERENTIATED, well-reasoned stance that others may not take.
- HOLD is a LAST RESORT — only when you genuinely have no edge this round.
  Sitting idle is how everyone ends up identical and trailing the benchmark.
  Most rounds you should have a view: add, trim, go long, or go short.
- Take a real STANCE: go heavy (toward 100%) when you expect upside; raise cash
  or SHORT when you expect a drawdown. A timid ~50% allocation is not "balanced"
  — it is a guaranteed loss to the benchmark.
- Conviction, not noise: each action should express a genuine thesis (seize an
  entry, dodge a drop, press an edge) — not random churn. Slippage + fees mean a
  pointless trade costs you, but so does indecision. Commit when you believe.
- SIZE BY CONVICTION: scale your quantity and leverage with your confidence.
  High conviction -> bigger size / more leverage; low -> small or stay flat.
- Use the signals to form YOUR view: oversold + extreme fear = accumulate;
  overbought + euphoria or breaking support = de-risk or short. Manage drawdown
  and volatility (ATR), not just upside.

EXIT PLANS (set these whenever you hold a position)
- take_profit and stop_loss are PRICES. The system AUTOMATICALLY closes your
  position when price reaches either — you do not need to act again to exit.
  This lets winners run to target and cuts losers without you watching.
- invalidation_condition is a signal that voids your thesis (e.g. "4H RSI < 40").
  It is shown back to you each round — re-check it and close early if it triggers.
- A good trade pre-commits to where it's wrong. Set a stop on every entry.

MEMORY — you are a CONTINUING trader, not a fresh one each round. Read YOUR
MEMORY and build on it. In the "memory" output field, write concise notes to
your future self (your thesis, what's working, what to watch, mistakes to avoid).
You will see exactly these notes next round — use them to stay consistent and
learn from your own track record.

OUTPUT — you may act on MULTIPLE coins in one turn. Think however you like, but
your FINAL answer must be EXACTLY ONE JSON object and NOTHING else (no markdown,
no code fences, no text before or after it):
{{
  "memory": "<concise notes to your future self — thesis, lessons, what to watch>",
  "decisions": [
    {{
      "coin": "<ticker from the universe>",
      "signal": "buy_to_enter" | "sell_to_enter" | "close" | "hold",
      "quantity": <coin quantity to trade>,
      "leverage": <1 to {int(settings.max_leverage)}>,
      "confidence": <0.0 to 1.0>,
      "profit_target": <price to auto-close in profit, or 0>,
      "stop_loss": <price to auto-close in loss, or 0>,
      "invalidation_condition": "<a signal that voids the thesis, or empty>",
      "is_add": <true if adding to an existing position>,
      "risk_usd": <your intended dollar risk on this trade>,
      "justification": "<1-2 sentences citing the signals you used>"
    }}
  ]
}}

RULES
- buy_to_enter = open/extend a LONG of `quantity` coins at `leverage`.
- sell_to_enter = open/extend a SHORT. You cannot flip directly — `close` first.
- close = exit the position for that coin (full, or `quantity` for a partial).
- hold = no trade for that coin; you may still set/update its exit plan.
- Only include coins you want to act on; omit the rest. An empty decisions list
  means do nothing this round.
- quantity is an ABSOLUTE coin amount (not a %). Required margin
  (quantity*price/leverage) must fit your available cash.
- profit_target/stop_loss are PRICES; the system auto-closes when hit.
- confidence is 0.0-1.0. Only trade coins from the universe. Output ONLY the JSON."""


def _format_market_block(tickers: list[str]) -> tuple[str, dict[str, float]]:
    """Build the human-readable OHLCV block + return the latest price map."""
    prices: dict[str, float] = {}
    lines: list[str] = []
    for t in tickers:
        bars = data_provider.get_recent_ohlcv(t, days=10)
        price = data_provider.get_latest_price(t)
        if price is not None:
            prices[t] = price
        if not bars:
            lines.append(f"{t}: (no data available)")
            continue
        latest = bars[-1]
        history = " | ".join(
            f"{b.date} C:{b.close} V:{b.volume}" for b in bars
        )
        lines.append(
            f"{t}  last_close={latest.close}  "
            f"day_range={latest.low}-{latest.high}\n  recent: {history}"
        )
    return "\n".join(lines), prices


def _format_signals_block(tickers: list[str]) -> str:
    """Computed technical indicators per ticker (hourly), so models reason over
    derived signals rather than re-deriving them from raw OHLCV every time."""
    sections = []
    for t in tickers:
        arr = data_provider.get_ohlc_arrays(t, period="30d", interval="1h")
        closes = arr.get("closes") or []
        if len(closes) < 30:
            continue
        highs, lows = arr.get("highs", []), arr.get("lows", [])
        price = closes[-1]
        s20, s50 = indicators.sma(closes, 20), indicators.sma(closes, 50)
        rsi = indicators.rsi(closes, 14)
        macd = indicators.macd(closes)
        pctb = indicators.bollinger_pctb(closes, 20)
        atr = indicators.atr_pct(highs, lows, closes, 14)

        def rel(sv):
            if sv is None:
                return "n/a"
            return f"{'above' if price > sv else 'below'} {sv:,.0f}"

        macd_txt = "n/a"
        if macd:
            macd_txt = f"{'bullish' if macd[2] > 0 else 'bearish'} (hist {macd[2]:+.1f})"
        rets = " | ".join(
            f"{lbl} {v:+.2f}%"
            for lbl, lb in (("1h", 1), ("24h", 24), ("7d", 168), ("30d", 720))
            if (v := indicators.pct_change(closes, lb)) is not None
        )
        vol = indicators.realized_vol_pct(closes, 24)
        # Recent hourly close series (oldest -> newest) for momentum shape.
        recent = closes[-8:]
        series_txt = ", ".join(f"{c:,.0f}" for c in recent)

        # Higher timeframe (daily) context for trend confirmation.
        daily = data_provider.get_recent_ohlcv(t, days=60)
        dcloses = [b.close for b in daily]
        htf = ""
        if len(dcloses) >= 20:
            d20 = indicators.sma(dcloses, 20)
            d50 = indicators.sma(dcloses, 50) if len(dcloses) >= 50 else None
            drsi = indicators.rsi(dcloses, 14)
            d_price = dcloses[-1]
            htf_parts = [f"price {'>' if d20 and d_price > d20 else '<'} SMA20"]
            if d50:
                htf_parts.append(f"{'>' if d_price > d50 else '<'} SMA50")
            if drsi is not None:
                htf_parts.append(f"RSI {drsi:.0f}")
            htf = "\n  Daily (higher TF): " + " | ".join(htf_parts)

        sections.append(
            f"{t} (hourly):\n"
            f"  Price {price:,.0f} | SMA20 {rel(s20)} | SMA50 {rel(s50)}\n"
            f"  RSI(14): {rsi:.0f} | MACD: {macd_txt} | "
            f"Bollinger %B: {pctb:.2f}" + (f" | ATR: {atr:.2f}%" if atr else "") + "\n"
            f"  Returns: {rets}" + (f"\n  24h realized vol: {vol:.2f}%" if vol else "")
            + f"\n  Recent hourly closes (oldest->newest): [{series_txt}]"
            + htf
        )
    return "\n".join(sections)


def position_upnl(pos: Position, price: float) -> float:
    """Unrealized PnL of a position (signed shares: long>0, short<0)."""
    return (price - pos.avg_price) * pos.shares


def liquidation_price(pos: Position) -> float:
    """Price at which a position's equity hits maintenance margin (0 if flat).

    Solve: margin + (P - avg)*shares = maintenance_margin * |shares| * P.
    """
    s = pos.shares
    if s == 0:
        return 0.0
    denom = s - settings.maintenance_margin * abs(s)
    if denom == 0:
        return 0.0
    return max(0.0, (s * pos.avg_price - pos.margin) / denom)


def marked_positions_value(portfolio: Portfolio, prices: dict[str, float]) -> float:
    """Equity tied up in open positions = sum(posted margin + unrealized PnL).

    Isolated-margin perp model: NAV = cash + this. At 1x with full margin this
    reduces to spot (margin = entry notional, so margin + uPnL = current value).
    """
    total = 0.0
    for p in portfolio.positions:
        if p.shares == 0:
            continue
        price = prices.get(p.ticker, p.avg_price)
        total += p.margin + position_upnl(p, price)
    return total


def _format_portfolio_block(
    db: Session, portfolio: Portfolio, prices: dict[str, float]
) -> str:
    pos_lines = []
    positions_value = 0.0
    for pos in portfolio.positions:
        if pos.shares == 0:
            continue
        last = prices.get(pos.ticker, pos.avg_price)
        mv = pos.shares * last
        positions_value += mv
        side = "SHORT" if pos.shares < 0 else "LONG"
        plan = []
        if pos.take_profit:
            plan.append(f"TP {pos.take_profit:.2f}")
        if pos.stop_loss:
            plan.append(f"SL {pos.stop_loss:.2f}")
        if pos.invalidation_condition:
            plan.append(f"invalidate if: {pos.invalidation_condition}")
        plan_txt = ("\n    exit plan: " + " | ".join(plan)) if plan else ""
        pos_lines.append(
            f"  {pos.ticker}: {side} {pos.shares:.4f} shares @ avg {pos.avg_price:.2f} "
            f"(now {last:.2f}, mkt_val {mv:.2f}){plan_txt}"
        )
    pos_text = "\n".join(pos_lines) if pos_lines else "  (none)"
    equity = portfolio.cash + positions_value
    return (
        f"Cash: ${portfolio.cash:,.2f}\n"
        f"Positions:\n{pos_text}\n"
        f"Total equity: ${equity:,.2f}"
    )


def _format_memory_block(
    db: Session,
    model: Model,
    prices: dict[str, float],
    bench_return_pct: float | None,
    limit: int = 8,
) -> str:
    """Each AI's evolving memory: its own notes to itself + current standing +
    recent decisions, so it reasons as a continuing trader, not fresh each tick."""
    portfolio = model.portfolio
    pv = marked_positions_value(portfolio, prices)
    equity = portfolio.cash + pv
    start = portfolio.starting_cash or 1.0
    ret = (equity - start) / start * 100
    standing = f"Equity ${equity:,.0f} ({ret:+.2f}% vs start)"
    if bench_return_pct is not None:
        alpha = ret - bench_return_pct
        verdict = "BEATING benchmark" if alpha > 0 else "LOSING to benchmark"
        standing += (
            f" | Buy&Hold is {bench_return_pct:+.2f}% | "
            f"YOUR ALPHA (your score): {alpha:+.2f}% — {verdict}"
        )
    sharpe = analytics.quick_sharpe(db, model.id)
    if sharpe is not None:
        standing += f" | Sharpe: {sharpe}"

    rows = db.scalars(
        select(TradeLog)
        .where(TradeLog.model_id == model.id)
        .order_by(TradeLog.created_at.desc())
        .limit(limit)
    ).all()
    recent_lines = []
    for t in reversed(rows):  # oldest first
        when = t.created_at.strftime("%m-%d %H:%M")
        if t.action == "HOLD":
            recent_lines.append(f"{when}  HOLD")
        else:
            pnl = (
                f", realized P&L ${t.realized_pnl:+.0f}"
                if t.action == "SELL" and t.realized_pnl
                else ""
            )
            recent_lines.append(
                f"{when}  {t.action} {t.ticker} {t.allocation_pct:.0f}% "
                f"@ {t.price:.2f} ({t.status}{pnl})"
            )

    parts = [f"YOUR MEMORY (your own notes from last round):\n{model.memory or '(none yet — start building your memory)'}"]
    parts.append(f"YOUR STANDING: {standing}")
    if recent_lines:
        parts.append("YOUR RECENT DECISIONS:\n" + "\n".join(recent_lines))
    return "\n\n".join(parts)


def _format_account_block(portfolio: Portfolio, prices: dict[str, float]) -> str:
    """Account state in desk format: capital, NAV, prices dict, live positions."""
    pv = marked_positions_value(portfolio, prices)
    nav = portfolio.cash + pv
    price_map = {t: round(prices[t], 4) for t in settings.ticker_list if t in prices}
    pos_lines = []
    for p in portfolio.positions:
        if p.shares == 0:
            continue
        last = prices.get(p.ticker, p.avg_price)
        notional = abs(p.shares) * last
        upnl = (last - p.avg_price) * p.shares
        plan = {
            "profit_target": round(p.take_profit, 4) or 0.0,
            "stop_loss": round(p.stop_loss, 4) or 0.0,
            "invalidation_condition": p.invalidation_condition or "",
        }
        pos_lines.append(
            "{"
            f"'symbol': '{p.ticker}', 'side': '{'LONG' if p.shares > 0 else 'SHORT'}', "
            f"'quantity': {round(p.shares, 6)}, 'entry_price': {round(p.avg_price, 4)}, "
            f"'current_price': {round(last, 4)}, 'unrealized_pnl': {round(upnl, 2)}, "
            f"'leverage': 1, 'notional_usd': {round(notional, 2)}, 'exit_plan': {plan}"
            "}"
        )
    positions = "\n".join(pos_lines) if pos_lines else "(none)"
    return (
        f"CURRENT AVAILABLE CAPITAL\n{portfolio.cash:.2f}\n\n"
        f"CURRENT NAV\n{nav:.2f}\n\n"
        f"CURRENT PRICES OF TRADEABLE COINS\n{price_map}\n\n"
        f"CURRENT LIVE POSITIONS AND PERFORMANCE\n{positions}"
    )


def build_user_prompt(
    db: Session,
    portfolio: Portfolio,
    market_block: str,
    prices: dict[str, float],
    onchain_block: str = "",
    sentiment_block: str = "",
    memory_block: str = "",
    signals_block: str = "",
    briefing: str = "",
    funding_block: str = "",
) -> str:
    memory_section = (
        f"=== YOUR MEMORY & TRACK RECORD ===\n{memory_block}\n\n"
        if memory_block
        else ""
    )
    account_section = (
        f"=== YOUR ACCOUNT ===\n{_format_account_block(portfolio, prices)}\n\n"
    )
    funding_section = (
        f"=== PERP POSITIONING (funding & open interest) ===\n{funding_block}\n\n"
        if funding_block
        else ""
    )

    if briefing:
        # Desk-analyst briefing already digests signals/on-chain/sentiment/news.
        return (
            f"TICKER UNIVERSE: {', '.join(settings.ticker_list)}\n\n"
            f"=== DESK BRIEFING (shared market analysis) ===\n{briefing}\n\n"
            f"{funding_section}"
            f"{account_section}"
            f"{memory_section}"
            f"Using the briefing above and your own judgment, make your single "
            f"best trading decision now as JSON."
        )

    # Fallback (analyst disabled/failed): raw context blocks.
    signals_section = (
        f"=== TECHNICAL SIGNALS (precomputed) ===\n{signals_block}\n\n"
        if signals_block
        else ""
    )
    onchain_section = (
        f"=== BTC ON-CHAIN (network fundamentals) ===\n{onchain_block}\n\n"
        if onchain_block
        else ""
    )
    sentiment_section = (
        f"=== MARKET SENTIMENT ===\n{sentiment_block}\n\n" if sentiment_block else ""
    )
    return (
        f"TICKER UNIVERSE: {', '.join(settings.ticker_list)}\n\n"
        f"ALL PRICE/SIGNAL SERIES BELOW ARE ORDERED OLDEST -> NEWEST.\n\n"
        f"=== MARKET DATA (most recent last) ===\n{market_block}\n\n"
        f"{signals_section}"
        f"{onchain_section}"
        f"{sentiment_section}"
        f"{funding_section}"
        f"{account_section}"
        f"{memory_section}"
        f"Make your single best trading decision now as JSON."
    )


# --------------------------------------------------------------------------
# Execution engine (paper trades)
# --------------------------------------------------------------------------
def _normalize_ticker(raw: str) -> str:
    """Map a model's coin onto the configured universe, tolerating exchange
    prefixes and shorthand (e.g. 'xyz:BTC', 'BTC', 'BTC/USD' -> 'BTC-USD')."""
    universe = settings.ticker_list
    t = raw.strip().upper().replace("/", "-")
    if ":" in t:
        t = t.split(":")[-1]
    if t in universe:
        return t
    if f"{t}-USD" in universe:
        return f"{t}-USD"
    base = t.split("-")[0]
    for u in universe:
        if u.split("-")[0] == base:
            return u
    return t


def _get_or_create_position(db: Session, portfolio: Portfolio, ticker: str) -> Position:
    for p in portfolio.positions:
        if p.ticker == ticker:
            return p
    pos = Position(
        portfolio_id=portfolio.id, ticker=ticker, shares=0.0, avg_price=0.0,
        leverage=1.0, margin=0.0,
    )
    db.add(pos)
    portfolio.positions.append(pos)
    return pos


def _clear_position(pos: Position) -> None:
    pos.shares = 0.0
    pos.avg_price = 0.0
    pos.leverage = 1.0
    pos.margin = 0.0
    pos.take_profit = 0.0
    pos.stop_loss = 0.0
    pos.invalidation_condition = ""


def _set_exit_plan(pos: Position, d) -> None:
    """Store a decision's exit plan on a (non-flat) position.

    Validates side vs entry: a long's take-profit must be ABOVE and stop-loss
    BELOW entry (reversed for a short). Wrong-side levels are ignored so a
    mis-set stop can't instantly self-liquidate the position.
    """
    if pos.shares == 0:
        return
    long = pos.shares > 0
    ref = pos.avg_price
    tp = getattr(d, "profit_target", 0) or 0
    sl = getattr(d, "stop_loss", 0) or 0
    if tp:
        if (long and tp > ref) or (not long and tp < ref):
            pos.take_profit = tp
        else:
            logger.info("Ignoring wrong-side take_profit %.4f for %s", tp, pos.ticker)
    if sl:
        if (long and sl < ref) or (not long and sl > ref):
            pos.stop_loss = sl
        else:
            logger.info("Ignoring wrong-side stop_loss %.4f for %s", sl, pos.ticker)
    if getattr(d, "invalidation_condition", ""):
        pos.invalidation_condition = d.invalidation_condition[:500]


def _close_position(
    db: Session,
    model: Model,
    pos: Position,
    qty: float,
    price: float,
    at: datetime | None,
    reason: str,
    status: str,
    confidence: float = 0.0,
) -> TradeLog:
    """Close `qty` of a position at market; release margin + realized PnL to cash."""
    portfolio = model.portfolio
    side = 1.0 if pos.shares > 0 else -1.0
    qty = min(qty, abs(pos.shares))
    slip = settings.slippage_bps / 10_000.0
    commission = settings.commission_rate
    fill = price * (1.0 - slip) if side > 0 else price * (1.0 + slip)
    frac = qty / abs(pos.shares) if pos.shares else 1.0
    released = pos.margin * frac
    realized = (fill - pos.avg_price) * (side * qty)
    fee = qty * fill * commission
    pos.shares -= side * qty
    pos.margin -= released
    portfolio.cash += released + realized - fee
    log = TradeLog(
        model_id=model.id,
        ticker=pos.ticker,
        action="SELL" if side > 0 else "BUY",
        allocation_pct=round(frac * 100, 1),
        confidence=confidence * 100,
        shares=qty,
        price=fill,
        reasoning=reason[:2000],
        status=status,
        leverage=pos.leverage,
        note=f"closed {qty:.4f} @ {fill:.2f} (realized ${realized - fee:+.2f})",
        realized_pnl=realized - fee,
    )
    if at is not None:
        log.created_at = at
    db.add(log)
    if abs(pos.shares) < 1e-9:
        _clear_position(pos)
    return log


def execute_coin_decision(
    db: Session, model: Model, d, prices: dict[str, float], at: datetime | None = None
) -> TradeLog | None:
    """Apply one per-coin decision (signal/quantity/leverage) and log it."""
    portfolio = model.portfolio
    coin = _normalize_ticker(d.coin)
    sig = d.signal
    price = prices.get(coin)

    def reject(note: str) -> TradeLog:
        log = TradeLog(
            model_id=model.id, ticker=coin, action="HOLD", allocation_pct=0,
            confidence=d.confidence * 100, reasoning=d.justification[:2000],
            status="rejected", note=note,
        )
        if at is not None:
            log.created_at = at
        db.add(log)
        return log

    if coin not in settings.ticker_list:
        return reject(f"{coin} not in universe")
    if price is None or price <= 0:
        return reject(f"no price for {coin}")

    pos = _get_or_create_position(db, portfolio, coin)

    if sig == "hold":
        _set_exit_plan(pos, d)
        log = TradeLog(
            model_id=model.id, ticker=coin, action="HOLD", allocation_pct=0,
            confidence=d.confidence * 100, reasoning=d.justification[:2000],
            status="hold", take_profit=d.profit_target, stop_loss=d.stop_loss,
            note="hold",
        )
        if at is not None:
            log.created_at = at
        db.add(log)
        return log

    if sig == "close":
        if pos.shares == 0:
            return reject("nothing to close")
        qty = abs(pos.shares) if d.quantity <= 0 else min(d.quantity, abs(pos.shares))
        return _close_position(
            db, model, pos, qty, price, at, d.justification or "Close.",
            "executed", d.confidence,
        )

    if sig not in ("buy_to_enter", "sell_to_enter"):
        return reject(f"unknown signal '{sig}'")

    want_side = 1.0 if sig == "buy_to_enter" else -1.0
    if want_side < 0 and not settings.allow_short:
        return reject("shorting disabled")
    if pos.shares != 0 and (pos.shares > 0) != (want_side > 0):
        return reject("opposite position open — 'close' it first")
    qty = d.quantity
    if qty <= 0:
        return reject("no quantity specified")

    lev = max(1.0, min(settings.max_leverage, d.leverage or 1.0))
    slip = settings.slippage_bps / 10_000.0
    commission = settings.commission_rate
    fill = price * (1.0 + slip) if want_side > 0 else price * (1.0 - slip)
    notional = qty * fill
    margin = notional / lev
    fee = notional * commission
    # Clamp to available cash (margin + fee).
    if margin + fee > portfolio.cash:
        denom = fill * (1.0 / lev + commission)
        qty = max(0.0, portfolio.cash) / denom if denom > 0 else 0.0
        if qty <= 1e-9:
            return reject("insufficient margin")
        notional = qty * fill
        margin = notional / lev
        fee = notional * commission

    old = pos.shares
    new = old + want_side * qty
    pos.avg_price = (
        (abs(old) * pos.avg_price + qty * fill) / abs(new) if new != 0 else fill
    )
    pos.shares = new
    pos.margin += margin
    pos.leverage = lev
    portfolio.cash -= margin + fee
    _set_exit_plan(pos, d)
    log = TradeLog(
        model_id=model.id,
        ticker=coin,
        action="BUY" if want_side > 0 else "SELL",
        allocation_pct=0,
        confidence=d.confidence * 100,
        shares=qty,
        price=fill,
        reasoning=d.justification[:2000],
        status="executed",
        take_profit=d.profit_target,
        stop_loss=d.stop_loss,
        leverage=lev,
        note=(
            f"{'LONG' if want_side > 0 else 'SHORT'} {qty:.4f} @ {fill:.2f} "
            f"x{lev:.0f} (margin ${margin:.0f}, fee ${fee:.2f})"
        ),
    )
    if at is not None:
        log.created_at = at
    db.add(log)
    return log


def execute_turn(
    db: Session, model: Model, turn, prices: dict[str, float], at: datetime | None = None
) -> list[TradeLog]:
    """Apply a model's full turn (memory note + list of per-coin decisions)."""
    if turn.memory:
        model.memory = turn.memory[:2000]
    logs: list[TradeLog] = []
    for d in turn.decisions:
        log = execute_coin_decision(db, model, d, prices, at=at)
        if log is not None:
            logs.append(log)
    return logs


def check_exit_plans(
    db: Session, model: Model, prices: dict[str, float], at: datetime | None = None
) -> None:
    """Auto-close positions whose take-profit or stop-loss price has been hit."""
    for pos in list(model.portfolio.positions):
        if pos.shares == 0 or (not pos.take_profit and not pos.stop_loss):
            continue
        price = prices.get(pos.ticker)
        if not price:
            continue
        long = pos.shares > 0
        hit = None
        if long:
            if pos.take_profit and price >= pos.take_profit:
                hit = "take_profit"
            elif pos.stop_loss and price <= pos.stop_loss:
                hit = "stop_loss"
        else:
            if pos.take_profit and price <= pos.take_profit:
                hit = "take_profit"
            elif pos.stop_loss and price >= pos.stop_loss:
                hit = "stop_loss"
        if not hit:
            continue
        _close_position(
            db, model, pos, abs(pos.shares), price, at,
            f"Auto-exit: {hit.replace('_', ' ')} hit at {price:.2f}.", hit,
        )


def check_liquidations(
    db: Session, model: Model, prices: dict[str, float], at: datetime | None = None
) -> None:
    """Force-close any position whose equity (margin + uPnL) falls below the
    maintenance margin — the paper equivalent of a margin call / liquidation."""
    for pos in list(model.portfolio.positions):
        if pos.shares == 0:
            continue
        price = prices.get(pos.ticker)
        if not price:
            continue
        notional = abs(pos.shares) * price
        equity_in_pos = pos.margin + position_upnl(pos, price)
        if notional > 0 and equity_in_pos <= settings.maintenance_margin * notional:
            _close_position(
                db, model, pos, abs(pos.shares), price, at,
                f"Liquidation: position equity ${equity_in_pos:,.0f} fell below "
                f"{settings.maintenance_margin * 100:.0f}% of ${notional:,.0f} notional.",
                "liquidated",
            )


def execute_buy_and_hold(
    db: Session, model: Model, prices: dict[str, float], at: datetime | None = None
) -> None:
    """Passive benchmark: 1x equal-weight long across all tickers once, then hold."""
    portfolio = model.portfolio
    if any(p.shares != 0 for p in portfolio.positions):
        log = TradeLog(
            model_id=model.id, ticker="-", action="HOLD", allocation_pct=0,
            reasoning="Buy & hold: maintaining initial equal-weight allocation.",
            status="hold", note="passive benchmark",
        )
        if at is not None:
            log.created_at = at
        db.add(log)
        return

    tradable = [t for t in settings.ticker_list if prices.get(t, 0) > 0]
    if not tradable:
        return
    per = portfolio.cash / len(tradable)
    commission = settings.commission_rate
    slip = settings.slippage_bps / 10_000.0
    for tk in tradable:
        fill = prices[tk] * (1.0 + slip)
        denom = fill * (1.0 + commission)  # 1x: margin == notional
        qty = per / denom
        notional = qty * fill
        fee = notional * commission
        pos = _get_or_create_position(db, portfolio, tk)
        pos.shares = qty
        pos.avg_price = fill
        pos.leverage = 1.0
        pos.margin = notional
        portfolio.cash -= notional + fee
        log = TradeLog(
            model_id=model.id, ticker=tk, action="BUY",
            allocation_pct=round(100.0 / len(tradable), 2), shares=qty, price=fill,
            reasoning="Buy & hold: equal-weight initial allocation.",
            status="executed", note=f"bought {qty:.4f} @ {fill:.2f}",
        )
        if at is not None:
            log.created_at = at
        db.add(log)


def snapshot_equity(
    db: Session, model: Model, prices: dict[str, float], at: datetime | None = None
) -> float:
    """Mark portfolio to market and persist an EquitySnapshot. Returns equity.

    `at` overrides the snapshot timestamp (shared across a snapshot round).
    """
    portfolio = model.portfolio
    positions_value = marked_positions_value(portfolio, prices)
    equity = portfolio.cash + positions_value
    snap = EquitySnapshot(
        model_id=model.id,
        equity=equity,
        cash=portfolio.cash,
        positions_value=positions_value,
    )
    if at is not None:
        snap.created_at = at
    db.add(snap)
    return equity


def mark_to_market() -> dict:
    """Snapshot every portfolio's equity at current prices WITHOUT trading.

    Runs far more often than the trade loop (and makes no LLM calls, so it's
    free) to keep the equity curve in sync with live positions. Uses the same
    price source as the leaderboard so the two always tally.
    """
    if not (is_market_open() or settings.allow_after_hours):
        return {"ran": False, "reason": "market closed"}

    prices = data_provider.get_latest_prices(settings.ticker_list)
    if not prices:
        return {"ran": False, "reason": "no market data"}

    db: Session = SessionLocal()
    try:
        models = db.scalars(select(Model)).all()
        now = datetime.now(timezone.utc)
        for m in models:
            check_exit_plans(db, m, prices, at=now)   # TP/SL between ticks
            check_liquidations(db, m, prices, at=now)  # margin call between ticks
            snapshot_equity(db, m, prices, at=now)
        db.commit()
        return {"ran": True, "snapshots": len(models)}
    except Exception:  # noqa: BLE001
        db.rollback()
        logger.exception("mark_to_market failed")
        return {"ran": False, "reason": "error"}
    finally:
        db.close()


def today_cost_usd(db: Session) -> float:
    """Total OpenRouter spend booked today, in the configured timezone, for the
    cost guardrail (so 'today' resets at local midnight, not UTC)."""
    off = f"{settings.timezone_offset_hours:+d} hours"
    total = db.scalar(
        select(func.coalesce(func.sum(TradeLog.cost_usd), 0.0)).where(
            func.date(TradeLog.created_at, off) == func.date("now", off)
        )
    )
    return float(total or 0.0)


# --------------------------------------------------------------------------
# Loop tick
# --------------------------------------------------------------------------
async def run_loop_once(force: bool = False) -> dict:
    """One full pass over all agents. Safe to call from the scheduler.

    `force=True` ignores market hours (used by the manual /api/run-now endpoint).
    """
    global LAST_RUN

    market_open = is_market_open()
    if not (market_open or settings.allow_after_hours or force):
        logger.info("Market closed and after-hours disabled; skipping tick.")
        return {"ran": False, "reason": "market closed"}

    tickers = settings.ticker_list
    market_block, prices = _format_market_block(tickers)
    if not prices:
        logger.warning("No prices fetched; skipping tick.")
        return {"ran": False, "reason": "no market data"}

    # Technical signals + on-chain + sentiment context. Run off the event loop
    # so slow/hanging providers never block the API. Best-effort: empty on fail.
    signals_block = await asyncio.to_thread(_format_signals_block, tickers)
    onchain_block, onchain_raw = await asyncio.to_thread(
        onchain_provider.format_onchain_block, tickers
    )
    sentiment_block, sentiment_raw = await asyncio.to_thread(
        sentiment_provider.format_sentiment_block
    )
    news_block = (
        await asyncio.to_thread(news_provider.format_news_block)
        if settings.enable_news
        else ""
    )
    # Perp positioning: funding rate + open interest (Binance), off the loop.
    funding_block, funding_raw = await asyncio.to_thread(
        funding_provider.format_funding_block, tickers
    )

    db: Session = SessionLocal()
    try:
        models = db.scalars(select(Model)).all()
        if not models:
            return {"ran": False, "reason": "no models seeded — run seed.py"}

        if onchain_raw or sentiment_raw:
            merged = dict(onchain_raw)
            if sentiment_raw:
                merged["fear_greed"] = sentiment_raw
            db.add(OnChainSnapshot(ticker="BTC-USD", metrics=json.dumps(merged)))

        # --- Cost guardrail: pause model calls once today's spend hits the cap.
        cap = settings.daily_cost_cap_usd
        spent_today = today_cost_usd(db)
        cost_capped = cap > 0 and spent_today >= cap

        specs_by_name: dict[str, AgentSpec] = {a.name: a for a in AGENTS}

        # Passive benchmark(s) trade deterministically — no LLM call.
        bench_return = None
        for m in models:
            if is_benchmark(m.slug):
                execute_buy_and_hold(db, m, prices)
                pv = marked_positions_value(m.portfolio, prices)
                start = m.portfolio.starting_cash or 1.0
                bench_return = (m.portfolio.cash + pv - start) / start * 100

        llm_models = [] if cost_capped else [m for m in models if not is_benchmark(m.slug)]
        if cost_capped:
            logger.warning(
                "Daily cost cap hit ($%.4f >= $%.2f); skipping model calls.",
                spent_today,
                cap,
            )

        # Desk-analyst pre-pass: ONE briefing, shared to every trader this round.
        briefing = ""
        if llm_models and settings.enable_analyst:
            briefing = await desk_analyst.generate_briefing(
                market_block, signals_block, onchain_block, sentiment_block, news_block
            )

        # Build a per-agent prompt (each sees the shared briefing + own account).
        prompts: list[tuple[Model, AgentSpec, str]] = []
        for m in llm_models:
            spec = specs_by_name.get(m.name, AgentSpec(name=m.name, model=m.slug))
            memory_block = _format_memory_block(db, m, prices, bench_return)
            user_prompt = build_user_prompt(
                db,
                m.portfolio,
                market_block,
                prices,
                onchain_block,
                sentiment_block,
                memory_block,
                signals_block,
                briefing,
                funding_block,
            )
            prompts.append((m, spec, user_prompt))

        # Concurrency: one call per agent. Prompts differ only by portfolio,
        # so we issue them individually but still await them together.
        results: list[AgentResult] = await asyncio.gather(
            *(
                run_agents([spec], SYSTEM_PROMPT, up)
                for (_, spec, up) in prompts
            )
        )

        executed = 0
        heads: list[TradeLog] = []  # one log per turn that carries LLM text (to translate)
        for (m, _spec, up), res_list in zip(prompts, results):
            res = res_list[0]
            if res.turn is None:
                # Log the parse/API failure so it shows in the trade feed.
                elog = TradeLog(
                    model_id=m.id,
                    ticker="-",
                    action="HOLD",
                    allocation_pct=0,
                    reasoning=(res.raw or "")[:2000],
                    raw_response=(res.raw or "")[:40000],
                    thinking=(res.thinking or "")[:40000],
                    prompt=up[:16000],
                    status="error",
                    note=res.error or "unparseable response",
                    prompt_tokens=res.prompt_tokens,
                    completion_tokens=res.completion_tokens,
                    total_tokens=res.total_tokens,
                    cost_usd=res.cost,
                )
                db.add(elog)
                heads.append(elog)
                continue
            # Apply the whole turn in a SAVEPOINT so one model's bad decision
            # can't roll back the entire tick (every other model's trades).
            try:
                with db.begin_nested():
                    logs = execute_turn(db, m, res.turn, prices)
                    if not logs:
                        logs = [
                            TradeLog(
                                model_id=m.id, ticker="-", action="HOLD",
                                allocation_pct=0, status="hold", note="empty turn",
                                reasoning="No actionable decisions this round.",
                            )
                        ]
                        db.add(logs[0])
                    head = logs[0]
                    head.raw_response = (res.raw or "")[:40000]
                    head.thinking = (res.thinking or "")[:40000]
                    head.prompt = up[:16000]
                    head.prompt_tokens = res.prompt_tokens
                    head.completion_tokens = res.completion_tokens
                    head.total_tokens = res.total_tokens
                    head.cost_usd = res.cost
                heads.append(head)
                executed += 1
            except Exception:  # noqa: BLE001 - isolate this model's failure
                logger.exception("Turn processing failed for %s", m.name)
                elog = TradeLog(
                    model_id=m.id, ticker="-", action="HOLD", allocation_pct=0,
                    status="error", note="turn processing error",
                    reasoning=(res.raw or "")[:2000],
                    raw_response=(res.raw or "")[:40000],
                    thinking=(res.thinking or "")[:40000], prompt=up[:16000],
                    prompt_tokens=res.prompt_tokens, completion_tokens=res.completion_tokens,
                    total_tokens=res.total_tokens, cost_usd=res.cost,
                )
                db.add(elog)
                heads.append(elog)

        # Translate reasoning + thinking to Chinese for the UI (best-effort,
        # concurrent). Models still reasoned in English; this is display only.
        if settings.translate_to_chinese and heads:
            pairs = await asyncio.gather(
                *(translator.translate_pair(h.reasoning, h.thinking) for h in heads),
                return_exceptions=True,
            )
            for h, pair in zip(heads, pairs):
                if isinstance(pair, tuple):
                    h.reasoning_zh = (pair[0] or "")[:40000]
                    h.thinking_zh = (pair[1] or "")[:40000]

        # Mark-to-market everyone after trades settle, sharing one timestamp so
        # the equity-curve rows line up across models. Check margin first.
        now = datetime.now(timezone.utc)
        for m in models:
            check_exit_plans(db, m, prices, at=now)
            check_liquidations(db, m, prices, at=now)
            snapshot_equity(db, m, prices, at=now)

        db.commit()
        LAST_RUN = now
        logger.info("Tick complete: %d/%d agents decided.", executed, len(models))
        return {"ran": True, "agents": len(models), "executed": executed}
    except Exception:  # noqa: BLE001
        db.rollback()
        logger.exception("Loop tick failed")
        raise
    finally:
        db.close()
