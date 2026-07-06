"""Repository layer — CAS concurrency, legal transitions, idempotent replay.

Works with RuntimeDatabase + typed runtime_state records.
"""
from __future__ import annotations

import json
import sqlite3
from typing import Callable

from atos.runtime_db import RuntimeDatabase, RuntimePersistenceError
from atos.runtime_state import (
    RuntimeMode, RuntimeSessionStatus, RuntimeCycleStatus, RecoveryStatus,
    RuntimeSessionRecord, RuntimeCycleRecord, RecoveryStateRecord,
    SESSION_TRANSITIONS, CYCLE_SEQUENCE, CYCLE_INDEX, RECOVERY_TRANSITIONS,
    utc_now,
)


# ═══════════════════════════════════════════════════════════════
# Exception hierarchy
# ═══════════════════════════════════════════════════════════════

class RuntimeRepositoryError(RuntimePersistenceError):
    pass


class RecordNotFoundError(RuntimeRepositoryError):
    pass


class IdempotencyConflictError(RuntimeRepositoryError):
    pass


class InvalidStateTransitionError(RuntimeRepositoryError):
    pass


class ConcurrentStateConflictError(RuntimeRepositoryError):
    pass


class RepositoryDataCorruptionError(RuntimeRepositoryError):
    pass


class RepositoryIntegrityError(RuntimeRepositoryError):
    pass


# ═══════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════

def _utc():
    return utc_now()


def _dump_items(items):
    return json.dumps(list(items), ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _parse_items(raw):
    try:
        items = json.loads(raw)
    except json.JSONDecodeError as e:
        raise RepositoryDataCorruptionError(f"unresolved_items not valid JSON: {e}") from e
    if not isinstance(items, list):
        raise RepositoryDataCorruptionError(f"unresolved_items is {type(items).__name__}, expected list")
    return tuple(items)


def _session_from_row(row):
    try:
        return RuntimeSessionRecord(
            session_id=row["session_id"],
            started_at=row["started_at"],
            mode=RuntimeMode(row["mode"]),
            status=RuntimeSessionStatus(row["status"]),
            stopped_at=row.get("stopped_at"),
            stop_reason=row.get("stop_reason"),
        )
    except (KeyError, ValueError) as e:
        raise RepositoryDataCorruptionError(f"Corrupt session row: {e}")


def _cycle_from_row(row):
    try:
        lcs = row["last_completed_stage"]
        return RuntimeCycleRecord(
            cycle_id=row["cycle_id"],
            session_id=row["session_id"],
            symbol=row["symbol"],
            started_at=row["started_at"],
            completed_at=row.get("completed_at"),
            status=RuntimeCycleStatus(row["status"]),
            last_completed_stage=RuntimeCycleStatus(lcs) if lcs else None,
            last_error=row.get("last_error"),
        )
    except (KeyError, ValueError) as e:
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
            recovered_at=row.get("recovered_at"),
        )
    except (KeyError, ValueError) as e:
        raise RepositoryDataCorruptionError(f"Corrupt recovery row: {e}")


    row = conn.execute(query, params).fetchone()
    if row is None:
        return None
    return klass(**dict(row))


# ═══════════════════════════════════════════════════════════════
# RuntimeSessionRepository
# ═══════════════════════════════════════════════════════════════

