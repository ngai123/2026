#!/usr/bin/env node
/**
 * AI Trading Arena — MCP server.
 *
 * Exposes the arena (a Python/FastAPI backend) as MCP tools so any MCP client
 * (Claude Desktop, Claude Code, etc.) can inspect and drive it conversationally:
 * leaderboard by alpha, holdings, each model's reasoning/memory, analytics, and
 * triggering a trading tick.
 *
 * It's a thin client over the backend's REST API (default http://localhost:8000,
 * override with ARENA_API_BASE). The backend must be running.
 */
import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import { z } from "zod";

const BASE = process.env.ARENA_API_BASE ?? "http://localhost:8000";

async function apiGet(path: string): Promise<unknown> {
  const res = await fetch(`${BASE}${path}`);
  if (!res.ok) {
    throw new Error(
      `GET ${path} failed: ${res.status} ${res.statusText}. Is the arena backend running at ${BASE}?`,
    );
  }
  return res.json();
}

async function apiPost(path: string): Promise<unknown> {
  const res = await fetch(`${BASE}${path}`, { method: "POST" });
  if (!res.ok) {
    throw new Error(`POST ${path} failed: ${res.status} ${res.statusText}.`);
  }
  return res.json();
}

// Wrap a result as an MCP tool response (human-readable text + structured data).
// structuredContent must be an object, so arrays are wrapped as { items: [...] }.
function ok(data: unknown) {
  const structured = Array.isArray(data) ? { items: data } : (data as Record<string, unknown>);
  return {
    content: [{ type: "text" as const, text: JSON.stringify(data, null, 2) }],
    structuredContent: structured,
  };
}

function fail(err: unknown) {
  return {
    content: [{ type: "text" as const, text: `Error: ${(err as Error).message}` }],
    isError: true,
  };
}

// Resolve a model by id ("3") or name (case-insensitive substring) to its row.
async function resolveModel(model: string): Promise<any> {
  const board = (await apiGet("/api/leaderboard")) as any[];
  const byId = board.find((m) => String(m.model_id) === model.trim());
  if (byId) return byId;
  const q = model.trim().toLowerCase();
  const byName = board.find((m) => String(m.name).toLowerCase().includes(q));
  if (!byName) {
    throw new Error(
      `No model matching "${model}". Available: ${board.map((m) => m.name).join(", ")}`,
    );
  }
  return byName;
}

const server = new McpServer({ name: "ai-trading-arena", version: "1.0.0" });

const RO = { readOnlyHint: true, openWorldHint: true };

server.registerTool(
  "arena_status",
  {
    title: "Arena status",
    description:
      "Market open/closed, tickers, loop interval, last/next run, total & today's spend, daily cost cap, and timezone.",
    inputSchema: {},
    annotations: RO,
  },
  async () => {
    try {
      return ok(await apiGet("/api/status"));
    } catch (e) {
      return fail(e);
    }
  },
);

server.registerTool(
  "arena_leaderboard",
  {
    title: "Leaderboard (ranked by alpha)",
    description:
      "All competitors ranked by ALPHA (excess return over the Buy & Hold benchmark). Positive alpha = beating the market. Includes equity, return, cash.",
    inputSchema: {},
    annotations: RO,
  },
  async () => {
    try {
      return ok(await apiGet("/api/leaderboard"));
    } catch (e) {
      return fail(e);
    }
  },
);

server.registerTool(
  "arena_positions",
  {
    title: "Live positions",
    description:
      "Holdings matrix: each model's shares and value per ticker, plus cash.",
    inputSchema: {},
    annotations: RO,
  },
  async () => {
    try {
      return ok(await apiGet("/api/positions"));
    } catch (e) {
      return fail(e);
    }
  },
);

server.registerTool(
  "arena_analytics",
  {
    title: "Per-model analytics",
    description:
      "Risk-adjusted performance (Sharpe, max drawdown, alpha, win rate), token/cost usage, and behavior (buy/sell/hold, conviction, what each model reasons about).",
    inputSchema: {},
    annotations: RO,
  },
  async () => {
    try {
      return ok(await apiGet("/api/analytics"));
    } catch (e) {
      return fail(e);
    }
  },
);

server.registerTool(
  "arena_recent_trades",
  {
    title: "Recent decisions",
    description:
      "Most recent decisions across all models (or one model): action, ticker, allocation, confidence, status, time. Reasoning text excluded — use arena_model_thoughts for that.",
    inputSchema: {
      limit: z.number().int().min(1).max(200).default(20).describe("How many to return"),
      model: z
        .string()
        .optional()
        .describe("Optional model name or id to filter to one model"),
    },
    annotations: RO,
  },
  async ({ limit, model }) => {
    try {
      let path = `/api/trades?limit=${limit}`;
      if (model) path += `&model_id=${(await resolveModel(model)).model_id}`;
      const trades = (await apiGet(path)) as any[];
      const slim = trades.map((t) => ({
        time: t.created_at,
        model: t.model_name,
        action: t.action,
        ticker: t.ticker,
        allocation_pct: t.allocation_pct,
        confidence: t.confidence,
        status: t.status,
      }));
      return ok(slim);
    } catch (e) {
      return fail(e);
    }
  },
);

server.registerTool(
  "arena_model_thoughts",
  {
    title: "A model's reasoning & memory",
    description:
      "For one model: its current self-authored memory note plus its recent decisions with full reasoning and chain-of-thought. Use to analyze how a model thinks.",
    inputSchema: {
      model: z.string().describe("Model name (e.g. 'Kimi') or id"),
      limit: z.number().int().min(1).max(50).default(5).describe("How many recent decisions"),
    },
    annotations: RO,
  },
  async ({ model, limit }) => {
    try {
      const m = await resolveModel(model);
      const trades = (await apiGet(
        `/api/trades?limit=${limit}&model_id=${m.model_id}`,
      )) as any[];
      return ok({
        model: m.name,
        alpha_vs_benchmark_pct: m.alpha_vs_benchmark_pct,
        current_memory: m.memory || "(none yet)",
        decisions: trades.map((t) => ({
          time: t.created_at,
          action: t.action,
          ticker: t.ticker,
          allocation_pct: t.allocation_pct,
          confidence: t.confidence,
          reasoning: t.reasoning,
          thinking: t.thinking || "",
          status: t.status,
        })),
      });
    } catch (e) {
      return fail(e);
    }
  },
);

server.registerTool(
  "arena_run_tick",
  {
    title: "Run a trading tick now",
    description:
      "Trigger one immediate trading round: fetches data, queries every model, and executes paper trades. This calls the paid LLMs and changes portfolio state — use deliberately.",
    inputSchema: {},
    annotations: { readOnlyHint: false, destructiveHint: false, openWorldHint: true },
  },
  async () => {
    try {
      return ok(await apiPost("/api/run-now"));
    } catch (e) {
      return fail(e);
    }
  },
);

const transport = new StdioServerTransport();
await server.connect(transport);
console.error(`AI Trading Arena MCP server running (backend: ${BASE})`);
