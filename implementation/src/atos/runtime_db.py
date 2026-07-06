"""Canonical Runtime Database — Phase B Runtime State Kernel authority.

Single source of truth for B1 persisted state entities.
Uses stdlib sqlite3. No ORM. No SQLAlchemy.

Database file: runtime/atos_runtime.sqlite
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

DEFAULT_RUNTIME_DB_PATH = "runtime/atos_runtime.sqlite"


class RuntimePersistenceError(Exception):
    """Raised when a required DB invariant cannot be satisfied."""


class RuntimeDatabase:
    """Canonical runtime-state database connection.

    Every connection:
      - PRAGMA foreign_keys = ON (verified)
      - PRAGMA journal_mode = WAL (verified)
      - PRAGMA synchronous = FULL
      - PRAGMA busy_timeout = 5000

    Transactions are explicit. No auto-commit per statement.
    """

    def __init__(self, path: str | Path = DEFAULT_RUNTIME_DB_PATH):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn: sqlite3.Connection | None = None

    def connect(self) -> sqlite3.Connection:
        """Open connection and enforce all safety pragmas."""
        conn = sqlite3.connect(str(self.path))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA busy_timeout = 5000")
        conn.execute("PRAGMA synchronous = FULL")
        conn.execute("PRAGMA journal_mode = WAL")

        # Verify critical pragmas — fail closed on any violation
        fk = conn.execute("PRAGMA foreign_keys").fetchone()[0]
        if fk != 1:
            conn.close()
            raise RuntimePersistenceError(f"foreign_keys is {fk}, expected 1")

        wal = conn.execute("PRAGMA journal_mode").fetchone()[0]
        if wal.lower() != "wal":
            conn.close()
            raise RuntimePersistenceError(f"journal_mode is {wal}, expected wal")

        self.conn = conn
        return conn

    @property
    def connection(self) -> sqlite3.Connection:
        if self.conn is None:
            self.connect()
        assert self.conn is not None
        return self.conn

    def transaction(self, immediate: bool = True):
        """Context manager for an atomic transaction.

        BEGIN (IMMEDIATE) → COMMIT on success, ROLLBACK on exception.
        Exception is re-raised — never swallowed.
        """
        from contextlib import contextmanager

        @contextmanager
        def _tx():
            c = self.connection
            if immediate:
                c.execute("BEGIN IMMEDIATE")
            try:
                yield c
                c.commit()
            except Exception:
                c.rollback()
                raise

        return _tx()

    def close(self):
        if self.conn:
            self.conn.close()
            self.conn = None

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, *args):
        self.close()
