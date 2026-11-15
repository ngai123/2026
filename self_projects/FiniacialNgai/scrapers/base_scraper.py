"""Base scraper with caching, retry logic, and rate limiting."""
import time
import json
import httpx
from pathlib import Path
from datetime import datetime, timedelta
from typing import Any, Optional
from database import repository as repo


class BaseScraper:
    BASE_HEADERS = {
        "User-Agent": "FinancialNgai/1.0 (personal finance app; educational use)",
        "Accept": "application/json",
    }
    REQUEST_DELAY = 1.5  # seconds between requests (be a good citizen)
    MAX_RETRIES = 3

    def __init__(self):
        self._last_request: float = 0

    def _throttle(self):
        elapsed = time.time() - self._last_request
        if elapsed < self.REQUEST_DELAY:
            time.sleep(self.REQUEST_DELAY - elapsed)
        self._last_request = time.time()

    def _get(self, url: str, headers: Optional[dict] = None,
             params: Optional[dict] = None, timeout: int = 15) -> Optional[Any]:
        """HTTP GET with retry and throttle."""
        merged_headers = {**self.BASE_HEADERS, **(headers or {})}
        for attempt in range(self.MAX_RETRIES):
            try:
                self._throttle()
                resp = httpx.get(url, headers=merged_headers,
                                 params=params, timeout=timeout,
                                 follow_redirects=True)
                resp.raise_for_status()
                ct = resp.headers.get("content-type", "")
                if "json" in ct:
                    return resp.json()
                return resp.text
            except httpx.HTTPStatusError as e:
                if e.response.status_code in (403, 404, 410):
                    return None  # don't retry client errors
                if attempt < self.MAX_RETRIES - 1:
                    time.sleep(2 ** attempt)
            except (httpx.TimeoutException, httpx.NetworkError):
                if attempt < self.MAX_RETRIES - 1:
                    time.sleep(2 ** attempt)
        return None

    def get_with_cache(self, source: str, fetcher_fn,
                       max_age_hours: int = 24) -> list[dict]:
        """
        Try DB cache first, fall back to live fetch.
        Returns list of {period, value} dicts.
        """
        cached = repo.get_cached_series(source, max_age_hours)
        if cached:
            return cached
        # Live fetch
        try:
            data = fetcher_fn()
            if data:
                for period, value in data.items():
                    repo.upsert_cache(source, str(period), float(value))
                return repo.get_all_cached_series(source)
        except Exception:
            pass
        # Fallback to stale cache
        return repo.get_all_cached_series(source)
