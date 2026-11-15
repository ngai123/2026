"""Market data scraper: gold, stocks, crypto, global indices via yfinance + LUNO API."""
import time
from typing import Optional
import yfinance as yf
import pandas as pd
from .base_scraper import BaseScraper
from database import repository as repo


class MarketScraper(BaseScraper):
    LUNO_TICKER_MAP = {
        "BTC": "XBTMYR",
        "ETH": "ETHMYR",
        "XRP": "XRPMYR",
        "LTC": "LTCMYR",
        "BCH": "BCHMYR",
        "SOL": "SOLMYR",
    }

    def __init__(self, usd_myr_rate: float = 4.47):
        super().__init__()
        self._usd_myr = usd_myr_rate

    # ─── Gold ─────────────────────────────────────────────────────────────────

    def get_gold_price_myr_per_gram(self) -> float:
        """Current gold price in MYR per gram."""
        try:
            ticker = yf.Ticker("GC=F")
            hist = ticker.history(period="5d")
            if not hist.empty:
                usd_per_troy_oz = hist["Close"].iloc[-1]
                grams_per_troy_oz = 31.1035
                usd_per_gram = usd_per_troy_oz / grams_per_troy_oz
                return round(usd_per_gram * self._usd_myr, 2)
        except Exception:
            pass
        return 380.0  # approximate fallback (MYR/gram)

    def get_gold_history_myr(self, years: int = 10) -> pd.DataFrame:
        """Historical gold price in MYR/gram."""
        try:
            ticker = yf.Ticker("GC=F")
            hist = ticker.history(period=f"{years}y")
            if not hist.empty:
                hist["myr_per_gram"] = (hist["Close"] / 31.1035) * self._usd_myr
                return hist[["myr_per_gram"]].rename(columns={"myr_per_gram": "price"})
        except Exception:
            pass
        return pd.DataFrame()

    # ─── Stocks ───────────────────────────────────────────────────────────────

    def get_stock_price(self, ticker: str, currency: str = "MYR") -> Optional[float]:
        """
        Fetch current price for any stock ticker.
        For Malaysian stocks use .KL suffix (e.g. MAYBANK.KL).
        For US stocks use standard ticker (e.g. AAPL).
        """
        try:
            t = yf.Ticker(ticker)
            hist = t.history(period="5d")
            if not hist.empty:
                price = hist["Close"].iloc[-1]
                info = t.info
                stock_currency = info.get("currency", "USD").upper()
                # Convert to MYR if needed
                if stock_currency != "MYR" and currency == "MYR":
                    if stock_currency == "USD":
                        price = price * self._usd_myr
                    elif stock_currency == "MYR":
                        pass  # already in MYR
                return round(price, 4)
        except Exception:
            pass
        return None

    def get_stock_history(self, ticker: str, years: int = 10) -> pd.DataFrame:
        """Historical OHLCV data for a stock."""
        try:
            t = yf.Ticker(ticker)
            return t.history(period=f"{years}y")
        except Exception:
            return pd.DataFrame()

    def get_portfolio_value(self, holdings: list[dict]) -> dict:
        """
        Calculate current value of a stock/crypto portfolio.
        holdings: [{"ticker": "AAPL", "quantity": 10, "currency": "USD"}, ...]
        Returns: {"total_myr": float, "positions": [...]}
        """
        positions = []
        total_myr = 0.0
        for h in holdings:
            ticker = h.get("ticker", "")
            qty = h.get("quantity", 0)
            if not ticker or not qty:
                continue
            price_myr = self.get_stock_price(ticker, currency="MYR")
            if price_myr:
                value_myr = price_myr * qty
                total_myr += value_myr
                positions.append({
                    "ticker": ticker,
                    "quantity": qty,
                    "price_myr": price_myr,
                    "value_myr": value_myr,
                })
        return {"total_myr": total_myr, "positions": positions}

    # ─── Crypto via LUNO ──────────────────────────────────────────────────────

    def get_crypto_price_myr(self, coin: str) -> Optional[float]:
        """Fetch crypto price in MYR from LUNO's public ticker API."""
        pair = self.LUNO_TICKER_MAP.get(coin.upper())
        if not pair:
            # Try yfinance as fallback (e.g. BTC-MYR on some exchanges)
            return self._crypto_via_yfinance(coin)
        url = f"https://api.luno.com/api/1/ticker?pair={pair}"
        data = self._get(url)
        if data and "last_trade" in data:
            return float(data["last_trade"])
        return self._crypto_via_yfinance(coin)

    def _crypto_via_yfinance(self, coin: str) -> Optional[float]:
        """Fallback: get crypto via yfinance (USD then convert)."""
        try:
            ticker_str = f"{coin.upper()}-USD"
            t = yf.Ticker(ticker_str)
            hist = t.history(period="5d")
            if not hist.empty:
                usd_price = hist["Close"].iloc[-1]
                return round(usd_price * self._usd_myr, 2)
        except Exception:
            pass
        return None

    def get_crypto_history(self, coin: str, years: int = 5) -> pd.DataFrame:
        """Historical crypto price in MYR."""
        try:
            t = yf.Ticker(f"{coin.upper()}-USD")
            hist = t.history(period=f"{years}y")
            if not hist.empty:
                hist["myr"] = hist["Close"] * self._usd_myr
                return hist[["myr"]].rename(columns={"myr": "price"})
        except Exception:
            pass
        return pd.DataFrame()

    # ─── Market Indices ───────────────────────────────────────────────────────

    def get_klci_history(self, years: int = 10) -> pd.DataFrame:
        """KLCI (Kuala Lumpur Composite Index) historical data."""
        try:
            t = yf.Ticker("^KLSE")
            return t.history(period=f"{years}y")
        except Exception:
            return pd.DataFrame()

    def get_sp500_history(self, years: int = 10) -> pd.DataFrame:
        """S&P 500 historical data."""
        try:
            t = yf.Ticker("^GSPC")
            return t.history(period=f"{years}y")
        except Exception:
            return pd.DataFrame()

    def get_index_cagr(self, index: str = "^KLSE", years: int = 10) -> float:
        """Calculate CAGR for a given index over N years."""
        try:
            t = yf.Ticker(index)
            hist = t.history(period=f"{years}y")
            if len(hist) >= 2:
                start = hist["Close"].iloc[0]
                end = hist["Close"].iloc[-1]
                cagr = (end / start) ** (1 / years) - 1
                return round(cagr * 100, 2)
        except Exception:
            pass
        return 6.0  # approximate KLCI CAGR fallback
