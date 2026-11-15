"""
Flexible balance sheet model.
Assets are NOT limited to preset types — users can add anything:
stocks, REITs, bonds, real estate, cryptocurrency, startups, etc.
"""
from enum import Enum
from typing import TypedDict, Optional
from pydantic import BaseModel, Field, field_validator


class AssetCategory(str, Enum):
    LIQUID      = "Liquid / Cash"
    SAVINGS     = "Savings & Fixed Deposits"
    RETIREMENT  = "Retirement (EPF/KWSP)"
    INVESTMENT  = "Investments"
    STOCKS      = "Stocks & Equities"
    CRYPTO      = "Cryptocurrency"
    UNIT_TRUST  = "Unit Trusts & Mutual Funds"
    GOLD        = "Gold & Precious Metals"
    REAL_ESTATE = "Real Estate / Property"
    BONDS       = "Bonds & Fixed Income"
    INSURANCE   = "Insurance / Takaful"
    EDUCATION   = "Education Savings"
    OTHER       = "Other Assets"
    LIABILITY   = "Liabilities / Loans"


# Preset assets for the Malaysian context — user can also add custom ones
PRESET_ASSETS = {
    # Liquid
    "CASH":            {"name": "Cash", "category": AssetCategory.LIQUID},
    "TNG_WALLET":      {"name": "Touch 'n Go eWallet", "category": AssetCategory.LIQUID},

    # Savings
    "MAYBANK_SAVINGS": {"name": "Maybank Savings", "category": AssetCategory.SAVINGS},
    "MAYBANK_FD":      {"name": "Maybank Fixed Deposit", "category": AssetCategory.SAVINGS},
    "RHB_SAVINGS":     {"name": "RHB Savings", "category": AssetCategory.SAVINGS},
    "RYT_BANK":        {"name": "Ryt Bank Savings", "category": AssetCategory.SAVINGS},

    # Retirement
    "KWSP_EPF":        {"name": "KWSP / EPF", "category": AssetCategory.RETIREMENT},

    # Unit Trusts / ASNB
    "ASNB_RIA":        {"name": "ASNB Ria", "category": AssetCategory.UNIT_TRUST},
    "ASNB_MUTUAL":     {"name": "ASNB Mutual Fund", "category": AssetCategory.UNIT_TRUST},
    "PTPTN_SAVINGS":   {"name": "PTPTN Simpanan", "category": AssetCategory.EDUCATION},

    # Stocks
    "MOOMOO_STOCKS":   {"name": "MooMoo Stocks", "category": AssetCategory.STOCKS},

    # Gold
    "GOLD":            {"name": "Gold", "category": AssetCategory.GOLD},

    # Crypto
    "LUNO_CRYPTO":     {"name": "LUNO Crypto", "category": AssetCategory.CRYPTO},

    # Unit Trust (generic)
    "PRINCIPAL_RETIRE": {"name": "Principal Retire", "category": AssetCategory.UNIT_TRUST},
    "PRINCIPAL_SAVE":   {"name": "Principal Save", "category": AssetCategory.UNIT_TRUST},

    # Liabilities
    "PTPTN_LOAN":      {"name": "PTPTN Loan", "category": AssetCategory.LIABILITY, "is_liability": True},
    "PERSONAL_LOAN":   {"name": "Personal Loan", "category": AssetCategory.LIABILITY, "is_liability": True},
    "CREDIT_CARD":     {"name": "Credit Card Debt", "category": AssetCategory.LIABILITY, "is_liability": True},
    "HOUSING_LOAN":    {"name": "Housing Loan / Mortgage", "category": AssetCategory.LIABILITY, "is_liability": True},
    "CAR_LOAN":        {"name": "Car Loan", "category": AssetCategory.LIABILITY, "is_liability": True},

    # Custom placeholder
    "CUSTOM":          {"name": "Custom Asset", "category": AssetCategory.OTHER},
}


