"""Typed repository layer for B1 runtime state entities.

Design constraints (B4.4):
  - No transition maps in the repository. No CAS rules in the DB layer.
  - _RepositoryBase._write_scope() for implicit BEGIN/COMMIT.
  - UoW provides shared tx_conn. Repos accept connection= in __init__.
  - State records are immutable frozen dataclasses.
  - get() returns RecordNotFoundError (not Optional).
  - _maybe_get() returns None (not throw).
"""
from __future__ import annotations

import contextlib
import json
import sqlite3
from atos.runtime_state import (
    RuntimeMode, RuntimeSessionStatus, RuntimeCycleStatus, RecoveryStatus,
    RuntimeSessionRecord, RuntimeCycleRecord, RecoveryStateRecord,
)


# ═══════════════════════════════════════════════════════════════
# Exceptions
# ═══════════════════════════════════════════════════════════════

class RepositoryError(Exception):
    """Base for all repository errors."""


class RecordNotFoundError(RepositoryError):
    """Entity not found."""


class IdempotencyConflictError(RepositoryError):
    """Idempotent create found a record with mismatched identity fields."""


class RepositoryDataCorruptionError(RepositoryError):
    """Stored data is irrecoverably corrupt."""


# ═══════════════════════════════════════════════════════════════
# Serialization helpers (P14-P15)
# ═══════════════════════════════════════════════════════════════

def _parse_items(raw):
    if not raw:
        return tuple()
    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, TypeError, UnicodeError) as e:
        raise RepositoryDataCorruptionError(f"Corrupt unresolved_items: {e}")
    if not isinstance(parsed, list):
        raise RepositoryDataCorruptionError(
            f"unresolved_items is {type(parsed).__name__}, expected list"
        )
    return tuple(parsed)


