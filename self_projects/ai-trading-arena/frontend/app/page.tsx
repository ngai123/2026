"use client";

import { useCallback, useEffect, useState } from "react";
import {
  Analytics,
  api,
  EquitySeries,
  Holdings,
  LeaderboardEntry,
  Status,
  Trade,
} from "@/lib/api";
import Leaderboard from "@/components/Leaderboard";
import EquityChart from "@/components/EquityChart";
import TradeFeed from "@/components/TradeFeed";
import PositionsGrid from "@/components/PositionsGrid";
import ModelLogs from "@/components/ModelLogs";
import AnalyticsView from "@/components/Analytics";

const REFRESH_MS = 30_000;

export default function Home() {
  const [rows, setRows] = useState<LeaderboardEntry[]>([]);
  const [trades, setTrades] = useState<Trade[]>([]);
  const [curves, setCurves] = useState<EquitySeries[]>([]);
  const [holdings, setHoldings] = useState<Holdings | null>(null);
  const [analytics, setAnalytics] = useState<Analytics | null>(null);
  const [status, setStatus] = useState<Status | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [running, setRunning] = useState(false);

  const load = useCallback(async () => {
    try {
      const [lb, tr, eq, ho, an, st] = await Promise.all([
        api.leaderboard(),
        api.trades(150),
        api.equityCurves(),
        api.positions(),
        api.analytics(),
        api.status(),
      ]);
      setRows(lb);
      setTrades(tr);
      setCurves(eq);
      setHoldings(ho);
      setAnalytics(an);
      setStatus(st);
      setError(null);
    } catch (e: any) {
      setError(e.message ?? "failed to load — is the backend running?");
    }
  }, []);

  useEffect(() => {
    load();
    const id = setInterval(load, REFRESH_MS);
    return () => clearInterval(id);
  }, [load]);

  const triggerRun = async () => {
    setRunning(true);
    try {
      await api.runNow();
      await load();
    } finally {
      setRunning(false);
    }
  };

  return (
    <main className="max-w-7xl mx-auto px-6 py-8">
      <header className="flex flex-wrap items-center justify-between gap-4 mb-8">
        <div className="flex items-center gap-3">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img src="/logo-mark.svg" alt="AI Trading Arena logo" className="h-11 w-11" />
          <div>
            <h1 className="text-3xl font-semibold tracking-tight text-brand-dark">
              AI Trading Arena
            </h1>
            <p className="text-brand-muted mt-1">
              Five models. Same data. One paper-trading leaderboard.
            </p>
          </div>
        </div>
        <div className="flex items-center gap-4">
          {status && (
            <div className="text-right text-xs text-brand-muted">
              <div>
                Market:{" "}
                <span
                  className={`font-semibold ${
                    status.market_open ? "text-brand-green" : "text-brand-orange"
                  }`}
                >
                  {status.market_open ? "OPEN" : "CLOSED"}
                </span>
              </div>
              <div>
                {status.tickers.join(" · ")}
                {status.timezone ? ` · ${status.timezone.split("/").pop()} time` : ""}
              </div>
              <div className="text-brand-dark font-medium mt-0.5">
                Spend: ${status.total_cost_usd.toFixed(4)}
                <span className="text-brand-mid">
                  {" "}
                  (today ${status.today_cost_usd.toFixed(4)}
                  {status.daily_cost_cap_usd > 0
                    ? ` / $${status.daily_cost_cap_usd.toFixed(2)} cap`
                    : ""}
                  )
                </span>
              </div>
            </div>
          )}
          <button
            onClick={triggerRun}
            disabled={running}
            className="px-4 py-2 rounded-lg bg-brand-orange hover:bg-brand-orange/90 text-brand-light font-heading font-medium text-sm disabled:opacity-50 transition-colors"
          >
            {running ? "Running…" : "Run tick now"}
          </button>
        </div>
      </header>

      {error && (
        <div className="mb-6 rounded-lg border border-brand-orange/40 bg-brand-orange/10 px-4 py-3 text-brand-dark text-sm">
          {error}
        </div>
      )}

      <div className="grid grid-cols-1 gap-6">
        <Leaderboard rows={rows} />

        <AnalyticsView data={analytics} />

        <PositionsGrid data={holdings} />

        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          <EquityChart series={curves} />
          <TradeFeed trades={trades} />
        </div>

        <ModelLogs models={rows} trades={trades} />
      </div>

      <footer className="mt-10 text-center text-xs text-brand-mid">
        Paper trading only · data via yfinance · inference via OpenRouter
      </footer>
    </main>
  );
}
