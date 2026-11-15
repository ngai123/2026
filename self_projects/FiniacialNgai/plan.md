# FinancialNgai — Implementation Plan

Concrete, step-by-step execution plan. Each task is self-contained and independently completable.

---

## Sprint 1 — Critical Bug Fixes (Target: ~8 hours)

### Task 1.1 — Add `health_score` column & `update_snapshot_health()` to repository.py

**File:** `database/repository.py`

1. In `init_db()`, add migration:
   ```sql
   ALTER TABLE snapshots ADD COLUMN health_score REAL DEFAULT NULL;
   ```
   Wrap in `try/except` (column may already exist on re-run).

2. Add method:
   ```python
   def update_snapshot_health(self, snapshot_id: int, health_score: float) -> None:
       with self._conn() as conn:
           conn.execute(
               "UPDATE snapshots SET health_score = ? WHERE id = ?",
               (health_score, snapshot_id)
           )
   ```

3. Add method to fetch latest snapshot with health score:
   ```python
   def get_latest_snapshot_with_health(self) -> sqlite3.Row | None:
       with self._conn() as conn:
           return conn.execute(
               "SELECT * FROM snapshots ORDER BY period DESC LIMIT 1"
           ).fetchone()
   ```

---

### Task 1.2 — Add `risk_profiles` table & methods to repository.py

**File:** `database/repository.py`

1. In `init_db()`, create table:
   ```sql
   CREATE TABLE IF NOT EXISTS risk_profiles (
       id INTEGER PRIMARY KEY AUTOINCREMENT,
       score INTEGER NOT NULL,
       profile TEXT NOT NULL,
       max_equity_pct REAL,
       max_crypto_pct REAL,
       min_bonds_pct REAL,
       time_horizon TEXT,
       notes TEXT,
       created_at TEXT DEFAULT (datetime('now'))
   );
   ```

2. Add method:
   ```python
   def save_risk_profile(self, profile: dict) -> int:
       with self._conn() as conn:
           cursor = conn.execute(
               """INSERT INTO risk_profiles
                  (score, profile, max_equity_pct, max_crypto_pct, min_bonds_pct, time_horizon, notes)
                  VALUES (:score, :profile, :max_equity_pct, :max_crypto_pct, :min_bonds_pct, :time_horizon, :notes)""",
               profile
           )
           return cursor.lastrowid
   ```

3. Add method:
   ```python
   def get_latest_risk_profile(self) -> sqlite3.Row | None:
       with self._conn() as conn:
           return conn.execute(
               "SELECT * FROM risk_profiles ORDER BY created_at DESC LIMIT 1"
           ).fetchone()
   ```

---

### Task 1.3 — Add `sensitivity_analysis()` to monte_carlo.py

**File:** `analysis/monte_carlo.py`

Add method to `MonteCarloEngine`:
```python
def sensitivity_analysis(
    self,
    base_wealth: float,
    base_contribution: float,
    years: int,
    contribution_range: list[float] | None = None,
    n_simulations: int = 5000,
) -> dict[float, MonteCarloResult]:
    """
    Run MC simulation for a range of monthly contributions.
    Returns {contribution_amount: MonteCarloResult}.
    """
    if contribution_range is None:
        contribution_range = [
            base_contribution + delta
            for delta in [-3000, -2000, -1000, -500, 0, 500, 1000, 2000, 3000]
            if base_contribution + delta >= 0
        ]

    results = {}
    for contrib in contribution_range:
        results[contrib] = self.run(
            initial_wealth=base_wealth,
            monthly_contribution=contrib,
            years=years,
            n_simulations=n_simulations,
        )
    return results
```

---

### Task 1.4 — Add `run_scenario_comparison()` to monte_carlo.py

**File:** `analysis/monte_carlo.py`

Add method to `MonteCarloEngine`:
```python
def run_scenario_comparison(
    self,
    base_wealth: float,
    scenarios: list[dict],
    years: int,
    n_simulations: int = 5000,
) -> list[dict]:
    """
    scenarios: [{"label": "Current Pace", "monthly_contribution": 1000}, ...]
    Returns list of dicts with label + MonteCarloResult fields.
    """
    output = []
    for scenario in scenarios:
        result = self.run(
            initial_wealth=base_wealth,
            monthly_contribution=scenario["monthly_contribution"],
            years=years,
            n_simulations=n_simulations,
        )
        output.append({
            "label": scenario["label"],
            "monthly_contribution": scenario["monthly_contribution"],
            "result": result,
        })
    return output
```

---

### Task 1.5 — Add `compare_strategies()` to backtester.py

**File:** `analysis/backtester.py`

