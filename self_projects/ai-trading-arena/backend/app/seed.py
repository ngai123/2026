"""Seed the database with the configured agents + fresh portfolios.

Run once after install:  python -m app.seed
Idempotent: existing models are left untouched.
"""
from __future__ import annotations

from sqlalchemy import select

from .config import AGENTS, BENCHMARK, get_settings
from .database import SessionLocal, init_db
from .models import Model, Portfolio


def seed() -> None:
    init_db()
    settings = get_settings()
    db = SessionLocal()
    try:
        for spec in [*AGENTS, BENCHMARK]:
            existing = db.scalar(select(Model).where(Model.name == spec.name))
            if existing:
                continue
            model = Model(name=spec.name, slug=spec.model)
            db.add(model)
            db.flush()  # assign model.id
            db.add(
                Portfolio(
                    model_id=model.id,
                    cash=settings.starting_cash,
                    starting_cash=settings.starting_cash,
                )
            )
            print(f"Seeded {spec.name} ({spec.model}) with ${settings.starting_cash:,.0f}")
        db.commit()
    finally:
        db.close()


if __name__ == "__main__":
    seed()
