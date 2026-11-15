"""
ToolExecutor — owns ALL tool implementations.

No LLM code, no HTTP code.  Pure tool execution only.
Merged from consultant.py, ollama_consultant.py, and mimo_consultant.py.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Optional

from database import repository as repo
from analysis.monte_carlo import MonteCarloEngine
from analysis.backtester import Backtester
from analysis.health_score import calculate_health_score
from scrapers.bnm_scraper import BNMScraper
from scrapers.kwsp_scraper import KWSPScraper
from scrapers.market_scraper import MarketScraper
import config


# ── Helpers ──────────────────────────────────────────────────────────

def _clean_items(items: list[dict]) -> list[dict]:
    """Normalise P&L item dicts (drop extra keys, coerce amount to float)."""
    return [
        {
            "description": i.get("description", ""),
            "category": i.get("category", "Other"),
            "amount": float(i.get("amount", 0)),
        }
        for i in items
    ]


# ── ToolExecutor ─────────────────────────────────────────────────────

class ToolExecutor:
    """Dispatch tool calls to analysis functions and return JSON-string results."""

    def __init__(self) -> None:
        self._mc: Optional[MonteCarloEngine] = None
        self._backtester: Optional[Backtester] = None
        self._bnm: Optional[BNMScraper] = None
        self._kwsp: Optional[KWSPScraper] = None
        self._market: Optional[MarketScraper] = None

    # ── Lazy engines ──────────────────────────────────────────────────

    def _mc_engine(self) -> MonteCarloEngine:
        if not self._mc:
            self._mc = MonteCarloEngine()
        return self._mc

    def _bt_engine(self) -> Backtester:
        if not self._backtester:
            self._backtester = Backtester()
        return self._backtester

    def _bnm_scraper(self) -> BNMScraper:
        if not self._bnm:
            self._bnm = BNMScraper()
        return self._bnm

    def _kwsp_scraper(self) -> KWSPScraper:
        if not self._kwsp:
            self._kwsp = KWSPScraper()
        return self._kwsp

    def _market_scraper(self) -> MarketScraper:
        if not self._market:
            usd_myr = self._bnm_scraper().fetch_exchange_rate("USD")
            self._market = MarketScraper(usd_myr_rate=usd_myr)
        return self._market

    # ── Dispatch ──────────────────────────────────────────────────────

    def execute(self, name: str, args: dict) -> str:
        """Dispatch a tool call by *name*.  Returns a JSON string."""
        try:
            dispatch = {
                "get_dashboard_summary": lambda: self._tool_dashboard(),
                "get_current_portfolio": lambda: self._tool_portfolio(),
                "get_balance_sheet_history": lambda: self._tool_bs_history(),
                "get_pnl_statement": lambda: self._tool_pnl(),
                "get_pnl_history": lambda: self._tool_pnl_history(),
                "get_expense_summary": lambda: self._tool_expense_summary(
                    args.get("period", ""),
                ),
                "record_expense": lambda: self._tool_record_expense(
                    description=str(args.get("description", "")),
                    amount=float(args.get("amount", 0)),
                    category=str(args.get("category", "Other")),
                    period=str(args.get("period", "")),
                ),
                "record_income": lambda: self._tool_record_income(
                    description=str(args.get("description", "")),
                    amount=float(args.get("amount", 0)),
                    category=str(args.get("category", "Other")),
                    period=str(args.get("period", "")),
                ),
                "run_monte_carlo": lambda: self._tool_monte_carlo(
                    years=int(args.get("years", 20)),
                    monthly_contribution=float(args.get("monthly_contribution", 0)),
                    inflation_adjust=bool(args.get("inflation_adjust", True)),
                ),
                "get_bnm_opr_history": lambda: self._tool_bnm_opr(),
                "get_kwsp_dividend_history": lambda: self._tool_kwsp(),
                "get_market_prices": lambda: self._tool_market_prices(
                    args.get("items", []),
                ),
                "backtest_strategies": lambda: self._tool_backtest(
                    strategies=args.get("strategies", []),
                    start_year=int(args.get("start_year", 2015)),
                    monthly_contribution=float(
                        args.get("monthly_contribution", 0)
                    ),
                ),
                "calculate_ptptn_payoff": lambda: self._tool_ptptn(
                    outstanding_balance=float(args.get("outstanding_balance", 0)),
                    monthly_payment=float(args.get("monthly_payment", 150)),
                    annual_rate=float(args.get("annual_rate", 1.0)),
                ),
                "analyse_investment": lambda: self._tool_analyse_investment(
                    investment_type=str(args.get("investment_type", "")),
                    symbol_or_name=str(args.get("symbol_or_name", "")),
                    amount_myr=(
                        float(args["amount_myr"])
                        if args.get("amount_myr")
                        else None
                    ),
                ),
                "get_sensitivity_analysis": lambda: self._tool_sensitivity(
                    years=int(args.get("years", 20)),
                ),
            }
            handler = dispatch.get(name)
            if handler:
                return handler()
            return json.dumps({"error": f"Unknown tool: {name}"})
        except Exception as e:
            return json.dumps({"error": str(e), "tool": name})

    # ── Tool implementations ──────────────────────────────────────────

    def _tool_dashboard(self) -> str:
        result: dict = {}
        snap_id = repo.get_latest_snapshot_id()
        if snap_id:
            snap = repo.get_snapshot(snap_id)
            result.update(
                {
                    "net_worth": snap["net_worth"],
                    "total_assets": snap["total_assets"],
                    "total_liabilities": snap["total_liabilities"],
                    "balance_sheet_period": snap.get("period", ""),
                }
            )
        pnl_id = repo.get_latest_pnl_id()
        if pnl_id:
            pnl = repo.get_pnl_items(pnl_id)
            result.update(
                {
                    "monthly_income": pnl["total_monthly_income"],
                    "monthly_expense": pnl["total_monthly_expense"],
                    "monthly_savings": pnl["net_monthly_savings"],
                    "savings_rate_pct": pnl["savings_rate_pct"],
                }
            )
        result["saved_periods"] = repo.list_all_periods()
        return json.dumps(result)

    def _tool_portfolio(self) -> str:
        snap_id = repo.get_latest_snapshot_id()
        if not snap_id:
            return json.dumps({"error": "No balance sheet data found."})
        snap = repo.get_snapshot(snap_id)
        assets = repo.get_snapshot_assets(snap_id)

        health = calculate_health_score(
            assets=assets,
            total_assets=snap["total_assets"],
            total_liabilities=snap["total_liabilities"],
            monthly_income=snap.get("monthly_income", 0),
            monthly_expense=snap.get("monthly_expense", 0),
            risk_profile=snap.get("risk_profile", "moderate"),
        )

        pnl_id = repo.get_latest_pnl_id()
        if pnl_id:
            pnl = repo.get_pnl_items(pnl_id)
            monthly_income = pnl["total_monthly_income"]
            monthly_expense = pnl["total_monthly_expense"]
        else:
            monthly_income = snap.get("monthly_income", 0)
            monthly_expense = snap.get("monthly_expense", 0)

        return json.dumps(
            {
                "label": snap.get("label", ""),
                "period": snap.get("period", ""),
                "date": snap.get("created_at", "")[:10],
                "net_worth": snap["net_worth"],
                "total_assets": snap["total_assets"],
                "total_liabilities": snap["total_liabilities"],
                "monthly_income": monthly_income,
                "monthly_expense": monthly_expense,
                "monthly_savings": max(0, monthly_income - monthly_expense),
                "risk_profile": snap.get("risk_profile", "moderate"),
                "health_score": health.total_score,
                "health_grade": health.grade,
                "top_issues": health.top_issues,
                "top_wins": health.top_wins,
                "recommendations": health.recommendations,
                "assets": [
                    {
                        "name": a["name"],
                        "category": a["category"],
                        "balance": a["balance"],
                        "is_liability": bool(a["is_liability"]),
                        "ticker": a.get("ticker", ""),
                    }
                    for a in assets
                ],
            }
        )

    def _tool_bs_history(self) -> str:
        rows = []
        for p in repo.list_snapshot_periods():
            snap = repo.get_snapshot_by_period(p)
            if snap:
                rows.append(
                    {
                        "period": p,
                        "net_worth": snap["net_worth"],
                        "total_assets": snap["total_assets"],
                        "total_liabilities": snap["total_liabilities"],
                    }
                )
        return json.dumps(rows)

    def _tool_pnl(self) -> str:
        pnl_id = repo.get_latest_pnl_id()
        if not pnl_id:
            return json.dumps({"error": "No P&L found."})
        return json.dumps(repo.get_pnl_items(pnl_id))

    def _tool_pnl_history(self) -> str:
        rows = []
        for p in repo.list_pnl_periods():
            data = repo.get_pnl_by_period(p)
            if data:
                rows.append(
                    {
                        "period": p,
                        "total_income": data["total_income"],
                        "total_expense": data["total_expense"],
                        "net_savings": data["net_savings"],
                        "savings_rate": data["savings_rate"],
                    }
                )
        return json.dumps(rows)

    def _tool_expense_summary(self, period: str = "") -> str:
        if not period:
            period = datetime.now().strftime("%Y-%m")
        data = repo.get_pnl_by_period(period)
        if not data:
            return json.dumps(
                {"period": period, "message": "No records for this period."}
            )
        by_cat: dict[str, float] = {}
        items = []
        for item in data.get("expense_items", []):
            cat = item.get("category", "Other")
            amt = float(item.get("amount", 0))
            by_cat[cat] = round(by_cat.get(cat, 0) + amt, 2)
            items.append(
                {
                    "description": item.get("description", ""),
                    "category": cat,
                    "amount": amt,
                }
            )
        return json.dumps(
            {
                "period": period,
                "total_income": data.get("total_income", 0),
                "total_expenses": data.get("total_expense", 0),
                "net_savings": data.get("net_savings", 0),
                "savings_rate_pct": round(data.get("savings_rate", 0), 1),
                "expense_by_category": by_cat,
                "expense_items": items,
            }
        )

    def _tool_record_expense(
        self,
        description: str,
        amount: float,
        category: str = "Other",
        period: str = "",
    ) -> str:
        if not period:
            period = datetime.now().strftime("%Y-%m")
        existing = repo.get_pnl_by_period(period)
        income_items = _clean_items(
            existing.get("income_items", []) if existing else []
        )
        expense_items = _clean_items(
            existing.get("expense_items", []) if existing else []
        )
        expense_items.append(
            {"description": description, "category": category, "amount": float(amount)}
        )
        repo.save_pnl(
            label="P&L",
            income_items=income_items,
            expense_items=expense_items,
            period=period,
        )
        return json.dumps(
            {
                "status": "recorded",
                "description": description,
                "amount": amount,
                "category": category,
                "period": period,
                "total_expenses_this_month": round(
                    sum(i["amount"] for i in expense_items), 2
                ),
            }
        )

    def _tool_record_income(
        self,
        description: str,
        amount: float,
        category: str = "Other",
        period: str = "",
    ) -> str:
        if not period:
            period = datetime.now().strftime("%Y-%m")
        existing = repo.get_pnl_by_period(period)
        income_items = _clean_items(
            existing.get("income_items", []) if existing else []
        )
        expense_items = _clean_items(
            existing.get("expense_items", []) if existing else []
        )
        income_items.append(
            {"description": description, "category": category, "amount": float(amount)}
        )
        repo.save_pnl(
            label="P&L",
            income_items=income_items,
            expense_items=expense_items,
            period=period,
        )
        return json.dumps(
            {
                "status": "recorded",
                "description": description,
                "amount": amount,
                "category": category,
                "period": period,
                "total_income_this_month": round(
                    sum(i["amount"] for i in income_items), 2
                ),
            }
        )

    def _tool_monte_carlo(
        self,
        years: int,
        monthly_contribution: float = 0,
        inflation_adjust: bool = True,
    ) -> str:
        snap_id = repo.get_latest_snapshot_id()
        if not snap_id:
            return json.dumps({"error": "No portfolio data."})
        snap = repo.get_snapshot(snap_id)
        assets = [
            a
            for a in repo.get_snapshot_assets(snap_id)
            if not a["is_liability"]
        ]
        if not monthly_contribution:
            monthly_contribution = max(
                0,
                snap.get("monthly_income", 0) - snap.get("monthly_expense", 0),
            )
        fire_number = snap.get("monthly_expense", 0) * 12 * config.FIRE_MULTIPLE
        r = self._mc_engine().run(
            assets=assets,
            years=years,
            monthly_contribution=monthly_contribution,
            fire_number=fire_number,
            inflation_adjust=inflation_adjust,
        )
        return json.dumps(
            {
                "years": years,
                "monthly_contribution": monthly_contribution,
                "initial_net_worth": snap["net_worth"],
                "median_final_rm": round(r.final_p50, 2),
                "optimistic_95th_rm": round(r.final_p95, 2),
                "pessimistic_5th_rm": round(r.final_p5, 2),
                "probability_of_doubling": f"{r.prob_double * 100:.1f}%",
                "probability_of_fire": f"{r.prob_fire * 100:.1f}%",
                "fire_number": round(fire_number, 2),
                "milestones": r.milestones,
            }
        )

    def _tool_bnm_opr(self) -> str:
        bnm = self._bnm_scraper()
        return json.dumps(
            {
                "opr_history": bnm.fetch_opr_history()[-20:],
                "current_opr": bnm.get_current_opr(),
                "estimated_12m_fd_rate": bnm.get_fd_rate_estimate(12),
                "base_lending_rate": bnm.fetch_base_lending_rate(),
            }
        )

    def _tool_kwsp(self) -> str:
        kwsp = self._kwsp_scraper()
        return json.dumps(
            {
                "history": kwsp.fetch_dividend_history()[-15:],
                "10yr_average": round(kwsp.get_average_return(10), 2),
                "current_dividend": kwsp.get_current_dividend(),
            }
        )

    def _tool_market_prices(self, items: list) -> str:
        market = self._market_scraper()
        results: dict = {}
        for item in items:
            t = (
                item.get("type", "stock")
                if isinstance(item, dict)
                else "stock"
            )
            symbol = (
                item.get("symbol", "") if isinstance(item, dict) else ""
            )
            if t == "gold":
                results["gold_myr_per_gram"] = market.get_gold_price_myr_per_gram()
            elif t == "crypto":
                results[symbol] = market.get_crypto_price_myr(symbol)
            elif t in ("stock", "index"):
                results[symbol] = market.get_stock_price(symbol)
        return json.dumps(results)

    def _tool_backtest(
        self,
        strategies: list,
        start_year: int,
        monthly_contribution: float = 0,
    ) -> str:
        snap_id = repo.get_latest_snapshot_id()
        initial = 10_000
        if snap_id:
            snap = repo.get_snapshot(snap_id)
            initial = snap.get("net_worth", 10_000)

        results = [
            self._bt_engine().run(
                allocation=s["allocation"],
                initial_capital=max(initial, 1000),
                start_year=start_year,
                monthly_contribution=monthly_contribution,
                strategy_name=s["name"],
            )
            for s in strategies
        ]

        return json.dumps(
            [
                {
                    "strategy": r.strategy_name,
                    "start_year": r.start_year,
                    "end_year": r.end_year,
                    "initial_capital": r.initial_capital,
                    "final_value": r.final_value,
                    "cagr_pct": r.cagr,
                    "total_return_pct": r.total_return_pct,
                    "best_year_pct": r.best_year_pct,
                    "worst_year_pct": r.worst_year_pct,
                    "max_drawdown_pct": r.max_drawdown_pct,
                    "sharpe_ratio": r.sharpe_ratio,
                    "yearly_values": r.yearly_values,
                }
                for r in results
            ]
        )

    def _tool_ptptn(
        self,
        outstanding_balance: float,
        monthly_payment: float = 150.0,
        annual_rate: float = 1.0,
    ) -> str:
        result = self._bt_engine().calculate_ptptn_payoff(
            outstanding=outstanding_balance,
            monthly_payment=monthly_payment,
            annual_rate=annual_rate,
        )
        return json.dumps(result)

    def _tool_analyse_investment(
        self,
        investment_type: str,
        symbol_or_name: str,
        amount_myr: Optional[float] = None,
    ) -> str:
        market = self._market_scraper()
        result: dict = {"investment": symbol_or_name, "type": investment_type}

        if investment_type in ("stock", "etf", "index", "reit"):
            hist = market.get_stock_history(symbol_or_name, years=5)
            if not hist.empty:
                start_price = hist["Close"].iloc[0]
                end_price = hist["Close"].iloc[-1]
                returns = hist["Close"].pct_change().dropna()
                result.update(
                    {
                        "price_5yr_ago": round(float(start_price), 4),
                        "current_price": round(float(end_price), 4),
                        "5yr_return_pct": round(
                            (end_price / start_price - 1) * 100, 2
                        ),
                        "5yr_cagr_pct": round(
                            ((end_price / start_price) ** (1 / 5) - 1) * 100, 2
                        ),
                        "annual_volatility_pct": round(
                            float(returns.std() * (252 ** 0.5) * 100), 2
                        ),
                        "data_available": True,
                    }
                )
            else:
                result["data_available"] = False

        elif investment_type == "crypto":
            hist = market.get_crypto_history(symbol_or_name, years=3)
            if not hist.empty:
                start_price = hist["price"].iloc[0]
                end_price = hist["price"].iloc[-1]
                result.update(
                    {
                        "price_3yr_ago_myr": round(float(start_price), 2),
                        "current_price_myr": round(float(end_price), 2),
                        "3yr_return_pct": round(
                            (end_price / start_price - 1) * 100, 2
                        ),
                        "note": (
                            "Crypto is highly volatile. Only invest what you "
                            "can afford to lose entirely."
                        ),
                        "data_available": True,
                    }
                )
            else:
                result["data_available"] = False

        elif investment_type == "gold":
            price = market.get_gold_price_myr_per_gram()
            result.update(
                {
                    "current_price_myr_per_gram": price,
                    "note": (
                        "Gold is a traditional hedge against inflation "
                        "and currency weakness."
                    ),
                    "data_available": True,
                }
            )

        snap_id = repo.get_latest_snapshot_id()
        if snap_id:
            snap = repo.get_snapshot(snap_id)
            result["risk_profile"] = snap.get("risk_profile", "moderate")
            if amount_myr:
                result["pct_of_portfolio"] = round(
                    amount_myr / max(snap["total_assets"], 1) * 100, 1
                )

        return json.dumps(result)

    def _tool_sensitivity(self, years: int = 20) -> str:
        snap_id = repo.get_latest_snapshot_id()
        if not snap_id:
            return json.dumps({"error": "No portfolio data."})
        assets = [
            a
            for a in repo.get_snapshot_assets(snap_id)
            if not a["is_liability"]
        ]
        df = self._mc_engine().sensitivity_analysis(assets, years=years)
        return json.dumps(df.to_dict(orient="records"))
