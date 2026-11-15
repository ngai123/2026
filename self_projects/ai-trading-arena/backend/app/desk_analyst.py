"""Desk-analyst pre-pass.

Once per round, ONE model digests the market (signals + on-chain + sentiment +
news) and writes a structured pre-trade briefing — regime, per-asset dashboard,
narrative vs reality, catalyst horizon, alpha-setup menu, edge-quality matrix.
That single briefing is injected into every trader's prompt, so all traders read
the same desk view (and pick/size their own trades from it).
"""
from __future__ import annotations

import asyncio
import logging

from .config import ANALYST_MODEL, get_settings

logger = logging.getLogger("arena.analyst")
settings = get_settings()

ANALYST_SYSTEM = """You are a senior crypto trading-desk analyst. From the data \
provided, write a concise, decision-useful PRE-TRADE BRIEFING for a desk of \
autonomous traders. Use EXACTLY these numbered sections:

0. Context Snapshot (Risk Regime): one or two lines — volatility regime,
   risk-on/off, overall trend posture, and any imminent event risk.
1. Per-Asset Dashboard: for EACH coin — global structure (trend up/down/range),
   key support/resistance levels (use the actual numbers), momentum (RSI/MACD),
   volatility (ATR), and a one-line on-chain/sentiment note if relevant.
2. Narrative vs Reality: 1-3 themes from the headlines. For each: is it a FRESH
   impulse, already PRICED IN, or a DIVERGENCE RISK (good news, flat price)?
3. Catalyst Horizon: upcoming catalysts/risks implied by news & sentiment.
4. Alpha Setups (Menu of Hypotheses): for each coin, 1-2 concrete hypotheses —
   view, direction (long/short), key entry level, invalidation level, and edge
   depth (deep/moderate/shallow).
5. Edge Quality Matrix: rank the highest-conviction setups; flag low-edge/avoid.

Rules: be specific with numbers and levels. Present a MENU — do NOT pick one
final trade; the traders choose and size themselves. Keep it tight and skimmable.
Output the briefing as markdown text only."""


async def generate_briefing(
    market_block: str,
    signals_block: str,
    onchain_block: str,
    sentiment_block: str,
    news_block: str,
) -> str:
    """Return the desk briefing text (empty string on failure/disabled)."""
    if not settings.enable_analyst:
        return ""
    # Imported here to avoid a circular import at module load.
    from .llm_client import _client, _content_of

    user = (
        f"TICKER UNIVERSE: {', '.join(settings.ticker_list)}\n\n"
        f"ALL SERIES ORDERED OLDEST -> NEWEST.\n\n"
        f"=== PRICE / OHLCV ===\n{market_block}\n\n"
        f"=== TECHNICAL SIGNALS ===\n{signals_block or '(none)'}\n\n"
        f"=== ON-CHAIN ===\n{onchain_block or '(none)'}\n\n"
        f"=== SENTIMENT ===\n{sentiment_block or '(none)'}\n\n"
        f"=== RECENT HEADLINES ===\n{news_block or '(none)'}\n\n"
        f"Write the pre-trade briefing now."
    )
    try:
        resp = await asyncio.wait_for(
            _client.chat.completions.create(
                model=ANALYST_MODEL,
                messages=[
                    {"role": "system", "content": ANALYST_SYSTEM},
                    {"role": "user", "content": user},
                ],
                temperature=0.3,
                max_tokens=3000,
                extra_body={"usage": {"include": True}},
            ),
            timeout=120,
        )
        return _content_of(resp).strip()
    except Exception as exc:  # noqa: BLE001
        logger.warning("analyst briefing failed: %s", exc)
        return ""
