"""Canonical Runtime Database — Phase B Runtime State Kernel authority.

Single source of truth for B1 persisted state entities.
Uses stdlib sqlite3. No ORM. No SQLAlchemy.

Database file: runtime/atos_runtime.sqlite
"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path

DEFAULT_RUNTIME_DB_PATH = "runtime/atos_runtime.sqlite"


class RuntimePersistenceError(Exception):
    """Raised when a required DB invariant cannot be satisfied."""


class RuntimeDatabase:
    """Canonical runtime-state database connection.

    Every connection:
      - PRAGMA foreign_keys = ON (verified)
      - PRAGMA journal_mode = WAL (verified)
      - PRAGMA synchronous = FULL (verified)
      - PRAGMA busy_timeout = 5000 (verified)

    connect() is idempotent — returns existing connection.
    Transactions are explicit. No auto-commit per statement.
    """

    def __init__(self, path: str | Path = DEFAULT_RUNTIME_DB_PATH):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn: sqlite3.Connection | None = None

    def connect(self) -> sqlite3.Connection:
        """Open connection and enforce all safety pragmas.

        Idempotent: returns existing connection if already open.
        Fails closed on any pragma violation.
        """
        # ── P5: idempotent — return existing connection ──────────
        if self.conn is not None:
            return self.conn

        conn = sqlite3.connect(str(self.path))
        conn.row_factory = sqlite3.Row

        try:
            conn.execute("PRAGMA foreign_keys = ON")
            conn.execute("PRAGMA busy_timeout = 5000")
            conn.execute("PRAGMA synchronous = FULL")
            conn.execute("PRAGMA journal_mode = WAL")

            # ── P6: verify ALL pragmas ──────────────────────────
            fk = conn.execute("PRAGMA foreign_keys").fetchone()[0]
            if fk != 1:
                raise RuntimePersistenceError(f"foreign_keys is {fk}, expected 1")

            wal = conn.execute("PRAGMA journal_mode").fetchone()[0]
            if wal.lower() != "wal":
                raise RuntimePersistenceError(f"journal_mode is {wal}, expected wal")

            sync = conn.execute("PRAGMA synchronous").fetchone()[0]
            if sync != 2:
                raise RuntimePersistenceError(f"synchronous is {sync}, expected 2 (FULL)")

            bt = conn.execute("PRAGMA busy_timeout").fetchone()[0]
            if bt != 5000:
                raise RuntimePersistenceError(f"busy_timeout is {bt}, expected 5000")

        except Exception:
            conn.close()
            raise

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

        BEGIN (IMMEDIATE or DEFERRED) → COMMIT on success, ROLLBACK on exception.
        immediate=False uses explicit BEGIN (deferred). Always explicit.
        Exception is re-raised — never swallowed.
        """
        @contextmanager
        def _tx():
            c = self.connection
            if immediate:
                c.execute("BEGIN IMMEDIATE")
            else:
                c.execute("BEGIN")
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
