"""
Database Migrations — versioned schema management for SQLite ledger.

Ensures the ledger database stays in sync as the schema evolves.
All migrations are idempotent (safe to run multiple times).

Version table tracks which migrations have been applied.
"""

from __future__ import annotations

import sqlite3
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

CURRENT_VERSION = 2

MIGRATIONS = {
    1: [
        """CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT NOT NULL,
            kind TEXT NOT NULL,
            payload_json TEXT NOT NULL
        )""",
        """CREATE TABLE IF NOT EXISTS strategy_scores (
            strategy_id TEXT PRIMARY KEY,
            updated_at TEXT NOT NULL,
            trades INTEGER NOT NULL,
            wins INTEGER NOT NULL,
            losses INTEGER NOT NULL,
            avg_pnl_pct REAL NOT NULL,
            weight REAL NOT NULL,
            status TEXT NOT NULL
        )""",
        """CREATE TABLE IF NOT EXISTS positions (
            id TEXT PRIMARY KEY,
            symbol TEXT NOT NULL,
            side TEXT NOT NULL,
            qty REAL NOT NULL,
            avg_price REAL NOT NULL,
            status TEXT NOT NULL,
            opened_at TEXT NOT NULL,
            closed_at TEXT
        )""",
    ],
    2: [
        # Add provider_calls and reviews tables
        """CREATE TABLE IF NOT EXISTS provider_calls (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT NOT NULL,
            provider TEXT NOT NULL,
            model TEXT NOT NULL DEFAULT '',
            symbol TEXT NOT NULL,
            latency_ms REAL NOT NULL DEFAULT 0,
            tokens_used INTEGER NOT NULL DEFAULT 0,
            error TEXT,
            payload_json TEXT NOT NULL
        )""",
        """CREATE TABLE IF NOT EXISTS reviews (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT NOT NULL,
            review_type TEXT NOT NULL,
            date TEXT NOT NULL,
            payload_json TEXT NOT NULL
        )""",
        """CREATE TABLE IF NOT EXISTS incidents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT NOT NULL,
            severity TEXT NOT NULL,
            kind TEXT NOT NULL,
            symbol TEXT,
            message TEXT NOT NULL,
            resolved_at TEXT
        )""",
        """CREATE TABLE IF NOT EXISTS config_versions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT NOT NULL,
            config_hash TEXT NOT NULL,
            config_snapshot_json TEXT NOT NULL
        )""",
    ],
}


def migrate(conn: sqlite3.Connection) -> int:
    """Run all pending migrations. Returns the new version."""
    _ensure_version_table(conn)

    current = _current_version(conn)
    target = CURRENT_VERSION

    if current >= target:
        return current

    logger.info(f"Migrating database: v{current} → v{target}")

    for version in range(current + 1, target + 1):
        if version in MIGRATIONS:
            for sql in MIGRATIONS[version]:
                try:
                    conn.execute(sql)
                except sqlite3.OperationalError as e:
                    logger.warning(f"Migration v{version} SQL failed (may already exist): {e}")
            conn.execute(
                "INSERT OR REPLACE INTO _schema_version (version, applied_at) VALUES (?, datetime('now'))",
                (version,),
            )
            conn.commit()
            logger.info(f"  Applied migration v{version}")

    return target


def _ensure_version_table(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS _schema_version (
            version INTEGER PRIMARY KEY,
            applied_at TEXT NOT NULL
        )
    """)
    conn.commit()


def _current_version(conn: sqlite3.Connection) -> int:
    row = conn.execute("SELECT MAX(version) FROM _schema_version").fetchone()
    return int(row[0]) if row and row[0] is not None else 0


def migrate_db_file(db_path: str) -> int:
    """Convenience: migrate a database file on disk."""
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    try:
        return migrate(conn)
    finally:
        conn.close()