class RuntimeSessionRepository:
    def __init__(self, db: RuntimeDatabase, clock: Callable[[], str] = _utc):
        self.db = db
        self.clock = clock

    @property
    def conn(self):
        return self.db.connection

    def _maybe_get(self, session_id):
        row = self.conn.execute(
            "SELECT session_id, started_at, mode, status, stopped_at, stop_reason FROM runtime_sessions WHERE session_id = ?",
            (session_id,),
        ).fetchone()
        return _session_from_row(row) if row else None

    def create(self, session_id, mode, started_at=None):
        mode = RuntimeMode(mode)
        started_at = started_at or self.clock()
        existing = self._maybe_get(session_id)
        if existing:
            if existing.mode == mode and existing.started_at == started_at:
                return existing
            raise IdempotencyConflictError(f"session {session_id} exists with different identity")
        with self.db.transaction(immediate=True):
            try:
                self.conn.execute(
                    "INSERT INTO runtime_sessions (session_id, started_at, mode, status) VALUES (?,?,?,?)",
                    (session_id, started_at, mode.value, RuntimeSessionStatus.STARTING.value),
                )
            except sqlite3.IntegrityError as e:
                raise RepositoryIntegrityError(str(e)) from e
        return self.get(session_id)

    def get(self, session_id):
        row = self._maybe_get(session_id)
        if row is None:
            raise RecordNotFoundError(f"session {session_id}")
        return row

    def transition(self, session_id, expected_status, target_status, *, stop_reason=None):
        expected = RuntimeSessionStatus(expected_status)
        target = RuntimeSessionStatus(target_status)

        # Validate transition legality
        if target not in SESSION_TRANSITIONS.get(expected, set()):
            raise InvalidStateTransitionError(f"session {expected.value} → {target.value} not allowed")

        if target == RuntimeSessionStatus.STOPPED and not stop_reason:
            raise InvalidStateTransitionError("STOPPED requires stop_reason")

        current = self.get(session_id)
        if current.status == target:
            # Idempotent replay
            if target == RuntimeSessionStatus.STOPPED and current.stop_reason != stop_reason:
                raise IdempotencyConflictError(f"STOPPED with different reason")
            return current

        with self.db.transaction(immediate=True):
            cur = self.conn.cursor()
            now = self.clock()
            if target == RuntimeSessionStatus.STOPPED:
                cur.execute(
                    "UPDATE runtime_sessions SET status=?, stopped_at=?, stop_reason=? "
                    "WHERE session_id=? AND status=?",
                    (target.value, now, stop_reason, session_id, expected.value),
                )
            else:
                cur.execute(
                    "UPDATE runtime_sessions SET status=? WHERE session_id=? AND status=?",
                    (target.value, session_id, expected.value),
                )
            if cur.rowcount != 1:
                # CAS failure — re-read and diagnose
                current2 = self.get(session_id)
                if current2.status == target:
                    return current2  # idempotent replay
                raise ConcurrentStateConflictError(
                    f"Expected session {expected.value}, got {current2.status.value}"
                )

        return self.get(session_id)

    def list_open_sessions(self):
        rows = self.conn.execute(
            "SELECT session_id, started_at, mode, status, stopped_at, stop_reason FROM runtime_sessions "
            "WHERE status != ? ORDER BY started_at ASC, session_id ASC",
            (RuntimeSessionStatus.STOPPED.value,),
        ).fetchall()
        return [_session_from_row(r) for r in rows]


# ═══════════════════════════════════════════════════════════════
# RuntimeCycleRepository
# ═══════════════════════════════════════════════════════════════

