# FinancialNgai — Domain Context

Glossary, invariants, and boundaries for FinancialNgai. Read this before editing unfamiliar modules — many terms here are Malaysia-specific or overloaded across projects.

## Glossary

- **KWSP / EPF** — Kumpulan Wang Simpanan Pekerja (Employee Provident Fund), Malaysia's mandatory retirement savings. Employees contribute 11%, employers 13%. Asset category key: `KWSP_EPF`.
- **ASNB** — Amanah Saham Nasional Berhad. Malaysian government-backed unit trusts. Two main products: ASNB Ria (conservative), ASNB Mutual Fund (growth).
- **BNM** — Bank Negara Malaysia (central bank). APIs provide OPR (Overnight Policy Rate), base lending rates, USD/MYR rates. Requires a specific `Accept` header.
- **PTPTN** — Government higher-education loan scheme. Standard repayment 3% p.a.; income-contingent 1% p.a.
- **Health Score** — Composite 0–100 wellness metric (Cemerlang / Baik / Sederhana / Perlu Perhatian) from 7 weighted components: emergency fund, debt ratio, savings rate, diversification, retirement, investment, liquidity. Stored in `snapshots.health_score`.
- **Monte Carlo Projection** — Stochastic wealth sim. 10,000 correlated trials across asset classes over N years. Returns percentile paths (p5/p25/p50/p75/p95) and milestone probabilities (FIRE, doubling).
- **Snapshot** — A single balance-sheet save tagged by `period` (YYYY-MM). Contains totals + linked asset entries.
- **Orchestrator** — `FinancialConsultant` in `ai/consultant.py`. Gemini agent that dispatches user requests to analysis engines via tool use.
- **Repository** — `database/repository.py`. Singleton wrapping `sqlite3` (no ORM, `row_factory=sqlite3.Row`). All DB access goes through it.
- **Asset Key** — Standardised id (`KWSP_EPF`, `ASNB_RIA`, `MOOMOO_STOCKS`, `LUNO_CRYPTO`, …) mapping to return params in `config/seed_data.py`. Unknown keys default to 7% mean / 15% std.
- **Preset Strategy** — Named allocation template (e.g. "Conservative (EPF + FD)") for backtesting. Weights must sum to 1.0 and use valid asset keys.

## Invariants

1. **Monetary values are floats in MYR**, not cents. `AssetEntry.balance` is `float`, `ge=0`. No fixed-point storage.
2. **`total_assets` / `total_liabilities` are computed sums, written atomically with the snapshot.** Never edit directly — recalculate from asset entries inside the same transaction.
3. **`period` is `YYYY-MM` (7 chars)**, derived from `created_at`. Validated on insert; primary sort key for time series.
4. **Snapshot asset entries are immutable after insert.** Updates = new snapshot with a new period; old snapshots stay as audit trail.
5. **Scraper seed data is fallback only.** Live API calls try first; on error, return seeds from `config/seed_data.py`. No merge logic.
6. **Risk profiles inform, don't enforce.** `RISK_PROFILE_PARAMS` shape scoring and recommendations but the system accepts portfolios outside these bounds.

## Boundaries

**Inside:** balance-sheet & P&L storage (SQLite), time-series tracking, Monte Carlo projections, health scoring, strategy backtesting against KWSP/ASNB seeds, Gemini tool-use orchestration.

**Live data sources:** BNM API, KWSP scraper, ASNB scraper, generic market scraper. Cached in `market_data_cache`.

**External surface:** `mcp_server.py` exposes a read-only subset (portfolio fetch, projection, KWSP/BNM history, health score, backtest) for Claude Desktop via stdio. Full Gemini chatbot is in-app only.

**Out of scope:** real-time trading, account linking, credential storage, tax filing, live alerts, broker integrations. This is a personal advisor, not a fintech platform.
