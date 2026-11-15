# 0001 — Use plain `sqlite3` with no ORM

- **Status:** accepted
- **Date:** 2026-05-17
- **Deciders:** Markues

## Context

This is a single-user personal advisor app. Data model is small (snapshots, asset entries, market cache, scrapers), schema is stable, and all queries are simple. An ORM would add a dependency, a query layer, and migration tooling we don't need.

## Decision

All database access goes through `database/repository.py`, a singleton wrapping the stdlib `sqlite3` module with `row_factory=sqlite3.Row`. No SQLAlchemy, no Tortoise, no Peewee.

## Consequences

- **Positive:** zero external DB dependency, full SQL visibility, trivial debugging, schema changes are raw `ALTER`s applied at startup.
- **Negative:** every new table needs hand-written CRUD; no automatic relationship loading; refactors that rename columns touch many SQL strings.
- **Follow-ups:** if the model ever grows to 10+ tables or we add multi-user support, revisit.

## Alternatives considered

- **SQLAlchemy:** adds a real query layer but introduces migrations (Alembic), session lifecycle complexity, and a learning curve that isn't worth it at this scale.
- **Pydantic + JSON files:** simpler than even SQLite but loses time-series queries and aggregate math.
