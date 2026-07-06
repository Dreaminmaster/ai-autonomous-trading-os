"""Exact enum + frozen record + slots contracts for B4.1A."""
import pytest
from dataclasses import FrozenInstanceError
from atos.runtime_state import (
    RuntimeMode, RuntimeSessionStatus, RuntimeCycleStatus, RecoveryStatus,
    RuntimeSessionRecord, RuntimeCycleRecord, RecoveryStateRecord,
)

# Exact enum value sets
def test_mode_exact():
    assert [m.value for m in RuntimeMode] == ["paper","shadow","guarded"]
def test_session_status_exact():
    assert [s.value for s in RuntimeSessionStatus] == [
        "STARTING","RECOVERING","READY","RUNNING","PAUSED",
        "PAUSED_RECOVERY_REQUIRED","STOPPED",
    ]
def test_cycle_status_exact():
    assert [c.value for c in RuntimeCycleStatus] == [
        "CREATED","MARKET_ACCEPTED","ACCOUNT_ACCEPTED","CANDIDATES_READY",
        "PROVIDER_DECIDED","RISK_DECIDED","EXECUTION_INTENT_CREATED",
        "EXECUTED","RECONCILED","COMPLETED",
    ]
def test_recovery_status_exact():
    assert [r.value for r in RecoveryStatus] == [
        "PENDING","IN_PROGRESS","RESOLVED","FAILED",
    ]

# Frozen record tests (exact exceptions)
def test_session_frozen():
    r = RuntimeSessionRecord("s","t",RuntimeMode.PAPER,RuntimeSessionStatus.STARTING)
    with pytest.raises(FrozenInstanceError): r.session_id = "x"
def test_cycle_frozen():
    r = RuntimeCycleRecord("c","s","X","t",None,RuntimeCycleStatus.CREATED,None,None)
    with pytest.raises(FrozenInstanceError): r.symbol = "Y"
def test_recovery_frozen():
    r = RecoveryStateRecord("r","s",RecoveryStatus.PENDING,(),"t",None)
    with pytest.raises(FrozenInstanceError): r.status = RecoveryStatus.RESOLVED

# Invalid enum
def test_invalid_mode():
    with pytest.raises(ValueError):
        RuntimeMode("LIVE")
def test_invalid_session_status():
    with pytest.raises(ValueError):
        RuntimeSessionStatus("DEAD")
def test_invalid_cycle_status():
    with pytest.raises(ValueError):
        RuntimeCycleStatus("CRASHED")
def test_invalid_recovery_status():
    with pytest.raises(ValueError):
        RecoveryStatus("LOST")

# Slots contracts (P3)
def test_session_no_dict():
    r = RuntimeSessionRecord("s","t",RuntimeMode.PAPER,RuntimeSessionStatus.STARTING)
    assert not hasattr(r, "__dict__")
def test_cycle_no_dict():
    r = RuntimeCycleRecord("c","s","X","t",None,RuntimeCycleStatus.CREATED,None,None)
    assert not hasattr(r, "__dict__")
def test_recovery_no_dict():
    r = RecoveryStateRecord("r","s",RecoveryStatus.PENDING,(),"t",None)
    assert not hasattr(r, "__dict__")
