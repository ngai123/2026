"""Gemini function declarations — give the AI access to real financial data and analysis."""

TOOLS = [
    {
        "name": "get_current_portfolio",
        "description": (
            "Retrieve the user's current balance sheet with all asset details, "
            "total assets, total liabilities, net worth, health score, risk profile, "
            "monthly income, expenses, and savings. Call this first before any analysis."
        ),
        "parameters": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "run_monte_carlo",
        "description": (
            "Run a Monte Carlo simulation (10,000 scenarios) projecting the user's "
            "net worth over a given number of years. Returns median, 5th, and 95th "
            "percentile outcomes, milestone years, and probability of reaching goals."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "years": {
                    "type": "integer",
                    "description": "Number of years to project (1–40)",
                },
                "monthly_contribution": {
                    "type": "number",
                    "description": "Additional monthly savings/investment in RM (default: user's current monthly savings)",
                },
                "inflation_adjust": {
                    "type": "boolean",
                    "description": "Whether to show results in today's purchasing power (real terms)",
                },
            },
            "required": ["years"],
        },
    },
    {
        "name": "get_kwsp_dividend_history",
        "description": "Return KWSP/EPF historical dividend rates by year (2010–present). Useful for benchmarking and backtesting.",
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "name": "get_bnm_opr_history",
        "description": "Return BNM Overnight Policy Rate (OPR) history. Use this to understand the interest rate environment and its impact on FDs, savings, and loans.",
        "parameters": {"type": "object", "properties": {}},
    },
    {
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
    {
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
    {
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
    {
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
    {
        "name": "get_pnl_statement",
        "description": (
            "Retrieve the user's latest P&L (Profit & Loss) statement showing all income sources "
            "and expense categories with monthly amounts, total income, total expenses, "
            "net monthly savings, and savings rate."
        ),
        "parameters": {"type": "object", "properties": {}},
    },
    {
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
]
