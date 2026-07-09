"""Atomic persisted state transition executor."""
from __future__ import annotations
import contextlib
from datetime import datetime, timedelta, timezone
from atos.runtime_db import RuntimeDatabase, RuntimePersistenceError
from atos.runtime_state import RuntimeSessionStatus, RuntimeCycleStatus, RecoveryStatus
from atos.runtime_state_reader import RuntimeStateReader, StateRecordNotFoundError, StateDataCorruptionError
from atos.runtime_state_transitions import InvalidStateTransitionError
from atos.runtime_state_transitions import validate_session_transition, validate_cycle_transition, validate_recovery_transition

__all__ = ("RuntimeStateWriter", "CycleJournalRepository", "ConcurrentStateTransitionError", "RuntimeStateWriteError")

class RuntimeStateWriteError(RuntimePersistenceError):
    """Base for all write-layer errors."""

class ConcurrentStateTransitionError(RuntimeStateWriteError):
    """Persisted status does not match expected_current."""

def _check_type(obj, expected, label):
    if type(obj) is not expected:
        raise RuntimeStateWriteError(f"{label} must be {expected.__name__}, got {type(obj).__name__}")

def _normalize_utc(at_utc):
    if not isinstance(at_utc, str):
        raise RuntimeStateWriteError(f"at_utc must be str, got {type(at_utc).__name__}")
    candidate = at_utc[:-1] + "+00:00" if at_utc.endswith("Z") else at_utc
    try:
        parsed = datetime.fromisoformat(candidate)
    except (ValueError, TypeError) as exc:
        raise RuntimeStateWriteError(f"Invalid UTC timestamp: {at_utc!r}") from exc
    if parsed.tzinfo is None:
        raise RuntimeStateWriteError(f"Naive timestamp rejected: {at_utc!r}")
    if parsed.utcoffset() != timedelta(0):
        raise RuntimeStateWriteError(f"Non-UTC offset rejected: {at_utc!r}")
    return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")

class CycleJournalRepository:
    def __init__(self, db, clock=None):
        self._db=db
        self._clock=clock
        self._connection=None
        self._owns=True
    def connect(self, conn):
        r=CycleJournalRepository(self._db,self._clock)
        r._connection=conn
        r._owns=False
        return r
    @property
    def conn(self):
        return self._connection if self._connection is not None else self._db.connection
    @contextlib.contextmanager
    def _write_scope(self):
        if not self._owns:
            assert self._connection is not None
            yield self._connection
        else:
            with self._db.transaction(immediate=True) as conn:
                yield conn
    def _append_transition(self, conn, cycle_id, from_state, to_state, recorded_at):
        fv=str(from_state.value) if hasattr(from_state,"value") else str(from_state)
        tv=str(to_state.value) if hasattr(to_state,"value") else str(to_state)
        if not isinstance(recorded_at,str) or not recorded_at.endswith("Z"):
            raise RuntimeStateWriteError(f"recorded_at must be UTC Z: {recorded_at!r}")
        conn.execute("INSERT INTO cycle_journal (cycle_id, from_state, to_state, recorded_at) VALUES (?,?,?,?)",(cycle_id,fv,tv,recorded_at))

    def get_journal(self, cycle_id):
        rows=self.conn.execute("SELECT journal_id, cycle_id, from_state, to_state, recorded_at FROM cycle_journal WHERE cycle_id=? ORDER BY journal_id ASC",(cycle_id,)).fetchall()
        from atos.runtime_state import JournalRecord, RuntimeCycleStatus
        return [JournalRecord(journal_id=int(r["journal_id"]),cycle_id=r["cycle_id"],from_state=RuntimeCycleStatus(r["from_state"]),to_state=RuntimeCycleStatus(r["to_state"]),recorded_at=r["recorded_at"]) for r in rows]

