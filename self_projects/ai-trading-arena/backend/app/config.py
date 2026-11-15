"""Central configuration, loaded from environment / .env file.

Everything tunable about the arena lives here so the rest of the code can stay
declarative. Edit the AGENTS list to change which models compete.
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


@dataclass(frozen=True)
class AgentSpec:
    """One AI competitor.

    `name` is a human-friendly display label; `model` is the exact OpenRouter
    model slug that gets passed to the API.
    """

    name: str
    model: str


# --- The five competitors -------------------------------------------------
# Slugs follow OpenRouter's naming (https://openrouter.ai/models). Swap freely.
AGENTS: list[AgentSpec] = [
    AgentSpec(name="GPT-OSS 120B", model="openai/gpt-oss-120b"),
    AgentSpec(name="DeepSeek V4 Pro", model="deepseek/deepseek-v4-pro"),
    AgentSpec(name="MiniMax M3", model="minimax/minimax-m3"),
    AgentSpec(name="Grok 4.3", model="x-ai/grok-4.3"),
    AgentSpec(name="Nemotron 3 Ultra", model="nvidia/nemotron-3-ultra-550b-a55b"),
    AgentSpec(name="Kimi K2.6", model="moonshotai/kimi-k2.6"),
]

# The "desk analyst": one model that writes a structured pre-trade briefing each
# round (regime, per-asset dashboard, narrative, alpha setups), shared to all
# trader models. Cheap + capable.
ANALYST_MODEL = "openai/gpt-oss-120b"


# --- Passive benchmark -----------------------------------------------------
# A non-LLM "competitor": equal-weight buy-and-hold across all tickers, bought
# once and never traded again. Lets you see whether the models beat the market.
BENCHMARK_SLUG = "strategy/buy-and-hold"
BENCHMARK = AgentSpec(name="Buy & Hold", model=BENCHMARK_SLUG)


def is_benchmark(slug: str) -> bool:
    return slug.startswith("strategy/")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    openrouter_api_key: str = ""
    openrouter_app_url: str = "http://localhost:3000"
    openrouter_app_title: str = "AI Trading Arena"

    database_url: str = "sqlite:///./arena.db"

    starting_cash: float = 100_000.0
    tickers: str = "AAPL,TSLA,SPY,NVDA,MSFT"
    loop_interval_minutes: int = 15
    # Display timezone + its fixed UTC offset (MYT is +8, no DST). Timestamps are
    # stored in UTC; this drives display and the daily-cost "today" boundary.
    timezone: str = "Asia/Kuala_Lumpur"
    timezone_offset_hours: int = 8
    commission_rate: float = 0.0
    # Per-trade slippage in basis points (10 = 0.10%). Buys fill above and sells
    # below the quoted price, so overtrading is penalized like real markets.
    slippage_bps: float = 10.0
    allow_after_hours: bool = False

    # --- Leverage / shorting (isolated-margin perp model) -------------------
    # Models trade with leverage and can go long or short. Each position posts
    # margin = notional / leverage from cash; it is liquidated if its equity
    # (margin + unrealized PnL) falls below maintenance_margin x notional.
    allow_short: bool = True
    max_leverage: float = 10.0           # cap per-position leverage
    maintenance_margin: float = 0.05     # liquidate below 5% of notional
    # Daily OpenRouter spend cap (USD). 0 = no cap. When today's spend reaches
    # this, the loop stops calling models (still marks-to-market) until midnight.
    daily_cost_cap_usd: float = 0.0

    # --- Output budget -------------------------------------------------------
    # Generous so models can reason as fully as they naturally do (their full
    # chain-of-thought is captured and shown). Input/context stays rich.
    max_output_tokens: int = 6000
    # Analyst pre-pass: one model writes a shared briefing each round.
    enable_analyst: bool = True
    # News feed: pull recent crypto headlines into the briefing.
    enable_news: bool = True
    # Reasoning effort: minimal | low | medium | high | none | default.
    # "default" sends no reasoning override — each model thinks as itself.
    reasoning_effort: str = "default"
    # Hard cap on reasoning tokens. 0 = no cap (let models think freely).
    reasoning_max_tokens: int = 0

    # --- Agentic tools -------------------------------------------------------
    # Let each model CALL tools to investigate before deciding (deeper history,
    # indicators, key levels, funding, fundamentals, news, cross-asset, calc).
    # Bounded rounds to cap cost/latency; graceful fallback to a direct decision.
    enable_tools: bool = True
    max_tool_rounds: int = 4

    # --- Display translation -------------------------------------------------
    # Models reason in English; for the UI we translate the reasoning/thinking to
    # Chinese with a cheap fast model. Best-effort; falls back to English.
    translate_to_chinese: bool = True
    translate_model: str = "deepseek/deepseek-v4-flash"
    translate_max_chars: int = 12000  # cap thinking input to bound cost/latency

    @property
    def ticker_list(self) -> list[str]:
        return [t.strip().upper() for t in self.tickers.split(",") if t.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