class RuntimeCycleRepository:
    def __init__(self, db: RuntimeDatabase, clock: Callable[[], str] = _utc):
        self.db = db
        self.clock = clock

    @property
    def conn(self):
        return self.db.connection

    def create(self, cycle_id, session_id, symbol, started_at=None):
        started_at = started_at or self.clock()
        existing = self._maybe_get(cycle_id)
        if existing:
            if existing.session_id == session_id and existing.symbol == symbol and existing.started_at == started_at:
                return existing
            raise IdempotencyConflictError(f"cycle {cycle_id} exists with different identity")
        with self.db.transaction(immediate=True):
            try:
                self.conn.execute(
                    "INSERT INTO runtime_cycles (cycle_id, session_id, symbol, started_at, status) "
                    "VALUES (?,?,?,?,?)",
                    (cycle_id, session_id, symbol, started_at, RuntimeCycleStatus.CREATED.value),
                )
            except sqlite3.IntegrityError as e:
                raise RepositoryIntegrityError(str(e)) from e
        return self.get(cycle_id)

    def _maybe_get(self, cycle_id):
        row = self.conn.execute(
            "SELECT cycle_id, session_id, symbol, started_at, completed_at, status, "
            "last_completed_stage, last_error FROM runtime_cycles WHERE cycle_id = ?",
            (cycle_id,),
        ).fetchone()
        return _cycle_from_row(row) if row else None

    def get(self, cycle_id):
        row = self._maybe_get(cycle_id)
        if row is None:
            raise RecordNotFoundError(f"cycle {cycle_id}")
        return row

    def transition(self, cycle_id, expected_status, target_status):
        expected = RuntimeCycleStatus(expected_status)
        target = RuntimeCycleStatus(target_status)

        # Only exact next stage allowed
        exp_idx = CYCLE_INDEX.get(expected)
        tgt_idx = CYCLE_INDEX.get(target)
        if exp_idx is None or tgt_idx is None or tgt_idx != exp_idx + 1:
            raise InvalidStateTransitionError(f"cycle {expected.value} → {target.value} not allowed")

        current = self.get(cycle_id)
        if current.status == target:
            return current  # idempotent

        with self.db.transaction(immediate=True):
            now = self.clock()
            if target == RuntimeCycleStatus.COMPLETED:
                cur = self.conn.execute(
                    "UPDATE runtime_cycles SET status=?, last_completed_stage=?, completed_at=? "
                    "WHERE cycle_id=? AND status=?",
                    (target.value, target.value, now, cycle_id, expected.value),
                )
            else:
                cur = self.conn.execute(
                    "UPDATE runtime_cycles SET status=?, last_completed_stage=? "
                    "WHERE cycle_id=? AND status=?",
                    (target.value, target.value, cycle_id, expected.value),
                )
            if cur.rowcount != 1:
                current2 = self.get(cycle_id)
                if current2.status == target:
                    return current2
                raise ConcurrentStateConflictError(
                    f"Expected cycle {expected.value}, got {current2.status.value}"
                )
        return self.get(cycle_id)

    def record_error(self, cycle_id, expected_status, error):
        if not error or not error.strip():
            raise InvalidStateTransitionError("record_error requires non-empty error")
        expected = RuntimeCycleStatus(expected_status)
        with self.db.transaction(immediate=True):
            cur = self.conn.execute(
                "UPDATE runtime_cycles SET last_error=? WHERE cycle_id=? AND status=?",
                (error, cycle_id, expected.value),
            )
            if cur.rowcount != 1:
                raise ConcurrentStateConflictError("record_error CAS failed")
        return self.get(cycle_id)

    def list_incomplete(self, session_id):
        rows = self.conn.execute(
            "SELECT cycle_id, session_id, symbol, started_at, completed_at, status, "
            "last_completed_stage, last_error FROM runtime_cycles "
            "WHERE session_id=? AND status != ? ORDER BY started_at ASC, cycle_id ASC",
            (session_id, RuntimeCycleStatus.COMPLETED.value),
        ).fetchall()
        return [_cycle_from_row(r) for r in rows]


# ═══════════════════════════════════════════════════════════════
# RecoveryStateRepository
# ═══════════════════════════════════════════════════════════════

