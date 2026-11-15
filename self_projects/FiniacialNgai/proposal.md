# FinancialNgai — Improvement Proposals

Personal AI financial advisor for Malaysian investors. This document proposes targeted improvements based on a full codebase audit.

---

## Executive Summary

FinancialNgai has a polished UI, solid data model, and a well-designed AI layer. However, **6 dormant pages are unreachable**, **10 critical backend methods are missing**, and **5 bugs crash features silently**. The highest-ROI work is fixing those broken methods (a few hours of work) to unlock pages that are already 70–95% complete.

Beyond bug fixes, three new features would meaningfully elevate the app: a **Goal Tracker**, **Malaysian Tax Estimator**, and a **Gemini-powered chat** (replacing the Ollama-only chat).

---

## Phase 1 — Bug Fixes & Activate Dormant Pages

### 1.1 Fix Missing Database Methods (Critical)

The following methods are called by pages but don't exist in `database/repository.py`:

| Missing Method | Called By | Fix |
|---|---|---|
| `update_snapshot_health(id, score)` | `dashboard.py` | Add column `health_score` to snapshots table + write method |
| `save_risk_profile(profile_dict)` | `risk_profile.py` | Create `risk_profiles` table + insert method |
| `get_latest_risk_profile()` | `risk_profile.py` | SELECT latest row from `risk_profiles` |

### 1.2 Fix Missing Analysis Engine Methods (Critical)

| Missing Method | Called By | Fix |
|---|---|---|
| `MonteCarloEngine.sensitivity_analysis(base, contributions, years)` | `projections.py` | Run MC for a range of ±RM200–3000/mo; return dict of outcomes |
| `MonteCarloEngine.run_scenario_comparison(scenarios)` | `projections.py` | Run MC for 3 contribution scenarios; return comparison table |
| `Backtester.compare_strategies(strategies, years, monthly)` | `backtesting.py` | Loop `run()` for each preset strategy; return list of BacktestResult |
| `Backtester.calculate_ptptn_payoff(balance, monthly, rate)` | `backtesting.py` | Amortization schedule: months to payoff, total interest, breakdown |

### 1.3 Fix Config Inconsistencies

- Remove `ANTHROPIC_API_KEY` from `settings.py` (app uses Gemini, not Anthropic)
- Ensure all API key references in `settings.py` match what `config.py` exports

### 1.4 Activate All 6 Dormant Pages

Wire into `app.py` sidebar navigation:

```
Balance Sheet | P&L | Monitoring | Analysis | Projections | Backtesting | AI Chat | Risk Profile | Dashboard | Settings
```

Suggested grouping:
- **Core:** Balance Sheet, P&L, Dashboard
- **Analysis:** Monitoring, Analysis, Projections, Backtesting
- **Tools:** AI Chat, Risk Profile, Settings

---

## Phase 2 — New Features

### 2.1 Goal Tracker
Allow users to set named financial goals (e.g., Emergency Fund, House Down Payment, FIRE, Holiday) with a target amount and deadline. Each goal shows:
- Progress bar (current vs target)
- Monthly contribution needed to hit target on time
- AI tip: which assets to liquidate/redirect

**Implementation:**
- New table: `goals` (id, name, target_amount, deadline, linked_asset_category, notes)
- New page: `ui/pages/goals.py`
- New AI tool: `get_goal_progress()` → feeds into Gemini context

### 2.2 Malaysian Tax Estimator (LHDN)
Auto-compute estimated income tax based on P&L income data:
- Total chargeable income (from salary, freelance, investment income)
- Tax reliefs: KWSP (RM 4k cap), PTPTN SSPN (RM 8k), medical, lifestyle, SOCSO
- Progressive tax bracket calculation (0% → 30%)
- PCB monthly deduction estimate
- Display: "You owe approx RM X this year" + breakdown

**Implementation:**
- New module: `analysis/tax_estimator.py`
- New section inside `pnl.py` or dedicated `ui/pages/tax.py`
- New AI tool: `estimate_tax(income, reliefs)` in `ai/tools.py`

### 2.3 Gemini Chat (Replace Ollama-only AI Chat)
Current `ai_chat.py` uses Ollama (requires local server). Replace with Gemini as primary, Ollama as fallback:
- Switch `ai_chat.py` to call `ai/consultant.py` (Gemini) instead of `ai/ollama_consultant.py`
- Keep Ollama fallback when `GEMINI_API_KEY` is not set
- Enable tool calling in chat (portfolio lookup, MC simulation, etc.)
- Show tool call results inline (e.g., "Running Monte Carlo…" → chart appears)

### 2.4 Portfolio Rebalancing Alerts
After every balance sheet save, compare current allocation % vs target allocation (from risk profile):
- Flag categories that have drifted >5% from target
- Show rebalancing suggestion: "Move RM X from Crypto → Bonds to restore balance"
- Integrate into Dashboard as a "Rebalancing Needed" warning card

### 2.5 Budget Mode (Monthly Budget vs Actual)
Extend `pnl.py` with a budget layer:
- User sets monthly budget per expense category (one-time setup in Settings)
- P&L page shows Budget vs Actual vs Variance columns
- Color-coded: green (under budget), red (over budget)
- Rollover tracking: "You saved RM 300 vs budget — redirect to KWSP?"

---

## Phase 3 — Polish & Quality of Life

### 3.1 Mobile-Responsive Layout
Streamlit's default layout is desktop-only. Improvements:
- Collapse sidebar to a top hamburger menu on narrow screens
- Single-column layouts for pages that use `st.columns(3+)`
- Larger touch targets on buttons

### 3.2 Data Export: CSV + PDF
- Per-page export buttons (CSV for spreadsheet, PDF for printable report)
- `ui/export.py` already has JSON; extend to CSV and a styled PDF via `reportlab`

### 3.3 Scraper Health Dashboard
Settings page shows last-fetched timestamps and status for each scraper (BNM, KWSP, ASNB, LUNO):
- Green: fetched < 24 hours ago
- Yellow: fetched 1–7 days ago
- Red: never fetched or failed

### 3.4 Error Boundary UI
Replace silent crashes with user-friendly error cards:
- Wrap all page `render()` calls in try/except
- Show "Something went wrong — please refresh" with error detail in expander
- Log to a `errors.log` file

---

## Priority Matrix

| Proposal | Effort | Impact | Priority |
|---|---|---|---|
| Fix missing DB methods | Low (2h) | High | 🔥 Now |
| Fix missing analysis methods | Medium (4h) | High | 🔥 Now |
| Activate dormant pages | Low (1h) | High | 🔥 Now |
| Fix config inconsistencies | Low (30min) | Medium | 🔥 Now |
| Goal Tracker | Medium (1 day) | High | Next |
| Tax Estimator | Medium (1 day) | High | Next |
| Gemini Chat | Low (3h) | High | Next |
| Rebalancing Alerts | Medium (4h) | Medium | Next |
| Budget Mode | Medium (1 day) | Medium | Soon |
| Mobile Layout | High (2 days) | Medium | Later |
| PDF Export | Low (3h) | Low | Later |
| Scraper Health Dashboard | Low (2h) | Low | Later |
| Error Boundaries | Low (2h) | Medium | Later |
