"""KWSP/EPF dividend history scraper with hardcoded seed fallback."""
from .base_scraper import BaseScraper
from database import repository as repo
from config import KWSP_DIVIDEND_HISTORY
from bs4 import BeautifulSoup


class KWSPScraper(BaseScraper):
    KWSP_URL = "https://www.kwsp.gov.my/en/member/about-your-savings/dividend-rate"

    def __init__(self):
        super().__init__()
        repo.seed_historical_data("KWSP_DIVIDEND", KWSP_DIVIDEND_HISTORY)

    def fetch_dividend_history(self) -> list[dict]:
        """Returns [{period (year), value (% p.a.)}] for EPF conventional account."""
        def live_fetch():
            html = self._get(self.KWSP_URL, headers={"Accept": "text/html"})
            if not html or not isinstance(html, str):
                return {}
            return self._parse_kwsp_table(html)

        return self.get_with_cache("KWSP_DIVIDEND", live_fetch, max_age_hours=720)  # monthly

    def _parse_kwsp_table(self, html: str) -> dict:
        """Parse dividend rate table from KWSP website."""
        result = {}
        try:
            soup = BeautifulSoup(html, "lxml")
            # KWSP usually has a table with year and rate columns
            tables = soup.find_all("table")
            for table in tables:
                rows = table.find_all("tr")
                for row in rows:
                    cells = row.find_all(["td", "th"])
                    if len(cells) >= 2:
                        year_text = cells[0].get_text(strip=True)
                        rate_text = cells[1].get_text(strip=True)
                        # Clean up
                        year_text = year_text.replace("%", "").strip()
                        rate_text = rate_text.replace("%", "").strip()
                        try:
                            year = int(year_text)
                            rate = float(rate_text)
                            if 2000 <= year <= 2030 and 0 < rate < 20:
                                result[year] = rate
                        except ValueError:
                            continue
        except Exception:
            pass
        return result

    def get_average_return(self, years: int = 10) -> float:
        """Returns average KWSP dividend over the last N years."""
        series = self.fetch_dividend_history()
        if not series:
            return 5.5
        recent = sorted(series, key=lambda x: x["period"])[-years:]
        if recent:
            return sum(r["value"] for r in recent) / len(recent)
        return 5.5

    def get_current_dividend(self) -> float:
        series = self.fetch_dividend_history()
        if series:
            return sorted(series, key=lambda x: x["period"])[-1]["value"]
        return 5.5
