"""Exhaustive transition policy tests — independent expected-edge sets."""
from itertools import product
import pytest
from atos.runtime_state import RuntimeSessionStatus, RuntimeCycleStatus, RecoveryStatus
from atos.runtime_state_transitions import (
    __all__ as PUBLIC_API,
    InvalidStateTransitionError,
    validate_session_transition,
    validate_cycle_transition,
    validate_recovery_transition,
)

S = RuntimeSessionStatus
C = RuntimeCycleStatus
R = RecoveryStatus

# ══════ P1: exact public API ══════

def test_public_api_is_exact():
    assert PUBLIC_API == (
        "InvalidStateTransitionError",
        "validate_session_transition",
        "validate_cycle_transition",
        "validate_recovery_transition",
    )

# ══════ Session exhaustive matrix ══════

EXPECTED_SESSION_EDGES = {
    (S.STARTING, S.RECOVERING), (S.STARTING, S.STOPPED),
    (S.RECOVERING, S.READY), (S.RECOVERING, S.PAUSED_RECOVERY_REQUIRED), (S.RECOVERING, S.STOPPED),
    (S.READY, S.RUNNING), (S.READY, S.PAUSED), (S.READY, S.STOPPED),
    (S.RUNNING, S.PAUSED), (S.RUNNING, S.PAUSED_RECOVERY_REQUIRED), (S.RUNNING, S.STOPPED),
    (S.PAUSED, S.RUNNING), (S.PAUSED, S.RECOVERING), (S.PAUSED, S.PAUSED_RECOVERY_REQUIRED), (S.PAUSED, S.STOPPED),
    (S.PAUSED_RECOVERY_REQUIRED, S.RECOVERING), (S.PAUSED_RECOVERY_REQUIRED, S.STOPPED),
}

def test_session_exhaustive():
    for current, target in product(S, S):
        if (current, target) in EXPECTED_SESSION_EDGES:
            validate_session_transition(current, target)
        else:
            with pytest.raises(InvalidStateTransitionError):
                validate_session_transition(current, target)

# ══════ Cycle exhaustive matrix ══════

EXPECTED_CYCLE_EDGES = {
    (C.CREATED, C.MARKET_ACCEPTED),
    (C.MARKET_ACCEPTED, C.ACCOUNT_ACCEPTED),
    (C.ACCOUNT_ACCEPTED, C.CANDIDATES_READY),
    (C.CANDIDATES_READY, C.PROVIDER_DECIDED),
    (C.PROVIDER_DECIDED, C.RISK_DECIDED),
    (C.RISK_DECIDED, C.EXECUTION_INTENT_CREATED),
    (C.EXECUTION_INTENT_CREATED, C.EXECUTED),
    (C.EXECUTED, C.RECONCILED),
    (C.RECONCILED, C.COMPLETED),
}

def test_cycle_exhaustive():
    for current, target in product(C, C):
        if (current, target) in EXPECTED_CYCLE_EDGES:
            validate_cycle_transition(current, target)
        else:
            with pytest.raises(InvalidStateTransitionError):
                validate_cycle_transition(current, target)

# ══════ Recovery exhaustive matrix ══════

EXPECTED_RECOVERY_EDGES = {
    (R.PENDING, R.IN_PROGRESS),
    (R.IN_PROGRESS, R.RESOLVED),
    (R.IN_PROGRESS, R.FAILED),
    (R.FAILED, R.IN_PROGRESS),
}

def test_recovery_exhaustive():
    for current, target in product(R, R):
        if (current, target) in EXPECTED_RECOVERY_EDGES:
            validate_recovery_transition(current, target)
        else:
            with pytest.raises(InvalidStateTransitionError):
                validate_recovery_transition(current, target)

# ══════ P2: Unified error contract — raw string/cross-enum → InvalidStateTransitionError ══════

def test_raw_string_raises_iste():
    with pytest.raises(InvalidStateTransitionError):
        validate_session_transition("READY", S.RUNNING)

def test_raw_string_target_raises_iste():
    with pytest.raises(InvalidStateTransitionError):
        validate_session_transition(S.READY, "RUNNING")

def test_cross_enum_raises_iste():
    with pytest.raises(InvalidStateTransitionError):
        validate_session_transition(C.CREATED, S.RUNNING)

# ══════ P5: Graph immutability ══════

def test_mapping_assignment_fails():
    from atos.runtime_state_transitions import _SESSION_GRAPH
    with pytest.raises(TypeError):
        _SESSION_GRAPH[S.STARTING] = frozenset()

def test_frozenset_no_mutation():
    from atos.runtime_state_transitions import _SESSION_GRAPH
    allowed = _SESSION_GRAPH[S.STARTING]
    assert not hasattr(allowed, "add")
    assert not hasattr(allowed, "append")
