"""
Monte Carlo simulation engine.
Runs N correlated simulations across all asset classes with Malaysian-specific
return parameters. Supports arbitrary asset types beyond presets.
"""
import numpy as np
import pandas as pd
from dataclasses import dataclass, field
from typing import Optional
from config import ASSET_RETURN_PARAMS, DEFAULT_SIMULATIONS, DEFAULT_INFLATION_RATE


@dataclass
class MonteCarloResult:
    years: int
    monthly_contribution: float
    n_simulations: int
    # Percentile paths — shape: (years*12,)
    p5:     np.ndarray
    p25:    np.ndarray
    p50:    np.ndarray
    p75:    np.ndarray
    p95:    np.ndarray
    # Final values
    final_p5:  float
    final_p25: float
    final_p50: float
    final_p75: float
    final_p95: float
    # Time to milestones (median path) in years
    milestones: dict[str, Optional[float]] = field(default_factory=dict)
    # Probability metrics
    prob_double:     float = 0.0   # probability of doubling net worth
    prob_fire:       float = 0.0   # probability of reaching FIRE number
    fire_number:     float = 0.0

    def months_array(self) -> np.ndarray:
        return np.arange(1, self.years * 12 + 1)

    def years_array(self) -> np.ndarray:
        return self.months_array() / 12


def _asset_params(asset_key: str, annual_return_override: Optional[float] = None) -> tuple[float, float]:
    """Returns (mean_monthly_return, monthly_std)."""
    if annual_return_override is not None:
        annual_mean = annual_return_override / 100
        annual_std = 0.02  # tight std for user-provided rates
    else:
        params = ASSET_RETURN_PARAMS.get(asset_key.upper())
        if params:
            annual_mean = params["mean"]
            annual_std  = params["std"]
        else:
            # Unknown asset — use moderate defaults
            annual_mean = 0.07
            annual_std  = 0.15

    monthly_mean = (1 + annual_mean) ** (1/12) - 1
    monthly_std  = annual_std / np.sqrt(12)
    return monthly_mean, monthly_std


