from __future__ import annotations

import os
from pathlib import Path
from typing import Dict, Iterable, List, Optional

from dotenv import load_dotenv
from sqlalchemy import event
from sqlalchemy import create_engine, text
from sqlalchemy.orm import declarative_base, sessionmaker

BASE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BASE_DIR.parent

load_dotenv(PROJECT_ROOT / ".env")
load_dotenv(BASE_DIR / ".env", override=False)

DB_NAME = os.getenv("DB_NAME", "jesse_ai.db")
DB_PATH = PROJECT_ROOT / DB_NAME
DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{DB_PATH}")

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False, "timeout": 30})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

if str(DATABASE_URL).lower().startswith("sqlite:"):
    @event.listens_for(engine, "connect")
    def _sqlite_pragmas(dbapi_connection, connection_record) -> None:  # type: ignore[no-redef]
        try:
            cur = dbapi_connection.cursor()
            cur.execute("PRAGMA journal_mode=WAL;")
            cur.execute("PRAGMA synchronous=NORMAL;")
            cur.execute("PRAGMA foreign_keys=ON;")
            cur.execute("PRAGMA busy_timeout=5000;")
            cur.close()
        except Exception:
            pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _is_sqlite() -> bool:
    return str(DATABASE_URL).lower().startswith("sqlite:")


def _sqlite_table_columns(conn, table: str) -> List[str]:
    rows = conn.execute(text(f"PRAGMA table_info({table})")).fetchall()
    return [str(r[1]) for r in rows]


def _sqlite_add_column(conn, table: str, column_ddl: str) -> None:
    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column_ddl}"))


def _sqlite_create_index(conn, name: str, table: str, columns_sql: str) -> None:
    conn.execute(text(f"CREATE INDEX IF NOT EXISTS {name} ON {table} ({columns_sql})"))


def ensure_schema() -> None:
    """
    Lightweight schema evolution for SQLite (no Alembic in this repo).
    Adds columns/tables required by new features without destroying data.
    """
    if not _is_sqlite():
        return

    with engine.begin() as conn:
        # Create new tables if missing (Base.metadata.create_all handles tables, but not columns).
        # Ensure columns exist for legacy DBs.
        table_to_columns: Dict[str, Iterable[str]] = {
            "bars": (
                "data_source TEXT DEFAULT 'LIVE_WS'",
                "day_utc TEXT",
                "ingested_at_utc DATETIME DEFAULT CURRENT_TIMESTAMP",
            ),
            "ai_signals": (
                "data_source TEXT DEFAULT 'LIVE_WS'",
                "ingested_at_utc DATETIME DEFAULT CURRENT_TIMESTAMP",
            ),
            "monitor_snapshots": (
                "data_source TEXT DEFAULT 'LIVE_WS'",
                "ingested_at_utc DATETIME DEFAULT CURRENT_TIMESTAMP",
            ),
            "trade_events": (
                "data_source TEXT DEFAULT 'LIVE_WS'",
                "day_utc TEXT",
                "ingested_at_utc DATETIME DEFAULT CURRENT_TIMESTAMP",
            ),
            "system_events": (
                # if table doesn't exist, create_all will create it.
            ),
        }

        existing_tables = {
            str(r[0])
            for r in conn.execute(text("SELECT name FROM sqlite_master WHERE type='table'")).fetchall()
        }

        for table, ddl_cols in table_to_columns.items():
            if table not in existing_tables:
                continue
            existing_cols = set(_sqlite_table_columns(conn, table))
            for ddl in ddl_cols:
                col_name = ddl.split()[0]
                if col_name not in existing_cols:
                    _sqlite_add_column(conn, table, ddl)

        # Indexes + backfills for day_utc based queries (avoids sqlite date() parsing edge-cases).
        if "bars" in existing_tables:
            _sqlite_create_index(conn, "idx_bars_bot_day", "bars", "bot_id, day_utc")
            _sqlite_create_index(conn, "idx_bars_key", "bars", "bot_id, symbol, timeframe, ts_utc")
            # Backfill if upgrading from older DBs.
            conn.execute(
                text(
                    """
                    UPDATE bars
                    SET day_utc = COALESCE(date(ts_utc), substr(ts_utc, 1, 10))
                    WHERE day_utc IS NULL OR day_utc = ''
                    """
                )
            )

        if "trade_events" in existing_tables:
            _sqlite_create_index(conn, "idx_trade_events_bot_day", "trade_events", "bot_id, day_utc")
            conn.execute(
                text(
                    """
                    UPDATE trade_events
                    SET day_utc = COALESCE(date(ts_utc), substr(ts_utc, 1, 10))
                    WHERE day_utc IS NULL OR day_utc = ''
                    """
                )
            )
