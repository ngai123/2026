# FinancialNgai — Claude Code Guide

Personal AI financial advisor for Malaysian investors. Built with Streamlit + SQLite + Gemini AI.

> **See also:** `proposal.md` (what to improve) · `plan.md` (how to implement it)

---

## ⚠️ Known Bugs (fix before adding features)

| Bug | File | Fix |
|---|---|---|
| `update_snapshot_health()` missing | `database/repository.py` | Add method + `health_score` column to `snapshots` |
| `save_risk_profile()` missing | `database/repository.py` | Create `risk_profiles` table + insert/select methods |
| `sensitivity_analysis()` missing | `analysis/monte_carlo.py` | Add method that loops `run()` over contribution range |
| `run_scenario_comparison()` missing | `analysis/monte_carlo.py` | Add method that runs MC for N labeled scenarios |
| `compare_strategies()` missing | `analysis/backtester.py` | Add method that loops `run()` for each preset strategy |
| `calculate_ptptn_payoff()` missing | `analysis/backtester.py` | Amortization schedule: months, total interest, breakdown |
| `ANTHROPIC_API_KEY` undefined | `ui/pages/settings.py` | Remove — app uses Gemini, not Anthropic |
| 6 pages not in navigation | `app.py` | Wire dashboard, projections, backtesting, ai_chat, risk_profile, settings into sidebar |

Full fix instructions in `plan.md` Sprint 1.

---

## Quick start

```bash
source .venv/bin/activate
streamlit run app.py          # http://localhost:8501
```

First-time setup:
```bash
bash setup.sh
cp .env.example .env          # fill in API keys
```

---

## Project structure

```
FinancialNgai/
├── app.py                    # Entry point — page router + global CSS/theme
├── config.py                 # All constants, API keys, Malaysian finance params
├── mcp_server.py             # MCP server for Claude Desktop integration (stdio transport)
├── requirements.txt
├── setup.sh
├── "Financial System - Sheet32.pdf"  # Source PDF for data import scripts
│
├── ai/                       # AI layer
│   ├── consultant.py         # Gemini orchestrator with tool use
│   ├── ollama_consultant.py  # Local LLM fallback (Ollama)
│   ├── prompts.py            # System prompts
│   └── tools.py              # Gemini function definitions
│
├── analysis/                 # Computation engines
│   ├── health_score.py       # Financial health scoring (0-100 + grade)
│   ├── monte_carlo.py        # Monte Carlo wealth projection
│   └── backtester.py         # Strategy backtesting
│
├── database/
│   └── repository.py         # All SQLite read/write (no ORM)
│
├── models/
│   └── balance_sheet.py      # Pydantic data models + AssetCategory enum
│
├── scrapers/                 # Live data fetchers
│   ├── base_scraper.py
│   ├── bnm_scraper.py        # Bank Negara Malaysia API
│   ├── kwsp_scraper.py       # EPF dividend data
│   ├── asnb_scraper.py       # ASNB fund returns
│   └── market_scraper.py     # General market data
│
├── scripts/                  # One-off utility scripts (not part of the app)
│   ├── cleanup_data.py       # Fix/re-categorise imported PnL records in DB
│   ├── import_pdf_data.py    # Initial PDF-to-DB importer (v1)
│   └── import_pdf_data_clean.py  # Cleaner PDF-to-DB importer (v2, use this)
│
├── ui/
│   ├── export.py             # Shared JSON export/download button helper
│   ├── i18n.py               # English / Chinese language strings
│   ├── components/
│   │   └── charts.py         # Reusable Plotly chart builders
│   └── pages/
│       # ── Active pages (wired in app.py navigation) ──
│       ├── balance_sheet.py  # Asset / liability spreadsheet with multi-month compare
│       ├── pnl.py            # Income & expense tracker (P&L)
│       ├── simulation.py     # AI Industry Monitoring (5-layer pyramid)
│       └── history.py        # Asset trends + Value Investing System
│       # ── Dormant pages (not in current navigation) ──
│       ├── dashboard.py      # Portfolio overview + health score
│       ├── projections.py    # Monte Carlo projections
│       ├── backtesting.py    # Strategy backtesting UI
│       ├── ai_chat.py        # Gemini AI chat interface
│       ├── risk_profile.py   # Risk questionnaire
│       └── settings.py       # App settings
│
└── data/
    ├── financial_ngai.db     # SQLite database (gitignored)
    └── cache/                # Scraper cache (gitignored)
```

---

## Navigation

`app.py` uses a sidebar radio with **4 active pages**:

```python
page = st.radio("Navigate", ["Balance Sheet", "P&L Statement", "Monitoring", "Analysis"])

if page == "Balance Sheet":   balance_sheet.render()
elif page == "P&L Statement": pnl.render()
elif page == "Monitoring":    simulation.render()
elif page == "Analysis":      history.render()
```

The dormant pages (`dashboard.py`, `projections.py`, `backtesting.py`, `ai_chat.py`, `risk_profile.py`, `settings.py`) exist but are **not wired into the sidebar**. To reactivate one, add it to the radio options and the if/elif chain.

---

## Rendering HTML safely

