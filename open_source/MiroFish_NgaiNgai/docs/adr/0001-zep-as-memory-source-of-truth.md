# 0001 — Zep Cloud is the single source of truth for agent memory

- **Status:** accepted (upstream observation)
- **Date:** 2026-05-17
- **Deciders:** upstream maintainers (recorded by Markues)

## Context

Each OASIS simulation may run thousands of agents over many rounds. Agents need persistent memory across rounds, an entity/relationship graph for reasoning, and a way to share extracted knowledge from seed materials. Holding all of this purely in-process would require custom persistence, GraphRAG, and embedding management.

## Decision

Zep Cloud owns the canonical state for agent memory and the knowledge graph. In-memory caches in the backend are treated as ephemeral; after every simulation round, `ZepGraphMemoryUpdater` syncs changes back to Zep.

## Consequences

- **Positive:** GraphRAG / memory infra delegated to a managed service; backend stays stateless across rounds; restarts don't lose state.
- **Negative:** hard dependency on Zep Cloud (network, auth, billing); offline development is restricted.
- **Follow-ups:** if Zep becomes a cost or vendor-lock problem, evaluate self-hosted Zep or a swap to an OSS GraphRAG stack.

## Alternatives considered

- **In-process state only:** simplest but loses GraphRAG and persistence.
- **Self-hosted graph DB (Neo4j) + custom RAG:** technically possible, significant build cost.
