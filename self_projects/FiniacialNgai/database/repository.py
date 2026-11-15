"""SQLite database repository — all read/write operations."""
import sqlite3
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Optional
import config as _config


class Repository:
    """Encapsulates all database operations behind a single class."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    # ─── Database initialisation ─────────────────────────────────────────────

    def init_db(self) -> None:
        """Create all tables and run migrations."""
        with self._connect() as conn:
            conn.executescript("""
            -- Balance Sheet snapshots (one per save; tagged with period YYYY-MM)
            CREATE TABLE IF NOT EXISTS snapshots (
                id                INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at        TEXT NOT NULL,
                period            TEXT NOT NULL DEFAULT '',   -- YYYY-MM
                label             TEXT NOT NULL,
                total_assets      REAL NOT NULL DEFAULT 0,
                total_liabilities REAL NOT NULL DEFAULT 0,
                net_worth         REAL NOT NULL DEFAULT 0,
                monthly_income    REAL DEFAULT 0,
                monthly_expense   REAL DEFAULT 0,
                notes             TEXT DEFAULT ''
            );

            CREATE TABLE IF NOT EXISTS asset_entries (
                id                INTEGER PRIMARY KEY AUTOINCREMENT,
                snapshot_id       INTEGER NOT NULL REFERENCES snapshots(id) ON DELETE CASCADE,
                name              TEXT NOT NULL,
                category          TEXT NOT NULL,
                asset_key         TEXT NOT NULL,
                institution       TEXT DEFAULT '',
                balance           REAL NOT NULL DEFAULT 0,
                currency          TEXT DEFAULT 'MYR',
                is_liability      INTEGER DEFAULT 0,
                annual_return_pct REAL,
                quantity          REAL,
                ticker            TEXT DEFAULT '',
                notes             TEXT DEFAULT ''
            );

            -- P&L snapshots (one per save; tagged with period YYYY-MM)
            CREATE TABLE IF NOT EXISTS pnl_snapshots (
                id             INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at     TEXT NOT NULL,
                period         TEXT NOT NULL DEFAULT '',   -- YYYY-MM
                label          TEXT NOT NULL,
                total_income   REAL NOT NULL DEFAULT 0,
                total_expense  REAL NOT NULL DEFAULT 0,
                net_savings    REAL NOT NULL DEFAULT 0,
                savings_rate   REAL NOT NULL DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS pnl_items (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                pnl_snapshot_id INTEGER NOT NULL REFERENCES pnl_snapshots(id) ON DELETE CASCADE,
                type            TEXT NOT NULL,   -- 'income' or 'expense'
                category        TEXT NOT NULL,
                description     TEXT DEFAULT '',
                amount          REAL NOT NULL DEFAULT 0
            );

            -- Market data cache (unchanged)
            CREATE TABLE IF NOT EXISTS market_data_cache (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                source     TEXT NOT NULL,
                period     TEXT NOT NULL,
                value      REAL NOT NULL,
                fetched_at TEXT NOT NULL,
                UNIQUE(source, period) ON CONFLICT REPLACE
            );

            -- AI conversation history
            CREATE TABLE IF NOT EXISTS ai_conversations (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id  TEXT NOT NULL,
                snapshot_id INTEGER REFERENCES snapshots(id),
                role        TEXT NOT NULL,
                content     TEXT NOT NULL,
                timestamp   TEXT NOT NULL
            );

            -- Watchlist: stocks to monitor
            CREATE TABLE IF NOT EXISTS watchlist (
                id       INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol   TEXT NOT NULL UNIQUE,
                name     TEXT DEFAULT '',
                added_at TEXT NOT NULL
            );

            -- Price alerts
            CREATE TABLE IF NOT EXISTS stock_alerts (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol       TEXT NOT NULL,
                target_price REAL NOT NULL,
                condition    TEXT NOT NULL,
                active       INTEGER DEFAULT 1,
                triggered    INTEGER DEFAULT 0,
                created_at   TEXT NOT NULL,
                expires_at   TEXT NOT NULL,
                triggered_at TEXT DEFAULT ''
            );

            -- Risk profiles (per-snapshot health / risk assessment)
            CREATE TABLE IF NOT EXISTS risk_profiles (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                snapshot_id     INTEGER REFERENCES snapshots(id),
                created_at      TEXT NOT NULL,
                profile_json    TEXT NOT NULL DEFAULT '{}'
            );
            """)

        # ── Migrations: add health_score column (if missing) ─────────────────
        with self._connect() as conn:
            cols = [r[1] for r in conn.execute("PRAGMA table_info(snapshots)").fetchall()]
            if "health_score" not in cols:
                conn.execute("ALTER TABLE snapshots ADD COLUMN health_score REAL DEFAULT NULL")

        # ── Migrations: backfill period on old rows ──────────────────────────
        with self._connect() as conn:
            # Add period column to snapshots if missing (old installs)
            cols = [r[1] for r in conn.execute("PRAGMA table_info(snapshots)").fetchall()]
            if "period" not in cols:
                conn.execute("ALTER TABLE snapshots ADD COLUMN period TEXT NOT NULL DEFAULT ''")
            # Backfill period from created_at
            conn.execute(
                "UPDATE snapshots SET period = substr(created_at, 1, 7) WHERE period = '' OR period IS NULL"
            )

    # ─── Balance Sheet Snapshots ─────────────────────────────────────────────

    def save_snapshot(self, label: str, assets: list[dict],
                      monthly_income: float = 0, monthly_expense: float = 0,
                      period: str = "", notes: str = "") -> int:
        if not period:
            period = datetime.now().strftime("%Y-%m")
        total_assets = sum(a["balance"] for a in assets if not a.get("is_liability"))
        total_liabilities = sum(a["balance"] for a in assets if a.get("is_liability"))
        net_worth = total_assets - total_liabilities

        with self._connect() as conn:
            # Delete existing snapshot(s) for this period so save always replaces
            old_ids = [r[0] for r in conn.execute(
                "SELECT id FROM snapshots WHERE period=?", (period,)
            ).fetchall()]
            for oid in old_ids:
                conn.execute("DELETE FROM asset_entries WHERE snapshot_id=?", (oid,))
                # ai_conversations references snapshots without CASCADE — null it out first
                conn.execute("UPDATE ai_conversations SET snapshot_id=NULL WHERE snapshot_id=?", (oid,))
            if old_ids:
                conn.execute(
                    "DELETE FROM snapshots WHERE id IN ({})".format(
                        ",".join("?" * len(old_ids))), old_ids
                )

            cur = conn.execute(
                """INSERT INTO snapshots
                   (created_at, period, label, total_assets, total_liabilities, net_worth,
                    monthly_income, monthly_expense, notes)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (datetime.now().isoformat(), period, label, total_assets, total_liabilities,
                 net_worth, monthly_income, monthly_expense, notes)
            )
            snapshot_id = cur.lastrowid

            for a in assets:
                conn.execute(
                    """INSERT INTO asset_entries
                       (snapshot_id, name, category, asset_key, institution, balance,
                        currency, is_liability, annual_return_pct, quantity, ticker, notes)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (snapshot_id, a["name"], a["category"], a["asset_key"],
                     a.get("institution", ""), a["balance"],
                     a.get("currency", "MYR"), int(a.get("is_liability", False)),
                     a.get("annual_return_pct"), a.get("quantity"),
                     a.get("ticker", ""), a.get("notes", ""))
                )
        return snapshot_id

    def get_snapshot(self, snapshot_id: int) -> Optional[dict]:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM snapshots WHERE id=?", (snapshot_id,)).fetchone()
            return dict(row) if row else None

    def get_snapshot_assets(self, snapshot_id: int) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM asset_entries WHERE snapshot_id=? ORDER BY is_liability, category, name",
                (snapshot_id,)
            ).fetchall()
            return [dict(r) for r in rows]

    def get_latest_snapshot_id(self) -> Optional[int]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT id FROM snapshots ORDER BY period DESC, created_at DESC LIMIT 1"
            ).fetchone()
            return row[0] if row else None

    def get_snapshot_by_period(self, period: str) -> Optional[dict]:
        """Return the most recent snapshot saved for a given YYYY-MM period."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM snapshots WHERE period=? ORDER BY created_at DESC LIMIT 1",
                (period,)
            ).fetchone()
            return dict(row) if row else None

    def list_snapshots(self) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM snapshots ORDER BY period DESC, created_at DESC"
            ).fetchall()
            return [dict(r) for r in rows]

    def list_snapshot_periods(self) -> list[str]:
        """Sorted list of distinct YYYY-MM periods that have a balance sheet snapshot."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT DISTINCT period FROM snapshots WHERE period != '' ORDER BY period DESC"
            ).fetchall()
            return [r[0] for r in rows]

    def delete_snapshot(self, snapshot_id: int) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM snapshots WHERE id=?", (snapshot_id,))

    def update_snapshot_health(self, snapshot_id: int, health_score: float) -> None:
        """Update the health_score column on a snapshot row."""
        with self._connect() as conn:
            conn.execute(
                "UPDATE snapshots SET health_score=? WHERE id=?",
                (health_score, snapshot_id),
            )

    # ─── P&L Snapshots ──────────────────────────────────────────────────────

    def save_pnl(self, label: str, income_items: list[dict], expense_items: list[dict],
                 period: str = "") -> int:
        if not period:
            period = datetime.now().strftime("%Y-%m")
        total_income  = sum(float(i.get("amount", 0)) for i in income_items)
        total_expense = sum(float(i.get("amount", 0)) for i in expense_items)
        net_savings   = total_income - total_expense
        savings_rate  = (net_savings / total_income * 100) if total_income > 0 else 0.0

        with self._connect() as conn:
            # Delete existing P&L record(s) for this period so save always replaces
            old_ids = [r[0] for r in conn.execute(
                "SELECT id FROM pnl_snapshots WHERE period=?", (period,)
            ).fetchall()]
            for oid in old_ids:
                conn.execute("DELETE FROM pnl_items WHERE pnl_snapshot_id=?", (oid,))
            if old_ids:
                conn.execute(
                    "DELETE FROM pnl_snapshots WHERE id IN ({})".format(
                        ",".join("?" * len(old_ids))), old_ids
                )

            cur = conn.execute(
                """INSERT INTO pnl_snapshots
                   (created_at, period, label, total_income, total_expense, net_savings, savings_rate)
                   VALUES (?,?,?,?,?,?,?)""",
                (datetime.now().isoformat(), period, label,
                 total_income, total_expense, net_savings, savings_rate)
            )
            pnl_id = cur.lastrowid

            for item in income_items:
                if float(item.get("amount", 0)) > 0 or str(item.get("description", "")).strip():
                    conn.execute(
                        "INSERT INTO pnl_items (pnl_snapshot_id, type, category, description, amount) VALUES (?,?,?,?,?)",
                        (pnl_id, "income", item.get("category", "Other"),
                         item.get("description", ""), float(item.get("amount", 0)))
                    )
            for item in expense_items:
                if float(item.get("amount", 0)) > 0 or str(item.get("description", "")).strip():
                    conn.execute(
                        "INSERT INTO pnl_items (pnl_snapshot_id, type, category, description, amount) VALUES (?,?,?,?,?)",
                        (pnl_id, "expense", item.get("category", "Other"),
                         item.get("description", ""), float(item.get("amount", 0)))
                    )
        return pnl_id

    def get_pnl(self, pnl_id: int) -> Optional[dict]:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM pnl_snapshots WHERE id=?", (pnl_id,)).fetchone()
            if not row:
                return None
            snap = dict(row)
            items = conn.execute(
                "SELECT * FROM pnl_items WHERE pnl_snapshot_id=? ORDER BY type, category",
                (pnl_id,)
            ).fetchall()
        snap["income_items"]  = [dict(r) for r in items if r["type"] == "income"]
        snap["expense_items"] = [dict(r) for r in items if r["type"] == "expense"]
        return snap

    def get_latest_pnl_id(self) -> Optional[int]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT id FROM pnl_snapshots ORDER BY period DESC, created_at DESC LIMIT 1"
            ).fetchone()
            return row[0] if row else None

    def get_pnl_items(self, pnl_id: int) -> dict:
        """Alias kept for backward compat with consultant.py."""
        result = self.get_pnl(pnl_id)
        if not result:
            return {"income_items": [], "expense_items": [],
                    "total_monthly_income": 0, "total_monthly_expense": 0,
                    "net_monthly_savings": 0, "savings_rate_pct": 0}
        result["total_monthly_income"]  = result["total_income"]
        result["total_monthly_expense"] = result["total_expense"]
        result["net_monthly_savings"]   = result["net_savings"]
        result["savings_rate_pct"]      = result["savings_rate"]
        return result

    def get_pnl_by_period(self, period: str) -> Optional[dict]:
        """Return the most recent P&L saved for a given YYYY-MM period."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT id FROM pnl_snapshots WHERE period=? ORDER BY created_at DESC LIMIT 1",
                (period,)
            ).fetchone()
        return self.get_pnl(row[0]) if row else None

    def list_pnl_periods(self) -> list[str]:
        """Sorted list of distinct YYYY-MM periods that have a P&L snapshot."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT DISTINCT period FROM pnl_snapshots WHERE period != '' ORDER BY period DESC"
            ).fetchall()
            return [r[0] for r in rows]

    def list_all_periods(self) -> list[str]:
        """All periods that have either a balance sheet or a P&L entry."""
        bs = set(self.list_snapshot_periods())
        pl = set(self.list_pnl_periods())
        return sorted(bs | pl, reverse=True)

    # ─── Market Data Cache ──────────────────────────────────────────────────

    def upsert_cache(self, source: str, period: str, value: float) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO market_data_cache (source, period, value, fetched_at) VALUES (?,?,?,?)",
                (source, period, value, datetime.now().isoformat())
            )

    def get_cached_series(self, source: str, max_age_hours: int = 24) -> list[dict]:
        cutoff = (datetime.now() - timedelta(hours=max_age_hours)).isoformat()
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT period, value FROM market_data_cache WHERE source=? AND fetched_at >= ? ORDER BY period",
                (source, cutoff)
            ).fetchall()
            return [dict(r) for r in rows]

    def get_all_cached_series(self, source: str) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT period, value FROM market_data_cache WHERE source=? ORDER BY period",
                (source,)
            ).fetchall()
            return [dict(r) for r in rows]

    def seed_historical_data(self, source: str, data: dict) -> None:
        with self._connect() as conn:
            for period, value in data.items():
                existing = conn.execute(
                    "SELECT id FROM market_data_cache WHERE source=? AND period=?",
                    (source, str(period))
                ).fetchone()
                if not existing:
                    conn.execute(
                        "INSERT INTO market_data_cache (source, period, value, fetched_at) VALUES (?,?,?,?)",
                        (source, str(period), value, "2000-01-01T00:00:00")
                    )

    # ─── AI Conversations ───────────────────────────────────────────────────

    def save_message(self, session_id: str, role: str, content: str,
                     snapshot_id: Optional[int] = None) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO ai_conversations (session_id, snapshot_id, role, content, timestamp) VALUES (?,?,?,?,?)",
                (session_id, snapshot_id, role, content, datetime.now().isoformat())
            )

    def get_conversation(self, session_id: str, limit: int = 50) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT role, content FROM ai_conversations WHERE session_id=? ORDER BY timestamp DESC LIMIT ?",
                (session_id, limit)
            ).fetchall()
            return [dict(r) for r in reversed(rows)]

    def clear_conversation(self, session_id: str) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM ai_conversations WHERE session_id=?", (session_id,))

    # ─── Watchlist ──────────────────────────────────────────────────────────

    def seed_default_watchlist(self, defaults: list) -> None:
        """Seed default symbols only when the watchlist is completely empty."""
        if self.get_watchlist():
            return
        with self._connect() as conn:
            for symbol, name in defaults:
                conn.execute(
                    "INSERT OR IGNORE INTO watchlist (symbol, name, added_at) VALUES (?,?,?)",
                    (symbol.upper(), name, datetime.now().isoformat()),
                )

    def add_to_watchlist(self, symbol: str, name: str = "") -> bool:
        """Returns True if added, False if already in watchlist."""
        try:
            with self._connect() as conn:
                conn.execute(
                    "INSERT INTO watchlist (symbol, name, added_at) VALUES (?,?,?)",
                    (symbol.upper(), name or symbol.upper(), datetime.now().isoformat()),
                )
            return True
        except Exception:
            return False

    def remove_from_watchlist(self, symbol: str) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM watchlist WHERE symbol=?", (symbol.upper(),))

    def get_watchlist(self) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM watchlist ORDER BY added_at ASC"
            ).fetchall()
            return [dict(r) for r in rows]

    # ─── Stock Alerts ───────────────────────────────────────────────────────

    def create_alert(self, symbol: str, target_price: float, condition: str,
                     days_valid: int = 90) -> int:
        now = datetime.now()
        expires_at = (now + timedelta(days=days_valid)).isoformat()
        with self._connect() as conn:
            cur = conn.execute(
                """INSERT INTO stock_alerts
                   (symbol, target_price, condition, active, triggered, created_at, expires_at)
                   VALUES (?,?,?,1,0,?,?)""",
                (symbol.upper(), target_price, condition.upper(),
                 now.isoformat(), expires_at),
            )
            return cur.lastrowid

    def get_active_alerts(self) -> list[dict]:
        """Non-triggered, active, non-expired alerts."""
        now = datetime.now().isoformat()
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT * FROM stock_alerts
                   WHERE active=1 AND triggered=0 AND expires_at > ?
                   ORDER BY created_at DESC""",
                (now,),
            ).fetchall()
            return [dict(r) for r in rows]

    def get_all_alerts(self) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM stock_alerts ORDER BY triggered ASC, created_at DESC"
            ).fetchall()
            return [dict(r) for r in rows]

    def delete_alert(self, alert_id: int) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM stock_alerts WHERE id=?", (alert_id,))

    def toggle_alert(self, alert_id: int) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE stock_alerts SET active = 1 - active WHERE id=?", (alert_id,)
            )

    def mark_alert_triggered(self, alert_id: int) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE stock_alerts SET triggered=1, active=0, triggered_at=? WHERE id=?",
                (datetime.now().isoformat(), alert_id),
            )

    def clear_triggered_alerts(self) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM stock_alerts WHERE triggered=1")

    # ─── Risk Profiles ──────────────────────────────────────────────────────

    def save_risk_profile(self, profile_dict: dict) -> int:
        """Insert a new row into risk_profiles, storing the full dict as JSON."""
        with self._connect() as conn:
            cur = conn.execute(
                """INSERT INTO risk_profiles (snapshot_id, created_at, profile_json)
                   VALUES (?,?,?)""",
                (
                    profile_dict.get("snapshot_id"),
                    datetime.now().isoformat(),
                    json.dumps(profile_dict),
                ),
            )
            return cur.lastrowid

    def get_latest_risk_profile(self) -> Optional[dict]:
        """Return the most recent risk_profiles row (deserialised from JSON)."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM risk_profiles ORDER BY created_at DESC LIMIT 1"
            ).fetchone()
            if not row:
                return None
            result = dict(row)
            result["profile"] = json.loads(result.pop("profile_json", "{}"))
            return result


# ─── Backward-compatible module-level API ────────────────────────────────────
# Create a default instance using the configured DB_PATH and re-export every
# public method so that existing callers (``repo.get_latest_snapshot_id()``)
# keep working with zero changes.

_default_repo = Repository(_config.DB_PATH)

# Re-export all public methods as module-level names
init_db               = _default_repo.init_db
save_snapshot          = _default_repo.save_snapshot
get_snapshot           = _default_repo.get_snapshot
get_snapshot_assets    = _default_repo.get_snapshot_assets
get_latest_snapshot_id = _default_repo.get_latest_snapshot_id
get_snapshot_by_period = _default_repo.get_snapshot_by_period
list_snapshots         = _default_repo.list_snapshots
list_snapshot_periods  = _default_repo.list_snapshot_periods
delete_snapshot        = _default_repo.delete_snapshot
update_snapshot_health = _default_repo.update_snapshot_health
save_pnl              = _default_repo.save_pnl
get_pnl               = _default_repo.get_pnl
get_latest_pnl_id     = _default_repo.get_latest_pnl_id
get_pnl_items         = _default_repo.get_pnl_items
get_pnl_by_period     = _default_repo.get_pnl_by_period
list_pnl_periods      = _default_repo.list_pnl_periods
list_all_periods       = _default_repo.list_all_periods
upsert_cache          = _default_repo.upsert_cache
get_cached_series     = _default_repo.get_cached_series
get_all_cached_series = _default_repo.get_all_cached_series
seed_historical_data  = _default_repo.seed_historical_data
save_message          = _default_repo.save_message
get_conversation      = _default_repo.get_conversation
clear_conversation    = _default_repo.clear_conversation
seed_default_watchlist = _default_repo.seed_default_watchlist
add_to_watchlist      = _default_repo.add_to_watchlist
remove_from_watchlist = _default_repo.remove_from_watchlist
get_watchlist         = _default_repo.get_watchlist
create_alert          = _default_repo.create_alert
get_active_alerts     = _default_repo.get_active_alerts
get_all_alerts        = _default_repo.get_all_alerts
delete_alert          = _default_repo.delete_alert
toggle_alert          = _default_repo.toggle_alert
mark_alert_triggered  = _default_repo.mark_alert_triggered
clear_triggered_alerts = _default_repo.clear_triggered_alerts
save_risk_profile     = _default_repo.save_risk_profile
get_latest_risk_profile = _default_repo.get_latest_risk_profile
