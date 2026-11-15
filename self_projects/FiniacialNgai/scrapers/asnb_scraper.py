"""ASNB (Amanah Saham Nasional Berhad) scraper with seed data fallback."""
from .base_scraper import BaseScraper
from database import repository as repo
from config import ASNB_RIA_HISTORY, ASNB_MUTUAL_HISTORY


class ASNBScraper(BaseScraper):
    ASNB_BASE = "https://www.asnb.com.my"

    def __init__(self):
        super().__init__()
        repo.seed_historical_data("ASNB_RIA", ASNB_RIA_HISTORY)
        repo.seed_historical_data("ASNB_MUTUAL", ASNB_MUTUAL_HISTORY)

    def fetch_ria_history(self) -> list[dict]:
        def live_fetch():
            # ASNB uses JavaScript rendering; try simple scrape, fallback to seed
            html = self._get(f"{self.ASNB_BASE}/en/funds/fixed-price/asnb-ria",
                             headers={"Accept": "text/html"})
            if html and isinstance(html, str):
                return self._parse_dividend_table(html, "RIA")
            return {}

        return self.get_with_cache("ASNB_RIA", live_fetch, max_age_hours=720)

    def fetch_mutual_history(self) -> list[dict]:
        def live_fetch():
            html = self._get(f"{self.ASNB_BASE}/en/funds/variable-price/asnb-mutual",
                             headers={"Accept": "text/html"})
            if html and isinstance(html, str):
                return self._parse_dividend_table(html, "MUTUAL")
            return {}

        return self.get_with_cache("ASNB_MUTUAL", live_fetch, max_age_hours=720)

    def _parse_dividend_table(self, html: str, fund_type: str) -> dict:
        from bs4 import BeautifulSoup
        result = {}
        try:
            soup = BeautifulSoup(html, "lxml")
            for table in soup.find_all("table"):
                rows = table.find_all("tr")
                for row in rows:
                    cells = row.find_all(["td", "th"])
                    if len(cells) >= 2:
                        try:
                            year = int(cells[0].get_text(strip=True))
                            rate = float(cells[1].get_text(strip=True).replace("%", ""))
                            if 2000 <= year <= 2030 and 0 < rate < 20:
                                result[year] = rate
                        except ValueError:
                            continue
        except Exception:
            pass
        return result

    def get_ria_average(self, years: int = 5) -> float:
        series = self.fetch_ria_history()
        recent = sorted(series, key=lambda x: x["period"])[-years:]
        if recent:
            return sum(r["value"] for r in recent) / len(recent)
        return 4.5

    def get_mutual_average(self, years: int = 5) -> float:
        series = self.fetch_mutual_history()
        recent = sorted(series, key=lambda x: x["period"])[-years:]
        if recent:
            return sum(r["value"] for r in recent) / len(recent)
        return 6.0