class RecoveryStateRepository:
    def __init__(self, db: RuntimeDatabase, clock: Callable[[], str] = _utc):
        self.db = db
        self.clock = clock

    @property
    def conn(self):
        return self.db.connection

    def create(self, recovery_id, session_id, unresolved_items, started_at=None):
        started_at = started_at or self.clock()
        items = _dump_items(unresolved_items)
        existing = self._maybe_get(recovery_id)
        if existing:
            if existing.status == RecoveryStatus.PENDING:
                if existing.session_id == session_id and existing.started_at == started_at:
                    if list(existing.unresolved_items) == list(unresolved_items):
                        return existing
            raise IdempotencyConflictError(f"recovery {recovery_id} exists with different identity")
        with self.db.transaction(immediate=True):
            try:
                self.conn.execute(
                    "INSERT INTO recovery_states (recovery_id, session_id, status, unresolved_items, started_at) "
                    "VALUES (?,?,?,?,?)",
                    (recovery_id, session_id, RecoveryStatus.PENDING.value, items, started_at),
                )
            except sqlite3.IntegrityError as e:
                raise RepositoryIntegrityError(str(e)) from e
        return self.get(recovery_id)

    def _maybe_get(self, recovery_id):
        row = self.conn.execute(
            "SELECT recovery_id, session_id, status, unresolved_items, started_at, recovered_at "
            "FROM recovery_states WHERE recovery_id = ?",
            (recovery_id,),
        ).fetchone()
        if row is None:
            return None
        d = dict(row)
        d["unresolved_items"] = _parse_items(d["unresolved_items"])
        return _recovery_from_row(row)

    def get(self, recovery_id):
        row = self._maybe_get(recovery_id)
        if row is None:
            raise RecordNotFoundError(f"recovery {recovery_id}")
        return row

    def transition(self, recovery_id, expected_status, target_status, *, unresolved_items=None):
        expected = RecoveryStatus(expected_status)
        target = RecoveryStatus(target_status)

        if target not in RECOVERY_TRANSITIONS.get(expected, set()):
            raise InvalidStateTransitionError(f"recovery {expected.value} → {target.value} not allowed")

        current = self.get(recovery_id)
        if current.status == target:
            return current  # replay

        if target == RecoveryStatus.RESOLVED:
            items = unresolved_items if unresolved_items is not None else list(current.unresolved_items)
            if list(items) != []:
                raise InvalidStateTransitionError("RESOLVED requires empty unresolved_items")

        with self.db.transaction(immediate=True):
            now = self.clock()
            if target == RecoveryStatus.RESOLVED:
                cur = self.conn.execute(
                    "UPDATE recovery_states SET status=?, unresolved_items='[]', recovered_at=? "
                    "WHERE recovery_id=? AND status=?",
                    (target.value, now, recovery_id, expected.value),
                )
            else:
                cur = self.conn.execute(
                    "UPDATE recovery_states SET status=? WHERE recovery_id=? AND status=?",
                    (target.value, recovery_id, expected.value),
                )
            if cur.rowcount != 1:
                current2 = self.get(recovery_id)
                if current2.status == target:
                    return current2
                raise ConcurrentStateConflictError("CAS failed")
        return self.get(recovery_id)

    def replace_unresolved_items(self, recovery_id, expected_status, unresolved_items):
        expected = RecoveryStatus(expected_status)
        items = _dump_items(unresolved_items)
        with self.db.transaction(immediate=True):
            cur = self.conn.execute(
                "UPDATE recovery_states SET unresolved_items=? WHERE recovery_id=? AND status=?",
                (items, recovery_id, expected.value),
            )
            if cur.rowcount != 1:
                raise ConcurrentStateConflictError("replace CAS failed")
        return self.get(recovery_id)

    def list_unresolved(self, session_id):
        rows = self.conn.execute(
            "SELECT recovery_id, session_id, status, unresolved_items, started_at, recovered_at "
            "FROM recovery_states "
            "WHERE session_id=? AND status != ? ORDER BY started_at ASC, recovery_id ASC",
            (session_id, RecoveryStatus.RESOLVED.value),
        ).fetchall()
        results = []
        for r in rows:
            d = dict(r)
            d["unresolved_items"] = _parse_items(d["unresolved_items"])
        return results


# ═══════════════════════════════════════════════════════════════
# RuntimeStateUnitOfWork
# ═══════════════════════════════════════════════════════════════

class RuntimeStateUnitOfWork:
    """Multi-repository atomic unit of work.

    All repositories share the same connection and transaction.
    Commit on success, rollback on exception.
    """

    def __init__(self, db: RuntimeDatabase, clock: Callable[[], str] = _utc):
        self.db = db
        self.clock = clock
        self._tx = None

    def __enter__(self):
        self._tx = self.db.transaction(immediate=True)
        self._tx.__enter__()
        self.sessions = RuntimeSessionRepository(self.db, self.clock)
        self.cycles = RuntimeCycleRepository(self.db, self.clock)
        self.recoveries = RecoveryStateRepository(self.db, self.clock)
        return self

    def __exit__(self, *args):
        if self._tx:
            self._tx.__exit__(*args)


# ═══════════════════════════════════════════════════════════════
# Unit of Work
# ═══════════════════════════════════════════════════════════════

