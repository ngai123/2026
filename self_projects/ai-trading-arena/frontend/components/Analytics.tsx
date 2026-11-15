"use client";

import { Analytics } from "@/lib/api";

function pct(n: number | null, plus = false) {
  if (n === null || n === undefined) return "—";
  return `${plus && n >= 0 ? "+" : ""}${n.toFixed(2)}%`;
}
function usd(n: number) {
  return `$${n.toFixed(n < 1 ? 4 : 2)}`;
}
function num(n: number) {
  return n.toLocaleString("en-US");
}

const focusColors: Record<string, string> = {
  "on-chain": "bg-brand-blue",
  technical: "bg-brand-orange",
  sentiment: "bg-brand-green",
};

export default function AnalyticsView({ data }: { data: Analytics | null }) {
  const rows = data?.models ?? [];

  return (
    <div className="space-y-6">
      {/* ---- Performance metrics ---- */}
      <div className="rounded-xl border border-brand-subtle bg-brand-card overflow-hidden shadow-sm">
        <div className="px-5 py-4 border-b border-brand-subtle">
          <h2 className="text-lg font-semibold text-brand-dark">
            📊 Performance Metrics
          </h2>
          <p className="text-xs text-brand-mid mt-0.5">
            Risk-adjusted — alpha is return vs the Buy &amp; Hold benchmark
          </p>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="text-brand-muted text-left font-heading">
              <tr className="border-b border-brand-subtle">
                <th className="px-5 py-3 font-medium">Model</th>
                <th className="px-4 py-3 font-medium text-right">Return</th>
                <th className="px-4 py-3 font-medium text-right">Alpha</th>
                <th className="px-4 py-3 font-medium text-right">Sharpe</th>
                <th className="px-4 py-3 font-medium text-right">Max DD</th>
                <th className="px-4 py-3 font-medium text-right">Win&nbsp;rate</th>
                <th className="px-4 py-3 font-medium text-right">Trades</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => {
                const p = r.performance;
                return (
                  <tr
                    key={r.model_id}
                    className="border-b border-brand-subtle/70 hover:bg-brand-light transition-colors"
                  >
                    <td className="px-5 py-3 font-medium text-brand-dark whitespace-nowrap">
                      {r.name}
                      {r.is_benchmark && (
                        <span className="ml-2 px-1.5 py-0.5 rounded text-[10px] uppercase font-heading bg-brand-blue/15 text-brand-blue">
                          benchmark
                        </span>
                      )}
                    </td>
                    <td
                      className={`px-4 py-3 text-right font-mono ${
                        p.total_return_pct >= 0 ? "text-brand-green" : "text-brand-orange"
                      }`}
                    >
                      {pct(p.total_return_pct, true)}
                    </td>
                    <td
                      className={`px-4 py-3 text-right font-mono ${
                        p.alpha_vs_benchmark_pct === null
                          ? "text-brand-mid"
                          : p.alpha_vs_benchmark_pct >= 0
                          ? "text-brand-green"
                          : "text-brand-orange"
                      }`}
                    >
                      {pct(p.alpha_vs_benchmark_pct, true)}
                    </td>
                    <td className="px-4 py-3 text-right font-mono text-brand-muted">
                      {p.sharpe ?? "—"}
                    </td>
                    <td className="px-4 py-3 text-right font-mono text-brand-muted">
                      {pct(p.max_drawdown_pct)}
                    </td>
                    <td className="px-4 py-3 text-right font-mono text-brand-muted">
                      {pct(p.win_rate_pct)}
                    </td>
                    <td className="px-4 py-3 text-right font-mono text-brand-muted">
                      {p.n_trades}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>

      {/* ---- Risk & reliability ---- */}
      <div className="rounded-xl border border-brand-subtle bg-brand-card overflow-hidden shadow-sm">
        <div className="px-5 py-4 border-b border-brand-subtle">
          <h2 className="text-lg font-semibold text-brand-dark">
            🛡️ Risk &amp; Reliability
          </h2>
          <p className="text-xs text-brand-mid mt-0.5">
            Leverage, exposure, liquidations, error rate, and whether confidence predicts P&amp;L
          </p>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="text-brand-muted text-left font-heading">
              <tr className="border-b border-brand-subtle">
                <th className="px-5 py-3 font-medium">Model</th>
                <th className="px-4 py-3 font-medium text-right">Avg lev</th>
                <th className="px-4 py-3 font-medium text-right">Gross exp</th>
                <th className="px-4 py-3 font-medium text-right">Open pos</th>
                <th className="px-4 py-3 font-medium text-right">Unrealized</th>
                <th className="px-4 py-3 font-medium text-right">Liq&apos;d</th>
                <th className="px-4 py-3 font-medium text-right">Err rate</th>
                <th className="px-4 py-3 font-medium text-right">Conf↔PnL</th>
              </tr>
            </thead>
            <tbody>
              {rows.filter((r) => !r.is_benchmark).map((r) => {
                const k = r.risk;
                if (!k) return null;
                return (
                  <tr key={r.model_id} className="border-b border-brand-subtle/70 hover:bg-brand-light transition-colors">
                    <td className="px-5 py-3 font-medium text-brand-dark whitespace-nowrap">{r.name}</td>
                    <td className="px-4 py-3 text-right font-mono text-brand-muted">{k.avg_leverage}×</td>
                    <td className="px-4 py-3 text-right font-mono text-brand-muted">{k.gross_exposure_x}×</td>
                    <td className="px-4 py-3 text-right font-mono text-brand-muted">{k.open_positions}</td>
                    <td className={`px-4 py-3 text-right font-mono ${k.unrealized_pnl >= 0 ? "text-brand-green" : "text-brand-orange"}`}>{k.unrealized_pnl >= 0 ? "+" : ""}{usd(k.unrealized_pnl)}</td>
                    <td className={`px-4 py-3 text-right font-mono ${k.n_liquidations > 0 ? "text-brand-orange" : "text-brand-mid"}`}>{k.n_liquidations}</td>
                    <td className={`px-4 py-3 text-right font-mono ${k.error_rate_pct > 20 ? "text-brand-orange" : "text-brand-muted"}`}>{k.error_rate_pct}%</td>
                    <td className="px-4 py-3 text-right font-mono text-brand-muted" title="Correlation of confidence with realized P&L on closed trades">
                      {k.confidence_pnl_corr === null ? "—" : k.confidence_pnl_corr}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>

      {/* ---- Cost & token usage ---- */}
      <div className="rounded-xl border border-brand-subtle bg-brand-card overflow-hidden shadow-sm">
        <div className="px-5 py-4 border-b border-brand-subtle">
          <h2 className="text-lg font-semibold text-brand-dark">
            💰 Cost &amp; Token Usage
          </h2>
          <p className="text-xs text-brand-mid mt-0.5">
            OpenRouter spend and tokens per model (paid via your API key)
          </p>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="text-brand-muted text-left font-heading">
              <tr className="border-b border-brand-subtle">
                <th className="px-5 py-3 font-medium">Model</th>
                <th className="px-4 py-3 font-medium text-right">Total cost</th>
                <th className="px-4 py-3 font-medium text-right">Calls</th>
                <th className="px-4 py-3 font-medium text-right">Avg / call</th>
                <th className="px-4 py-3 font-medium text-right">Prompt tok</th>
                <th className="px-4 py-3 font-medium text-right">Output tok</th>
                <th className="px-4 py-3 font-medium text-right">Total tok</th>
              </tr>
            </thead>
            <tbody>
              {rows
                .filter((r) => !r.is_benchmark)
                .map((r) => {
                  const u = r.usage;
                  return (
                    <tr
                      key={r.model_id}
                      className="border-b border-brand-subtle/70 hover:bg-brand-light transition-colors"
                    >
                      <td className="px-5 py-3 font-medium text-brand-dark whitespace-nowrap">
                        {r.name}
                      </td>
                      <td className="px-4 py-3 text-right font-mono font-semibold text-brand-dark">
                        {usd(u.total_cost_usd)}
                      </td>
                      <td className="px-4 py-3 text-right font-mono text-brand-muted">
                        {u.n_calls}
                      </td>
                      <td className="px-4 py-3 text-right font-mono text-brand-muted">
                        {usd(u.avg_cost_per_call_usd)}
                      </td>
                      <td className="px-4 py-3 text-right font-mono text-brand-muted">
                        {num(u.prompt_tokens)}
                      </td>
                      <td className="px-4 py-3 text-right font-mono text-brand-muted">
                        {num(u.completion_tokens)}
                      </td>
                      <td className="px-4 py-3 text-right font-mono text-brand-dark">
                        {num(u.total_tokens)}
                      </td>
                    </tr>
                  );
                })}
            </tbody>
          </table>
        </div>
      </div>

      {/* ---- Behavior ---- */}
      <div className="rounded-xl border border-brand-subtle bg-brand-card p-5 shadow-sm">
        <h2 className="text-lg font-semibold text-brand-dark mb-1">
          🧭 Behavior
        </h2>
        <p className="text-xs text-brand-mid mb-4">
          Action bias, conviction (avg allocation), and what each model reasons about
        </p>
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
          {rows
            .filter((r) => !r.is_benchmark)
            .map((r) => {
              const b = r.behavior;
              const total = b.buy + b.sell + b.hold || 1;
              return (
                <div
                  key={r.model_id}
                  className="rounded-lg border border-brand-subtle bg-brand-light/60 p-3"
                >
                  <div className="font-heading font-medium text-brand-dark mb-2">
                    {r.name}
                  </div>
                  {/* buy/sell/hold bar */}
                  <div className="flex h-2 rounded overflow-hidden mb-1">
                    <div className="bg-brand-green" style={{ width: `${(b.buy / total) * 100}%` }} />
                    <div className="bg-brand-orange" style={{ width: `${(b.sell / total) * 100}%` }} />
                    <div className="bg-brand-mid/40" style={{ width: `${(b.hold / total) * 100}%` }} />
                  </div>
                  <div className="text-[11px] text-brand-muted mb-2">
                    {b.buy} buy · {b.sell} sell · {b.hold} hold · conviction{" "}
                    {b.avg_conviction_pct}%
                  </div>
                  <div className="text-[11px] text-brand-mid mb-1">Reasons about:</div>
                  <div className="space-y-1">
                    {Object.entries(b.focus).map(([cat, n]) => (
                      <div key={cat} className="flex items-center gap-2">
                        <span className="w-16 text-[11px] text-brand-muted capitalize">
                          {cat}
                        </span>
                        <div className="flex-1 h-1.5 bg-brand-subtle rounded overflow-hidden">
                          <div
                            className={`h-full ${focusColors[cat] ?? "bg-brand-mid"}`}
                            style={{
                              width: `${total ? (n / total) * 100 : 0}%`,
                            }}
                          />
                        </div>
                        <span className="w-6 text-[11px] text-brand-mid text-right">
                          {n}
                        </span>
                      </div>
                    ))}
                  </div>
                </div>
              );
            })}
        </div>
      </div>
    </div>
  );
}
