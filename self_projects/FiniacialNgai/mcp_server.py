"""FinancialNgai MCP Server — exposes financial tools via MCP protocol (JSON-RPC 2.0 / stdio).

Works with Python 3.9+. No external MCP package required.

Usage (stdio transport — for Claude Desktop or any MCP client):
    python mcp_server.py

Configure in Claude Desktop (~/.config/claude/claude_desktop_config.json):
    {
        "mcpServers": {
            "financialngai": {
                "command": "/path/to/.venv/bin/python3",
                "args": ["/path/to/mcp_server.py"]
            }
        }
    }
"""
from __future__ import annotations
import json
import sys
from pathlib import Path
from datetime import datetime
from typing import Any, Optional

sys.path.insert(0, str(Path(__file__).parent))

from database import repository as repo
from analysis.monte_carlo import MonteCarloEngine
from analysis.health_score import calculate_health_score
from scrapers.bnm_scraper import BNMScraper
from scrapers.kwsp_scraper import KWSPScraper
import config

# ── Lazy engines ──────────────────────────────────────────────────────────────

_mc: Optional[MonteCarloEngine] = None
_bnm: Optional[BNMScraper] = None
_kwsp: Optional[KWSPScraper] = None


def _mc_engine() -> MonteCarloEngine:
    global _mc
    if not _mc:
        _mc = MonteCarloEngine()
    return _mc


def _bnm_scraper() -> BNMScraper:
    global _bnm
    if not _bnm:
        _bnm = BNMScraper()
    return _bnm


def _kwsp_scraper() -> KWSPScraper:
    global _kwsp
    if not _kwsp:
        _kwsp = KWSPScraper()
    return _kwsp


def _clean_items(items: list[dict]) -> list[dict]:
    return [
        {
            "description": i.get("description", ""),
            "category": i.get("category", "Other"),
            "amount": float(i.get("amount", 0)),
        }
        for i in items
    ]


# ── Tool definitions (MCP schema format) ─────────────────────────────────────

TOOL_DEFS: list[dict] = [
    {
        "name": "get_dashboard_summary",
        "description": "Quick financial overview: net worth, monthly cash flow, savings rate, all saved periods.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_current_portfolio",
        "description": "Full balance sheet: all assets, liabilities, net worth, health score, monthly income/expenses.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_balance_sheet_history",
        "description": "Net worth, total assets, and liabilities for every saved month.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_pnl_statement",
        "description": "Latest P&L statement: all income and expense items, net savings, savings rate.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_pnl_history",
        "description": "Income, expense, and savings for every saved P&L month.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_expense_summary",
        "description": "Expense and income breakdown for a month, grouped by category.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "period": {"type": "string", "description": "YYYY-MM (defaults to current month)"},
            },
        },
    },
    {
        "name": "record_expense",
        "description": "Record a daily expense into a month's P&L statement.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "description": {"type": "string", "description": "What was purchased"},
                "amount": {"type": "number", "description": "Amount in RM"},
                "category": {
                    "type": "string",
                    "description": (
                        "Food & Groceries | Transport | Entertainment | Utilities & Phone | "
                        "Education | Insurance / Takaful | Loan Repayment | Housing / Rent | Other"
                    ),
                },
                "period": {"type": "string", "description": "YYYY-MM (defaults to current month)"},
            },
            "required": ["description", "amount"],
        },
    },
    {
        "name": "record_income",
        "description": "Record an income entry into a month's P&L statement.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "description": {"type": "string", "description": "Income source"},
                "amount": {"type": "number", "description": "Amount in RM"},
                "category": {
                    "type": "string",
                    "description": (
                        "Salary / Employment | Part-time / Freelance | "
                        "Investment Returns | Allowance / Gift | Other"
                    ),
                },
                "period": {"type": "string", "description": "YYYY-MM (defaults to current month)"},
            },
            "required": ["description", "amount"],
        },
    },
    {
        "name": "run_monte_carlo",
        "description": "Project future net worth via Monte Carlo simulation (10,000 scenarios).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "years": {"type": "integer", "description": "Years to project (1–40)"},
                "monthly_contribution": {"type": "number", "description": "Monthly savings in RM (0 = auto)"},
                "inflation_adjust": {"type": "boolean", "description": "Adjust for inflation"},
            },
            "required": ["years"],
        },
    },
    {
        "name": "get_bnm_opr_history",
        "description": "Bank Negara Malaysia OPR history, current rate, and FD rate estimate.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_kwsp_dividend_history",
        "description": "KWSP/EPF dividend history and 10-year average return.",
        "inputSchema": {"type": "object", "properties": {}},
    },
]


