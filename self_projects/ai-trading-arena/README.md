# ⚔️ Multi-Agent AI Trading Arena

Six AI models (via OpenRouter) paper-trade the same crypto market against each
other and a passive Buy & Hold benchmark, 24/7. Inspired by nof1.ai.

Each model sees identical, rich context — OHLCV, precomputed technical signals,
BTC on-chain fundamentals, Fear & Greed sentiment, and its own track record —
and returns a JSON decision. The harness captures every model's full reasoning,
token usage and cost.

```
ai-trading-arena/
├── backend/                  FastAPI + APScheduler trading engine
│   └── app/
│       ├── config.py         agents + tunables (models, costs, output budget, tz)
│       ├── database.py       SQLAlchemy engine/session
│       ├── models.py         Model / Portfolio / Position / TradeLog / EquitySnapshot / OnChainSnapshot
│       ├── schemas.py        Pydantic API + strict LLM decision schema
│       ├── market_hours.py   crypto = 24/7, else NYSE session
│       ├── data_provider.py  yfinance OHLCV + prices + intraday arrays
│       ├── indicators.py     pure-function technical indicators
│       ├── onchain_provider.py   free BTC on-chain (blockchain.com/mempool.space)
│       ├── sentiment_provider.py Fear & Greed index (alternative.me)
│       ├── analytics.py      Sharpe / drawdown / alpha / usage / behavior
│       ├── llm_client.py     OpenRouter fan-out, retries + JSON repair, usage
│       ├── engine.py         context build + paper execution + loop tick
│       ├── seed.py           create agents/portfolios
│       └── main.py           REST endpoints + scheduler
├── alembic/                  schema migrations (additive, never wipes data)
├── deploy/                   launchd plist for 24/7 running
└── frontend/                 Next.js + Tailwind + Recharts dashboard
```

## Backend

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env        # add your OPENROUTER_API_KEY
python -m app.seed          # create the agents + portfolios
alembic stamp head          # mark schema current (fresh DB)
uvicorn app.main:app --reload --port 8000
```

The scheduler fires a trade tick on startup, then every `LOOP_INTERVAL_MINUTES`,
plus a free mark-to-market every 2 min so equity curves track live prices. With
a crypto-only universe it runs 24/7. Force a tick: `curl -X POST localhost:8000/api/run-now`.
For durable 24/7 running, see [deploy/README.md](deploy/README.md).

### Key endpoints
| Endpoint | Purpose |
|---|---|
| `GET /api/leaderboard` | ranked models by equity |
| `GET /api/portfolio/{id}` | one model's cash + positions |
| `GET /api/trades?limit=50` | recent decisions + reasoning |
| `GET /api/equity-curves` | equity snapshots for charts |
| `GET /api/status` | market/loop state |
| `POST /api/run-now` | trigger a tick manually |

## Frontend

```bash
cd frontend
npm install
cp .env.local.example .env.local   # point NEXT_PUBLIC_API_BASE at the backend
npm run dev                         # http://localhost:3000
```

## Data persistence & migrations

All state lives in `arena.db` (SQLite) and persists across restarts — Models,
Portfolios, Positions, TradeLogs (incl. full thinking/raw output), EquitySnapshots
and OnChainSnapshots all accumulate.

Schema changes are handled by **Alembic** so updates never wipe data:

```bash
# after editing app/models.py
.venv/bin/alembic revision --autogenerate -m "describe change"
.venv/bin/alembic upgrade head      # applies additively, keeps existing rows
```

Fresh install: `python -m app.seed` then `.venv/bin/alembic stamp head`.

## On-chain data (BTC)

Each tick also feeds the models a BTC on-chain block (free, no API key) from
blockchain.com + mempool.space — hash rate, active addresses, 24h tx count &
volume, mempool congestion and fees ([onchain_provider.py](backend/app/onchain_provider.py)).
It's best-effort: if a source is unreachable the block is omitted and the models
still get OHLCV. Snapshots are stored in `onchain_snapshots` for history.

## Notes
- **Paper only.** No broker, no real orders. All P&L is simulated in SQLite.
- **Robust parsing.** Models often return prose/markdown around JSON;
  `llm_client.parse_decision` strips fences and extracts the first balanced
  object before schema-validating. Failures are logged as `error` trades.
- **Swap competitors** by editing `AGENTS` in `backend/app/config.py`
  (then re-run `python -m app.seed`).
