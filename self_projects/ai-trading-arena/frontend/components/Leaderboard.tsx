"use client";

import { LeaderboardEntry } from "@/lib/api";

const medal = ["🥇", "🥈", "🥉"];

function money(n: number) {
  return n.toLocaleString("en-US", { style: "currency", currency: "USD" });
}

export default function Leaderboard({ rows }: { rows: LeaderboardEntry[] }) {
  return (
    <div className="rounded-xl border border-brand-subtle bg-brand-card overflow-hidden shadow-sm">
      <div className="px-5 py-4 border-b border-brand-subtle">
        <h2 className="text-lg font-semibold text-brand-dark">🏆 Leaderboard</h2>
        <p className="text-xs text-brand-mid mt-0.5">
          Ranked by alpha — excess return over Buy &amp; Hold. Positive = beating the market.
        </p>
      </div>
      <table className="w-full text-sm">
        <thead className="text-brand-muted text-left font-heading">
          <tr className="border-b border-brand-subtle">
            <th className="px-5 py-3 font-medium">Rank</th>
            <th className="px-5 py-3 font-medium">Model</th>
            <th className="px-5 py-3 font-medium text-right">Alpha vs B&amp;H</th>
            <th className="px-5 py-3 font-medium text-right">Return</th>
            <th className="px-5 py-3 font-medium text-right">Equity</th>
            <th className="px-5 py-3 font-medium text-right">Cash</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => {
            const up = r.total_return_pct >= 0;
            return (
              <tr
                key={r.model_id}
                className="border-b border-brand-subtle/70 hover:bg-brand-light transition-colors"
              >
                <td className="px-5 py-3">
                  <span className="text-lg">{medal[r.rank - 1] ?? r.rank}</span>
                </td>
                <td className="px-5 py-3">
                  <div className="font-medium text-brand-dark flex items-center gap-2">
                    {r.name}
                    {r.slug.startsWith("strategy/") && (
                      <span className="px-1.5 py-0.5 rounded text-[10px] uppercase tracking-wide font-heading bg-brand-blue/15 text-brand-blue">
                        benchmark
                      </span>
                    )}
                  </div>
                  <div className="text-xs text-brand-mid">{r.slug}</div>
                </td>
                <td
                  className={`px-5 py-3 text-right font-mono font-semibold ${
                    r.is_benchmark
                      ? "text-brand-mid"
                      : r.alpha_vs_benchmark_pct > 0
                      ? "text-brand-green"
                      : "text-brand-orange"
                  }`}
                >
                  {r.is_benchmark
                    ? "—"
                    : `${r.alpha_vs_benchmark_pct >= 0 ? "+" : ""}${r.alpha_vs_benchmark_pct.toFixed(2)}%`}
                </td>
                <td
                  className={`px-5 py-3 text-right font-mono ${
                    up ? "text-brand-green/80" : "text-brand-orange/80"
                  }`}
                >
                  {up ? "+" : ""}
                  {r.total_return_pct.toFixed(2)}%
                </td>
                <td className="px-5 py-3 text-right font-mono text-brand-dark">
                  {money(r.equity)}
                </td>
                <td className="px-5 py-3 text-right font-mono text-brand-muted">
                  {money(r.cash)}
                </td>
              </tr>
            );
          })}
          {rows.length === 0 && (
            <tr>
              <td colSpan={6} className="px-5 py-8 text-center text-brand-mid">
                No data yet — start the backend and run a tick.
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}
