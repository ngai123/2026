"""BNM (Bank Negara Malaysia) public API scraper.

Endpoints used:
  GET /public/opr          — Overnight Policy Rate history
  GET /public/base-rate    — Base lending rate
  GET /public/exchange-rate — USD/MYR and other forex rates

BNM requires the Accept header: application/vnd.BNM.API.v1+json
"""
from .base_scraper import BaseScraper
from database import repository as repo
import config


class BNMScraper(BaseScraper):
    BASE_URL = config.BNM_API_BASE
    BNM_ACCEPT = "application/vnd.BNM.API.v1+json"

    # Hardcoded OPR history as reliable fallback (% p.a.)
    OPR_SEED = {
        "2010": 2.75, "2011": 3.00, "2012": 3.00, "2013": 3.00,
        "2014": 3.25, "2015": 3.25, "2016": 3.00, "2017": 3.00,
        "2018": 3.25, "2019": 3.00, "2020-H1": 2.75, "2020-H2": 1.75,
        "2021": 1.75, "2022-H1": 2.25, "2022-H2": 2.75,
        "2023": 3.00, "2024": 3.00, "2025": 3.00,
    }

    def __init__(self):
        super().__init__()
        # Ensure seed data exists
        repo.seed_historical_data("BNM_OPR", self.OPR_SEED)

    def _bnm_get(self, endpoint: str):
        url = f"{self.BASE_URL}/{endpoint}"
        return self._get(url, headers={"Accept": self.BNM_ACCEPT})

    def fetch_opr_history(self) -> list[dict]:
        """Returns [{period, value}] sorted by period."""
        def live_fetch():
            data = self._bnm_get("opr")
            if not data or "data" not in data:
                return {}
            result = {}
            for item in data["data"]:
                period = item.get("date", item.get("period", ""))[:7]  # YYYY-MM
                rate = item.get("rate", item.get("opr_rate"))
                if period and rate is not None:
                    result[period] = float(rate)
            return result

        return self.get_with_cache("BNM_OPR", live_fetch, max_age_hours=168)  # weekly

    def fetch_exchange_rate(self, currency: str = "USD") -> float:
        """Returns MYR per 1 unit of given currency."""
        try:
            data = self._bnm_get(f"exchange-rate")
            if data and "data" in data:
                for item in data["data"]:
                    if item.get("currency_code") == currency:
                        rate = item.get("middle_rate") or item.get("rate")
                        if rate:
                            return float(rate)
        except Exception:
            pass
        # Fallback: approximate rate
        fallback = {"USD": 4.47, "SGD": 3.30, "EUR": 4.90, "GBP": 5.60}
        return fallback.get(currency, 4.47)

    def fetch_base_lending_rate(self) -> float:
        """Returns current Base Rate (BR) as %."""
        try:
            data = self._bnm_get("base-rate")
            if data and "data" in data:
                items = data["data"]
                if items:
                    return float(items[0].get("base_rate", 3.0))
        except Exception:
            pass
        return 3.0  # fallback approximate

    def get_current_opr(self) -> float:
        """Returns the most recent OPR rate."""
        series = self.fetch_opr_history()
        if series:
            return series[-1]["value"]
        return 3.0

    def get_fd_rate_estimate(self, tenure_months: int = 12) -> float:
        """Estimate FD rate based on current OPR.
        Typical spread: 12M FD ≈ OPR - 0.5%
        """
        opr = self.get_current_opr()
        spreads = {1: -1.0, 3: -0.75, 6: -0.6, 12: -0.5}
        closest = min(spreads.keys(), key=lambda m: abs(m - tenure_months))
        return max(0, opr + spreads[closest])
