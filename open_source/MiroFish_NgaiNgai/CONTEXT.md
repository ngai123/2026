# MiroFish — Domain Context

Glossary, invariants, and boundaries for the multi-agent prediction engine. "Agent" here means an OASIS persona, not a Claude sub-agent — terms overlap with other projects on this SSD.

## Glossary

- **Seed Material** — Input documents (reports, news, novels) the user uploads. Source for knowledge graph extraction and agent backstories.
- **Knowledge Graph** — Entity/relationship structure built in Zep Cloud (GraphRAG) from seed material. Foundation for agent reasoning during simulation.
- **Agent Persona** — LLM-generated profile (personality, background, goals, rules) for one simulated actor. Injected into OASIS before simulation start.
- **OASIS Simulation** — CAMEL-AI's multi-agent social simulation. Orchestrates thousands of agents on Twitter/Reddit-style platforms across many rounds.
- **Simulation Round** — One discrete time step in which all agents act (post / like / comment) in parallel. Agents read Zep memory before deciding.
- **ReportAgent** — Agentic system that queries the post-simulation environment, runs analytical tools, and emits structured prediction reports.
- **Prediction Requirement** — User's natural-language query (e.g. "will this policy succeed?"). Scopes both simulation config and report generation.
- **Project Lifecycle** — Five fixed steps: GraphBuild → EntityRead → SimSetup → Simulation → Report.

## Invariants

1. **One project, one lifecycle.** Projects move through the five steps in order. State lives in `backend/uploads/projects/{project_id}/`. No skipping.
2. **LLM config is fixed for the session.** API key + model from `.env`. Switching requires restart — agents, graph analysis, and reports all use the same model.
3. **Zep is the single source of truth for memory and entities.** In-memory caches sync back to Zep after each simulation round via `ZepGraphMemoryUpdater`.
4. **Graph is frozen before simulation.** Simulation reads the graph but cannot modify it; the graph must be fully built before entity filtering / OASIS profile generation.
5. **Reports run on frozen sim output.** `ReportAgent` reads logs and final graph state; cannot re-trigger or extend the simulation mid-report.

## Boundaries

**Frontend ↔ backend:** REST at `/api/{graph,simulation,report,intelligence}`. Frontend polls for status — no WebSocket. UI state local to the browser.

**External services:**
- LLM via OpenAI-compatible endpoint (default Alibaba Qwen-plus)
- Zep Cloud for memory + knowledge graph
- CAMEL-AI OASIS for simulation runtime

**Persistent storage:** `./backend/uploads/` (project files), Zep Cloud (memory / graph), no local DB beyond filesystem state.

**Ports:** frontend `3000`, backend `5001`.

**Out of scope:** real-time multi-user collaboration, authentication, billing, hosted deployment beyond Docker Compose.
