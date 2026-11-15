"""SQLAlchemy engine / session plumbing."""
from __future__ import annotations

from collections.abc import Generator

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import get_settings

settings = get_settings()

_is_sqlite = settings.database_url.startswith("sqlite")

# check_same_thread=False so the APScheduler background thread and the FastAPI
# request threads can share the same SQLite file.
engine = create_engine(
    settings.database_url,
    connect_args={"check_same_thread": False} if _is_sqlite else {},
    echo=False,
)


if _is_sqlite:

    @event.listens_for(engine, "connect")
    def _sqlite_pragmas(dbapi_conn, _rec):  # noqa: ANN001
        """Robust concurrency for the scheduler (trade tick + 2-min snapshot) and
        API readers sharing one SQLite file:
        - WAL: readers don't block the writer, fewer 'database is locked'.
        - busy_timeout: wait up to 10s for a lock instead of erroring instantly.
        """
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA busy_timeout=10000")
        cur.execute("PRAGMA synchronous=NORMAL")
        cur.close()

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


class Base(DeclarativeBase):
    pass


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency that yields a request-scoped session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    """Create all tables. Safe to call repeatedly."""
    from . import models  # noqa: F401  (register models on Base)

    Base.metadata.create_all(bind=engine)
