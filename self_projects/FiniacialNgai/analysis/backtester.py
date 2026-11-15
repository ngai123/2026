"""
Backtesting engine — replays historical returns against the user's allocation.
Uses real KWSP/ASNB seed data for historical accuracy.
"""
import numpy as np
from dataclasses import dataclass
from typing import Optional
import datetime

from config.seed_data import (
    KWSP_DIVIDEND_HISTORY,
    ASNB_RIA_HISTORY,
    ASNB_MUTUAL_HISTORY,
)

# ── Preset strategies (shared lookup table) ──────────────────────────────────
PRESET_STRATEGIES = {
    "100% KWSP": {
        "KWSP_EPF": 1.0,
    },
    "Conservative (EPF + FD)": {
        "KWSP_EPF": 0.70,
        "MAYBANK_FD": 0.20,
        "ASNB_RIA": 0.10,
    },
    "Balanced (EPF + ASNB + Stocks)": {
        "KWSP_EPF": 0.50,
        "ASNB_MUTUAL": 0.20,
        "MOOMOO_STOCKS": 0.20,
        "GOLD": 0.10,
    },
    "Growth (Stocks + Gold + Crypto)": {
        "MOOMOO_STOCKS": 0.40,
        "SP500": 0.30,
        "GOLD": 0.20,
        "LUNO_CRYPTO": 0.10,
    },
    "Malaysian Diversified": {
        "KWSP_EPF": 0.30,
        "ASNB_RIA": 0.15,
        "ASNB_MUTUAL": 0.15,
        "MOOMOO_STOCKS": 0.20,
        "GOLD": 0.10,
        "MAYBANK_FD": 0.10,
    },
}


@dataclass
class BacktestResult:
    strategy_name: str
    start_year: int
    end_year: int
    initial_capital: float
    monthly_contribution: float
    final_value: float
    cagr: float              # annualised return %
    total_invested: float
    total_return_pct: float
    best_year_pct: float
    worst_year_pct: float
    max_drawdown_pct: float
    sharpe_ratio: float
    yearly_values: dict       # {year: portfolio_value}


def _cagr(start: float, end: float, years: float) -> float:
    if start <= 0 or years <= 0:
        return 0.0
    return ((end / start) ** (1 / years) - 1) * 100


def _max_drawdown(values: list[float]) -> float:
    arr = np.array(values)
    peak = np.maximum.accumulate(arr)
    drawdown = (arr - peak) / peak
    return float(drawdown.min() * 100)


def _sharpe(annual_returns: list[float], risk_free_rate: float = 3.0) -> float:
    if len(annual_returns) < 2:
        return 0.0
    r = np.array(annual_returns)
    excess = r - risk_free_rate
    if np.std(r) == 0:
        return 0.0
    return float(np.mean(excess) / np.std(r))


