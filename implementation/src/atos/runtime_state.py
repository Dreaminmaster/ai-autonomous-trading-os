"""Runtime state model — typed, immutable, with legal transition maps.

All records are immutable. Invalid data from DB must fail closed.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Callable


# ═══════════════════════════════════════════════════════════════
# Enums
# ═══════════════════════════════════════════════════════════════

class RuntimeMode(StrEnum):
    PAPER = "paper"
    SHADOW = "shadow"
    GUARDED = "guarded"


class RuntimeSessionStatus(StrEnum):
    STARTING = "STARTING"
    RECOVERING = "RECOVERING"
    READY = "READY"
    RUNNING = "RUNNING"
    PAUSED = "PAUSED"
    PAUSED_RECOVERY_REQUIRED = "PAUSED_RECOVERY_REQUIRED"
    STOPPED = "STOPPED"


class RuntimeCycleStatus(StrEnum):
    CREATED = "CREATED"
    MARKET_ACCEPTED = "MARKET_ACCEPTED"
    ACCOUNT_ACCEPTED = "ACCOUNT_ACCEPTED"
    CANDIDATES_READY = "CANDIDATES_READY"
    PROVIDER_DECIDED = "PROVIDER_DECIDED"
    RISK_DECIDED = "RISK_DECIDED"
    EXECUTION_INTENT_CREATED = "EXECUTION_INTENT_CREATED"
    EXECUTED = "EXECUTED"
    RECONCILED = "RECONCILED"
    COMPLETED = "COMPLETED"


class RecoveryStatus(StrEnum):
    PENDING = "PENDING"
    IN_PROGRESS = "IN_PROGRESS"
    RESOLVED = "RESOLVED"
    FAILED = "FAILED"


# ═══════════════════════════════════════════════════════════════
# Transition maps (canonical authority)
# ═══════════════════════════════════════════════════════════════

SESSION_TRANSITIONS = {
    RuntimeSessionStatus.STARTING: {
        RuntimeSessionStatus.RECOVERING,
        RuntimeSessionStatus.STOPPED,
    },
    RuntimeSessionStatus.RECOVERING: {
        RuntimeSessionStatus.READY,
        RuntimeSessionStatus.PAUSED_RECOVERY_REQUIRED,
        RuntimeSessionStatus.STOPPED,
    },
    RuntimeSessionStatus.READY: {
        RuntimeSessionStatus.RUNNING,
        RuntimeSessionStatus.PAUSED,
        RuntimeSessionStatus.PAUSED_RECOVERY_REQUIRED,
        RuntimeSessionStatus.STOPPED,
    },
    RuntimeSessionStatus.RUNNING: {
        RuntimeSessionStatus.PAUSED,
        RuntimeSessionStatus.PAUSED_RECOVERY_REQUIRED,
        RuntimeSessionStatus.STOPPED,
    },
    RuntimeSessionStatus.PAUSED: {
        RuntimeSessionStatus.RUNNING,
        RuntimeSessionStatus.PAUSED_RECOVERY_REQUIRED,
        RuntimeSessionStatus.STOPPED,
    },
    RuntimeSessionStatus.PAUSED_RECOVERY_REQUIRED: {
        RuntimeSessionStatus.RECOVERING,
        RuntimeSessionStatus.STOPPED,
    },
    RuntimeSessionStatus.STOPPED: set(),
}

CYCLE_SEQUENCE = [
    RuntimeCycleStatus.CREATED,
    RuntimeCycleStatus.MARKET_ACCEPTED,
    RuntimeCycleStatus.ACCOUNT_ACCEPTED,
    RuntimeCycleStatus.CANDIDATES_READY,
    RuntimeCycleStatus.PROVIDER_DECIDED,
    RuntimeCycleStatus.RISK_DECIDED,
    RuntimeCycleStatus.EXECUTION_INTENT_CREATED,
    RuntimeCycleStatus.EXECUTED,
    RuntimeCycleStatus.RECONCILED,
    RuntimeCycleStatus.COMPLETED,
]
CYCLE_INDEX = {s: i for i, s in enumerate(CYCLE_SEQUENCE)}

RECOVERY_TRANSITIONS = {
    RecoveryStatus.PENDING: {RecoveryStatus.IN_PROGRESS, RecoveryStatus.FAILED},
    RecoveryStatus.IN_PROGRESS: {RecoveryStatus.RESOLVED, RecoveryStatus.FAILED},
    RecoveryStatus.RESOLVED: set(),
    RecoveryStatus.FAILED: set(),
}


# ═══════════════════════════════════════════════════════════════
# Frozen dataclass records
# ═══════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class RuntimeSessionRecord:
    session_id: str
    started_at: str
    mode: RuntimeMode
    status: RuntimeSessionStatus
    stopped_at: str | None = None
    stop_reason: str | None = None


@dataclass(frozen=True)
class RuntimeCycleRecord:
    cycle_id: str
    session_id: str
    symbol: str
    started_at: str
    status: RuntimeCycleStatus
    completed_at: str | None = None
    last_completed_stage: RuntimeCycleStatus | None = None
    last_error: str | None = None


@dataclass(frozen=True)
class RecoveryStateRecord:
    recovery_id: str
    session_id: str
    status: RecoveryStatus
    unresolved_items: tuple
    started_at: str
    recovered_at: str | None = None


# ═══════════════════════════════════════════════════════════════
# Clock contract
# ═══════════════════════════════════════════════════════════════

_utc_clock: Callable[[], str] | None = None


def set_utc_clock(clock: Callable[[], str]) -> None:
    """Inject UTC clock for tests. Production uses default (real time)."""
    global _utc_clock
    _utc_clock = clock


def utc_now() -> str:
    """ISO-8601 UTC with trailing Z. Replaces utc_now in core.py for this module."""
    import datetime
    if _utc_clock is not None:
        return _utc_clock()
    return datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z")
