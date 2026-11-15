# AI Trading Arena — MCP server

Exposes the arena as MCP tools so any MCP client (Claude Desktop, Claude Code,
etc.) can inspect and drive it conversationally. It's a thin client over the
backend's REST API — **the backend must be running** (default
`http://localhost:8000`, override with `ARENA_API_BASE`).

## Tools

| Tool | What it does |
|---|---|
| `arena_status` | market state, loop timing, spend, timezone |
| `arena_leaderboard` | competitors ranked by **alpha** vs Buy & Hold |
| `arena_positions` | holdings matrix (shares + value per ticker, cash) |
| `arena_analytics` | Sharpe / drawdown / alpha / win-rate, cost & tokens, behavior |
| `arena_recent_trades` | recent decisions (optionally one model) |
| `arena_model_thoughts` | a model's current memory + reasoning/chain-of-thought |
| `arena_run_tick` | trigger one trading round now (calls paid LLMs) |

## Build

```bash
cd mcp
npm install
npm run build
```

## Connect

**Claude Desktop** — add to `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "ai-trading-arena": {
      "command": "node",
      "args": ["/Volumes/SSD/SelfProject/ai-trading-arena/mcp/dist/index.js"],
      "env": { "ARENA_API_BASE": "http://localhost:8000" }
    }
  }
}
```

**Claude Code:**

```bash
claude mcp add ai-trading-arena --env ARENA_API_BASE=http://localhost:8000 \
  -- node /Volumes/SSD/SelfProject/ai-trading-arena/mcp/dist/index.js
```

Then ask things like *"who's leading the arena on alpha?"*, *"what is Kimi
thinking right now?"*, *"show the holdings"*, or *"run a tick."*

## Test (without a client)

```bash
npx @modelcontextprotocol/inspector node dist/index.js
```
