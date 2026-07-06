"""Read-only runtime state query layer.

Design constraints:
  - Strict typed row mappers: row["col"] only
  - Strict recovery JSON parsing
  - No create/update/delete/transition/transaction
  - No MigrationManager.migrate()
"""
from __future__ import annotations

import json
from atos.runtime_db import RuntimePersistenceError
from atos.runtime_state import (
    RuntimeMode, RuntimeSessionStatus, RuntimeCycleStatus, RecoveryStatus,
    RuntimeSessionRecord, RuntimeCycleRecord, RecoveryStateRecord,
)


# ═══════════════════════════════════════════════════════════════
# Exception hierarchy (P3)
# ═══════════════════════════════════════════════════════════════

class RuntimeStateReadError(RuntimePersistenceError):
    """Base for all read-layer errors."""


class StateRecordNotFoundError(RuntimeStateReadError):
    """Entity not found."""


class StateDataCorruptionError(RuntimeStateReadError):
    """Stored data is irrecoverably corrupt."""


# ═══════════════════════════════════════════════════════════════
# Strict typed row mappers (P3)
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
        raise StateDataCorruptionError(f"Corrupt session row: {e}")


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
        raise StateDataCorruptionError(f"Corrupt cycle row: {e}")


def _recovery_from_row(row):
    try:
        items = _parse_unresolved_items(row["unresolved_items"])
        return RecoveryStateRecord(
            recovery_id=row["recovery_id"],
            session_id=row["session_id"],
            status=RecoveryStatus(row["status"]),
            unresolved_items=items,
            started_at=row["started_at"],
            recovered_at=row["recovered_at"],
        )
    except (KeyError, IndexError, TypeError, ValueError) as e:
        raise StateDataCorruptionError(f"Corrupt recovery row: {e}")


# ═══════════════════════════════════════════════════════════════
# Strict recovery JSON (P4)
# ═══════════════════════════════════════════════════════════════

def _parse_unresolved_items(raw):
    """A: not str → corrupt. B: empty str → corrupt. C: json.loads fail → corrupt. D: not list → corrupt. E: list → tuple."""
    if not isinstance(raw, str):
        raise StateDataCorruptionError(f"unresolved_items is {type(raw).__name__}, expected str")
    if raw == "":
        raise StateDataCorruptionError("unresolved_items is empty string")
    try:
        decoded = json.loads(raw)
    except (json.JSONDecodeError, TypeError, UnicodeError) as e:
        raise StateDataCorruptionError(f"unresolved_items JSON parse failed: {e}")
    if not isinstance(decoded, list):
        raise StateDataCorruptionError(f"unresolved_items decoded to {type(decoded).__name__}, expected list")
    return tuple(decoded)


def _dump_items(items):
    """Canonical JSON dump for unresolved_items (used only in tests)."""
    if items is None:
        return "[]"
    if not isinstance(items, list):
        raise StateDataCorruptionError(f"items must be list, got {type(items).__name__}")
    return json.dumps(items, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


# ═══════════════════════════════════════════════════════════════
# RuntimeStateReader (P5 — read-only)
# ═══════════════════════════════════════════════════════════════

class RuntimeStateReader:
    """Read-only typed queries over the runtime state DB.

    Requires a pre-migrated RuntimeDatabase.
    Does NOT run migrations. Does NOT create/update/delete/transition.
    """

    def __init__(self, db_connection):
        self._conn = db_connection

    # ── Session queries ───────────────────────────────────────

    def get_session(self, session_id):
        row = self._conn.execute(
            "SELECT session_id, started_at, mode, status, stopped_at, stop_reason"
            "  FROM runtime_sessions WHERE session_id = ?",
            (session_id,),
        ).fetchone()
        if row is None:
            raise StateRecordNotFoundError(f"session {session_id}")
        return _session_from_row(row)

    def list_open_sessions(self):
        rows = self._conn.execute(
            "SELECT session_id, started_at, mode, status, stopped_at, stop_reason"
            "  FROM runtime_sessions WHERE status != ?"
            "  ORDER BY started_at ASC, session_id ASC",
            (RuntimeSessionStatus.STOPPED.value,),
        ).fetchall()
        return [_session_from_row(r) for r in rows]

    # ── Cycle queries ────────────────────────────────────────

    def get_cycle(self, cycle_id):
        row = self._conn.execute(
            "SELECT cycle_id, session_id, symbol, started_at, completed_at, status, last_completed_stage, last_error"
            "  FROM runtime_cycles WHERE cycle_id = ?",
            (cycle_id,),
        ).fetchone()
        if row is None:
            raise StateRecordNotFoundError(f"cycle {cycle_id}")
        return _cycle_from_row(row)

    def list_incomplete_cycles(self):
        rows = self._conn.execute(
            "SELECT cycle_id, session_id, symbol, started_at, completed_at, status, last_completed_stage, last_error"
            "  FROM runtime_cycles WHERE status != ?"
            "  ORDER BY started_at ASC, cycle_id ASC",
            (RuntimeCycleStatus.COMPLETED.value,),
        ).fetchall()
        return [_cycle_from_row(r) for r in rows]

    # ── Recovery queries ──────────────────────────────────────

    def get_recovery(self, recovery_id):
        row = self._conn.execute(
            "SELECT recovery_id, session_id, status, unresolved_items, started_at, recovered_at"
            "  FROM recovery_states WHERE recovery_id = ?",
            (recovery_id,),
        ).fetchone()
        if row is None:
            raise StateRecordNotFoundError(f"recovery {recovery_id}")
        return _recovery_from_row(row)

    def list_unresolved_recoveries(self):
        rows = self._conn.execute(
            "SELECT recovery_id, session_id, status, unresolved_items, started_at, recovered_at"
            "  FROM recovery_states WHERE status != ?"
            "  ORDER BY started_at ASC, recovery_id ASC",
            (RecoveryStatus.RESOLVED.value,),
        ).fetchall()
        return [_recovery_from_row(r) for r in rows]