# ── Tool executor ─────────────────────────────────────────────────────────────

def _execute_tool(name: str, args: dict) -> str:
    try:
        if name == "get_dashboard_summary":
            return _tool_dashboard()
        elif name == "get_current_portfolio":
            return _tool_portfolio()
        elif name == "get_balance_sheet_history":
            return _tool_bs_history()
        elif name == "get_pnl_statement":
            return _tool_pnl()
        elif name == "get_pnl_history":
            return _tool_pnl_history()
        elif name == "get_expense_summary":
            return _tool_expense_summary(args.get("period", ""))
        elif name == "record_expense":
            return _tool_record_expense(
                description=str(args.get("description", "")),
                amount=float(args.get("amount", 0)),
                category=str(args.get("category", "Other")),
                period=str(args.get("period", "")),
            )
        elif name == "record_income":
            return _tool_record_income(
                description=str(args.get("description", "")),
                amount=float(args.get("amount", 0)),
                category=str(args.get("category", "Other")),
                period=str(args.get("period", "")),
            )
        elif name == "run_monte_carlo":
            return _tool_monte_carlo(
                years=int(args.get("years", 20)),
                monthly_contribution=float(args.get("monthly_contribution", 0)),
                inflation_adjust=bool(args.get("inflation_adjust", True)),
            )
        elif name == "get_bnm_opr_history":
            return _tool_bnm_opr()
        elif name == "get_kwsp_dividend_history":
            return _tool_kwsp()
        else:
            return json.dumps({"error": f"Unknown tool: {name}"})
    except Exception as e:
        return json.dumps({"error": str(e), "tool": name})


def _tool_dashboard() -> str:
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
            "monthly_income": pnl["total_monthly_income"],
            "monthly_expense": pnl["total_monthly_expense"],
            "monthly_savings": pnl["net_monthly_savings"],
            "savings_rate_pct": pnl["savings_rate_pct"],
        })
    result["saved_periods"] = repo.list_all_periods()
    return json.dumps(result)


def _tool_portfolio() -> str:
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
    return json.dumps({
        "period": snap.get("period", ""),
        "net_worth": snap["net_worth"],
        "total_assets": snap["total_assets"],
        "total_liabilities": snap["total_liabilities"],
        "monthly_income": monthly_income,
        "monthly_expense": monthly_expense,
        "health_score": health.total_score,
        "health_grade": health.grade,
        "recommendations": health.recommendations,
        "assets": [
            {
                "name": a["name"],
                "category": a["category"],
                "balance": a["balance"],
                "is_liability": bool(a["is_liability"]),
            }
            for a in assets
        ],
    })


def _tool_bs_history() -> str:
    rows = []
    for p in repo.list_snapshot_periods():
        snap = repo.get_snapshot_by_period(p)
        if snap:
            rows.append({
                "period": p,
                "net_worth": snap["net_worth"],
                "total_assets": snap["total_assets"],
                "total_liabilities": snap["total_liabilities"],
            })
    return json.dumps(rows)


def _tool_pnl() -> str:
    pnl_id = repo.get_latest_pnl_id()
    if not pnl_id:
        return json.dumps({"error": "No P&L found."})
    return json.dumps(repo.get_pnl_items(pnl_id))


def _tool_pnl_history() -> str:
    rows = []
    for p in repo.list_pnl_periods():
        data = repo.get_pnl_by_period(p)
        if data:
            rows.append({
                "period": p,
                "total_income": data["total_income"],
                "total_expense": data["total_expense"],
                "net_savings": data["net_savings"],
                "savings_rate": data["savings_rate"],
            })
    return json.dumps(rows)


def _tool_expense_summary(period: str = "") -> str:
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
        "period": period,
        "total_income": data.get("total_income", 0),
        "total_expenses": data.get("total_expense", 0),
        "net_savings": data.get("net_savings", 0),
        "savings_rate_pct": round(data.get("savings_rate", 0), 1),
        "expense_by_category": by_cat,
        "expense_items": items,
    })


