"""Pure transition policy tests — no DB, no filesystem, no network."""
import pytest
from atos.runtime_state import RuntimeSessionStatus, RuntimeCycleStatus, RecoveryStatus
from atos.runtime_state_transitions import (
    validate_session_transition,
    validate_cycle_transition,
    validate_recovery_transition,
    InvalidStateTransitionError,
    SESSION_GRAPH as S_G,
    CYCLE_GRAPH as C_G,
    RECOVERY_GRAPH as R_G,
)

S = RuntimeSessionStatus
C = RuntimeCycleStatus
R = RecoveryStatus

# ══════ Session: all allowed edges pass ══════

@pytest.mark.parametrize("current,target", [
    (S.STARTING, S.RECOVERING), (S.STARTING, S.STOPPED),
    (S.RECOVERING, S.READY), (S.RECOVERING, S.PAUSED_RECOVERY_REQUIRED), (S.RECOVERING, S.STOPPED),
    (S.READY, S.RUNNING), (S.READY, S.PAUSED), (S.READY, S.STOPPED),
    (S.RUNNING, S.PAUSED), (S.RUNNING, S.PAUSED_RECOVERY_REQUIRED), (S.RUNNING, S.STOPPED),
    (S.PAUSED, S.RUNNING), (S.PAUSED, S.RECOVERING), (S.PAUSED, S.PAUSED_RECOVERY_REQUIRED), (S.PAUSED, S.STOPPED),
    (S.PAUSED_RECOVERY_REQUIRED, S.RECOVERING), (S.PAUSED_RECOVERY_REQUIRED, S.STOPPED),
])
def test_session_allowed(current, target):
    validate_session_transition(current, target)

# ══════ Session: illegal edges ══════

@pytest.mark.parametrize("current,target", [
    (S.STARTING, S.RUNNING), (S.RECOVERING, S.RUNNING), (S.READY, S.STARTING),
    (S.RUNNING, S.READY), (S.STOPPED, S.STARTING), (S.STOPPED, S.RECOVERING),
])
def test_session_illegal(current, target):
    with pytest.raises(InvalidStateTransitionError):
        validate_session_transition(current, target)

def test_session_self_transition():
    with pytest.raises(InvalidStateTransitionError):
        validate_session_transition(S.RUNNING, S.RUNNING)

def test_stopped_resurrection_fails():
    with pytest.raises(InvalidStateTransitionError):
        validate_session_transition(S.STOPPED, S.STARTING)

# ══════ Cycle: adjacent edges pass ══════

@pytest.mark.parametrize("current,target", [
    (C.CREATED, C.MARKET_ACCEPTED), (C.MARKET_ACCEPTED, C.ACCOUNT_ACCEPTED),
    (C.ACCOUNT_ACCEPTED, C.CANDIDATES_READY), (C.CANDIDATES_READY, C.PROVIDER_DECIDED),
    (C.PROVIDER_DECIDED, C.RISK_DECIDED), (C.RISK_DECIDED, C.EXECUTION_INTENT_CREATED),
    (C.EXECUTION_INTENT_CREATED, C.EXECUTED), (C.EXECUTED, C.RECONCILED),
    (C.RECONCILED, C.COMPLETED),
])
def test_cycle_adjacent_pass(current, target):
    validate_cycle_transition(current, target)

# ══════ Cycle: skip-edges fail ══════

@pytest.mark.parametrize("current,target", [
    (C.CREATED, C.ACCOUNT_ACCEPTED), (C.CREATED, C.COMPLETED),
    (C.EXECUTED, C.COMPLETED),
])
def test_cycle_skip_fails(current, target):
    with pytest.raises(InvalidStateTransitionError):
        validate_cycle_transition(current, target)

# ══════ Cycle: backward fails ══════

@pytest.mark.parametrize("current,target", [
    (C.EXECUTED, C.RISK_DECIDED), (C.COMPLETED, C.RECONCILED),
])
def test_cycle_backward_fails(current, target):
    with pytest.raises(InvalidStateTransitionError):
        validate_cycle_transition(current, target)

def test_cycle_self_transition_fails():
    with pytest.raises(InvalidStateTransitionError):
        validate_cycle_transition(C.CREATED, C.CREATED)

def test_cycle_completed_terminal():
    with pytest.raises(InvalidStateTransitionError):
        validate_cycle_transition(C.COMPLETED, C.CREATED)

# ══════ Recovery: allowed edges pass ══════

def test_recovery_pending_to_in_progress():
    validate_recovery_transition(R.PENDING, R.IN_PROGRESS)

def test_recovery_in_progress_to_resolved():
    validate_recovery_transition(R.IN_PROGRESS, R.RESOLVED)

def test_recovery_in_progress_to_failed():
    validate_recovery_transition(R.IN_PROGRESS, R.FAILED)

def test_recovery_failed_to_in_progress():
    validate_recovery_transition(R.FAILED, R.IN_PROGRESS)

# ══════ Recovery: illegal edges fail ══════

@pytest.mark.parametrize("current,target", [
    (R.PENDING, R.RESOLVED), (R.PENDING, R.FAILED),
    (R.RESOLVED, R.PENDING), (R.RESOLVED, R.IN_PROGRESS),
])
def test_recovery_illegal(current, target):
    with pytest.raises(InvalidStateTransitionError):
        validate_recovery_transition(current, target)

def test_recovery_self_transition_fails():
    with pytest.raises(InvalidStateTransitionError):
        validate_recovery_transition(R.PENDING, R.PENDING)

# ══════ Type safety ══════

def test_session_raw_string_current_fails():
    with pytest.raises(TypeError):
        validate_session_transition("READY", S.RUNNING)

def test_session_raw_string_target_fails():
    with pytest.raises(TypeError):
        validate_session_transition(S.READY, "RUNNING")

def test_cross_enum_type_fails():
    with pytest.raises(TypeError):
        validate_session_transition(C.CREATED, S.RUNNING)

# ══════ Immutability ══════

def test_session_graph_immutable():
    with pytest.raises(TypeError):
        S_G[S.STARTING] = frozenset()

def test_cycle_graph_immutable():
    with pytest.raises(TypeError):
        C_G[C.CREATED] = frozenset()

def test_recovery_graph_immutable():
    with pytest.raises(TypeError):
        R_G[R.PENDING] = frozenset()
