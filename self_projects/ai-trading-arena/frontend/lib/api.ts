// Typed client for the FastAPI backend.

const BASE = process.env.NEXT_PUBLIC_API_BASE || "http://localhost:8000";

export interface LeaderboardEntry {
  model_id: number;
  name: string;
  slug: string;
  cash: number;
  positions_value: number;
  equity: number;
  starting_cash: number;
  total_return_pct: number;
  alpha_vs_benchmark_pct: number;
  is_benchmark: boolean;
  rank: number;
  memory: string;
}

export interface Trade {
  id: number;
  model_id: number;
  model_name: string;
  ticker: string;
  action: string;
  allocation_pct: number;
  confidence: number;
  shares: number;
  price: number;
  leverage: number;
  take_profit: number;
  stop_loss: number;
  reasoning: string;
  reasoning_zh: string;
  thinking_zh: string;
  raw_response: string;
  thinking: string;
  status: string;
  note: string;
  created_at: string;
}

export interface EquityPoint {
  t: string;
  equity: number;
}

export interface EquitySeries {
  model_id: number;
  name: string;
  points: EquityPoint[];
}

export interface HoldingCell {
  shares: number;
  value: number;
  side: string;
  leverage: number;
  notional: number;
  unrealized_pnl: number;
  liquidation_price: number;
}

export interface HoldingsRow {
  model_id: number;
  name: string;
  cash: number;
  equity: number;
  cells: Record<string, HoldingCell>;
}

export interface Holdings {
  tickers: string[];
  rows: HoldingsRow[];
}

export interface ModelAnalytics {
  model_id: number;
  name: string;
  is_benchmark: boolean;
  performance: {
    total_return_pct: number;
    sharpe: number | null;
    max_drawdown_pct: number;
    volatility_pct: number | null;
    alpha_vs_benchmark_pct: number | null;
    n_trades: number;
    win_rate_pct: number | null;
    realized_pnl: number;
  };
  usage: {
    prompt_tokens: number;
    completion_tokens: number;
    total_tokens: number;
    total_cost_usd: number;
    n_calls: number;
    avg_cost_per_call_usd: number;
  };
  behavior: {
    buy: number;
    sell: number;
    hold: number;
    avg_conviction_pct: number;
    focus: Record<string, number>;
  };
  risk: {
    avg_leverage: number;
    n_liquidations: number;
    error_rate_pct: number;
    confidence_pnl_corr: number | null;
    gross_exposure_x: number;
    unrealized_pnl: number;
    open_positions: number;
  };
}

export interface Analytics {
  models: ModelAnalytics[];
}

export interface Status {
  market_open: boolean;
  allow_after_hours: boolean;
  tickers: string[];
  loop_interval_minutes: number;
  last_run: string | null;
  next_run: string | null;
  today_cost_usd: number;
  total_cost_usd: number;
  daily_cost_cap_usd: number;
}

async function get<T>(path: string): Promise<T> {
  const res = await fetch(`${BASE}${path}`, { cache: "no-store" });
  if (!res.ok) throw new Error(`${path} -> ${res.status}`);
  return res.json();
}

export const api = {
  leaderboard: () => get<LeaderboardEntry[]>("/api/leaderboard"),
  trades: (limit = 50) => get<Trade[]>(`/api/trades?limit=${limit}`),
  modelTrades: (modelId: number, limit = 1000) =>
    get<Trade[]>(`/api/trades?model_id=${modelId}&limit=${limit}`),
  equityCurves: () => get<EquitySeries[]>("/api/equity-curves"),
  positions: () => get<Holdings>("/api/positions"),
  analytics: () => get<Analytics>("/api/analytics"),
  status: () => get<Status>("/api/status"),
  runNow: async () => {
    const res = await fetch(`${BASE}/api/run-now`, { method: "POST" });
    return res.json();
  },
};