Add method to `Backtester`:
```python
def compare_strategies(
    self,
    strategy_names: list[str],
    years: int,
    monthly_contribution: float,
    initial_wealth: float = 0.0,
) -> list:
    """
    Run backtest for each named strategy. Returns list of BacktestResult.
    strategy_names: e.g. ["100% KWSP", "Balanced", "Growth"]
    """
    results = []
    for name in strategy_names:
        allocation = PRESET_STRATEGIES.get(name)
        if allocation is None:
            continue
        result = self.run(
            allocation=allocation,
            years=years,
            monthly_contribution=monthly_contribution,
            initial_wealth=initial_wealth,
            label=name,
        )
        results.append(result)
    return results
```

Move `PRESET_STRATEGIES` dict from `backtesting.py` into `backtester.py` as a module-level constant so it can be shared.

---

### Task 1.6 — Add `calculate_ptptn_payoff()` to backtester.py

**File:** `analysis/backtester.py`

Add method to `Backtester` (or as standalone function):
```python
def calculate_ptptn_payoff(
    self,
    balance: float,
    monthly_payment: float,
    annual_rate: float = 0.01,  # 1% ICR default; 3% standard
) -> dict:
    """
    Returns amortization schedule.
    {
        "months_to_payoff": int,
        "total_interest": float,
        "total_paid": float,
        "schedule": [{"month": 1, "payment": x, "principal": x, "interest": x, "balance": x}, ...]
    }
    """
    monthly_rate = annual_rate / 12
    remaining = balance
    schedule = []
    month = 0

    while remaining > 0.01 and month < 600:
        month += 1
        interest = remaining * monthly_rate
        principal = min(monthly_payment - interest, remaining)
        if principal <= 0:
            break  # payment doesn't cover interest
        remaining -= principal
        schedule.append({
            "month": month,
            "payment": monthly_payment,
            "principal": round(principal, 2),
            "interest": round(interest, 2),
            "balance": round(max(remaining, 0), 2),
        })

    return {
        "months_to_payoff": month,
        "total_interest": round(sum(r["interest"] for r in schedule), 2),
        "total_paid": round(sum(r["payment"] for r in schedule), 2),
        "schedule": schedule,
    }
```

---

### Task 1.7 — Fix config.py: Remove ANTHROPIC_API_KEY reference

**File:** `ui/pages/settings.py`

- Find and remove any `ANTHROPIC_API_KEY` references
- Replace with `GEMINI_API_KEY` display (already in config.py)
- The settings page API section should only show: `GEMINI_API_KEY`, `OPENROUTER_API_KEY`

---

### Task 1.8 — Wire all dormant pages into app.py navigation

**File:** `app.py`

Replace the current 4-item sidebar with a grouped navigation:
```python
import ui.pages.dashboard as dashboard
import ui.pages.goals as goals          # Phase 2
import ui.pages.projections as projections
import ui.pages.backtesting as backtesting
import ui.pages.ai_chat as ai_chat
import ui.pages.risk_profile as risk_profile
import ui.pages.settings as settings

PAGES = {
    "🏠 Dashboard":       dashboard,
    "📊 Balance Sheet":   balance_sheet,
    "📈 P&L Statement":   pnl,
    "🔭 Monitoring":      simulation,
    "📉 Analysis":        history,
    "🎯 Projections":     projections,
    "⚔️ Backtesting":    backtesting,
    "🤖 AI Chat":         ai_chat,
    "🧠 Risk Profile":    risk_profile,
    "⚙️ Settings":        settings,
}

page_name = st.sidebar.radio("Navigate", list(PAGES.keys()))
PAGES[page_name].render()
```

---

## Sprint 2 — New Features (Target: ~3–4 days)

### Task 2.1 — Goal Tracker page

**New file:** `ui/pages/goals.py`
**New DB table:** `goals`

Schema:
```sql
CREATE TABLE IF NOT EXISTS goals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    target_amount REAL NOT NULL,
    current_amount REAL DEFAULT 0,
    deadline TEXT,
    category TEXT,
    notes TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    completed INTEGER DEFAULT 0
);
```

UI:
1. "Add Goal" form (name, target RM, deadline, optional category link)
2. Goals list — each shows progress bar, months remaining, monthly amount needed
3. "Mark Complete" button per goal
4. AI insight button: "Ask Gemini about this goal"

New repository methods:
- `create_goal(goal_dict)` → int id
- `get_all_goals()` → list
- `update_goal_progress(id, current_amount)`
- `complete_goal(id)`

---

### Task 2.2 — Malaysian Tax Estimator

**New file:** `analysis/tax_estimator.py`

```python
BRACKETS_2024 = [
    (5_000,    0.00),
    (20_000,   0.01),
    (35_000,   0.03),
    (50_000,   0.08),
    (70_000,   0.13),
    (100_000,  0.21),
    (250_000,  0.24),
    (400_000,  0.245),
    (600_000,  0.25),
    (1_000_000, 0.26),
    (float('inf'), 0.28),
]

def estimate_tax(
    gross_income: float,
    kwsp_contribution: float = 0,
    sspn_contribution: float = 0,
    lifestyle_relief: float = 2_500,   # default lifestyle cap
    medical_relief: float = 0,
    other_reliefs: float = 0,
) -> dict:
    ...
```

