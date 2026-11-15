# Backtester — Improvement Specification
## Written by: Claude (tech lead) | To be implemented by: Xiaomi MiMo

---

## What we want

A fully working, visually rich backtesting page for Malaysian investors.
The user picks one or more investment strategies, sets a start year and monthly contribution,
and sees exactly how their money would have grown historically — with real numbers.

---

## Part A — Fix the core backtester engine (analysis/backtester.py)

### What the run() method must do

Given a strategy (a mix of assets like KWSP 60%, Stocks 40%), a start year, end year,
monthly contribution in RM, and starting capital:

1. For each year from start to end, apply that year's actual return for each asset class.
   Use these data sources in priority order:
   - KWSP dividends: use KWSP_DIVIDEND_HISTORY from config/seed_data.py
   - ASNB RIA: use ASNB_RIA_HISTORY from config/seed_data.py
   - ASNB Mutual: use ASNB_MUTUAL_HISTORY from config/seed_data.py
   - FD/savings: use 3.0% for years before 2020, 2.0% for 2020 onwards (BNM OPR proxy)
   - Gold: use 8% average per year (approximate)
   - Malaysian stocks: use 7% average per year (KLCI approximate)
   - S&P 500: use 10% average per year
   - Crypto: use 50% average but with ±80% volatility (very risky)

2. Each month: add the monthly contribution, then apply 1/12th of that year's return.

3. Track the portfolio value at the end of each year.

4. Calculate these final stats:
   - Final portfolio value in RM
   - CAGR (compound annual growth rate) as a percentage
   - Total return percentage
   - Best single year return (highest % gain in one year)
   - Worst single year return (lowest % gain in one year)
   - Maximum drawdown (biggest peak-to-trough drop)
   - Sharpe ratio (annualised return divided by annualised volatility, risk-free rate = 3%)
   - A list of yearly values (year → RM value) for charting

### The preset strategies to support

These are the standard Malaysian investor profiles:

1. **100% KWSP** — put everything in EPF. Safe, guaranteed returns.
   Allocation: KWSP 100%

2. **Conservative (EPF + FD)** — mostly safe instruments.
   Allocation: KWSP 70%, Fixed Deposit 20%, ASNB RIA 10%

3. **Balanced (EPF + ASNB + Stocks)** — mix of safe and growth.
   Allocation: KWSP 50%, ASNB Mutual 20%, Malaysian Stocks 20%, Gold 10%

4. **Growth (Stocks + Gold + Crypto)** — higher risk, higher potential.
   Allocation: Malaysian Stocks 40%, S&P 500 30%, Gold 20%, Crypto 10%

5. **Malaysian Diversified** — spread across all major Malaysian instruments.
   Allocation: KWSP 30%, ASNB RIA 15%, ASNB Mutual 15%, Malaysian Stocks 20%, Gold 10%, FD 10%

---

## Part B — Fix the backtesting UI page (ui/pages/backtesting.py)

### Layout

**Left column (controls, 1/3 width):**
- Dropdown: "Select strategies to compare" — multiselect from the 5 presets above
- Number input: "Start year" — minimum 2010, maximum 2023, default 2015
- Number input: "Monthly contribution (RM)" — default 500
- Number input: "Starting capital (RM)" — default 10,000
- Button: "Run Backtest"

**Right column (results, 2/3 width):**
Shows results only after the button is clicked.

### Results display

1. **Summary table** — one row per strategy, columns:
   - Strategy name
   - Final value (RM, formatted with comma separators)
   - CAGR %
   - Total return %
   - Best year %
   - Worst year %
   - Max drawdown %
   - Sharpe ratio

2. **Equity curve chart** — a line chart showing portfolio value over time for each strategy.
   - X axis: years
   - Y axis: RM value
   - One line per strategy, different colours
   - Use Plotly with transparent background (matching app theme)

3. **Annual returns bar chart** — for the best-performing strategy, show each year's return as a bar.
   - Green bars for positive years, red bars for negative years

4. **Insights card** — a text summary below the charts saying things like:
   - "The best strategy was X with a CAGR of Y%"
   - "Compared to 100% KWSP, the Growth strategy returned Z% more over N years"
   - "Your RM 10,000 grew to RM X"

---

## Part C — PTPTN Payoff Calculator section (in the same page)

Below the backtesting section, add a horizontal divider, then a PTPTN calculator.

### Layout

Three input fields side by side:
- Outstanding balance (RM) — default 20,000
- Monthly payment (RM) — default 150
- Interest rate — dropdown with two choices: "ICR (1% p.a.)" and "Standard (3% p.a.)"

A "Calculate" button.

### Results

Show:
1. A summary: "You will pay off your PTPTN in X years and Y months"
2. Total interest paid: RM X
3. Total amount paid: RM X
4. A table showing the first 24 months of the amortization schedule:
   - Month number, payment amount, principal portion, interest portion, remaining balance
5. A tip: if the user is on ICR (1%), show how much they save vs standard rate

---

## Part D — Error handling

- If start year has no historical data for a chosen strategy, show a friendly warning card
- If monthly contribution is 0 and starting capital is 0, show "Please enter at least a starting capital or monthly contribution"
- Wrap the whole render() in try/except — if anything crashes, show an error card with details in an expander

---

## Technical notes for MiMo

- Read analysis/backtester.py, ui/pages/backtesting.py, config/seed_data.py first
- The backtester.py already has compare_strategies() and calculate_ptptn_payoff() — check if they work correctly with the spec above, fix if needed
- Use .venv/bin/python3 to run all checks
- Plotly charts should use: paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)"
- Test the full render logic with: .venv/bin/python3 -m py_compile ui/pages/backtesting.py
- Do not import from ui/ inside analysis/ (one-way dependency rule)
