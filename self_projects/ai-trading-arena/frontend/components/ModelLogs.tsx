"use client";

import { useEffect, useState } from "react";
import { api, LeaderboardEntry, Trade } from "@/lib/api";
import { fmtDateTime, fmtFull } from "@/lib/time";

function esc(s: string): string {
  return (s || "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

// Build a standalone, readable HTML page of a model's full thought history.
function buildThoughtsHtml(name: string, trades: Trade[]): string {
  const ordered = [...trades].reverse(); // oldest first
  const blocks = ordered
    .map((t) => {
      const when = fmtFull(t.created_at);
      const size = t.shares > 0 ? `${t.shares} @ ${t.price}` : "";
      const lev = t.leverage > 1 ? ` ${t.leverage}×` : "";
      const head = `${when} — ${t.action}${
        t.ticker !== "-" ? " " + t.ticker : ""
      } ${size}${lev} [${t.status}]`;
      const decisionTxt = t.reasoning_zh || t.reasoning;
      const decision = decisionTxt
        ? `<p><b>决策 Decision:</b> ${esc(decisionTxt)}</p>`
        : "";
      const thinkTxt = t.thinking_zh || t.thinking;
      const thinking = thinkTxt
        ? `<details open><summary>思考 Thinking</summary><pre>${esc(
            thinkTxt
          )}</pre></details>`
        : "";
      const raw = t.raw_response
        ? `<details><summary>Raw output (English)</summary><pre>${esc(
            t.raw_response
          )}</pre></details>`
        : "";
      return `<section><h3>${esc(head)}</h3>${decision}${thinking}${raw}</section>`;
    })
    .join("\n");

  return `<!doctype html><html><head><meta charset="utf-8">
<title>${esc(name)} — thought history</title>
<style>
  body{font-family:Georgia,serif;background:#faf9f5;color:#141413;max-width:860px;margin:40px auto;padding:0 20px;line-height:1.6}
  h1{font-family:'Poppins',Arial,sans-serif}
  h3{font-family:'Poppins',Arial,sans-serif;font-size:14px;color:#d97757;margin:28px 0 8px;border-top:1px solid #e8e6dc;padding-top:16px}
  pre{white-space:pre-wrap;word-break:break-word;background:#fff;border:1px solid #e8e6dc;border-radius:8px;padding:12px;font-size:12px;font-family:ui-monospace,Menlo,monospace}
  summary{cursor:pointer;font-family:'Poppins',Arial,sans-serif;font-size:12px;color:#6a9bcc;text-transform:uppercase;letter-spacing:1px}
</style></head><body>
<h1>${esc(name)} — full thought history</h1>
<p>${ordered.length} decisions · generated ${fmtFull(new Date().toISOString())} (MYT)</p>
${blocks}
</body></html>`;
}

function downloadBlob(filename: string, content: string, type: string) {
  const url = URL.createObjectURL(new Blob([content], { type }));
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

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

// Per-model action log — actions only, no reasoning text.
export default function ModelLogs({
  models,
  trades,
}: {
  models: LeaderboardEntry[];
  trades: Trade[];
}) {
  const [selected, setSelected] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);

  // Default to the top-ranked model once data arrives.
  useEffect(() => {
    if (selected === null && models.length) setSelected(models[0].model_id);
  }, [models, selected]);

  const rows = trades.filter((t) => t.model_id === selected);
  const selectedName =
    models.find((m) => m.model_id === selected)?.name ?? "model";

  // Fetch the model's FULL history (not just the recent window in props).
  const exportThoughts = async (mode: "view" | "json") => {
    if (selected === null) return;
    setBusy(true);
    // Open the tab SYNCHRONOUSLY (before any await) so it isn't popup-blocked.
    const win = mode === "view" ? window.open("", "_blank") : null;
    if (win) {
      win.document.write(
        "<!doctype html><meta charset='utf-8'><title>Loading thoughts…</title>" +
          "<body style='font-family:Georgia,serif;padding:40px;color:#141413'>" +
          "Loading full thought history…</body>"
      );
    }
    try {
      const all = await api.modelTrades(selected);
      const safe = selectedName.replace(/[^a-z0-9]+/gi, "_");
      if (mode === "json") {
        downloadBlob(
          `${safe}_thoughts.json`,
          JSON.stringify(all, null, 2),
          "application/json"
        );
      } else {
        const html = buildThoughtsHtml(selectedName, all);
        if (win) {
          win.document.open();
          win.document.write(html);
          win.document.close();
        } else {
          // Popup blocked — fall back to downloading the HTML.
          downloadBlob(`${safe}_thoughts.html`, html, "text/html");
        }
      }
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="rounded-xl border border-brand-subtle bg-brand-card p-5 shadow-sm">
      <div className="flex items-center justify-between gap-3 mb-4 flex-wrap">
        <h2 className="text-lg font-semibold text-brand-dark">
          📜 Trade Log by Model
        </h2>
        <div className="flex items-center gap-2">
          <button
            onClick={() => exportThoughts("view")}
            disabled={busy || selected === null}
            className="px-3 py-1.5 rounded-lg font-heading text-sm bg-brand-blue/15 text-brand-blue hover:bg-brand-blue/25 disabled:opacity-50 transition-colors"
          >
            🧠 View all thoughts
          </button>
          <button
            onClick={() => exportThoughts("json")}
            disabled={busy || selected === null}
            className="px-3 py-1.5 rounded-lg font-heading text-sm border border-brand-subtle text-brand-muted hover:text-brand-dark disabled:opacity-50 transition-colors"
          >
            ⤓ .json
          </button>
        </div>
      </div>

      {/* Model selector */}
      <div className="flex flex-wrap gap-2 mb-4">
        {models.map((m) => (
          <button
            key={m.model_id}
            onClick={() => setSelected(m.model_id)}
            className={`px-3 py-1.5 rounded-lg font-heading text-sm transition-colors ${
              selected === m.model_id
                ? "bg-brand-dark text-brand-light"
                : "border border-brand-subtle text-brand-muted hover:text-brand-dark"
            }`}
          >
            {m.name}
          </button>
        ))}
      </div>

      {/* The model's own evolving memory (notes it writes to its future self) */}
      {(() => {
        const mem = models.find((m) => m.model_id === selected)?.memory;
        return mem ? (
          <div className="mb-4 rounded-lg border border-brand-blue/30 bg-brand-blue/5 p-3">
            <div className="text-[10px] uppercase tracking-wide text-brand-blue font-heading mb-1">
              🧠 {selectedName}&apos;s memory (notes to itself)
            </div>
            <p className="text-sm text-brand-dark/80 leading-snug">{mem}</p>
          </div>
        ) : null;
      })()}

      {/* Action table */}
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="text-brand-muted text-left font-heading">
            <tr className="border-b border-brand-subtle">
              <th className="py-2 pr-3 font-medium">Time</th>
              <th className="py-2 pr-3 font-medium">Action</th>
              <th className="py-2 pr-3 font-medium text-right">Lev</th>
              <th className="py-2 pr-3 font-medium text-right">Conf</th>
              <th className="py-2 pr-3 font-medium text-right">Qty</th>
              <th className="py-2 pr-3 font-medium text-right">Price</th>
              <th className="py-2 font-medium">Status</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((t) => (
              <tr key={t.id} className="border-b border-brand-subtle/60">
                <td className="py-2 pr-3 text-brand-mid whitespace-nowrap">
                  {fmtDateTime(t.created_at)}
                </td>
                <td className="py-2 pr-3">
                  <span
                    className={`px-2 py-0.5 rounded text-xs font-semibold ${
                      actionStyle[t.action] ?? actionStyle.HOLD
                    }`}
                  >
                    {t.action} {t.ticker !== "-" ? t.ticker : ""}
                  </span>
                </td>
                <td className="py-2 pr-3 text-right font-mono text-brand-blue">
                  {t.leverage > 1 ? `${t.leverage}×` : "—"}
                </td>
                <td className="py-2 pr-3 text-right font-mono text-brand-blue">
                  {t.confidence > 0 ? (t.confidence / 100).toFixed(2) : "—"}
                </td>
                <td className="py-2 pr-3 text-right font-mono text-brand-muted">
                  {t.shares > 0 ? t.shares : "—"}
                </td>
                <td className="py-2 pr-3 text-right font-mono text-brand-muted">
                  {t.price > 0 ? `$${t.price}` : "—"}
                </td>
                <td
                  className={`py-2 text-xs ${
                    statusStyle[t.status] ?? "text-brand-muted"
                  }`}
                >
                  {t.status}
                </td>
              </tr>
            ))}
            {rows.length === 0 && (
              <tr>
                <td colSpan={7} className="py-8 text-center text-brand-mid">
                  No actions logged for this model yet.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
