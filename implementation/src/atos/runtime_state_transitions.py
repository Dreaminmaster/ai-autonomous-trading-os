"""Pure deterministic state-transition policy.

No persistence, filesystem, clock, or network side effects.
"""
from __future__ import annotations

from types import MappingProxyType
from atos.runtime_state import RuntimeSessionStatus, RuntimeCycleStatus, RecoveryStatus


class InvalidStateTransitionError(ValueError):
    """State transition is not allowed by the authoritative policy."""


__all__ = (
    "InvalidStateTransitionError",
    "validate_session_transition",
    "validate_cycle_transition",
    "validate_recovery_transition",
)


# ═══════════════════════════════════════════════════════════════
# Private transition graphs — immutable
# ═══════════════════════════════════════════════════════════════

_SESSION_GRAPH = MappingProxyType({
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

_CYCLE_SEQUENCE = (
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

_CYCLE_GRAPH = MappingProxyType({
    status: frozenset({_CYCLE_SEQUENCE[i + 1]}) if i + 1 < len(_CYCLE_SEQUENCE) else frozenset()
    for i, status in enumerate(_CYCLE_SEQUENCE)
})

_RECOVERY_GRAPH = MappingProxyType({
    RecoveryStatus.PENDING: frozenset({RecoveryStatus.IN_PROGRESS}),
    RecoveryStatus.IN_PROGRESS: frozenset({RecoveryStatus.RESOLVED, RecoveryStatus.FAILED}),
    RecoveryStatus.FAILED: frozenset({RecoveryStatus.IN_PROGRESS}),
    RecoveryStatus.RESOLVED: frozenset(),
})


# ═══════════════════════════════════════════════════════════════
# Core validation logic
# ═══════════════════════════════════════════════════════════════

def _validate(current, target, allowed_graph, typename):
    if type(current) is not typename or type(target) is not typename:
        raise InvalidStateTransitionError(
            f"expected {typename.__name__}, got {type(current).__name__} → {type(target).__name__}"
        )
    if current == target:
        raise InvalidStateTransitionError(f"self-transition {current.value} → {target.value}")
    if target not in allowed_graph.get(current, frozenset()):
        raise InvalidStateTransitionError(f"{current.value} → {target.value}")


# ═══════════════════════════════════════════════════════════════
# Public API
# ═══════════════════════════════════════════════════════════════

def validate_session_transition(
    current: RuntimeSessionStatus,
    target: RuntimeSessionStatus,
) -> None:
    """Validate session state transition (V3.3 authority)."""
    _validate(current, target, _SESSION_GRAPH, RuntimeSessionStatus)


def validate_cycle_transition(
    current: RuntimeCycleStatus,
    target: RuntimeCycleStatus,
) -> None:
    """Validate cycle state transition (strict forward-only chain)."""
    _validate(current, target, _CYCLE_GRAPH, RuntimeCycleStatus)


def validate_recovery_transition(
    current: RecoveryStatus,
    target: RecoveryStatus,
) -> None:
    """Validate recovery state transition (V3.3 authority)."""
    _validate(current, target, _RECOVERY_GRAPH, RecoveryStatus)