def _tool_record_expense(description: str, amount: float, category: str = "Other", period: str = "") -> str:
    if not period:
        period = datetime.now().strftime("%Y-%m")
    existing = repo.get_pnl_by_period(period)
    income_items = _clean_items(existing.get("income_items", []) if existing else [])
    expense_items = _clean_items(existing.get("expense_items", []) if existing else [])
    expense_items.append({"description": description, "category": category, "amount": float(amount)})
    repo.save_pnl(label="P&L", income_items=income_items, expense_items=expense_items, period=period)
    return json.dumps({
        "status": "recorded",
        "description": description,
        "amount": amount,
        "category": category,
        "period": period,
        "total_expenses_this_month": round(sum(i["amount"] for i in expense_items), 2),
    })


def _tool_record_income(description: str, amount: float, category: str = "Other", period: str = "") -> str:
    if not period:
        period = datetime.now().strftime("%Y-%m")
    existing = repo.get_pnl_by_period(period)
    income_items = _clean_items(existing.get("income_items", []) if existing else [])
    expense_items = _clean_items(existing.get("expense_items", []) if existing else [])
    income_items.append({"description": description, "category": category, "amount": float(amount)})
    repo.save_pnl(label="P&L", income_items=income_items, expense_items=expense_items, period=period)
    return json.dumps({
        "status": "recorded",
        "description": description,
        "amount": amount,
        "category": category,
        "period": period,
        "total_income_this_month": round(sum(i["amount"] for i in income_items), 2),
    })


def _tool_monte_carlo(years: int, monthly_contribution: float = 0, inflation_adjust: bool = True) -> str:
    snap_id = repo.get_latest_snapshot_id()
    if not snap_id:
        return json.dumps({"error": "No portfolio data."})
    snap = repo.get_snapshot(snap_id)
    assets = [a for a in repo.get_snapshot_assets(snap_id) if not a["is_liability"]]
    if not monthly_contribution:
        monthly_contribution = max(0, snap.get("monthly_income", 0) - snap.get("monthly_expense", 0))
    fire_number = snap.get("monthly_expense", 0) * 12 * config.FIRE_MULTIPLE
    r = _mc_engine().run(
        assets=assets, years=years,
        monthly_contribution=monthly_contribution,
        fire_number=fire_number,
        inflation_adjust=inflation_adjust,
    )
    return json.dumps({
        "years": years,
        "monthly_contribution": monthly_contribution,
        "initial_net_worth": snap["net_worth"],
        "median_final_rm": round(r.final_p50, 2),
        "optimistic_95th_rm": round(r.final_p95, 2),
        "pessimistic_5th_rm": round(r.final_p5, 2),
        "probability_of_fire": f"{r.prob_fire * 100:.1f}%",
        "milestones": r.milestones,
    })


def _tool_bnm_opr() -> str:
    bnm = _bnm_scraper()
    return json.dumps({
        "opr_history": bnm.fetch_opr_history()[-20:],
        "current_opr": bnm.get_current_opr(),
        "estimated_12m_fd_rate": bnm.get_fd_rate_estimate(12),
    })


def _tool_kwsp() -> str:
    kwsp = _kwsp_scraper()
    return json.dumps({
        "history": kwsp.fetch_dividend_history()[-15:],
        "10yr_average": round(kwsp.get_average_return(10), 2),
        "current_dividend": kwsp.get_current_dividend(),
    })


# ── MCP JSON-RPC 2.0 stdio transport ─────────────────────────────────────────

def _handle(req: dict) -> Optional[dict]:
    method: str = req.get("method", "")
    params: dict = req.get("params") or {}
    req_id: Any = req.get("id")

    # Notifications have no id and require no response
    if req_id is None and method.startswith("notifications/"):
        return None

    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "FinancialNgai", "version": "1.0.0"},
            },
        }

    if method == "tools/list":
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {"tools": TOOL_DEFS},
        }

    if method == "tools/call":
        name: str = params.get("name", "")
        args: dict = params.get("arguments") or {}
        result_text = _execute_tool(name, args)
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "content": [{"type": "text", "text": result_text}],
                "isError": False,
            },
        }

    if method == "ping":
        return {"jsonrpc": "2.0", "id": req_id, "result": {}}

    return {
        "jsonrpc": "2.0",
        "id": req_id,
        "error": {"code": -32601, "message": f"Method not found: {method}"},
    }


def main() -> None:
    for raw in sys.stdin:
        raw = raw.strip()
        if not raw:
            continue
        try:
            req = json.loads(raw)
        except json.JSONDecodeError:
            continue
        resp = _handle(req)
        if resp is not None:
            sys.stdout.write(json.dumps(resp) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
