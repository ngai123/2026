"""Historical seed data for Malaysian financial products."""

# KWSP Historical Dividends
KWSP_DIVIDEND_HISTORY = {
    2010: 5.80, 2011: 6.00, 2012: 6.15, 2013: 6.35,
    2014: 6.75, 2015: 6.40, 2016: 5.70, 2017: 6.90,
    2018: 6.15, 2019: 5.45, 2020: 5.20, 2021: 6.10,
    2022: 5.35, 2023: 5.40, 2024: 6.30,
}

# ASNB Historical Returns (seed data, % p.a.)
ASNB_RIA_HISTORY = {
    2015: 4.75, 2016: 4.50, 2017: 4.65, 2018: 4.50,
    2019: 5.50, 2020: 4.25, 2021: 4.50, 2022: 4.25,
    2023: 4.25, 2024: 4.50,
}

ASNB_MUTUAL_HISTORY = {
    2015: 5.20, 2016: 4.80, 2017: 6.50, 2018: 3.10,
    2019: 7.20, 2020: 3.50, 2021: 8.10, 2022: 2.80,
    2023: 5.60, 2024: 6.20,
}

# Asset Return Parameters for Monte Carlo
# (mean annual return, std dev) — updated from scraped data when available
ASSET_RETURN_PARAMS = {
    "KWSP_EPF":        {"mean": 0.057, "std": 0.008},
    "ASNB_RIA":        {"mean": 0.045, "std": 0.005},
    "ASNB_MUTUAL":     {"mean": 0.060, "std": 0.035},
    "MAYBANK_FD":      {"mean": 0.030, "std": 0.003},
    "MAYBANK_SAVINGS": {"mean": 0.020, "std": 0.002},
    "RHB_SAVINGS":     {"mean": 0.020, "std": 0.002},
    "RYT_BANK":        {"mean": 0.020, "std": 0.002},
    "MOOMOO_STOCKS":   {"mean": 0.080, "std": 0.200},
    "GOLD":            {"mean": 0.060, "std": 0.150},
    "LUNO_CRYPTO":     {"mean": 0.150, "std": 0.600},
    "UNIT_TRUST":      {"mean": 0.065, "std": 0.080},
    "CASH":            {"mean": 0.000, "std": 0.000},
    "TNG_WALLET":      {"mean": 0.000, "std": 0.000},
    "PTPTN_SAVINGS":   {"mean": 0.010, "std": 0.001},
    "PRINCIPAL":       {"mean": 0.050, "std": 0.050},
}
