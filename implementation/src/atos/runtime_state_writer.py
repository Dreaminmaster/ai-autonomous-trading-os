"""Atomic persisted state transition executor.

Combines B4.1A reader, B4.1B policy, and RuntimeDatabase transaction
authority into a strict CAS-aware durable mutation layer.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from atos.runtime_db import RuntimeDatabase, RuntimePersistenceError
from atos.runtime_state import (
    RuntimeSessionStatus, RuntimeCycleStatus, RecoveryStatus,
    RuntimeSessionRecord, RuntimeCycleRecord, RecoveryStateRecord,
)
from atos.runtime_state_reader import (
    RuntimeStateReader, StateRecordNotFoundError, StateDataCorruptionError,
)
from atos.runtime_state_transitions import (
    InvalidStateTransitionError,
    validate_session_transition,
    validate_cycle_transition,
    validate_recovery_transition,
)


__all__ = (
    "RuntimeStateWriter",
    "ConcurrentStateTransitionError",
    "RuntimeStateWriteError",
)


# ═══════════════════════════════════════════════════════════════
# Exception hierarchy
# ═══════════════════════════════════════════════════════════════

class RuntimeStateWriteError(RuntimePersistenceError):
    """Base for all write-layer errors."""


class ConcurrentStateTransitionError(RuntimeStateWriteError):
    """Persisted status does not match expected_current."""


# ═══════════════════════════════════════════════════════════════
# UTC clock normalization (P2)
# ═══════════════════════════════════════════════════════════════

def _normalize_utc(at_utc: str) -> str:
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


# ═══════════════════════════════════════════════════════════════
# RuntimeStateWriter
# ═══════════════════════════════════════════════════════════════

class RuntimeStateWriter:
    """Atomic CAS persisted state transition executor.

    Reads persisted state, validates transition via B4.1B policy,
    executes conditional UPDATE within BEGIN IMMEDIATE transaction.
    Re-reads result within the SAME transaction before commit.
    """

    def __init__(self, db: RuntimeDatabase):
        self._db = db
        self._reader = RuntimeStateReader(db)

    # ── Session ───────────────────────────────────────────────

    def transition_session(
        self,
        session_id: str,
        expected_current: RuntimeSessionStatus,
        target: RuntimeSessionStatus,
        *,
        at_utc: str,
        stop_reason: str | None = None,
    ) -> RuntimeSessionRecord:
        at_norm = _normalize_utc(at_utc)
        result = None

        with self._db.transaction(immediate=True) as conn:
            row = conn.execute(
                "SELECT status FROM runtime_sessions WHERE session_id = ?",
                (session_id,),
            ).fetchone()
            if row is None:
                raise RuntimeStateWriteError(f"session {session_id} not found")
            try:
                actual = RuntimeSessionStatus(row["status"])
            except (KeyError, IndexError, TypeError, ValueError) as e:
                raise StateDataCorruptionError(f"Corrupt session status: {e}") from e

            if actual != expected_current:
                raise ConcurrentStateTransitionError(
                    f"session {session_id}: expected {expected_current.value}, actual {actual.value}"
                )

            validate_session_transition(actual, target)

            if target == RuntimeSessionStatus.STOPPED:
                cur = conn.execute(
                    "UPDATE runtime_sessions SET status=?, stopped_at=?, stop_reason=? WHERE session_id=? AND status=?",
                    (target.value, at_norm, stop_reason, session_id, actual.value),
                )
            else:
                cur = conn.execute(
                    "UPDATE runtime_sessions SET status=? WHERE session_id=? AND status=?",
                    (target.value, session_id, actual.value),
                )
            if cur.rowcount != 1:
                raise ConcurrentStateTransitionError(
                    f"session {session_id}: CAS rowcount {cur.rowcount}"
                )

            result = self._reader.get_session(session_id)

        return result

    # ── Cycle ─────────────────────────────────────────────────

    def transition_cycle(
        self,
        cycle_id: str,
        expected_current: RuntimeCycleStatus,
        target: RuntimeCycleStatus,
        *,
        at_utc: str,
    ) -> RuntimeCycleRecord:
        at_norm = _normalize_utc(at_utc)
        result = None

        with self._db.transaction(immediate=True) as conn:
            row = conn.execute(
                "SELECT status FROM runtime_cycles WHERE cycle_id = ?",
                (cycle_id,),
            ).fetchone()
            if row is None:
                raise RuntimeStateWriteError(f"cycle {cycle_id} not found")
            try:
                actual = RuntimeCycleStatus(row["status"])
            except (KeyError, IndexError, TypeError, ValueError) as e:
                raise StateDataCorruptionError(f"Corrupt cycle status: {e}") from e

            if actual != expected_current:
                raise ConcurrentStateTransitionError(
                    f"cycle {cycle_id}: expected {expected_current.value}, actual {actual.value}"
                )

            validate_cycle_transition(actual, target)

            if target == RuntimeCycleStatus.COMPLETED:
                cur = conn.execute(
                    "UPDATE runtime_cycles SET status=?, last_completed_stage=?, completed_at=? WHERE cycle_id=? AND status=?",
                    (target.value, target.value, at_norm, cycle_id, actual.value),
                )
            else:
                cur = conn.execute(
                    "UPDATE runtime_cycles SET status=?, last_completed_stage=? WHERE cycle_id=? AND status=?",
                    (target.value, target.value, cycle_id, actual.value),
                )
            if cur.rowcount != 1:
                raise ConcurrentStateTransitionError(
                    f"cycle {cycle_id}: CAS rowcount {cur.rowcount}"
                )

            result = self._reader.get_cycle(cycle_id)

        return result

    # ── Recovery ──────────────────────────────────────────────

    def transition_recovery(
        self,
        recovery_id: str,
        expected_current: RecoveryStatus,
        target: RecoveryStatus,
        *,
        at_utc: str,
    ) -> RecoveryStateRecord:
        at_norm = _normalize_utc(at_utc)
        result = None

        with self._db.transaction(immediate=True) as conn:
            row = conn.execute(
                "SELECT status FROM recovery_states WHERE recovery_id = ?",
                (recovery_id,),
            ).fetchone()
            if row is None:
                raise RuntimeStateWriteError(f"recovery {recovery_id} not found")
            try:
                actual = RecoveryStatus(row["status"])
            except (KeyError, IndexError, TypeError, ValueError) as e:
                raise StateDataCorruptionError(f"Corrupt recovery status: {e}") from e

            if actual != expected_current:
                raise ConcurrentStateTransitionError(
                    f"recovery {recovery_id}: expected {expected_current.value}, actual {actual.value}"
                )

            validate_recovery_transition(actual, target)

            if target == RecoveryStatus.RESOLVED:
                cur = conn.execute(
                    "UPDATE recovery_states SET status=?, recovered_at=? WHERE recovery_id=? AND status=?",
                    (target.value, at_norm, recovery_id, actual.value),
                )
            else:
                cur = conn.execute(
                    "UPDATE recovery_states SET status=? WHERE recovery_id=? AND status=?",
                    (target.value, recovery_id, actual.value),
                )
            if cur.rowcount != 1:
                raise ConcurrentStateTransitionError(
                    f"recovery {recovery_id}: CAS rowcount {cur.rowcount}"
                )

            result = self._reader.get_recovery(recovery_id)

        return result
