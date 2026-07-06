"""Atomic persisted state transition executor.

Combines B4.1A reader, B4.1B policy, and RuntimeDatabase transaction
authority into a strict CAS-aware durable mutation layer.
"""
from __future__ import annotations

from atos.runtime_db import RuntimeDatabase, RuntimePersistenceError
from atos.runtime_state import (
    RuntimeSessionStatus, RuntimeCycleStatus, RecoveryStatus,
    RuntimeSessionRecord, RuntimeCycleRecord, RecoveryStateRecord,
)
from atos.runtime_state_reader import RuntimeStateReader
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
# Clock validation
# ═══════════════════════════════════════════════════════════════

def _validate_utc(at_utc):
    if not isinstance(at_utc, str):
        raise RuntimeStateWriteError(f"at_utc must be str, got {type(at_utc).__name__}")
    if not (at_utc.endswith("Z") or "+00:00" in at_utc):
        raise RuntimeStateWriteError(f"at_utc must be UTC (Z or +00:00), got {at_utc!r}")


# ═══════════════════════════════════════════════════════════════
# RuntimeStateWriter
# ═══════════════════════════════════════════════════════════════

class RuntimeStateWriter:
    """Atomic CAS persisted state transition executor.

    Reads persisted state, validates transition via B4.1B policy,
    executes conditional UPDATE within BEGIN IMMEDIATE transaction.
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
        _validate_utc(at_utc)

        with self._db.transaction(immediate=True) as conn:
            row = conn.execute(
                "SELECT status FROM runtime_sessions WHERE session_id = ?",
                (session_id,),
            ).fetchone()
            if row is None:
                raise RuntimeStateWriteError(f"session {session_id} not found")
            try:
                actual = RuntimeSessionStatus(row["status"])
            except (KeyError, ValueError) as e:
                raise RuntimeStateWriteError(f"Corrupt session status: {e}") from e

            # P1: Already at target — return as-is (idempotent)
            if actual == target:
                return self._reader.get_session(session_id)

            if actual != expected_current:
                raise ConcurrentStateTransitionError(
                    f"session {session_id}: expected {expected_current.value}, actual {actual.value}"
                )

            validate_session_transition(expected_current, target)

            if target == RuntimeSessionStatus.STOPPED:
                cur = conn.execute(
                    "UPDATE runtime_sessions SET status=?, stopped_at=?, stop_reason=? WHERE session_id=? AND status=?",
                    (target.value, at_utc, stop_reason, session_id, expected_current.value),
                )
            else:
                cur = conn.execute(
                    "UPDATE runtime_sessions SET status=? WHERE session_id=? AND status=?",
                    (target.value, session_id, expected_current.value),
                )
            if cur.rowcount != 1:
                raise ConcurrentStateTransitionError(
                    f"session {session_id}: CAS rowcount {cur.rowcount} != 1"
                )

        return self._reader.get_session(session_id)

