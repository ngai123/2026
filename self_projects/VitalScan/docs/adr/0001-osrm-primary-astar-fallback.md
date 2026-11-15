# 0001 — OSRM as primary router, A* on a virtual grid as fallback

- **Status:** accepted
- **Date:** 2026-05-17
- **Deciders:** Markues

## Context

Drones need realistic movement in Metro Manila for the simulation to feel like a real SAR operation. We have two routing options:

1. **OSRM public router** (router.project-osrm.org) — real street geometry, but public, rate-limited, and occasionally times out.
2. **A\* on a Haversine grid** — fast, deterministic, offline, but produces straight-line-ish paths that ignore streets.

Public OSRM is "good enough" for ~95% of requests; the rest need graceful degradation, not a crash.

## Decision

Route requests always try OSRM first with a 3-second timeout. On timeout or HTTP error, fall back to A* over a 15×15 virtual grid covering Manila GPS bounds, using Haversine distance as the heuristic.

## Consequences

- **Positive:** realistic paths in the common case; deterministic behaviour when the network blips; no paid map service required.
- **Negative:** fallback paths are visibly less realistic, which is observable in the dashboard; two routing code paths to maintain.
- **Follow-ups:** if we ever go offline-first (no network), increase A* grid resolution and pre-bake a street network.

## Alternatives considered

- **Self-host OSRM:** removes the rate-limit concern but adds operational overhead the project doesn't need.
- **A\* only:** simpler but loses the realism that makes the simulation compelling as a portfolio piece.
- **Mapbox / Google Directions:** paid, adds API key management for a personal project.
