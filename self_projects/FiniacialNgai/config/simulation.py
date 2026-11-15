"""Simulation and financial-planning constants."""

# Monte Carlo
DEFAULT_SIMULATIONS = 10_000
DEFAULT_INFLATION_RATE = 0.025     # Malaysia avg CPI ~2.5%
DEFAULT_PROJECTION_YEARS = 20

# Malaysian Finance Constants
PTPTN_STANDARD_RATE = 0.03         # 3% p.a. standard repayment
PTPTN_ICR_RATE = 0.01              # 1% income-contingent repayment
KWSP_EMPLOYEE_RATE = 0.11          # 11% (age < 60)
KWSP_EMPLOYER_RATE = 0.13          # 13% (for salary <= RM5,000)
EMERGENCY_FUND_MONTHS_TARGET = 6
FIRE_MULTIPLE = 25                  # 4% withdrawal rule

# Correlation Matrix (asset order matches ASSET_RETURN_PARAMS keys)
# KWSP, ASNB_RIA, ASNB_MUTUAL, FD, GOLD, STOCKS, CRYPTO
CORRELATION_MATRIX_KEYS = [
    "KWSP_EPF", "ASNB_RIA", "ASNB_MUTUAL", "MAYBANK_FD",
    "GOLD", "MOOMOO_STOCKS", "LUNO_CRYPTO"
]
