"use client";

import { Trade } from "@/lib/api";
import { fmtDateTime, fmtTime } from "@/lib/time";

const actionStyle: Record<string, string> = {
  BUY: "bg-brand-green/15 text-brand-green",
  SELL: "bg-brand-orange/15 text-brand-orange",
  HOLD: "bg-brand-subtle text-brand-muted",
};

const statusStyle: Record<string, string> = {
  executed: "text-brand-green",
  rejected: "text-brand-orange",
  hold: "text-brand-muted",
  error: "text-brand-orange",
};

// Trades within one tick share ~the same timestamp (they run concurrently);
// ticks are spaced minutes apart. Cluster consecutive trades into "rounds"
// whenever the gap between them exceeds this threshold.
const ROUND_GAP_MS = 5 * 60 * 1000;

interface Round {
  key: string;
  label: string;
  trades: Trade[];
}

// `trades` arrives newest-first; group adjacent ones into rounds.
function groupIntoRounds(trades: Trade[]): Round[] {
  const rounds: Round[] = [];
  let current: Trade[] = [];

  const flush = () => {
    if (!current.length) return;
    rounds.push({
      key: `${current[0].id}`,
      label: fmtDateTime(current[0].created_at),
      trades: current,
    });
    current = [];
  };

  for (const t of trades) {
    if (current.length === 0) {
      current.push(t);
      continue;
    }
    const prev = new Date(current[current.length - 1].created_at).getTime();
    const gap = prev - new Date(t.created_at).getTime();
    if (gap > ROUND_GAP_MS) flush();
    current.push(t);
  }
  flush();
  return rounds;
}

function RoundDivider({ label, count }: { label: string; count: number }) {
  return (
    <div className="flex items-center gap-3 pt-1">
      <div className="h-px flex-1 bg-brand-subtle" />
      <span className="font-heading text-[11px] uppercase tracking-wider text-brand-mid whitespace-nowrap">
        {label} · {count} {count === 1 ? "action" : "actions"}
      </span>
      <div className="h-px flex-1 bg-brand-subtle" />
    </div>
  );
}

export default function TradeFeed({ trades }: { trades: Trade[] }) {
  const rounds = groupIntoRounds(trades);

  return (
    <div className="rounded-xl border border-brand-subtle bg-brand-card p-5 shadow-sm">
      <h2 className="text-lg font-semibold mb-4 text-brand-dark">
        🧠 Recent Decisions
      </h2>
      <div className="space-y-3 max-h-[520px] overflow-y-auto pr-1">
        {rounds.map((round) => (
          <div key={round.key} className="space-y-3">
            <RoundDivider label={round.label} count={round.trades.length} />
            {round.trades.map((t) => (
              <div
                key={t.id}
                className="rounded-lg border border-brand-subtle bg-brand-light/60 p-3 text-sm"
              >
                <div className="flex items-center justify-between gap-2">
                  <div className="flex items-center gap-2">
                    <span className="font-heading font-medium text-brand-dark">
                      {t.model_name}
                    </span>
                    <span
                      className={`px-2 py-0.5 rounded text-xs font-semibold ${
                        actionStyle[t.action] ?? actionStyle.HOLD
                      }`}
                    >
                      {t.action} {t.ticker !== "-" ? t.ticker : ""}
                    </span>
                    {t.shares > 0 && (
                      <span className="text-xs text-brand-mid font-mono">
                        {t.shares} @ ${t.price}
                        {t.leverage > 1 && (
                          <span className="text-brand-blue"> {t.leverage}×</span>
                        )}
                      </span>
                    )}
                    {t.confidence > 0 && (
                      <span className="text-xs text-brand-blue">
                        conf {(t.confidence / 100).toFixed(2)}
                      </span>
                    )}
                  </div>
                  <span className="text-xs text-brand-mid">
                    {fmtTime(t.created_at)}
                  </span>
                </div>
                <p className="text-brand-dark/80 mt-2 leading-snug">
                  {t.reasoning_zh || t.reasoning}
                </p>
                {(t.take_profit > 0 || t.stop_loss > 0) && (
                  <div className="mt-1 text-[11px] font-mono text-brand-mid">
                    {t.take_profit > 0 && (
                      <span className="text-brand-green">TP ${t.take_profit}</span>
                    )}
                    {t.take_profit > 0 && t.stop_loss > 0 && " · "}
                    {t.stop_loss > 0 && (
                      <span className="text-brand-orange">SL ${t.stop_loss}</span>
                    )}
                  </div>
                )}
                {(t.thinking || t.thinking_zh || t.raw_response) && (
                  <details className="mt-2 group">
                    <summary className="cursor-pointer text-xs font-heading text-brand-blue hover:underline list-none">
                      ▸ 完整思考过程 (full thought process)
                    </summary>
                    {(t.thinking_zh || t.thinking) && (
                      <div className="mt-2">
                        <div className="text-[10px] uppercase tracking-wide text-brand-mid font-heading mb-1">
                          思考 Thinking{t.thinking_zh ? " (中文)" : ""}
                        </div>
                        <pre className="whitespace-pre-wrap break-words text-[11px] leading-relaxed text-brand-dark/75 bg-brand-light rounded-md p-2 max-h-60 overflow-y-auto">
                          {t.thinking_zh || t.thinking}
                        </pre>
                      </div>
                    )}
                    {t.raw_response && (
                      <div className="mt-2">
                        <div className="text-[10px] uppercase tracking-wide text-brand-mid font-heading mb-1">
                          Raw output (English)
                        </div>
                        <pre className="whitespace-pre-wrap break-words text-[11px] leading-relaxed text-brand-dark/75 bg-brand-light rounded-md p-2 max-h-60 overflow-y-auto font-mono">
                          {t.raw_response}
                        </pre>
                      </div>
                    )}
                  </details>
                )}
                <div className="mt-2 flex items-center justify-between text-xs">
                  <span className={statusStyle[t.status] ?? "text-brand-muted"}>
                    {t.status}
                    {t.note ? ` — ${t.note}` : ""}
                  </span>
                  {t.status === "executed" && (
                    <span className="font-mono text-brand-mid">
                      {t.shares} @ ${t.price}
                    </span>
                  )}
                </div>
              </div>
            ))}
          </div>
        ))}
        {trades.length === 0 && (
          <p className="text-center text-brand-mid py-8">No trades yet.</p>
        )}
      </div>
    </div>
  );
}