class MonteCarloEngine:
    def __init__(self, n_simulations: int = DEFAULT_SIMULATIONS,
                 inflation_rate: float = DEFAULT_INFLATION_RATE,
                 random_seed: int = 42):
        self.n_simulations = n_simulations
        self.inflation_rate = inflation_rate
        self.rng = np.random.default_rng(random_seed)

    def run(
        self,
        assets: list[dict],          # from DB: [{asset_key, balance, annual_return_pct, ...}]
        years: int = 20,
        monthly_contribution: float = 0.0,
        fire_number: float = 0.0,
        inflation_adjust: bool = True,
    ) -> MonteCarloResult:
        """
        Run correlated Monte Carlo simulation.

        assets: list of asset dicts with at least 'balance', 'asset_key'.
                Any asset type is supported — unknowns use moderate defaults.
        """
        n_months = years * 12
        n_assets = len(assets)

        if n_assets == 0:
            return self._empty_result(years, monthly_contribution, fire_number)

        # Build parameter arrays
        means = np.zeros(n_assets)
        stds  = np.zeros(n_assets)
        balances = np.zeros(n_assets)
        for i, a in enumerate(assets):
            m, s = _asset_params(a.get("asset_key", "CUSTOM"),
                                  a.get("annual_return_pct"))
            means[i] = m
            stds[i]  = s
            balances[i] = float(a.get("balance", 0))

        total_initial = balances.sum()
        weights = balances / total_initial if total_initial > 0 else np.ones(n_assets) / n_assets

        # Portfolio-level simulation (weighted blend)
        port_mean = float(np.dot(weights, means))
        port_std  = float(np.sqrt(np.dot(weights ** 2, stds ** 2)))  # simplified, no full covariance

        # Simulate: shape (n_simulations, n_months)
        monthly_returns = self.rng.normal(
            loc=port_mean,
            scale=port_std,
            size=(self.n_simulations, n_months)
        )

        # Compound growth paths
        paths = np.zeros((self.n_simulations, n_months))
        current = np.full(self.n_simulations, total_initial)

        monthly_inflation = (1 + self.inflation_rate) ** (1/12) - 1

        for t in range(n_months):
            current = current * (1 + monthly_returns[:, t]) + monthly_contribution
            if inflation_adjust:
                paths[:, t] = current / ((1 + monthly_inflation) ** (t + 1))
            else:
                paths[:, t] = current

        p5  = np.percentile(paths, 5,  axis=0)
        p25 = np.percentile(paths, 25, axis=0)
        p50 = np.percentile(paths, 50, axis=0)
        p75 = np.percentile(paths, 75, axis=0)
        p95 = np.percentile(paths, 95, axis=0)

        # Milestones on median path
        milestones = self._compute_milestones(p50, total_initial, n_months)

        # Probabilities
        final_values = paths[:, -1]
        prob_double = float(np.mean(final_values >= 2 * total_initial))
        prob_fire = float(np.mean(final_values >= fire_number)) if fire_number > 0 else 0.0

        return MonteCarloResult(
            years=years,
            monthly_contribution=monthly_contribution,
            n_simulations=self.n_simulations,
            p5=p5, p25=p25, p50=p50, p75=p75, p95=p95,
            final_p5=float(p5[-1]),
            final_p25=float(p25[-1]),
            final_p50=float(p50[-1]),
            final_p75=float(p75[-1]),
            final_p95=float(p95[-1]),
            milestones=milestones,
            prob_double=prob_double,
            prob_fire=prob_fire,
            fire_number=fire_number,
        )

    def sensitivity_analysis(
        self,
        assets: list[dict],
        years: int = 20,
        contributions_range: Optional[list] = None,
    ) -> list[dict]:
        """Run MC for a range of monthly contribution deltas and return summary stats.

        Parameters
        ----------
        assets : list[dict]
            Asset dicts accepted by :meth:`run`.
        years : int
            Projection horizon.
        contributions_range : list[float] | None
            Monthly contribution amounts to test. Defaults to
            [-3000, -2000, -1000, -500, 0, 500, 1000, 2000, 3000].

        Returns
        -------
        list[dict]
            Each dict has keys: monthly_contribution, median_rm, p5_rm,
            p95_rm, prob_fire_pct.
        """
        if contributions_range is None:
            contributions_range = [-3000, -2000, -1000, -500, 0, 500, 1000, 2000, 3000]

        results = []
        for mc in contributions_range:
            res = self.run(assets=assets, years=years, monthly_contribution=mc)
            results.append({
                "monthly_contribution": mc,
                "median_rm":     res.final_p50,
                "p5_rm":         res.final_p5,
                "p95_rm":        res.final_p95,
                "prob_fire_pct": round(res.prob_fire * 100, 2),
            })
        return results

    def run_scenario_comparison(
        self,
        assets: list[dict],
        scenarios: list[dict],
        years: int = 20,
    ) -> list[dict]:
        """Compare multiple contribution scenarios side by side.

        Parameters
        ----------
        assets : list[dict]
            Asset dicts accepted by :meth:`run`.
        scenarios : list[dict]
            Each dict must have keys ``label`` (str) and
            ``monthly_contribution`` (float).
        years : int
            Projection horizon (shared across all scenarios).

        Returns
        -------
        list[dict]
            Each dict has keys: label, monthly_contribution, median_rm,
            p5_rm, p95_rm, prob_fire_pct.
        """
        results = []
        for s in scenarios:
            res = self.run(
                assets=assets,
                years=years,
                monthly_contribution=s["monthly_contribution"],
            )
            results.append({
                "label":                s["label"],
                "monthly_contribution": s["monthly_contribution"],
                "median_rm":            res.final_p50,
                "p5_rm":                res.final_p5,
                "p95_rm":               res.final_p95,
                "prob_fire_pct":        round(res.prob_fire * 100, 2),
            })
        return results

    def _compute_milestones(self, p50: np.ndarray,
                             initial: float, n_months: int) -> dict[str, Optional[float]]:
        targets = {
            "RM 100,000": 100_000,
            "RM 250,000": 250_000,
            "RM 500,000": 500_000,
            "RM 1,000,000": 1_000_000,
        }
        milestones = {}
        for label, target in targets.items():
            if target <= initial:
                milestones[label] = 0.0  # already there
                continue
            idx = np.argmax(p50 >= target)
            if p50[idx] >= target:
                milestones[label] = round((idx + 1) / 12, 1)
            else:
                milestones[label] = None  # won't reach within horizon
        return milestones

    def _empty_result(self, years, monthly_contribution, fire_number) -> MonteCarloResult:
        arr = np.zeros(years * 12)
        return MonteCarloResult(
            years=years, monthly_contribution=monthly_contribution,
            n_simulations=self.n_simulations,
            p5=arr, p25=arr, p50=arr, p75=arr, p95=arr,
            final_p5=0, final_p25=0, final_p50=0, final_p75=0, final_p95=0,
        )
