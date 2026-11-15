"""
Canonical tool registry and system prompt.

Every consultant (Ollama, MiMo, Gemini) imports TOOLS and SYSTEM_PROMPT
from this module so definitions stay in sync.

- TOOLS              — master tool list in OpenAI function-calling format
- SYSTEM_PROMPT      — the single source-of-truth system prompt
- build_gemini_tools() — converts TOOLS to Gemini FunctionDeclaration format
"""

# ── System prompt ─────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """\
You are Ngai's personal AI financial advisor — knowledgeable, warm, and practical, specialising in Malaysian personal finance.

## Tools available
You have REAL tools connected to the user's actual database. ALWAYS call the relevant tool before answering any financial question. Never guess numbers.

- get_dashboard_summary   — quick overview of net worth, cash flow, savings rate
- get_current_portfolio   — full balance sheet with all assets, health score
- get_balance_sheet_history — net worth trend across months
- get_pnl_statement       — latest income & expense statement
- get_pnl_history         — income/expense trend across months
- get_expense_summary     — breakdown of expenses for a specific month
- record_expense          — add a daily expense (description, amount, category)
- record_income           — add an income entry (description, amount, category)
- run_monte_carlo         — project net worth over N years
- get_bnm_opr_history     — BNM interest rates
- get_kwsp_dividend_history — EPF dividend history
- get_market_prices       — live stock, crypto, gold, index prices
- backtest_strategies     — compare investment strategies against historical data
- calculate_ptptn_payoff  — PTPTN loan payoff schedule and comparison
- analyse_investment      — analyse any investment (stocks, REITs, crypto, etc.)
- get_sensitivity_analysis — how different savings rates affect long-term wealth

## Recording expenses / income
When the user says things like "I spent RM15 on lunch" or "record my coffee RM6", immediately call record_expense with the right description, amount, and category. Confirm back what was recorded.

## Tone
- Warm and direct like a trusted finance-savvy friend
- Use real RM figures from the tools, never made-up numbers
- Format responses with headers and bullet points for clarity
- Responses should be in the same language the user writes in (English or Malay)

