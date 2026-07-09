"""Typed runtime state model — enums + immutable records only."""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


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


def _utc():
    return datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z")


class RecoveryStatus(StrEnum):
    PENDING = "PENDING"
    IN_PROGRESS = "IN_PROGRESS"
    RESOLVED = "RESOLVED"
    FAILED = "FAILED"


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
    completed_at: str | None
    status: RuntimeCycleStatus
    last_completed_stage: RuntimeCycleStatus | None
    last_error: str | None


@dataclass(frozen=True)
class JournalRecord:
    journal_id: int
    cycle_id: str
    from_state: RuntimeCycleStatus
    to_state: RuntimeCycleStatus
    recorded_at: str

class RecoveryStateRecord:
    recovery_id: str
    session_id: str
    status: RecoveryStatus
    unresolved_items: tuple
    started_at: str
    recovered_at: str | None = None