def _dump_items(items):
    if items is None:
        items = []
    if not isinstance(items, list):
        raise RepositoryDataCorruptionError(
            f"unresolved_items must be list, got {type(items).__name__}"
        )
    return json.dumps(items, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


# ═══════════════════════════════════════════════════════════════
# Typed row mappers
# ═══════════════════════════════════════════════════════════════

def _session_from_row(row):
    try:
        return RuntimeSessionRecord(
            session_id=row["session_id"],
            started_at=row["started_at"],
            mode=RuntimeMode(row["mode"]),
            status=RuntimeSessionStatus(row["status"]),
            stopped_at=row["stopped_at"],
            stop_reason=row["stop_reason"],
        )
    except (KeyError, IndexError, TypeError, ValueError) as e:
        raise RepositoryDataCorruptionError(f"Corrupt session row: {e}")


def _cycle_from_row(row):
    try:
        lcs = row["last_completed_stage"]
        return RuntimeCycleRecord(
            cycle_id=row["cycle_id"],
            session_id=row["session_id"],
            symbol=row["symbol"],
            started_at=row["started_at"],
            completed_at=row["completed_at"],
            status=RuntimeCycleStatus(row["status"]),
            last_completed_stage=RuntimeCycleStatus(lcs) if lcs else None,
            last_error=row["last_error"],
        )
    except (KeyError, IndexError, TypeError, ValueError) as e:
        raise RepositoryDataCorruptionError(f"Corrupt cycle row: {e}")


def _recovery_from_row(row):
    try:
        items = _parse_items(row["unresolved_items"])
        return RecoveryStateRecord(
            recovery_id=row["recovery_id"],
            session_id=row["session_id"],
            status=RecoveryStatus(row["status"]),
            unresolved_items=items,
            started_at=row["started_at"],
            recovered_at=row["recovered_at"],
        )
    except (KeyError, IndexError, TypeError, ValueError) as e:
        raise RepositoryDataCorruptionError(f"Corrupt recovery row: {e}")


# ═══════════════════════════════════════════════════════════════
# Repository base
# ═══════════════════════════════════════════════════════════════

class _RepositoryBase:
    """Transaction-aware repository kernel."""

    def __init__(self, db, clock, connection=None, owns_transaction=True):
        self._db = db
        self._clock = clock
        self._connection = connection
        self._owns = owns_transaction

    @property
    def conn(self):
        if self._connection is not None:
            return self._connection
        return self._db.connection

    @contextlib.contextmanager
    def _write_scope(self):
        if not self._owns:
            assert self._connection is not None
            yield self._connection
        else:
            with self._db.transaction(immediate=True) as conn:
                yield conn


# ═══════════════════════════════════════════════════════════════
# RuntimeSessionRepository
# ═══════════════════════════════════════════════════════════════

class RuntimeSessionRepository(_RepositoryBase):

    def _maybe_get(self, session_id):
        row = self.conn.execute(
            "SELECT session_id, started_at, mode, status, stopped_at, stop_reason FROM runtime_sessions WHERE session_id = ?",
            (session_id,),
        ).fetchone()
        return _session_from_row(row) if row else None

    def get(self, session_id):
        s = self._maybe_get(session_id)
        if s is None:
            raise RecordNotFoundError(f"session {session_id}")
        return s

    def create(self, session_id, mode, started_at=None):
        mode = RuntimeMode(mode)
        started_at = started_at or self._clock()
        existing = self._maybe_get(session_id)
        if existing is not None:
            if existing.mode == mode and existing.started_at == started_at:
                return existing
            raise IdempotencyConflictError(
                f"session {session_id} exists with mode={existing.mode.value}, requested {mode.value}"
            )
        with self._write_scope() as conn:
            conn.execute(
                "INSERT INTO runtime_sessions (session_id, started_at, mode, status) VALUES (?, ?, ?, ?)",
                (session_id, started_at, mode.value, RuntimeSessionStatus.STARTING.value),
            )
        return self.get(session_id)

    def transition(self, session_id, expected, target, stop_reason=None):
        target_st = RuntimeSessionStatus(target)
        if target_st == RuntimeSessionStatus.STOPPED and not stop_reason:
            raise ValueError("stop_reason is required when transitioning to STOPPED")
        with self._write_scope() as conn:
            row = conn.execute(
                "SELECT status FROM runtime_sessions WHERE session_id = ?",
                (session_id,),
            ).fetchone()
            if row is None:
                raise RecordNotFoundError(f"session {session_id}")
            if row["status"] == target:
                return self.get(session_id)
            if row["status"] != expected:
                raise ValueError(
                    f"Expected status {expected}, actual {row['status']}"
                )
            if target_st == RuntimeSessionStatus.STOPPED:
                conn.execute(
                    "UPDATE runtime_sessions SET status=?, stopped_at=?, stop_reason=? WHERE session_id=? AND status=?",
                    (target_st.value, self._clock(), stop_reason, session_id, row["status"]),
                )
            else:
                conn.execute(
                    "UPDATE runtime_sessions SET status=? WHERE session_id=? AND status=?",
                    (target_st.value, session_id, row["status"]),
                )
        return self.get(session_id)


# ═══════════════════════════════════════════════════════════════
# RuntimeCycleRepository
# ═══════════════════════════════════════════════════════════════

class RuntimeCycleRepository(_RepositoryBase):

    def _maybe_get(self, cycle_id):
        row = self.conn.execute(
            "SELECT cycle_id, session_id, symbol, started_at, completed_at, status, last_completed_stage, last_error FROM runtime_cycles WHERE cycle_id = ?",
            (cycle_id,),
        ).fetchone()
        return _cycle_from_row(row) if row else None

    def get(self, cycle_id):
        c = self._maybe_get(cycle_id)
        if c is None:
            raise RecordNotFoundError(f"cycle {cycle_id}")
        return c

    def create(self, cycle_id, session_id, symbol):
        with self._write_scope() as conn:
            conn.execute(
                "INSERT INTO runtime_cycles (cycle_id, session_id, symbol, started_at, status) VALUES (?, ?, ?, ?, ?)",
                (cycle_id, session_id, symbol, self._clock(), RuntimeCycleStatus.CREATED.value),
            )
        return self.get(cycle_id)

    def transition(self, cycle_id, expected, target):
        target_st = RuntimeCycleStatus(target)
        with self._write_scope() as conn:
            row = conn.execute(
                "SELECT status FROM runtime_cycles WHERE cycle_id = ?",
                (cycle_id,),
            ).fetchone()
            if row is None:
                raise RecordNotFoundError(f"cycle {cycle_id}")
            if row["status"] == target:
                return self.get(cycle_id)
            if row["status"] != expected:
                raise ValueError(
                    f"Expected status {expected}, actual {row['status']}"
                )
            conn.execute(
                "UPDATE runtime_cycles SET status=?, last_completed_stage=? WHERE cycle_id=? AND status=?",
                (target_st.value, expected, cycle_id, row["status"]),
            )
        return self.get(cycle_id)

    def record_error(self, cycle_id, expected, error_msg):
        with self._write_scope() as conn:
            row = conn.execute(
                "SELECT status FROM runtime_cycles WHERE cycle_id = ?",
                (cycle_id,),
            ).fetchone()
            if row is None:
                raise RecordNotFoundError(f"cycle {cycle_id}")
            if row["status"] != expected:
                raise ValueError(
                    f"Expected status {expected}, actual {row['status']}"
                )
            conn.execute(
                "UPDATE runtime_cycles SET last_error=? WHERE cycle_id=?",
                (str(error_msg)[:200], cycle_id),
            )
        return self.get(cycle_id)


# ═══════════════════════════════════════════════════════════════
# RecoveryStateRepository
# ═══════════════════════════════════════════════════════════════

class RecoveryStateRepository(_RepositoryBase):

    def _maybe_get(self, recovery_id):
        row = self.conn.execute(
            "SELECT recovery_id, session_id, status, unresolved_items, started_at, recovered_at FROM recovery_states WHERE recovery_id = ?",
            (recovery_id,),
        ).fetchone()
        return _recovery_from_row(row) if row else None

    def get(self, recovery_id):
        r = self._maybe_get(recovery_id)
        if r is None:
            raise RecordNotFoundError(f"recovery {recovery_id}")
        return r

    def create(self, recovery_id, session_id, items=None):
        items = items or []
        if not isinstance(items, list):
            raise RepositoryDataCorruptionError(
                f"unresolved_items must be list, got {type(items).__name__}"
            )
        with self._write_scope() as conn:
            conn.execute(
                "INSERT INTO recovery_states (recovery_id, session_id, status, unresolved_items, started_at) VALUES (?, ?, ?, ?, ?)",
                (recovery_id, session_id, RecoveryStatus.PENDING.value, _dump_items(items), self._clock()),
            )
        return self.get(recovery_id)


# ═══════════════════════════════════════════════════════════════
# RuntimeStateUnitOfWork
# ═══════════════════════════════════════════════════════════════

class RuntimeStateUnitOfWork:
    """Coordinates multiple repositories within a single outer transaction."""

    def __init__(self, db, clock=None):
        self.db = db
        self.clock = clock
        self._outer_tx = None
        self._tx_conn = None

    def __enter__(self):
        self._outer_tx = self.db.transaction(immediate=True)
        self._tx_conn = self._outer_tx.__enter__()
        self.sessions = RuntimeSessionRepository(
            self.db, self.clock, connection=self._tx_conn, owns_transaction=False
        )
        self.cycles = RuntimeCycleRepository(
            self.db, self.clock, connection=self._tx_conn, owns_transaction=False
        )
        self.recoveries = RecoveryStateRepository(
            self.db, self.clock, connection=self._tx_conn, owns_transaction=False
        )
        return self

    def __exit__(self, *args):
        if self._outer_tx:
            self._outer_tx.__exit__(*args)