## Disclaimer
Educational financial analysis only — not regulated financial advice.
"""

# ── Tool definitions (OpenAI / Ollama format) ────────────────────────────────

TOOLS: list[dict] = [
    # ── Ollama / MiMo tools ──────────────────────────────────────────────
    {
        "type": "function",
        "function": {
            "name": "get_dashboard_summary",
            "description": "Quick financial overview: net worth, monthly cash flow, savings rate, available periods.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_current_portfolio",
            "description": "Full balance sheet: all assets, liabilities, net worth, health score, monthly income/expenses.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_balance_sheet_history",
            "description": "Net worth, total assets, and liabilities for every saved month.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_pnl_statement",
            "description": "Latest P&L: income sources, expense categories, net savings, savings rate.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_pnl_history",
            "description": "Income, expense, and savings for every saved P&L month.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_expense_summary",
            "description": "Expense breakdown by category for a specific month.",
            "parameters": {
                "type": "object",
                "properties": {
                    "period": {
                        "type": "string",
                        "description": "Month in YYYY-MM format. Leave empty for current month.",
                    }
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "record_expense",
            "description": (
                "Record a daily expense into the P&L. Call this whenever the user mentions "
                "spending money on anything — food, transport, bills, etc."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "description": {
                        "type": "string",
                        "description": "What was purchased (e.g. 'lunch', 'grab ride', 'coffee')",
                    },
                    "amount": {"type": "number", "description": "Amount in RM"},
                    "category": {
                        "type": "string",
                        "description": (
                            "Category: Food & Groceries | Transport | Entertainment | "
                            "Utilities & Phone | Education | Insurance / Takaful | "
                            "Loan Repayment | Housing / Rent | Other"
                        ),
                    },
                    "period": {
                        "type": "string",
                        "description": "YYYY-MM month (leave empty for current month)",
                    },
                },
                "required": ["description", "amount"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "record_income",
            "description": (
                "Record an income entry into the P&L. Call this when the user mentions "
                "receiving money — salary, freelance, allowance, dividends, etc."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "description": {
                        "type": "string",
                        "description": "Income source (e.g. 'salary', 'freelance project', 'allowance')",
                    },
                    "amount": {"type": "number", "description": "Amount in RM"},
                    "category": {
                        "type": "string",
                        "description": (
                            "Category: Salary / Employment | Part-time / Freelance | "
                            "Investment Returns | Allowance / Gift | Other"
                        ),
                    },
                    "period": {
                        "type": "string",
                        "description": "YYYY-MM month (leave empty for current month)",
                    },
                },
                "required": ["description", "amount"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_monte_carlo",
            "description": "Project future net worth via Monte Carlo simulation over N years.",
            "parameters": {
                "type": "object",
                "properties": {
                    "years": {"type": "integer", "description": "Number of years to project (1–40)"},
                    "monthly_contribution": {
                        "type": "number",
                        "description": "Monthly savings in RM (0 = auto from P&L)",
                    },
                    "inflation_adjust": {
                        "type": "boolean",
                        "description": "Adjust for inflation (real terms). Default: true",
                    },
                },
                "required": ["years"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_bnm_opr_history",
            "description": "Bank Negara Malaysia OPR history, current rate, and FD rate estimate.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_kwsp_dividend_history",
            "description": "KWSP/EPF dividend history and 10-year average return.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    # ── Gemini-origin tools (analysing, prices, backtesting) ─────────────
    {
        "type": "function",
        "function": {
            "name": "get_market_prices",
            "description": (
                "Fetch current market prices for stocks, crypto, gold, or indices. "
                "Supports any yfinance ticker (e.g. 'AAPL', 'MAYBANK.KL', '^KLSE'), "
                "LUNO crypto pairs (BTC, ETH, XRP, SOL), and gold in MYR/gram."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "items": {
                        "type": "array",
                        "description": "List of items to fetch prices for. Each item has 'type' (stock/crypto/gold/index) and 'symbol'.",
                        "items": {
                            "type": "object",
                            "properties": {
                                "type": {
                                    "type": "string",
                                    "description": "Type of asset: stock, crypto, gold, or index",
                                },
                                "symbol": {
                                    "type": "string",
                                    "description": "Ticker symbol or coin name (e.g. 'AAPL', 'BTC', 'MAYBANK.KL')",
                                },
                            },
                        },
                    },
                },
                "required": ["items"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "backtest_strategies",
            "description": (
                "Backtest one or more investment allocation strategies against historical data "
                "(KWSP dividends, BNM OPR, KLCI, gold prices, etc.). "
                "Returns CAGR, Sharpe ratio, max drawdown, and year-by-year performance."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "strategies": {
                        "type": "array",
                        "description": "List of strategies to compare. Each has 'name' (string) and 'allocation' (object mapping asset_key to weight, e.g. {'KWSP_EPF': 0.5, 'GOLD': 0.5}).",
                        "items": {
                            "type": "object",
                            "properties": {
                                "name": {"type": "string"},
                                "allocation": {
                                    "type": "object",
                                    "description": "Dict of asset_key to weight (must sum to ~1.0)",
                                },
                            },
                        },
                    },
                    "start_year": {
                        "type": "integer",
                        "description": "Start year for backtest (e.g. 2015)",
                    },
                    "monthly_contribution": {
                        "type": "number",
                        "description": "Monthly contribution in RM",
                    },
                },
                "required": ["strategies", "start_year"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "calculate_ptptn_payoff",
            "description": "Calculate PTPTN loan payoff schedule, total interest paid, and compare early vs standard repayment.",
            "parameters": {
                "type": "object",
                "properties": {
                    "outstanding_balance": {
                        "type": "number",
                        "description": "Current PTPTN outstanding balance in RM",
                    },
                    "monthly_payment": {
                        "type": "number",
                        "description": "Monthly repayment amount in RM (default: 150)",
                    },
                    "annual_rate": {
                        "type": "number",
                        "description": "Annual interest rate % (1.0 for ICR, 3.0 for standard)",
                    },
                },
                "required": ["outstanding_balance"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "analyse_investment",
            "description": (
                "Analyse any investment the user is considering — stocks, REITs, ETFs, bonds, "
                "crypto, real estate, unit trusts — and assess it relative to their risk profile "
                "and current portfolio. Returns historical performance, risk metrics, "
                "and portfolio fit assessment."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "investment_type": {
                        "type": "string",
                        "description": "Type of investment: stock, reit, etf, crypto, bond, unit_trust, real_estate, or other",
                    },
                    "symbol_or_name": {
                        "type": "string",
                        "description": "Ticker symbol (for stocks/ETFs) or investment name",
                    },
                    "amount_myr": {
                        "type": "number",
                        "description": "Amount user is considering investing in RM",
                    },
                },
                "required": ["investment_type", "symbol_or_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_sensitivity_analysis",
            "description": (
                "Show how different monthly savings amounts affect the user's long-term wealth. "
                "Returns a table comparing scenarios (save RM 0/200/500/1000/2000/3000 per month)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "years": {
                        "type": "integer",
                        "description": "Projection horizon in years",
                    },
                },
            },
        },
    },
]


# ── Gemini format conversion ─────────────────────────────────────────────────

def _build_schema(d: dict) -> "types.Schema":
    """Convert a JSON-schema dict to a google.genai types.Schema object."""
    from google.genai import types

    if not d:
        return types.Schema(type="OBJECT")

    type_map = {
        "object": "OBJECT", "string": "STRING", "number": "NUMBER",
        "integer": "INTEGER", "boolean": "BOOLEAN", "array": "ARRAY",
    }
    raw_type = d.get("type", "object")
    schema_type = type_map.get(raw_type.lower(), "OBJECT")

    props = None
    if d.get("properties"):
        props = {k: _build_schema(v) for k, v in d["properties"].items()}

    items = _build_schema(d["items"]) if "items" in d else None

    return types.Schema(
        type=schema_type,
        description=d.get("description"),
        properties=props,
        required=d.get("required"),
        items=items,
        enum=d.get("enum"),
    )


def build_gemini_tools() -> list:
    """Convert the master TOOLS list to Gemini Tool objects.

    Each OpenAI-format entry (``{"type": "function", "function": {…}}``) is
    converted to a ``types.FunctionDeclaration`` and wrapped in a single
    ``types.Tool``.

    Returns a one-element ``list[types.Tool]`` (Gemini's expected format).
    """
    from google.genai import types

    decls = []
    for t in TOOLS:
        fn = t["function"]
        params = fn.get("parameters", {})
        decls.append(types.FunctionDeclaration(
            name=fn["name"],
            description=fn["description"],
            parameters=_build_schema(params),
        ))
    return [types.Tool(function_declarations=decls)]
