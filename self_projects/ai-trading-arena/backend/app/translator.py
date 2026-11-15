"""Translate model reasoning/thinking to Chinese for the UI.

The models reason in English (their actual decisions are made in English); this is
purely a display layer. Uses a cheap fast model via OpenRouter. Best-effort:
returns "" on failure so the UI falls back to the original English.
"""
from __future__ import annotations

import asyncio
import logging

from .config import get_settings
from .llm_client import _client  # reuse the configured OpenRouter client

logger = logging.getLogger("arena.translate")
settings = get_settings()

_SYS = (
    "You are a translator. Translate the user's text to Simplified Chinese, "
    "faithfully and naturally. Preserve numbers, tickers (e.g. BTC-USD), and "
    "trading terms. Output ONLY the translation — no notes, no preamble."
)


async def translate_to_chinese(text: str) -> str:
    """Translate one block of text to Chinese. Empty input or failure -> ''."""
    text = (text or "").strip()
    if not text or not settings.translate_to_chinese:
        return ""
    snippet = text[: settings.translate_max_chars]
    try:
        resp = await asyncio.wait_for(
            _client.chat.completions.create(
                model=settings.translate_model,
                messages=[
                    {"role": "system", "content": _SYS},
                    {"role": "user", "content": snippet},
                ],
                temperature=0.0,
                max_tokens=8000,
                extra_body={"reasoning": {"enabled": False}},  # no CoT — just translate
            ),
            timeout=120,
        )
        return (resp.choices[0].message.content or "").strip()
    except Exception as exc:  # noqa: BLE001
        logger.warning("translation failed: %s", exc)
        return ""


async def translate_pair(reasoning: str, thinking: str) -> tuple[str, str]:
    """Translate reasoning and thinking concurrently."""
    r, t = await asyncio.gather(
        translate_to_chinese(reasoning), translate_to_chinese(thinking)
    )
    return r, t
