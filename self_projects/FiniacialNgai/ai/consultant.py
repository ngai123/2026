# DEPRECATED — use ai/chat.py Consultant instead
"""
Gemini Financial Consultant — orchestrates the AI with tool use.
Connects Gemini function calls to the actual analysis engines.
"""
import json
from typing import Generator, Optional
from google import genai
from google.genai import types
from database import repository as repo
from analysis.monte_carlo import MonteCarloEngine
from analysis.backtester import Backtester
from analysis.health_score import calculate_health_score
from scrapers.bnm_scraper import BNMScraper
from scrapers.kwsp_scraper import KWSPScraper
from scrapers.market_scraper import MarketScraper
from ai.registry import SYSTEM_PROMPT, build_gemini_tools
import config


def _to_python(val):
    """Recursively convert proto MapComposite/RepeatedComposite to plain Python."""
    if hasattr(val, "items"):
        return {k: _to_python(v) for k, v in val.items()}
    if hasattr(val, "__iter__") and not isinstance(val, (str, bytes)):
        return [_to_python(v) for v in val]
    return val


class FinancialConsultant:
    """Main AI consultant class — streams responses and handles tool use loop."""

    def __init__(self, api_key: str):
        self.client = genai.Client(api_key=api_key)
        self._tools = build_gemini_tools()
        self._gen_config = types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT,
            tools=self._tools,
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        )
        self.mc_engine = MonteCarloEngine()
        self.backtester = Backtester()
        self._bnm = None
        self._kwsp = None
        self._market = None

    @property
    def bnm(self) -> BNMScraper:
        if not self._bnm:
            self._bnm = BNMScraper()
        return self._bnm

    @property
    def kwsp(self) -> KWSPScraper:
        if not self._kwsp:
            self._kwsp = KWSPScraper()
        return self._kwsp

    def _market_scraper(self) -> MarketScraper:
        if not self._market:
            usd_myr = self.bnm.fetch_exchange_rate("USD")
            self._market = MarketScraper(usd_myr_rate=usd_myr)
        return self._market

    # ─── Tool Executor ────────────────────────────────────────────────

    def _execute_tool(self, tool_name: str, tool_input: dict) -> str:
        """Dispatch tool calls to analysis functions and return JSON string result."""
        try:
            if tool_name == "get_current_portfolio":
                return self._tool_get_portfolio()
            elif tool_name == "run_monte_carlo":
                return self._tool_monte_carlo(**tool_input)
            elif tool_name == "get_kwsp_dividend_history":
                return self._tool_kwsp_history()
            elif tool_name == "get_bnm_opr_history":
                return self._tool_bnm_opr()
            elif tool_name == "get_market_prices":
                return self._tool_market_prices(tool_input.get("items", []))
            elif tool_name == "backtest_strategies":
                return self._tool_backtest(**tool_input)
            elif tool_name == "calculate_ptptn_payoff":
                return self._tool_ptptn(**tool_input)
            elif tool_name == "analyse_investment":
                return self._tool_analyse_investment(**tool_input)
            elif tool_name == "get_pnl_statement":
                return self._tool_get_pnl()
            elif tool_name == "get_sensitivity_analysis":
                return self._tool_sensitivity(**tool_input)
            else:
                return json.dumps({"error": f"Unknown tool: {tool_name}"})
        except Exception as e:
            return json.dumps({"error": str(e), "tool": tool_name})

    def _tool_get_portfolio(self) -> str:
        snapshot_id = repo.get_latest_snapshot_id()
        if not snapshot_id:
            return json.dumps({"error": "No balance sheet data found. Please add your assets first."})

        snapshot = repo.get_snapshot(snapshot_id)
        assets = repo.get_snapshot_assets(snapshot_id)

        health = calculate_health_score(
            assets=assets,
            total_assets=snapshot["total_assets"],
            total_liabilities=snapshot["total_liabilities"],
            monthly_income=snapshot.get("monthly_income", 0),
            monthly_expense=snapshot.get("monthly_expense", 0),
            risk_profile=snapshot.get("risk_profile", "moderate"),
        )

        pnl_id = repo.get_latest_pnl_id()
        if pnl_id:
            pnl = repo.get_pnl_items(pnl_id)
            monthly_income = pnl["total_monthly_income"]
            monthly_expense = pnl["total_monthly_expense"]
        else:
            monthly_income = snapshot.get("monthly_income", 0)
            monthly_expense = snapshot.get("monthly_expense", 0)

        return json.dumps({
            "label": snapshot["label"],
            "date": snapshot["created_at"][:10],
            "net_worth": snapshot["net_worth"],
            "total_assets": snapshot["total_assets"],
            "total_liabilities": snapshot["total_liabilities"],
            "monthly_income": monthly_income,
            "monthly_expense": monthly_expense,
            "monthly_savings": max(0, monthly_income - monthly_expense),
            "risk_profile": snapshot.get("risk_profile", "moderate"),
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
        })

    def _tool_monte_carlo(self, years: int = 20,
                           monthly_contribution: Optional[float] = None,
                           inflation_adjust: bool = True) -> str:
        snapshot_id = repo.get_latest_snapshot_id()
        if not snapshot_id:
            return json.dumps({"error": "No portfolio data."})

        snapshot = repo.get_snapshot(snapshot_id)
        assets = [a for a in repo.get_snapshot_assets(snapshot_id) if not a["is_liability"]]

        if monthly_contribution is None:
            monthly_contribution = max(
                0,
                snapshot.get("monthly_income", 0) - snapshot.get("monthly_expense", 0)
            )

        monthly_expense = snapshot.get("monthly_expense", 0)
        fire_number = monthly_expense * 12 * config.FIRE_MULTIPLE if monthly_expense > 0 else 0

        result = self.mc_engine.run(
            assets=assets,
            years=years,
            monthly_contribution=monthly_contribution,
            fire_number=fire_number,
            inflation_adjust=inflation_adjust,
        )

        return json.dumps({
            "years": years,
            "monthly_contribution": monthly_contribution,
            "inflation_adjusted": inflation_adjust,
            "initial_net_worth": snapshot["net_worth"],
            "median_final": round(result.final_p50, 2),
            "optimistic_95th": round(result.final_p95, 2),
            "pessimistic_5th": round(result.final_p5, 2),
            "probability_of_doubling": f"{result.prob_double*100:.1f}%",
            "probability_of_fire": f"{result.prob_fire*100:.1f}%",
            "fire_number": round(fire_number, 2),
            "milestones": result.milestones,
        })

    def _tool_kwsp_history(self) -> str:
        series = self.kwsp.fetch_dividend_history()
        avg = self.kwsp.get_average_return(10)
        return json.dumps({
            "kwsp_dividend_history": series[-15:],
            "10yr_average": round(avg, 2),
            "current_dividend": self.kwsp.get_current_dividend(),
        })

    def _tool_bnm_opr(self) -> str:
        series = self.bnm.fetch_opr_history()
        current = self.bnm.get_current_opr()
        fd_12m = self.bnm.get_fd_rate_estimate(12)
        return json.dumps({
            "opr_history": series[-20:],
            "current_opr": current,
            "estimated_12m_fd_rate": fd_12m,
            "base_lending_rate": self.bnm.fetch_base_lending_rate(),
        })

    def _tool_market_prices(self, items: list) -> str:
        market = self._market_scraper()
        results = {}
        for item in items:
            t = item.get("type", "stock") if isinstance(item, dict) else getattr(item, "type", "stock")
            symbol = item.get("symbol", "") if isinstance(item, dict) else getattr(item, "symbol", "")
            if t == "gold":
                results["gold_myr_per_gram"] = market.get_gold_price_myr_per_gram()
            elif t == "crypto":
                results[symbol] = market.get_crypto_price_myr(symbol)
            elif t in ("stock", "index"):
                results[symbol] = market.get_stock_price(symbol)
        return json.dumps(results)

    def _tool_backtest(self, strategies: list, start_year: int,
                        monthly_contribution: float = 0) -> str:
        snapshot_id = repo.get_latest_snapshot_id()
        initial = 10_000
        if snapshot_id:
            snapshot = repo.get_snapshot(snapshot_id)
            initial = snapshot.get("net_worth", 10_000)

        results = [
            self.backtester.run(
                allocation=s["allocation"],
                initial_capital=max(initial, 1000),
                start_year=start_year,
                monthly_contribution=monthly_contribution,
                strategy_name=s["name"],
            )
            for s in strategies
        ]

        return json.dumps([{
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
        } for r in results])

    def _tool_ptptn(self, outstanding_balance: float,
                    monthly_payment: float = 150.0,
                    annual_rate: float = 1.0) -> str:
        result = self.backtester.calculate_ptptn_payoff(
            outstanding=outstanding_balance,
            monthly_payment=monthly_payment,
            annual_rate=annual_rate,
        )
        return json.dumps(result)

    def _tool_analyse_investment(self, investment_type: str,
                                  symbol_or_name: str,
                                  amount_myr: Optional[float] = None) -> str:
        market = self._market_scraper()
        result = {"investment": symbol_or_name, "type": investment_type}

        if investment_type in ("stock", "etf", "index", "reit"):
            hist = market.get_stock_history(symbol_or_name, years=5)
            if not hist.empty:
                start_price = hist["Close"].iloc[0]
                end_price = hist["Close"].iloc[-1]
                returns = hist["Close"].pct_change().dropna()
                result.update({
                    "price_5yr_ago": round(float(start_price), 4),
                    "current_price": round(float(end_price), 4),
                    "5yr_return_pct": round((end_price/start_price - 1)*100, 2),
                    "5yr_cagr_pct": round(((end_price/start_price)**(1/5)-1)*100, 2),
                    "annual_volatility_pct": round(float(returns.std() * (252**0.5) * 100), 2),
                    "data_available": True,
                })
            else:
                result["data_available"] = False

        elif investment_type == "crypto":
            hist = market.get_crypto_history(symbol_or_name, years=3)
            if not hist.empty:
                start_price = hist["price"].iloc[0]
                end_price = hist["price"].iloc[-1]
                result.update({
                    "price_3yr_ago_myr": round(float(start_price), 2),
                    "current_price_myr": round(float(end_price), 2),
                    "3yr_return_pct": round((end_price/start_price - 1)*100, 2),
                    "note": "Crypto is highly volatile. Only invest what you can afford to lose entirely.",
                    "data_available": True,
                })
            else:
                result["data_available"] = False

        elif investment_type == "gold":
            price = market.get_gold_price_myr_per_gram()
            result.update({
                "current_price_myr_per_gram": price,
                "note": "Gold is a traditional hedge against inflation and currency weakness.",
                "data_available": True,
            })

        snapshot_id = repo.get_latest_snapshot_id()
        if snapshot_id:
            snapshot = repo.get_snapshot(snapshot_id)
            result["risk_profile"] = snapshot.get("risk_profile", "moderate")
            if amount_myr:
                result["pct_of_portfolio"] = round(
                    amount_myr / max(snapshot["total_assets"], 1) * 100, 1
                )

        return json.dumps(result)

    def _tool_get_pnl(self) -> str:
        pnl_id = repo.get_latest_pnl_id()
        if not pnl_id:
            return json.dumps({"error": "No P&L statement found. Please fill in the P&L tab first."})
        return json.dumps(repo.get_pnl_items(pnl_id))

    def _tool_sensitivity(self, years: int = 20) -> str:
        snapshot_id = repo.get_latest_snapshot_id()
        if not snapshot_id:
            return json.dumps({"error": "No portfolio data."})
        assets = [a for a in repo.get_snapshot_assets(snapshot_id) if not a["is_liability"]]
        df = self.mc_engine.sensitivity_analysis(assets, years=years)
        return json.dumps(df.to_dict(orient="records"))

    # ─── Main Chat Interface ──────────────────────────────────────────

    @staticmethod
    def _build_contents(messages: list[dict]) -> list[types.Content]:
        contents = []
        for m in messages:
            role = "model" if m["role"] == "assistant" else "user"
            contents.append(types.Content(
                role=role,
                parts=[types.Part.from_text(text=m["content"])],
            ))
        return contents

    def stream_chat(
        self,
        messages: list[dict],
        snapshot_id: Optional[int] = None,
    ) -> Generator[str, None, None]:
        """
        Full streaming agentic loop with Gemini.
        Yields text chunks as they arrive. Handles function calls internally.
        """
        contents = self._build_contents(messages)

        while True:
            stream = self.client.models.generate_content_stream(
                model=config.GEMINI_MODEL,
                contents=contents,
                config=self._gen_config,
            )

            # Stream text and collect all model response parts
            model_parts = []
            yielded_text = ""
            for chunk in stream:
                try:
                    if chunk.text:
                        yielded_text += chunk.text
                        yield chunk.text
                except Exception:
                    pass
                try:
                    for cand in (chunk.candidates or []):
                        for part in (cand.content.parts or []):
                            model_parts.append(part)
                except Exception:
                    pass

            # Deduplicate and find function calls
            fn_calls = []
            seen = set()
            for part in model_parts:
                try:
                    if part.function_call and part.function_call.name:
                        name = part.function_call.name
                        if name not in seen:
                            fn_calls.append(part.function_call)
                            seen.add(name)
                except AttributeError:
                    pass

            if not fn_calls:
                break

            # Add model's response (text + function_calls) to history
            fc_parts = [types.Part.from_function_call(name=fc.name, args=dict(fc.args)) for fc in fn_calls]
            if yielded_text:
                contents.append(types.Content(
                    role="model",
                    parts=[types.Part.from_text(text=yielded_text)] + fc_parts,
                ))
            else:
                contents.append(types.Content(role="model", parts=fc_parts))

            # Execute tools and collect function responses
            fn_response_parts = []
            for fc in fn_calls:
                yield f"\n\n*[Fetching: {fc.name.replace('_', ' ').title()}...]*\n\n"
                args = _to_python(fc.args)
                result_str = self._execute_tool(fc.name, args)
                fn_response_parts.append(
                    types.Part.from_function_response(
                        name=fc.name,
                        response={"result": result_str},
                    )
                )

            # Add function responses as user turn
            contents.append(types.Content(role="user", parts=fn_response_parts))

    def chat_sync(self, messages: list[dict]) -> str:
        """Non-streaming version — returns full response string."""
        full = ""
        for chunk in self.stream_chat(messages):
            full += chunk
        return full
