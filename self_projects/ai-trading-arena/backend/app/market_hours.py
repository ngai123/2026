"""US equity market-hours helper.

Uses pandas_market_calendars (NYSE schedule) so holidays and half-days are
handled correctly, with a naive fallback if the calendar package is missing.
"""
from __future__ import annotations

from datetime import datetime

import pytz

from .config import get_settings

_EASTERN = pytz.timezone("America/New_York")


def is_crypto(ticker: str) -> bool:
    """Crypto pairs use the `XXX-USD` convention on yfinance."""
    return ticker.upper().endswith("-USD")


def all_crypto() -> bool:
    """True when every configured ticker is a crypto pair (24/7 market)."""
    tl = get_settings().ticker_list
    return bool(tl) and all(is_crypto(t) for t in tl)

try:
    import pandas_market_calendars as mcal

    _NYSE = mcal.get_calendar("NYSE")
except Exception:  # pragma: no cover - fallback path
    _NYSE = None


def is_market_open(now: datetime | None = None) -> bool:
    """True if trading is currently allowed.

    Crypto-only universes are open 24/7; otherwise we follow the NYSE session.
    """
    if all_crypto():
        return True

    now = now or datetime.now(tz=_EASTERN)
    if now.tzinfo is None:
        now = _EASTERN.localize(now)
    now_et = now.astimezone(_EASTERN)

    if _NYSE is not None:
        sched = _NYSE.schedule(
            start_date=now_et.date(), end_date=now_et.date()
        )
        if sched.empty:
            return False  # weekend or holiday
        open_t = sched.iloc[0]["market_open"].to_pydatetime()
        close_t = sched.iloc[0]["market_close"].to_pydatetime()
        return open_t <= now_et <= close_t

    # --- Fallback: Mon-Fri, 9:30-16:00 ET, ignores holidays ---
    if now_et.weekday() >= 5:
        return False
    minutes = now_et.hour * 60 + now_et.minute
    return 9 * 60 + 30 <= minutes <= 16 * 60