class RuntimeStateWriter:
    def __init__(self, db: RuntimeDatabase):
        self._db = db
        self._reader = RuntimeStateReader(db)

    def transition_session(self, session_id, expected_current, target, *, at_utc, stop_reason=None):
        _check_type(expected_current, RuntimeSessionStatus, "expected_current")
        _check_type(target, RuntimeSessionStatus, "target")
        if stop_reason is not None and not isinstance(stop_reason, str):
            raise RuntimeStateWriteError(f"stop_reason must be str or None, got {type(stop_reason).__name__}")
        at_norm = _normalize_utc(at_utc)
        result = None
        with self._db.transaction(immediate=True) as conn:
            row = conn.execute("SELECT status FROM runtime_sessions WHERE session_id=?", (session_id,)).fetchone()
            if row is None:
                raise StateRecordNotFoundError(f"session {session_id}")
            try:
                actual = RuntimeSessionStatus(row["status"])
            except (KeyError, IndexError, TypeError, ValueError) as e:
                raise StateDataCorruptionError(f"Corrupt session status: {e}") from e
            if actual != expected_current:
                raise ConcurrentStateTransitionError(f"session {session_id}: expected {expected_current.value}, actual {actual.value}")
            validate_session_transition(actual, target)
            if target == RuntimeSessionStatus.STOPPED:
                cur = conn.execute(
                    "UPDATE runtime_sessions SET status=?, stopped_at=?, stop_reason=? WHERE session_id=? AND status=?",
                    (target.value, at_norm, stop_reason, session_id, actual.value))
            else:
                cur = conn.execute(
                    "UPDATE runtime_sessions SET status=? WHERE session_id=? AND status=?",
                    (target.value, session_id, actual.value))
            if cur.rowcount != 1:
                raise ConcurrentStateTransitionError(f"session {session_id}: CAS rowcount {cur.rowcount}")
            row2 = conn.execute("SELECT status FROM runtime_sessions WHERE session_id=?", (session_id,)).fetchone()
            if row2 is None or row2["status"] != target.value:
                raise RuntimeStateWriteError(f"session {session_id}: re-read failed")
            result = self._reader.get_session(session_id)
        return result

    def transition_cycle(self, cycle_id, expected_current, target, *, at_utc):
        _check_type(expected_current, RuntimeCycleStatus, "expected_current")
        _check_type(target, RuntimeCycleStatus, "target")
        at_norm = _normalize_utc(at_utc)
        result = None
        with self._db.transaction(immediate=True) as conn:
            row = conn.execute("SELECT status FROM runtime_cycles WHERE cycle_id=?", (cycle_id,)).fetchone()
            if row is None:
                raise StateRecordNotFoundError(f"cycle {cycle_id}")
            try:
                actual = RuntimeCycleStatus(row["status"])
            except (KeyError, IndexError, TypeError, ValueError) as e:
                raise StateDataCorruptionError(f"Corrupt cycle status: {e}") from e
            if actual != expected_current:
                raise ConcurrentStateTransitionError(f"cycle {cycle_id}: expected {expected_current.value}, actual {actual.value}")
            validate_cycle_transition(actual, target)
            if target == RuntimeCycleStatus.COMPLETED:
                cur = conn.execute(
                    "UPDATE runtime_cycles SET status=?,last_completed_stage=?,completed_at=? WHERE cycle_id=? AND status=?",
                    (target.value, target.value, at_norm, cycle_id, actual.value))
            else:
                cur = conn.execute(
                    "UPDATE runtime_cycles SET status=?,last_completed_stage=? WHERE cycle_id=? AND status=?",
                    (target.value, target.value, cycle_id, actual.value))
            if cur.rowcount != 1:
                raise ConcurrentStateTransitionError(f"cycle {cycle_id}: CAS rowcount {cur.rowcount}")
            result = self._reader.get_cycle(cycle_id)
            CycleJournalRepository(self._db, clock=lambda: at_norm)._append_transition(conn=conn,
                cycle_id=result.cycle_id,
                from_state=actual, to_state=target,
    recorded_at=at_norm,
            )
        return result

    def transition_recovery(self, recovery_id, expected_current, target, *, at_utc):
        _check_type(expected_current, RecoveryStatus, "expected_current")
        _check_type(target, RecoveryStatus, "target")
        at_norm = _normalize_utc(at_utc)
        result = None
        with self._db.transaction(immediate=True) as conn:
            row = conn.execute("SELECT status FROM recovery_states WHERE recovery_id=?", (recovery_id,)).fetchone()
            if row is None:
                raise StateRecordNotFoundError(f"recovery {recovery_id}")
            try:
                actual = RecoveryStatus(row["status"])
            except (KeyError, IndexError, TypeError, ValueError) as e:
                raise StateDataCorruptionError(f"Corrupt recovery status: {e}") from e
            if actual != expected_current:
                raise ConcurrentStateTransitionError(f"recovery {recovery_id}: expected {expected_current.value}, actual {actual.value}")
            validate_recovery_transition(actual, target)
            if target == RecoveryStatus.RESOLVED:
                cur = conn.execute(
                    "UPDATE recovery_states SET status=?,recovered_at=? WHERE recovery_id=? AND status=?",
                    (target.value, at_norm, recovery_id, actual.value))
            else:
                cur = conn.execute(
                    "UPDATE recovery_states SET status=? WHERE recovery_id=? AND status=?",
                    (target.value, recovery_id, actual.value))
            if cur.rowcount != 1:
                raise ConcurrentStateTransitionError(f"recovery {recovery_id}: CAS rowcount {cur.rowcount}")
            result = self._reader.get_recovery(recovery_id)
        return result