class AssetEntry(BaseModel):
    """A single line item on the balance sheet."""
    name:               str
    category:           AssetCategory
    asset_key:          str           = "CUSTOM"
    institution:        str           = ""
    balance:            float         = Field(ge=0)
    currency:           str           = "MYR"
    is_liability:       bool          = False
    annual_return_pct:  Optional[float] = None  # user override
    quantity:           Optional[float] = None  # for stocks/crypto: units held
    ticker:             str           = ""       # e.g. "AAPL", "MAYBANK.KL", "BTC"
    notes:              str           = ""

    @field_validator("balance")
    @classmethod
    def non_negative(cls, v):
        if v < 0:
            raise ValueError("Balance must be >= 0")
        return v

    @property
    def balance_myr(self) -> float:
        """Returns balance in MYR (FX conversion applied externally if needed)."""
        return self.balance


class RiskProfile(str, Enum):
    VERY_CONSERVATIVE = "very_conservative"
    CONSERVATIVE      = "conservative"
    MODERATE          = "moderate"
    AGGRESSIVE        = "aggressive"
    VERY_AGGRESSIVE   = "very_aggressive"


RISK_PROFILE_LABELS = {
    RiskProfile.VERY_CONSERVATIVE: "Very Conservative (Capital preservation)",
    RiskProfile.CONSERVATIVE:      "Conservative (Low risk, stable returns)",
    RiskProfile.MODERATE:          "Moderate (Balanced growth & safety)",
    RiskProfile.AGGRESSIVE:        "Aggressive (Growth-oriented)",
    RiskProfile.VERY_AGGRESSIVE:   "Very Aggressive (Maximum growth, high risk)",
}

RISK_PROFILE_PARAMS = {
    RiskProfile.VERY_CONSERVATIVE: {
        "max_equity_pct": 10,
        "max_crypto_pct": 0,
        "min_bond_pct":   60,
        "description":    "Focus on capital preservation. Mostly FDs, ASNB, KWSP.",
    },
    RiskProfile.CONSERVATIVE: {
        "max_equity_pct": 30,
        "max_crypto_pct": 2,
        "min_bond_pct":   40,
        "description":    "Stable returns with minimal risk. Mostly FDs + unit trusts.",
    },
    RiskProfile.MODERATE: {
        "max_equity_pct": 60,
        "max_crypto_pct": 5,
        "min_bond_pct":   20,
        "description":    "Balanced portfolio with mix of growth and stable assets.",
    },
    RiskProfile.AGGRESSIVE: {
        "max_equity_pct": 80,
        "max_crypto_pct": 15,
        "min_bond_pct":   5,
        "description":    "Growth-first. Heavy stocks, some crypto, minimal FDs.",
    },
    RiskProfile.VERY_AGGRESSIVE: {
        "max_equity_pct": 100,
        "max_crypto_pct": 40,
        "min_bond_pct":   0,
        "description":    "Maximum growth. Heavy crypto and growth stocks.",
    },
}


class BalanceSheet(BaseModel):
    label:           str
    entries:         list[AssetEntry]
    monthly_income:  float = 0.0
    monthly_expense: float = 0.0
    risk_profile:    RiskProfile = RiskProfile.MODERATE
    notes:           str = ""

    @property
    def assets(self) -> list[AssetEntry]:
        return [e for e in self.entries if not e.is_liability]

    @property
    def liabilities(self) -> list[AssetEntry]:
        return [e for e in self.entries if e.is_liability]

    @property
    def total_assets(self) -> float:
        return sum(e.balance for e in self.assets)

    @property
    def total_liabilities(self) -> float:
        return sum(e.balance for e in self.liabilities)

    @property
    def net_worth(self) -> float:
        return self.total_assets - self.total_liabilities

    @property
    def monthly_savings(self) -> float:
        return max(0, self.monthly_income - self.monthly_expense)

    def by_category(self) -> dict[str, float]:
        result: dict[str, float] = {}
        for e in self.assets:
            key = e.category.value
            result[key] = result.get(key, 0) + e.balance
        return result

    def to_db_list(self) -> list[dict]:
        return [
            {
                "name":              e.name,
                "category":         e.category.value,
                "asset_key":        e.asset_key,
                "institution":      e.institution,
                "balance":          e.balance,
                "currency":         e.currency,
                "is_liability":     e.is_liability,
                "annual_return_pct": e.annual_return_pct,
                "quantity":         e.quantity,
                "ticker":           e.ticker,
                "notes":            e.notes,
            }
            for e in self.entries
        ]

    def summary_text(self) -> str:
        lines = [
            f"Balance Sheet: {self.label}",
            f"Total Assets:       RM {self.total_assets:,.2f}",
            f"Total Liabilities:  RM {self.total_liabilities:,.2f}",
            f"Net Worth:          RM {self.net_worth:,.2f}",
            f"Monthly Income:     RM {self.monthly_income:,.2f}",
            f"Monthly Expense:    RM {self.monthly_expense:,.2f}",
            f"Monthly Savings:    RM {self.monthly_savings:,.2f}",
            f"Risk Profile:       {self.risk_profile.value}",
            "",
            "Asset Breakdown:",
        ]
        for e in self.entries:
            prefix = "  LIABILITY" if e.is_liability else "  ASSET    "
            ticker = f" [{e.ticker}]" if e.ticker else ""
            lines.append(f"{prefix}  {e.name}{ticker}: RM {e.balance:,.2f}")
        return "\n".join(lines)