**Critical rule:** Never put blank lines inside `st.markdown(html, unsafe_allow_html=True)` strings. CommonMark terminates an HTML block at the first blank line, causing everything after it to render as raw text.

Use the `_clean()` / `_md()` helpers defined in `simulation.py` as the pattern:

```python
import re

def _clean(html: str) -> str:
    html = re.sub(r"<!--.*?-->", "", html, flags=re.DOTALL)
    return "\n".join(ln for ln in html.splitlines() if ln.strip())

def _md(html: str) -> None:
    st.markdown(_clean(html), unsafe_allow_html=True)
```

---

## JavaScript injection

`st.markdown` scripts are **not executed** by Streamlit's React frontend. Use `st.components.v1.html(js_string, height=0)` and access the real page via `window.parent.document`.

See the background glow cursor effect in `app.py` for the working pattern.

---

## Database

Single SQLite file at `data/financial_ngai.db`. All queries go through `database/repository.py`. No ORM — plain `sqlite3` with `row_factory = sqlite3.Row`.

Key tables: `snapshots`, `asset_entries`, `pnl_snapshots`, `pnl_items`, `market_data_cache`.

---

## Scripts

All utility scripts live in `scripts/`. Run them from the project root:

```bash
python scripts/import_pdf_data_clean.py   # import from PDF (preferred)
python scripts/cleanup_data.py            # fix P&L categorisation
```

Each script adds `sys.path.insert(0, project_root)` automatically, so running from any CWD works.

---

## AI

- **Primary:** Gemini 2.0 Flash (`GEMINI_API_KEY` in `.env`)
- **Fallback:** Ollama local LLM (`ollama_consultant.py`)
- **MCP server:** `mcp_server.py` — exposes DB tools via stdio for Claude Desktop
- Tool use defined in `ai/tools.py`, executed in `ai/consultant.py`

---

## Config

All constants live in `config.py`:
- Malaysian finance: EPF rates, PTPTN rates, emergency fund targets, FIRE multiple
- Asset return parameters + correlation matrix for Monte Carlo
- Historical KWSP / ASNB dividend data (seed)

---

## i18n

`ui/i18n.py` exports `get_text(key)` — reads `st.session_state["language"]` (default `"en"`).
Supported: `"en"` and `"zh"`.

---

## Design system

Global CSS injected in `app.py`:
- Font: SF Pro / -apple-system
- Background: radial gradient (blue → purple), fixed
- Glass cards: `backdrop-filter: blur(22px)`, white with low opacity
- Animations: `fadeInUp` keyframe on all cards and headings
- Cursor: background glow follows mouse (injected via `components.html`)

Monitoring page (`simulation.py`) uses a minimalist style:
- No emojis
- Plotly charts with transparent backgrounds
- 50/50 split layout for layer detail (chart left, data right)
- Multi-line normalised % return chart (ETF + 3 stocks)

---

## Environment variables (.env)

```
GEMINI_API_KEY=
OPENROUTER_API_KEY=
```

---

## Database schema

Single SQLite file at `data/financial_ngai.db`. All access via `database/repository.py` (plain `sqlite3`, no ORM).

| Table | Purpose | Key columns |
|---|---|---|
| `snapshots` | Balance sheet per period | `period` (YYYY-MM), `total_assets`, `total_liabilities`, `health_score` (nullable) |
| `asset_entries` | Individual assets/liabilities | `snapshot_id`, `name`, `category`, `balance`, `is_liability`, `ticker`, `annual_return_pct` |
| `pnl_snapshots` | Monthly P&L summary | `period`, `total_income`, `total_expense`, `net_savings`, `savings_rate` |
| `pnl_items` | P&L line items | `pnl_snapshot_id`, `type` (income/expense), `category`, `amount` |
| `market_data_cache` | Scraper cache | `source`, `period`, `value`, `fetched_at` |
| `ai_conversations` | Chat history | `session_id`, `role`, `content`, `timestamp` |
| `watchlist` | Tickers to monitor | `symbol`, `added_at` |
| `stock_alerts` | Price alerts | `symbol`, `target_price`, `condition`, `active`, `triggered` |
| `risk_profiles` | Risk questionnaire results | `score`, `profile`, `max_equity_pct`, `max_crypto_pct` — **table not yet created** |
| `goals` | Financial goals | `name`, `target_amount`, `deadline` — **not yet implemented** |

---

## Dormant pages — readiness

| Page | Completeness | Blocker |
|---|---|---|
| `dashboard.py` | 70% | Missing `update_snapshot_health()` in repo |
| `risk_profile.py` | 80% | Missing `save_risk_profile()` / `get_latest_risk_profile()` + no `risk_profiles` table |
| `projections.py` | 90% | Missing `sensitivity_analysis()` + `run_scenario_comparison()` in Monte Carlo engine |
| `backtesting.py` | 95% | Missing `compare_strategies()` + `calculate_ptptn_payoff()` in Backtester |
| `ai_chat.py` | 100% | Requires Ollama on localhost:11434; upgrade to Gemini in plan.md |
| `settings.py` | 70% | References undefined `ANTHROPIC_API_KEY` |

All activation steps are in `plan.md` Sprint 1.
