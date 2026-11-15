# DEPRECATED — use ai/chat.py Consultant instead
"""
Xiaomi MiMo Financial Consultant
---------------------------------
OpenAI-compatible streaming consultant that targets Xiaomi's MiMo API.
Supports full tool calling and  reasoning block rendering.

Priority in ai_chat.py: MiMo → Gemini → Ollama
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Generator, Optional

from openai import OpenAI

from database import repository as repo
from analysis.monte_carlo import MonteCarloEngine
from analysis.health_score import calculate_health_score
from scrapers.bnm_scraper import BNMScraper
from scrapers.kwsp_scraper import KWSPScraper
from scrapers.market_scraper import MarketScraper
import config

from ai.registry import TOOLS, SYSTEM_PROMPT

# ── Separator — reasoning vs response (same as ollama_consultant) ──────────────
_REASON_SEP = "\n\n---\n\n"

# Use the canonical prompt directly (no /no_think prefix for MiMo)
_SYSTEM_PROMPT = SYSTEM_PROMPT


class MiMoConsultant:
    """
    Xiaomi MiMo financial consultant via OpenAI-compatible streaming API.
    Handles tool calling and  reasoning block extraction.
    """

    def __init__(
        self,
        api_key: str = "",
        base_url: str = "",
        model: str = "",
    ):
        self.api_key  = api_key  or config.XIAOMI_API_KEY
        self.base_url = base_url or config.XIAOMI_BASE_URL
        self.model    = model    or config.XIAOMI_MODEL

        self.client = OpenAI(
            api_key=self.api_key,
            base_url=self.base_url,
        )

        self._mc: Optional[MonteCarloEngine] = None
        self._bnm: Optional[BNMScraper] = None
        self._kwsp: Optional[KWSPScraper] = None
        self._market: Optional[MarketScraper] = None

    # ── Lazy engines ──────────────────────────────────────────────────────────

    def _mc_engine(self) -> MonteCarloEngine:
        if not self._mc:
            self._mc = MonteCarloEngine()
        return self._mc

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

    # ── Streaming chat loop ───────────────────────────────────────────────────

    def stream_chat(
        self,
        messages: list[dict],
        snapshot_id: Optional[int] = None,
    ) -> Generator[str, None, None]:
        """
        Stream response tokens. Handles:
        -  blocks → rendered as blockquote reasoning
        - Tool calls → executed and fed back into the conversation loop
        - _REASON_SEP emitted between reasoning and response (ai_chat.py splits on this)
        """
        history: list[dict] = [{"role": "system", "content": _SYSTEM_PROMPT}]
        history += [{"role": m["role"], "content": m["content"]} for m in messages]

        while True:
            accumulated = ""        # actual response text (no think), kept for tool history
            tool_calls_map: dict[int, dict] = {}   # index → partial tool call
            buf = ""
            in_think = False
            think_started = False

            try:
                stream = self.client.chat.completions.create(
                    model=self.model,
                    messages=history,
                    tools=TOOLS,
                    tool_choice="auto",
                    stream=True,
                    temperature=0.3,
                )

                for chunk in stream:
                    if not chunk.choices:
                        continue
                    delta = chunk.choices[0].delta
                    if delta is None:
                        continue

                    # ── Accumulate tool call deltas ────────────────────────────
                    if delta.tool_calls:
                        for tc_delta in delta.tool_calls:
                            idx = tc_delta.index
                            if idx not in tool_calls_map:
                                tool_calls_map[idx] = {
                                    "id": tc_delta.id or "",
                                    "type": "function",
                                    "function": {"name": "", "arguments": ""},
                                }
                            if tc_delta.function:
                                if tc_delta.function.name:
                                    tool_calls_map[idx]["function"]["name"] += tc_delta.function.name
                                if tc_delta.function.arguments:
                                    tool_calls_map[idx]["function"]["arguments"] += tc_delta.function.arguments
                        continue

                    content: str = delta.content or ""
                    if not content:
                        continue

                    buf += content

                    # ──  state machine ──────────────────────────────────
                    while buf:
                        if in_think:
                            end = buf.find("</think>")
                            if end == -1:
                                out = buf.replace("\n", "\n> ")
                                buf = ""
                                yield out
                            else:
                                tail = buf[:end]
                                if tail:
                                    yield tail.replace("\n", "\n> ")
                                in_think = False
                                buf = buf[end + len("</think>"):]
                                yield _REASON_SEP
                        else:
                            start = buf.find("")
                            if start == -1:
                                accumulated += buf
                                yield buf
                                buf = ""
                            else:
                                if start > 0:
                                    pre = buf[:start]
                                    accumulated += pre
                                    yield pre
                                in_think = True
                                buf = buf[start + len(""):]
                                if not think_started:
                                    think_started = True
                                    yield "> **Reasoning**\n> "

            except Exception as e:
                yield f"\n\n**MiMo error:** {e}\n"
                return

            # ── No tool calls → done ───────────────────────────────────────────
            if not tool_calls_map:
                break

            tool_calls = list(tool_calls_map.values())

            # Add assistant message with tool calls to history
            history.append({
                "role": "assistant",
                "content": accumulated or None,
                "tool_calls": tool_calls,
            })

            # Execute each tool and append result
            for tc in tool_calls:
                fn   = tc["function"]
                name = fn["name"]
                try:
                    args = json.loads(fn["arguments"] or "{}")
                except json.JSONDecodeError:
                    args = {}

                yield f"\n\n*\\[Fetching: {name.replace('_', ' ').title()}...]*\n\n"
                result = self._execute_tool(name, args)

                history.append({
                    "role": "tool",
                    "tool_call_id": tc["id"],
                    "content": result,
                })

    # ── Tool executor ─────────────────────────────────────────────────────────

    def _execute_tool(self, name: str, args: dict) -> str:
        try:
            if name == "get_dashboard_summary":
                return self._tool_dashboard()
            elif name == "get_current_portfolio":
                return self._tool_portfolio()
            elif name == "get_balance_sheet_history":
                return self._tool_bs_history()
            elif name == "get_pnl_statement":
                return self._tool_pnl()
            elif name == "get_pnl_history":
                return self._tool_pnl_history()
            elif name == "get_expense_summary":
                return self._tool_expense_summary(args.get("period", ""))
            elif name == "record_expense":
                return self._tool_record_expense(
                    description=str(args.get("description", "")),
                    amount=float(args.get("amount", 0)),
                    category=str(args.get("category", "Other")),
                    period=str(args.get("period", "")),
                )
            elif name == "record_income":
                return self._tool_record_income(
                    description=str(args.get("description", "")),
                    amount=float(args.get("amount", 0)),
                    category=str(args.get("category", "Other")),
                    period=str(args.get("period", "")),
                )
            elif name == "run_monte_carlo":
                return self._tool_monte_carlo(
                    years=int(args.get("years", 20)),
                    monthly_contribution=float(args.get("monthly_contribution", 0)),
                    inflation_adjust=bool(args.get("inflation_adjust", True)),
                )
            elif name == "get_bnm_opr_history":
                return self._tool_bnm_opr()
            elif name == "get_kwsp_dividend_history":
                return self._tool_kwsp()
            else:
                return json.dumps({"error": f"Unknown tool: {name}"})
        except Exception as e:
            return json.dumps({"error": str(e), "tool": name})

    # ── Tool implementations ──────────────────────────────────────────────────

    def _tool_dashboard(self) -> str:
        result: dict = {}
        snap_id = repo.get_latest_snapshot_id()
        if snap_id:
            snap = repo.get_snapshot(snap_id)
            result.update({
                "net_worth": snap["net_worth"],
                "total_assets": snap["total_assets"],
                "total_liabilities": snap["total_liabilities"],
                "balance_sheet_period": snap.get("period", ""),
            })
        pnl_id = repo.get_latest_pnl_id()
        if pnl_id:
            pnl = repo.get_pnl_items(pnl_id)
            result.update({
                "monthly_income":   pnl["total_monthly_income"],
                "monthly_expense":  pnl["total_monthly_expense"],
                "monthly_savings":  pnl["net_monthly_savings"],
                "savings_rate_pct": pnl["savings_rate_pct"],
            })
        result["saved_periods"] = repo.list_all_periods()
        return json.dumps(result)

    def _tool_portfolio(self) -> str:
        snap_id = repo.get_latest_snapshot_id()
        if not snap_id:
            return json.dumps({"error": "No balance sheet data found."})
        snap   = repo.get_snapshot(snap_id)
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
            monthly_income  = pnl["total_monthly_income"]
            monthly_expense = pnl["total_monthly_expense"]
        else:
            monthly_income  = snap.get("monthly_income", 0)
            monthly_expense = snap.get("monthly_expense", 0)
        return json.dumps({
            "period":            snap.get("period", ""),
            "net_worth":         snap["net_worth"],
            "total_assets":      snap["total_assets"],
            "total_liabilities": snap["total_liabilities"],
            "monthly_income":    monthly_income,
            "monthly_expense":   monthly_expense,
            "health_score":      health.total_score,
            "health_grade":      health.grade,
            "top_issues":        health.top_issues,
            "recommendations":   health.recommendations,
            "assets": [
                {
                    "name":         a["name"],
                    "category":     a["category"],
                    "balance":      a["balance"],
                    "is_liability": bool(a["is_liability"]),
                }
                for a in assets
            ],
        })

    def _tool_bs_history(self) -> str:
        rows = []
        for p in repo.list_snapshot_periods():
            snap = repo.get_snapshot_by_period(p)
            if snap:
                rows.append({
                    "period":            p,
                    "net_worth":         snap["net_worth"],
                    "total_assets":      snap["total_assets"],
                    "total_liabilities": snap["total_liabilities"],
                })
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
                rows.append({
                    "period":        p,
                    "total_income":  data["total_income"],
                    "total_expense": data["total_expense"],
                    "net_savings":   data["net_savings"],
                    "savings_rate":  data["savings_rate"],
                })
        return json.dumps(rows)

    def _tool_expense_summary(self, period: str = "") -> str:
        if not period:
            period = datetime.now().strftime("%Y-%m")
        data = repo.get_pnl_by_period(period)
        if not data:
            return json.dumps({"period": period, "message": "No records for this period."})
        by_cat: dict[str, float] = {}
        items = []
        for item in data.get("expense_items", []):
            cat = item.get("category", "Other")
            amt = float(item.get("amount", 0))
            by_cat[cat] = round(by_cat.get(cat, 0) + amt, 2)
            items.append({"description": item.get("description", ""), "category": cat, "amount": amt})
        return json.dumps({
            "period":               period,
            "total_income":         data.get("total_income", 0),
            "total_expenses":       data.get("total_expense", 0),
            "net_savings":          data.get("net_savings", 0),
            "savings_rate_pct":     round(data.get("savings_rate", 0), 1),
            "expense_by_category":  by_cat,
            "expense_items":        items,
        })

    def _tool_record_expense(
        self, description: str, amount: float, category: str = "Other", period: str = ""
    ) -> str:
        if not period:
            period = datetime.now().strftime("%Y-%m")
        existing     = repo.get_pnl_by_period(period)
        income_items  = _clean_items(existing.get("income_items", []) if existing else [])
        expense_items = _clean_items(existing.get("expense_items", []) if existing else [])
        expense_items.append({"description": description, "category": category, "amount": float(amount)})
        repo.save_pnl(label="P&L", income_items=income_items, expense_items=expense_items, period=period)
        return json.dumps({
            "status":      "recorded",
            "description": description,
            "amount":      amount,
            "category":    category,
            "period":      period,
            "total_expenses_this_month": round(sum(i["amount"] for i in expense_items), 2),
        })

    def _tool_record_income(
        self, description: str, amount: float, category: str = "Other", period: str = ""
    ) -> str:
        if not period:
            period = datetime.now().strftime("%Y-%m")
        existing     = repo.get_pnl_by_period(period)
        income_items  = _clean_items(existing.get("income_items", []) if existing else [])
        expense_items = _clean_items(existing.get("expense_items", []) if existing else [])
        income_items.append({"description": description, "category": category, "amount": float(amount)})
        repo.save_pnl(label="P&L", income_items=income_items, expense_items=expense_items, period=period)
        return json.dumps({
            "status":      "recorded",
            "description": description,
            "amount":      amount,
            "category":    category,
            "period":      period,
            "total_income_this_month": round(sum(i["amount"] for i in income_items), 2),
        })

    def _tool_monte_carlo(
        self, years: int, monthly_contribution: float = 0, inflation_adjust: bool = True
    ) -> str:
        snap_id = repo.get_latest_snapshot_id()
        if not snap_id:
            return json.dumps({"error": "No portfolio data."})
        snap   = repo.get_snapshot(snap_id)
        assets = [a for a in repo.get_snapshot_assets(snap_id) if not a["is_liability"]]
        if not monthly_contribution:
            monthly_contribution = max(0, snap.get("monthly_income", 0) - snap.get("monthly_expense", 0))
        fire_number = snap.get("monthly_expense", 0) * 12 * config.FIRE_MULTIPLE
        r = self._mc_engine().run(
            assets=assets,
            years=years,
            monthly_contribution=monthly_contribution,
            fire_number=fire_number,
            inflation_adjust=inflation_adjust,
        )
        return json.dumps({
            "years":                  years,
            "monthly_contribution":   monthly_contribution,
            "initial_net_worth":      snap["net_worth"],
            "median_final_rm":        round(r.final_p50, 2),
            "optimistic_95th_rm":     round(r.final_p95, 2),
            "pessimistic_5th_rm":     round(r.final_p5, 2),
            "probability_of_fire":    f"{r.prob_fire * 100:.1f}%",
            "milestones":             r.milestones,
        })

    def _tool_bnm_opr(self) -> str:
        bnm = self._bnm_scraper()
        return json.dumps({
            "opr_history":           bnm.fetch_opr_history()[-20:],
            "current_opr":           bnm.get_current_opr(),
            "estimated_12m_fd_rate": bnm.get_fd_rate_estimate(12),
        })

    def _tool_kwsp(self) -> str:
        kwsp = self._kwsp_scraper()
        return json.dumps({
            "history":         kwsp.fetch_dividend_history()[-15:],
            "10yr_average":    round(kwsp.get_average_return(10), 2),
            "current_dividend": kwsp.get_current_dividend(),
        })


# ── Helper ─────────────────────────────────────────────────────────────────────

def _clean_items(items: list[dict]) -> list[dict]:
    return [
        {
            "description": i.get("description", ""),
            "category":    i.get("category", "Other"),
            "amount":      float(i.get("amount", 0)),
        }
        for i in items
    ]
