"""Exact enum + frozen record contracts for B4.1A."""
import pytest
from dataclasses import FrozenInstanceError
from atos.runtime_state import (
    RuntimeMode, RuntimeSessionStatus, RuntimeCycleStatus, RecoveryStatus,
    RuntimeSessionRecord, RuntimeCycleRecord, RecoveryStateRecord,
)

# ── P7: Exact enum value sets ────────────────────────────────

def test_runtime_mode_exact():
    assert [m.value for m in RuntimeMode] == ["paper", "shadow", "guarded"]

def test_session_status_exact():
    assert [s.value for s in RuntimeSessionStatus] == [
        "STARTING", "RECOVERING", "READY", "RUNNING", "PAUSED",
        "PAUSED_RECOVERY_REQUIRED", "STOPPED",
    ]

def test_cycle_status_exact():
    assert [c.value for c in RuntimeCycleStatus] == [
        "CREATED", "MARKET_ACCEPTED", "ACCOUNT_ACCEPTED", "CANDIDATES_READY",
        "PROVIDER_DECIDED", "RISK_DECIDED", "EXECUTION_INTENT_CREATED",
        "EXECUTED", "RECONCILED", "COMPLETED",
    ]

def test_recovery_status_exact():
    assert [r.value for r in RecoveryStatus] == [
        "PENDING", "IN_PROGRESS", "RESOLVED", "FAILED",
    ]

# ── P5: Frozen record tests (exact exceptions) ───────────────

def test_session_frozen():
    r = RuntimeSessionRecord("s","t",RuntimeMode.PAPER,RuntimeSessionStatus.STARTING)
    with pytest.raises(FrozenInstanceError):
        r.session_id = "x"

def test_cycle_frozen():
    r = RuntimeCycleRecord("c","s","X","t",None,RuntimeCycleStatus.CREATED,None,None)
    with pytest.raises(FrozenInstanceError):
        r.symbol = "Y"

def test_recovery_frozen():
    r = RecoveryStateRecord("r","s",RecoveryStatus.PENDING,(),"t",None)
    with pytest.raises(FrozenInstanceError):
        r.status = RecoveryStatus.RESOLVED

# ── Invalid enum values ──────────────────────────────────────

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
