"""Free crypto news headlines via public RSS feeds (no API key).

Feeds the desk-analyst pre-pass real narratives. Best-effort and cached; returns
[] on failure so the briefing still works without it.
"""
from __future__ import annotations

import logging
import re
import time
from xml.etree import ElementTree as ET

import requests

logger = logging.getLogger("arena.news")

_FEEDS = [
    "https://cointelegraph.com/rss",
    "https://decrypt.co/feed",
    "https://www.coindesk.com/arc/outboundfeeds/rss/",
]
_CACHE: tuple[list[dict], float] | None = None
_TTL = 1200  # 20 min
_TIMEOUT = 8


def _parse_feed(xml_text: str) -> list[dict]:
    out = []
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return out
    for item in root.iter("item"):
        title = item.findtext("title") or ""
        pub = item.findtext("pubDate") or ""
        title = re.sub(r"<[^>]+>", "", title).strip()
        if title:
            out.append({"title": title, "published": pub.strip()})
    return out


def get_headlines(limit: int = 12) -> list[dict]:
    """Most recent crypto headlines across feeds. Cached ~20 min."""
    global _CACHE
    if _CACHE and time.time() - _CACHE[1] < _TTL:
        return _CACHE[0][:limit]
    items: list[dict] = []
    seen: set[str] = set()
    for url in _FEEDS:
        try:
            r = requests.get(
                url, timeout=_TIMEOUT, headers={"User-Agent": "ai-trading-arena"}
            )
            r.raise_for_status()
            for it in _parse_feed(r.text):
                key = it["title"].lower()
                if key not in seen:
                    seen.add(key)
                    items.append(it)
        except Exception as exc:  # noqa: BLE001
            logger.warning("news feed failed (%s): %s", url, exc)
    if items:
        _CACHE = (items, time.time())
    return items[:limit]


def format_news_block(limit: int = 12) -> str:
    items = get_headlines(limit)
    if not items:
        return ""
    return "\n".join(f"- {it['title']}" for it in items)
