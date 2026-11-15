"use client";

import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
  Legend,
} from "recharts";
import { EquitySeries } from "@/lib/api";
import { fmtTime } from "@/lib/time";

// Anthropic accent palette, cycled across model series.
const COLORS = ["#d97757", "#6a9bcc", "#788c5d", "#141413", "#b0aea5"];

export default function EquityChart({ series }: { series: EquitySeries[] }) {
  // Merge all series onto a shared time axis keyed by ISO timestamp.
  const byTime: Record<string, any> = {};
  series.forEach((s) => {
    s.points.forEach((p) => {
      const key = p.t;
      byTime[key] = byTime[key] || { t: fmtTime(p.t) };
      byTime[key][s.name] = p.equity;
    });
  });
  const data = Object.keys(byTime)
    .sort()
    .map((k) => byTime[k]);

  return (
    <div className="rounded-xl border border-brand-subtle bg-brand-card p-5 shadow-sm">
      <h2 className="text-lg font-semibold mb-4 text-brand-dark">
        📈 Equity Curves
      </h2>
      <ResponsiveContainer width="100%" height={320}>
        <LineChart data={data}>
          <CartesianGrid strokeDasharray="3 3" stroke="#e8e6dc" />
          <XAxis dataKey="t" stroke="#b0aea5" fontSize={11} />
          <YAxis
            stroke="#b0aea5"
            fontSize={11}
            domain={["auto", "auto"]}
            tickFormatter={(v) => `$${(v / 1000).toFixed(0)}k`}
          />
          <Tooltip
            contentStyle={{
              backgroundColor: "#ffffff",
              border: "1px solid #e8e6dc",
              borderRadius: 8,
              color: "#141413",
            }}
            formatter={(v: number) => `$${v.toLocaleString()}`}
          />
          <Legend />
          {series.map((s, i) => {
            const isBenchmark = s.name === "Buy & Hold";
            return (
              <Line
                key={s.model_id}
                type="monotone"
                dataKey={s.name}
                stroke={isBenchmark ? "#141413" : COLORS[i % COLORS.length]}
                strokeDasharray={isBenchmark ? "6 4" : undefined}
                dot={false}
                strokeWidth={2}
                connectNulls
              />
            );
          })}
        </LineChart>
      </ResponsiveContainer>
      {data.length === 0 && (
        <p className="text-center text-brand-mid py-8">
          No equity snapshots yet.
        </p>
      )}
    </div>
  );
}