class Backtester:
    """Replay historical returns for user-defined allocations."""

    def __init__(self):
        pass

    # ── Core run ─────────────────────────────────────────────────────────────

    def run(
        self,
        allocation: dict,        # {"KWSP_EPF": 0.5, "ASNB_RIA": 0.3, "GOLD": 0.2}
        initial_capital: float,
        start_year: int,
        end_year: Optional[int] = None,
        monthly_contribution: float = 0.0,
        strategy_name: str = "Strategy",
    ) -> BacktestResult:
        """
        Backtest an allocation using historical rates.

        Each month: add the monthly contribution, then apply 1/12th of that
        year's annual return for the weighted portfolio.
        """
        if end_year is None:
            end_year = datetime.date.today().year - 1

        years = list(range(start_year, end_year + 1))
        portfolio_value = initial_capital
        yearly_values = {}
        total_invested = initial_capital
        annual_returns = []
        all_values = [initial_capital]

        for year in years:
            year_start_value = portfolio_value

            # Get annual return for each asset (cached per year)
            annual_weighted_return = self._get_weighted_return(allocation, year)
            monthly_return = annual_weighted_return / 100.0 / 12.0

            # Simulate 12 months: add contribution then compound
            for _month in range(12):
                portfolio_value += monthly_contribution
                total_invested += monthly_contribution
                portfolio_value *= (1.0 + monthly_return)

            yearly_values[year] = round(portfolio_value, 2)
            all_values.append(portfolio_value)

            if year_start_value > 0:
                annual_returns.append(
                    ((portfolio_value - year_start_value) / year_start_value) * 100
                )

        total_years = len(years)
        cagr = _cagr(initial_capital, portfolio_value, total_years)
        total_return = ((portfolio_value - initial_capital) / initial_capital) * 100
        best_year = max(annual_returns) if annual_returns else 0
        worst_year = min(annual_returns) if annual_returns else 0
        drawdown = _max_drawdown(all_values)
        risk_free = self._get_avg_opr(start_year, end_year)
        sharpe = _sharpe(annual_returns, risk_free)

        return BacktestResult(
            strategy_name=strategy_name,
            start_year=start_year,
            end_year=end_year,
            initial_capital=initial_capital,
            monthly_contribution=monthly_contribution,
            final_value=round(portfolio_value, 2),
            cagr=round(cagr, 2),
            total_invested=round(total_invested, 2),
            total_return_pct=round(total_return, 2),
            best_year_pct=round(best_year, 2),
            worst_year_pct=round(worst_year, 2),
            max_drawdown_pct=round(drawdown, 2),
            sharpe_ratio=round(sharpe, 2),
            yearly_values=yearly_values,
        )

    # ── Compare presets ──────────────────────────────────────────────────────

    def compare_strategies(
        self,
        strategies: list[str],
        initial_capital: float,
        start_year: int,
        monthly_contribution: float = 0.0,
    ) -> list[BacktestResult]:
        """Run preset strategies by name for side-by-side comparison.

        Parameters
        ----------
        strategies : list[str]
            Strategy name strings that exist as keys in ``PRESET_STRATEGIES``.
        initial_capital : float
            Starting portfolio value in RM.
        start_year : int
            First year of the backtest window.
        monthly_contribution : float
            Additional monthly investment in RM (default 0).

        Returns
        -------
        list[BacktestResult]
            One result per strategy, in the same order as *strategies*.
        """
        results: list[BacktestResult] = []
        for name in strategies:
            allocation = PRESET_STRATEGIES.get(name)
            if allocation is None:
                raise KeyError(
                    f"Unknown preset strategy '{name}'. "
                    f"Available: {list(PRESET_STRATEGIES.keys())}"
                )
            result = self.run(
                allocation=allocation,
                initial_capital=initial_capital,
                start_year=start_year,
                monthly_contribution=monthly_contribution,
                strategy_name=name,
            )
            results.append(result)
        return results

    # ── PTPTN calculator ─────────────────────────────────────────────────────

    def calculate_ptptn_payoff(
        self,
        outstanding: float,
        monthly_payment: float = 150.0,
        annual_rate: float = 1.0,       # 1% ICR default
    ) -> dict:
        """Compute PTPTN loan amortization schedule.

        Returns
        -------
        dict with keys:
            months_to_payoff, total_interest, total_paid,
            years_to_payoff, schedule (first 24 months)
        """
        monthly_rate = annual_rate / 100 / 12
        schedule = []
        balance = outstanding
        total_interest = 0.0
        month = 0

        while balance > 0.01 and month < 600:  # max 50 years
            interest = balance * monthly_rate
            principal = min(monthly_payment - interest, balance)
            if principal <= 0:
                break  # payment doesn't cover interest
            balance -= principal
            total_interest += interest
            month += 1
            schedule.append({
                "month": month,
                "payment": round(monthly_payment, 2),
                "principal": round(principal, 2),
                "interest": round(interest, 2),
                "balance": round(balance, 2),
            })

        return {
            "months_to_payoff": month,
            "years_to_payoff": round(month / 12, 1),
            "total_interest": round(total_interest, 2),
            "total_paid": round(outstanding + total_interest, 2),
            "schedule": schedule[:24],  # first 2 years for display
        }

    # ── Asset return lookups ─────────────────────────────────────────────────

    def _get_weighted_return(self, allocation: dict, year: int) -> float:
        """Get weighted portfolio return for a year."""
        total_return = 0.0
        for asset_key, weight in allocation.items():
            rate = self._get_asset_return(asset_key, year)
            total_return += rate * weight
        return total_return

    def _get_asset_return(self, asset_key: str, year: int) -> float:
        """Look up historical return for an asset in a given year.

        Priority: seed data (KWSP/ASNB), then averages for other assets.
        """
        key = asset_key.upper()

        # KWSP/EPF — use real dividend history
        if key in ("KWSP_EPF", "KWSP", "EPF"):
            if year in KWSP_DIVIDEND_HISTORY:
                return KWSP_DIVIDEND_HISTORY[year]
            # Fallback: use average of all available years
            return float(np.mean(list(KWSP_DIVIDEND_HISTORY.values())))

        # ASNB RIA — use real return history
        if key in ("ASNB_RIA",):
            if year in ASNB_RIA_HISTORY:
                return ASNB_RIA_HISTORY[year]
            return float(np.mean(list(ASNB_RIA_HISTORY.values())))

        # ASNB Mutual — use real return history
        if key in ("ASNB_MUTUAL",):
            if year in ASNB_MUTUAL_HISTORY:
                return ASNB_MUTUAL_HISTORY[year]
            return float(np.mean(list(ASNB_MUTUAL_HISTORY.values())))

        # Fixed Deposit / Savings — proxy by BNM OPR
        if key in ("MAYBANK_FD", "FD", "FIXED_DEPOSIT"):
            return 3.0 if year < 2020 else 2.0

        # Gold — approximate 8% average per year
        if key == "GOLD":
            return 8.0

        # Malaysian Stocks (KLCI) — approximate 7% average per year
        if key in ("MOOMOO_STOCKS", "KLCI", "MALAYSIAN_STOCKS"):
            return 7.0

        # S&P 500 — approximate 10% average per year
        if key in ("SP500", "S&P500"):
            return 10.0

        # Crypto — 50% average but very volatile
        if key in ("LUNO_CRYPTO", "BTC", "ETH", "CRYPTO"):
            # Use seeded random for reproducibility per year+key
            rng = np.random.RandomState(hash(f"{key}_{year}") % (2**31))
            base = 50.0
            volatility = 80.0
            return float(rng.normal(base, volatility))

        # Default fallback
        return 6.0

    def _get_avg_opr(self, start_year: int, end_year: int) -> float:
        """Estimate average risk-free rate across the period."""
        rates = []
        for yr in range(start_year, end_year + 1):
            rates.append(3.0 if yr < 2020 else 2.0)
        return float(np.mean(rates)) if rates else 3.0
