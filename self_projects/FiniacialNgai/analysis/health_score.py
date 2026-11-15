"""
Financial Health Score calculator — Malaysian student context.
Composite score 0–100 with weighted components.
"""
from dataclasses import dataclass
from config import EMERGENCY_FUND_MONTHS_TARGET, FIRE_MULTIPLE
from models.balance_sheet import AssetCategory


@dataclass
class HealthScoreResult:
    total_score: float           # 0–100
    grade: str                   # Cemerlang / Baik / Sederhana / Perlu Perhatian
    grade_color: str             # green / blue / orange / red
    components: dict             # {component_name: {score, weight, feedback}}
    top_issues: list[str]
    top_wins: list[str]
    recommendations: list[str]


def calculate_health_score(
    assets: list[dict],          # DB asset dicts
    total_assets: float,
    total_liabilities: float,
    monthly_income: float,
    monthly_expense: float,
    risk_profile: str = "moderate",
) -> HealthScoreResult:
    """Calculate composite financial health score."""
    net_worth = total_assets - total_liabilities
    monthly_savings = max(0, monthly_income - monthly_expense)

    components = {}
    issues = []
    wins = []
    recommendations = []

    # ── 1. Emergency Fund (20%) ────────────────────────────────────────────
    liquid_assets = sum(
        a["balance"] for a in assets
        if a["category"] in (
            AssetCategory.LIQUID.value, AssetCategory.SAVINGS.value
        ) and not a["is_liability"]
    )
    emergency_target = monthly_expense * EMERGENCY_FUND_MONTHS_TARGET
    if monthly_expense > 0:
        ef_ratio = liquid_assets / emergency_target
        ef_score = min(100, ef_ratio * 100)
        if ef_ratio >= 1:
            wins.append(f"Emergency fund covered ({ef_ratio:.1f}x target)")
        elif ef_ratio >= 0.5:
            issues.append("Emergency fund at 50–100% of target")
            recommendations.append(
                f"Build emergency fund to RM {emergency_target:,.0f} "
                f"({EMERGENCY_FUND_MONTHS_TARGET} months expenses)."
            )
        else:
            issues.append("Emergency fund critically low (<50% of target)")
            recommendations.append(
                f"Priority #1: Build emergency fund. Target: RM {emergency_target:,.0f}."
            )
    else:
        ef_score = 50  # no expense data
        ef_ratio = 0

    components["Emergency Fund"] = {
        "score": ef_score, "weight": 0.20,
        "feedback": f"Liquid: RM {liquid_assets:,.0f} / Target: RM {emergency_target:,.0f}",
    }

    # ── 2. Debt-to-Asset Ratio (20%) ──────────────────────────────────────
    if total_assets > 0:
        dta = total_liabilities / total_assets
        dta_score = max(0, 100 - dta * 200)  # 0% debt = 100, 50%+ = 0
        if dta < 0.1:
            wins.append("Low debt relative to assets")
        elif dta > 0.4:
            issues.append(f"High debt-to-asset ratio ({dta:.0%})")
            recommendations.append("Consider accelerating debt repayment.")
    else:
        dta, dta_score = 0, 50

    components["Debt Management"] = {
        "score": dta_score, "weight": 0.20,
        "feedback": f"Debt-to-Asset: {dta:.1%} (lower is better)",
    }

    # ── 3. Savings Rate (15%) ─────────────────────────────────────────────
    if monthly_income > 0:
        savings_rate = monthly_savings / monthly_income
        sr_score = min(100, savings_rate * 333)  # 30% savings = 100 score
        if savings_rate >= 0.20:
            wins.append(f"Good savings rate ({savings_rate:.0%})")
        elif savings_rate < 0.10:
            issues.append(f"Low savings rate ({savings_rate:.0%})")
            recommendations.append(
                "Aim to save at least 20% of income. "
                "Review expenses and look for ways to increase income."
            )
    else:
        savings_rate, sr_score = 0, 0

    components["Savings Rate"] = {
        "score": sr_score, "weight": 0.15,
        "feedback": f"Saving RM {monthly_savings:,.0f}/month ({savings_rate:.0%} of income)",
    }

    # ── 4. Diversification (15%) ──────────────────────────────────────────
    categories = {}
    for a in assets:
        if not a["is_liability"]:
            cat = a["category"]
            categories[cat] = categories.get(cat, 0) + a["balance"]

    n_cats = len(categories)
    if n_cats >= 5:
        div_score = 100
        wins.append(f"Well-diversified across {n_cats} asset categories")
    elif n_cats >= 3:
        div_score = 70
    elif n_cats >= 2:
        div_score = 40
        recommendations.append(
            "Diversify across more asset classes: "
            "consider adding stocks, bonds, or REITs."
        )
    else:
        div_score = 20
        issues.append("Very concentrated portfolio (1 asset class)")
        recommendations.append(
            "Dangerous concentration. Diversify across at least 3-4 asset classes."
        )

    # Concentration check: any single asset > 60%?
    if total_assets > 0:
        for cat, val in categories.items():
            if val / total_assets > 0.60:
                issues.append(f"Over-concentrated in {cat} ({val/total_assets:.0%})")
                div_score = max(0, div_score - 30)
                recommendations.append(
                    f"Reduce concentration in {cat} below 60% of total assets."
                )
                break

    components["Diversification"] = {
        "score": div_score, "weight": 0.15,
        "feedback": f"{n_cats} asset categories in portfolio",
    }

    # ── 5. Retirement Adequacy (15%) ──────────────────────────────────────
    kwsp_balance = sum(
        a["balance"] for a in assets
        if a["asset_key"] in ("KWSP_EPF",) and not a["is_liability"]
    )
    # EPF target by age: rough benchmark RM 240k by 55
    # For students: just reward having a KWSP balance at all
    if kwsp_balance >= 10_000:
        ret_score = 80
        wins.append(f"KWSP balance: RM {kwsp_balance:,.0f}")
    elif kwsp_balance > 0:
        ret_score = 40
        recommendations.append(
            "Consider voluntary KWSP top-ups (RM 60k/yr limit) for "
            "tax relief + forced savings compound growth."
        )
    else:
        ret_score = 10
        issues.append("No KWSP/EPF balance detected")

    components["Retirement Savings"] = {
        "score": ret_score, "weight": 0.15,
        "feedback": f"KWSP balance: RM {kwsp_balance:,.0f}",
    }

    # ── 6. Investment Ratio (10%) ─────────────────────────────────────────
    investment_cats = {
        AssetCategory.INVESTMENT.value,
        AssetCategory.STOCKS.value,
        AssetCategory.CRYPTO.value,
        AssetCategory.UNIT_TRUST.value,
        AssetCategory.GOLD.value,
        AssetCategory.REAL_ESTATE.value,
        AssetCategory.BONDS.value,
    }
    investment_value = sum(
        a["balance"] for a in assets
        if a["category"] in investment_cats and not a["is_liability"]
    )
    inv_ratio = investment_value / total_assets if total_assets > 0 else 0

    if inv_ratio >= 0.4:
        inv_score = 100
        wins.append(f"Strong investment ratio ({inv_ratio:.0%} of assets invested)")
    elif inv_ratio >= 0.2:
        inv_score = 70
    elif inv_ratio >= 0.05:
        inv_score = 40
        recommendations.append(
            "Increase investment ratio. As a student, compound time is your biggest advantage. "
            "Even RM 100/month in index funds can grow significantly over decades."
        )
    else:
        inv_score = 15
        issues.append("Very low investment ratio — mostly in cash/savings")
        recommendations.append(
            "Start investing! ASNB, KWSP voluntary top-up, or a simple unit trust "
            "is better than leaving money idle in savings."
        )

    components["Investment Ratio"] = {
        "score": inv_score, "weight": 0.10,
        "feedback": f"RM {investment_value:,.0f} ({inv_ratio:.0%}) in growth assets",
    }

    # ── 7. Liquidity (5%) ─────────────────────────────────────────────────
    liq_ratio = liquid_assets / total_assets if total_assets > 0 else 0
    if 0.10 <= liq_ratio <= 0.30:
        liq_score = 100
    elif liq_ratio > 0.30:
        liq_score = 70  # too much cash drag
        recommendations.append(
            f"You hold {liq_ratio:.0%} of assets in cash/liquid — "
            "consider putting excess into higher-yield investments."
        )
    elif liq_ratio >= 0.05:
        liq_score = 50
    else:
        liq_score = 20
        issues.append("Very low liquidity ratio")

    components["Liquidity"] = {
        "score": liq_score, "weight": 0.05,
        "feedback": f"{liq_ratio:.1%} of assets in liquid form",
    }

    # ── Composite Score ───────────────────────────────────────────────────
    total_score = sum(
        c["score"] * c["weight"] for c in components.values()
    )
    total_score = round(total_score, 1)

    if total_score >= 80:
        grade, color = "Cemerlang (Excellent)", "green"
    elif total_score >= 60:
        grade, color = "Baik (Good)", "blue"
    elif total_score >= 40:
        grade, color = "Sederhana (Fair)", "orange"
    else:
        grade, color = "Perlu Perhatian (Needs Work)", "red"

    # Limit to top 3 of each
    return HealthScoreResult(
        total_score=total_score,
        grade=grade,
        grade_color=color,
        components=components,
        top_issues=issues[:3],
        top_wins=wins[:3],
        recommendations=recommendations[:5],
    )
