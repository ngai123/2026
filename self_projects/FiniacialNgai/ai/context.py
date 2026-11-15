"""
Financial context snapshot — populated by DataOrchestrator and passed to the AI
as a pre-filled text block so every model call starts with real numbers.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Optional


@dataclass
class FinancialContext:
    """Holds all financial data fields that may be pre-fetched before an AI call.

    Every field is Optional with a default of None so partial hydration is fine —
    only non-None fields are serialised by to_context_block().
    """

    # ── Portfolio summary ──────────────────────────────────────────────────────
    portfolio_total_value: Optional[float] = None
    # Each entry: {"asset_class": str, "pct": float, "value": float}
    portfolio_allocations: Optional[list[dict]] = None

    # ── P&L (income / expense) ─────────────────────────────────────────────────
    monthly_income: Optional[float] = None
    monthly_expense: Optional[float] = None
    monthly_savings: Optional[float] = None
    savings_rate_pct: Optional[float] = None

    # ── Expenses (last 30 days) ────────────────────────────────────────────────
    monthly_expenses_total: Optional[float] = None
    # {"category": amount_rm}
    expense_categories: Optional[dict[str, float]] = None

    # ── KWSP / EPF ─────────────────────────────────────────────────────────────
    kwsp_balance: Optional[float] = None
    kwsp_dividend_rate: Optional[float] = None  # latest annual % (e.g. 5.5)

    # ── ASNB ──────────────────────────────────────────────────────────────────
    asnb_balance: Optional[float] = None
    asnb_dividend_rate: Optional[float] = None  # latest RIA annual %

    # ── Macro / market data ────────────────────────────────────────────────────
    bnm_opr_rate: Optional[float] = None
    gold_price_myr_per_gram: Optional[float] = None
    usd_myr_rate: Optional[float] = None

    # ── Summary ────────────────────────────────────────────────────────────────
    net_worth: Optional[float] = None
    health_score: Optional[float] = None   # 0–100
    health_grade: Optional[str] = None    # e.g. "Baik (Good)"

    as_of_date: str = field(default_factory=lambda: date.today().isoformat())

    # ──────────────────────────────────────────────────────────────────────────

    def to_context_block(self) -> str:
        """Serialise non-None fields into a human-readable text block.

        Returns an empty string if no fields are populated.

        Example output:
            === YOUR FINANCIAL SNAPSHOT (as of 2026-05-15) ===
            Net Worth: RM 245,300
            Portfolio Value: RM 180,000
              - Stocks: 45% (RM 81,000)
            Monthly Income: RM 5,000 | Expenses: RM 3,200 | Savings: RM 1,800 (36%)
            KWSP Balance: RM 52,000 | Latest Dividend: 5.50%
            BNM OPR: 3.00%
            Gold: RM 385/g | USD/MYR: 4.4700
            Financial Health Score: 72/100 (Baik (Good))
            ===
        """
        lines: list[str] = []

        # ── Net worth ──────────────────────────────────────────────────────────
        if self.net_worth is not None:
            lines.append(f"Net Worth: RM {self.net_worth:,.0f}")

        # ── Portfolio ──────────────────────────────────────────────────────────
        if self.portfolio_total_value is not None:
            lines.append(f"Portfolio Value: RM {self.portfolio_total_value:,.0f}")
            if self.portfolio_allocations:
                for alloc in self.portfolio_allocations:
                    lines.append(
                        f"  - {alloc.get('asset_class', '?')}: "
                        f"{alloc.get('pct', 0):.0f}%"
                        f" (RM {alloc.get('value', 0):,.0f})"
                    )

        # ── Cash flow ──────────────────────────────────────────────────────────
        if self.monthly_income is not None or self.monthly_expense is not None:
            inc = self.monthly_income or 0.0
            exp = self.monthly_expense or 0.0
            sav = self.monthly_savings if self.monthly_savings is not None else max(0.0, inc - exp)
            if inc > 0:
                rate = self.savings_rate_pct if self.savings_rate_pct is not None else (sav / inc * 100)
            else:
                rate = 0.0
            lines.append(
                f"Monthly Income: RM {inc:,.0f} | Expenses: RM {exp:,.0f}"
                f" | Savings: RM {sav:,.0f} ({rate:.0f}%)"
            )

        # ── Expenses detail ────────────────────────────────────────────────────
        if self.monthly_expenses_total is not None:
            lines.append(f"Monthly Expenses (last 30d): RM {self.monthly_expenses_total:,.0f}")
            if self.expense_categories:
                top = sorted(self.expense_categories.items(), key=lambda x: -x[1])[:5]
                cat_str = " | ".join(f"{cat}: RM {amt:,.0f}" for cat, amt in top)
                lines.append(f"  - {cat_str}")

        # ── KWSP ──────────────────────────────────────────────────────────────
        if self.kwsp_balance is not None:
            kwsp_line = f"KWSP Balance: RM {self.kwsp_balance:,.0f}"
            if self.kwsp_dividend_rate is not None:
                kwsp_line += f" | Latest Dividend: {self.kwsp_dividend_rate:.2f}%"
            lines.append(kwsp_line)

        # ── ASNB ──────────────────────────────────────────────────────────────
        if self.asnb_balance is not None:
            asnb_line = f"ASNB Balance: RM {self.asnb_balance:,.0f}"
            if self.asnb_dividend_rate is not None:
                asnb_line += f" | Latest Dividend: {self.asnb_dividend_rate:.2f}%"
            lines.append(asnb_line)

        # ── Macro ──────────────────────────────────────────────────────────────
        if self.bnm_opr_rate is not None:
            lines.append(f"BNM OPR: {self.bnm_opr_rate:.2f}%")

        market_parts: list[str] = []
        if self.gold_price_myr_per_gram is not None:
            market_parts.append(f"Gold: RM {self.gold_price_myr_per_gram:.0f}/g")
        if self.usd_myr_rate is not None:
            market_parts.append(f"USD/MYR: {self.usd_myr_rate:.4f}")
        if market_parts:
            lines.append(" | ".join(market_parts))

        # ── Health score ───────────────────────────────────────────────────────
        if self.health_score is not None:
            score_line = f"Financial Health Score: {self.health_score:.0f}/100"
            if self.health_grade:
                score_line += f" ({self.health_grade})"
            lines.append(score_line)

        if not lines:
            return ""

        header = f"=== YOUR FINANCIAL SNAPSHOT (as of {self.as_of_date}) ==="
        return "\n".join([header] + lines + ["==="])
