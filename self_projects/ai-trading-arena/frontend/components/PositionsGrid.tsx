"use client";

import { Holdings } from "@/lib/api";

function fmtShares(n: number) {
  if (n === 0) return "—";
  // Crypto holdings can be fractional; stocks too (we allow fractional shares).
  return n >= 1 ? n.toLocaleString("en-US", { maximumFractionDigits: 2 }) : n.toPrecision(3);
}

function money(n: number) {
  return n.toLocaleString("en-US", { style: "currency", currency: "USD" });
}

export default function PositionsGrid({ data }: { data: Holdings | null }) {
  const tickers = data?.tickers ?? [];
  const rows = data?.rows ?? [];

  return (
    <div className="rounded-xl border border-brand-subtle bg-brand-card overflow-hidden shadow-sm">
      <div className="px-5 py-4 border-b border-brand-subtle">
        <h2 className="text-lg font-semibold text-brand-dark">
          📦 Live Positions
        </h2>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="text-brand-muted text-left font-heading">
            <tr className="border-b border-brand-subtle">
              <th className="px-5 py-3 font-medium">Model</th>
              {tickers.map((tk) => (
                <th key={tk} className="px-4 py-3 font-medium text-right">
                  {tk}
                </th>
              ))}
              <th className="px-5 py-3 font-medium text-right">Cash</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr
                key={r.model_id}
                className="border-b border-brand-subtle/70 hover:bg-brand-light transition-colors"
              >
                <td className="px-5 py-3 font-medium text-brand-dark whitespace-nowrap">
                  {r.name}
                </td>
                {tickers.map((tk) => {
                  const cell = r.cells[tk];
                  const shares = cell?.shares ?? 0;
                  const has = shares !== 0;
                  if (!has) {
                    return (
                      <td key={tk} className="px-4 py-3 text-right align-top text-brand-mid font-mono">
                        —
                      </td>
                    );
                  }
                  const isShort = shares < 0;
                  const upnl = cell.unrealized_pnl ?? 0;
                  return (
                    <td key={tk} className="px-4 py-3 text-right align-top whitespace-nowrap">
                      <div className="font-mono font-medium">
                        <span className={isShort ? "text-brand-orange" : "text-brand-green"}>
                          {cell.side}
                        </span>{" "}
                        <span className="text-brand-dark">{fmtShares(Math.abs(shares))}</span>
                        {cell.leverage > 1 && (
                          <span className="text-brand-blue"> {cell.leverage}×</span>
                        )}
                      </div>
                      <div className="text-[11px] text-brand-mid font-mono">
                        {money(cell.notional)} notional
                      </div>
                      <div
                        className={`text-[11px] font-mono ${
                          upnl >= 0 ? "text-brand-green" : "text-brand-orange"
                        }`}
                      >
                        {upnl >= 0 ? "+" : ""}
                        {money(upnl)} uPnL
                      </div>
                      {cell.liquidation_price > 0 && (
                        <div className="text-[10px] text-brand-mid/80 font-mono">
                          liq {money(cell.liquidation_price)}
                        </div>
                      )}
                    </td>
                  );
                })}
                <td className="px-5 py-3 text-right font-mono text-brand-muted whitespace-nowrap">
                  {money(r.cash)}
                </td>
              </tr>
            ))}
            {rows.length === 0 && (
              <tr>
                <td
                  colSpan={tickers.length + 2}
                  className="px-5 py-8 text-center text-brand-mid"
                >
                  No positions yet.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