Returns:
```python
{
    "gross_income": float,
    "total_reliefs": float,
    "chargeable_income": float,
    "tax_payable": float,
    "effective_rate_pct": float,
    "breakdown": [{"bracket": "...", "rate": "%", "tax": RM}, ...]
}
```

Add a "Tax Estimate" section to `pnl.py` below the P&L table, auto-populating from the latest P&L income.

---

### Task 2.3 — MiMo / Gemini Chat (upgrade ai_chat.py) ✅ DONE

**Files changed:** `ai/mimo_consultant.py` (new), `ui/pages/ai_chat.py`, `config.py`, `requirements.txt`

Provider priority (auto-detected):
1. **Xiaomi MiMo** — `XIAOMI_API_KEY` set → `MiMoConsultant` (mimo-v2.5-pro, OpenAI-compatible, streaming, tool calling)
2. **Gemini** — `GEMINI_API_KEY` set → `FinancialConsultant`
3. **Ollama** — fallback → `OllamaConsultant`

Features added:
- Provider badge in chat header (orange MiMo / blue Gemini / grey Ollama)
- Starter prompt buttons shown on empty chat
- `<think>` reasoning blocks rendered as collapsible expander
- Streamed tool call feedback ("Fetching: Dashboard Summary…")

---

### Task 2.4 — Rebalancing Alerts in Dashboard

**File:** `ui/pages/dashboard.py`

After rendering the health score card:
1. Fetch latest risk profile (target allocations)
2. Fetch latest balance sheet (current allocations by category %)
3. Compare: if any category drifts > 5% from target → show warning card:
   ```
   ⚠️ Rebalancing Needed
   Crypto is at 18% (target: 10%) — consider moving RM 2,400 to Bonds
   ```
4. Link: "Go to Balance Sheet to adjust"

---

## Sprint 3 — Polish (Ongoing)

### Task 3.1 — Error boundaries in app.py
Wrap every `PAGES[page_name].render()` in:
```python
try:
    PAGES[page_name].render()
except Exception as e:
    st.error(f"Something went wrong on this page.")
    with st.expander("Error detail"):
        st.code(traceback.format_exc())
```

### Task 3.2 — Scraper health in Settings
Show a status table in `settings.py`:
```
| Scraper   | Last Fetched       | Status |
| BNM OPR   | 2026-05-17 09:30   | 🟢     |
| KWSP      | 2026-05-10 14:00   | 🟡     |
| LUNO      | Never              | 🔴     |
```

### Task 3.3 — CSV + PDF export
Extend `ui/export.py`:
- `export_csv(df, filename)` — wraps `df.to_csv()` with `st.download_button`
- `export_pdf(html_string, filename)` — uses `weasyprint` or `reportlab`

---

## File Change Manifest

| File | Change Type | Sprint |
|---|---|---|
| `database/repository.py` | Add 5 methods + 2 table migrations | 1 |
| `analysis/monte_carlo.py` | Add 2 methods | 1 |
| `analysis/backtester.py` | Add 2 methods + import PRESET_STRATEGIES | 1 |
| `ui/pages/settings.py` | Remove ANTHROPIC_API_KEY ref | 1 |
| `app.py` | Expand navigation to 10 pages | 1 |
| `ui/pages/goals.py` | New file | 2 |
| `analysis/tax_estimator.py` | New file | 2 |
| `ui/pages/ai_chat.py` | Upgrade to Gemini + tool call rendering | 2 |
| `ui/pages/dashboard.py` | Add rebalancing alerts section | 2 |
| `ui/export.py` | Add CSV + PDF helpers | 3 |
| `ui/pages/settings.py` | Add scraper health table | 3 |

---

## Testing Checklist

After Sprint 1:
- [ ] `streamlit run app.py` — all 10 pages reachable, no crashes
- [ ] Dashboard renders health score without error
- [ ] Risk Profile saves and reloads correctly
- [ ] Projections page shows sensitivity chart and scenario table
- [ ] Backtesting shows multi-strategy comparison
- [ ] PTPTN calculator shows amortization schedule
- [ ] Settings page shows only Gemini/OpenRouter API keys

After Sprint 2:
- [ ] Goal Tracker: create, progress-update, complete a goal
- [ ] Tax Estimator: correct computation for RM 60,000 chargeable income
- [ ] AI Chat: Gemini responds with tool call results inline
- [ ] Dashboard: rebalancing alert appears when crypto > 5% over target

After Sprint 3:
- [ ] Crash on any page shows error card, not a blank screen
- [ ] BNM scraper status shows in Settings
- [ ] CSV download works from Balance Sheet and P&L pages