# ─── Typed data models (match repository.py row shapes) ─────────────

class Asset(TypedDict):
    """Row returned by balance_sheet_repository for a single asset."""
    id: int
    snapshot_id: int
    name: str
    category: str          # will eventually be AssetCategory; keep str for now
    balance: float
    is_liability: bool
    institution: str
    ticker: str
    annual_return_pct: float
    quantity: float
    asset_key: str
    notes: str


class PnlItem(TypedDict):
    """Row returned by pnl_repository for a single income/expense line."""
    id: int
    pnl_snapshot_id: int
    type: str              # 'income' or 'expense'
    category: str
    description: str
    amount: float


class Snapshot(TypedDict):
    """Row returned by snapshot_repository for a balance-sheet snapshot."""
    id: int
    period: str
    label: str
    total_assets: float
    total_liabilities: float
    net_worth: float
    monthly_income: float
    monthly_expense: float
    health_score: Optional[float]
    risk_profile: str
    notes: str
    created_at: str


# ─── Risk Questionnaire ──────────────────────────────────────────────

RISK_QUESTIONS = [
    {
        "id": "time_horizon",
        "question": "When do you plan to use most of this money?",
        "options": [
            ("Less than 1 year", 1),
            ("1–3 years", 2),
            ("3–7 years", 3),
            ("7–15 years", 4),
            ("15+ years", 5),
        ],
    },
    {
        "id": "loss_tolerance",
        "question": "If your portfolio dropped 20% in a month, you would:",
        "options": [
            ("Sell everything immediately", 1),
            ("Sell some to reduce exposure", 2),
            ("Hold and wait for recovery", 3),
            ("Buy a little more at lower price", 4),
            ("Buy aggressively — great opportunity!", 5),
        ],
    },
    {
        "id": "income_stability",
        "question": "How stable is your income?",
        "options": [
            ("No income / very unstable", 1),
            ("Part-time / variable income", 2),
            ("Stable employment (student with allowance)", 3),
            ("Full-time employed, stable", 4),
            ("Multiple income streams, very stable", 5),
        ],
    },
    {
        "id": "investment_goal",
        "question": "What is your primary investment goal?",
        "options": [
            ("Preserve my money from inflation", 1),
            ("Slow and steady growth", 2),
            ("Balance between growth and safety", 3),
            ("Grow wealth significantly over time", 4),
            ("Maximum returns, I accept high risk", 5),
        ],
    },
    {
        "id": "experience",
        "question": "How would you describe your investment experience?",
        "options": [
            ("None — just starting out", 1),
            ("Beginner — some knowledge", 2),
            ("Intermediate — invested in funds/stocks", 3),
            ("Experienced — understand market cycles", 4),
            ("Expert — derivatives, options, crypto DeFi etc.", 5),
        ],
    },
]


def score_to_profile(score: int) -> RiskProfile:
    if score <= 8:
        return RiskProfile.VERY_CONSERVATIVE
    elif score <= 12:
        return RiskProfile.CONSERVATIVE
    elif score <= 16:
        return RiskProfile.MODERATE
    elif score <= 20:
        return RiskProfile.AGGRESSIVE
    else:
        return RiskProfile.VERY_AGGRESSIVE
