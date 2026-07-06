"""Pure state transition policy — deterministic validation only.

Zero dependencies: no sqlite3, no RuntimeDatabase, no filesystem, no network.
Input: exact enum instances → output: None (valid) or InvalidStateTransitionError.
"""
from __future__ import annotations

from types import MappingProxyType
from atos.runtime_state import RuntimeSessionStatus, RuntimeCycleStatus, RecoveryStatus


class InvalidStateTransitionError(ValueError):
    """State transition is not allowed by the authoritative policy."""


# ═══════════════════════════════════════════════════════════════
# Session transition graph (immutable)
# ═══════════════════════════════════════════════════════════════

SESSION_GRAPH = MappingProxyType({
    RuntimeSessionStatus.STARTING: frozenset({
        RuntimeSessionStatus.RECOVERING,
        RuntimeSessionStatus.STOPPED,
    }),
    RuntimeSessionStatus.RECOVERING: frozenset({
        RuntimeSessionStatus.READY,
        RuntimeSessionStatus.PAUSED_RECOVERY_REQUIRED,
        RuntimeSessionStatus.STOPPED,
    }),
    RuntimeSessionStatus.READY: frozenset({
        RuntimeSessionStatus.RUNNING,
        RuntimeSessionStatus.PAUSED,
        RuntimeSessionStatus.STOPPED,
    }),
    RuntimeSessionStatus.RUNNING: frozenset({
        RuntimeSessionStatus.PAUSED,
        RuntimeSessionStatus.PAUSED_RECOVERY_REQUIRED,
        RuntimeSessionStatus.STOPPED,
    }),
    RuntimeSessionStatus.PAUSED: frozenset({
        RuntimeSessionStatus.RUNNING,
        RuntimeSessionStatus.RECOVERING,
        RuntimeSessionStatus.PAUSED_RECOVERY_REQUIRED,
        RuntimeSessionStatus.STOPPED,
    }),
    RuntimeSessionStatus.PAUSED_RECOVERY_REQUIRED: frozenset({
        RuntimeSessionStatus.RECOVERING,
        RuntimeSessionStatus.STOPPED,
    }),
    RuntimeSessionStatus.STOPPED: frozenset(),
})


# ═══════════════════════════════════════════════════════════════
# Cycle transition graph — strict forward-only chain
# ═══════════════════════════════════════════════════════════════

CYCLE_SEQUENCE = (
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
)

CYCLE_GRAPH = MappingProxyType({
    status: frozenset({CYCLE_SEQUENCE[i + 1]}) if i + 1 < len(CYCLE_SEQUENCE) else frozenset()
    for i, status in enumerate(CYCLE_SEQUENCE)
})


# ═══════════════════════════════════════════════════════════════
# Recovery transition graph
# ═══════════════════════════════════════════════════════════════

RECOVERY_GRAPH = MappingProxyType({
    RecoveryStatus.PENDING: frozenset({RecoveryStatus.IN_PROGRESS}),
    RecoveryStatus.IN_PROGRESS: frozenset({RecoveryStatus.RESOLVED, RecoveryStatus.FAILED}),
    RecoveryStatus.FAILED: frozenset({RecoveryStatus.IN_PROGRESS}),
    RecoveryStatus.RESOLVED: frozenset(),
})


# ═══════════════════════════════════════════════════════════════
# Public validation API
# ═══════════════════════════════════════════════════════════════

def validate_session_transition(
    current: RuntimeSessionStatus,
    target: RuntimeSessionStatus,
) -> None:
    """Raise InvalidStateTransitionError if transition is not allowed."""
    if not isinstance(current, RuntimeSessionStatus):
        raise TypeError(f"current must be RuntimeSessionStatus, got {type(current).__name__}")
    if not isinstance(target, RuntimeSessionStatus):
        raise TypeError(f"target must be RuntimeSessionStatus, got {type(target).__name__}")
    if current == target:
        raise InvalidStateTransitionError(f"self-transition {current.value} → {target.value}")
    allowed = SESSION_GRAPH.get(current, frozenset())
    if target not in allowed:
        raise InvalidStateTransitionError(f"{current.value} → {target.value}")


def validate_cycle_transition(
    current: RuntimeCycleStatus,
    target: RuntimeCycleStatus,
) -> None:
    """Raise InvalidStateTransitionError if transition is not allowed."""
    if not isinstance(current, RuntimeCycleStatus):
        raise TypeError(f"current must be RuntimeCycleStatus, got {type(current).__name__}")
    if not isinstance(target, RuntimeCycleStatus):
        raise TypeError(f"target must be RuntimeCycleStatus, got {type(target).__name__}")
    if current == target:
        raise InvalidStateTransitionError(f"self-transition {current.value} → {target.value}")
    allowed = CYCLE_GRAPH.get(current, frozenset())
    if target not in allowed:
        raise InvalidStateTransitionError(f"{current.value} → {target.value}")


def validate_recovery_transition(
    current: RecoveryStatus,
    target: RecoveryStatus,
) -> None:
    """Raise InvalidStateTransitionError if transition is not allowed."""
    if not isinstance(current, RecoveryStatus):
        raise TypeError(f"current must be RecoveryStatus, got {type(current).__name__}")
    if not isinstance(target, RecoveryStatus):
        raise TypeError(f"target must be RecoveryStatus, got {type(target).__name__}")
    if current == target:
        raise InvalidStateTransitionError(f"self-transition {current.value} → {target.value}")
    allowed = RECOVERY_GRAPH.get(current, frozenset())
    if target not in allowed:
        raise InvalidStateTransitionError(f"{current.value} → {target.value}")
