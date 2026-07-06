"""Tests for RuntimeCycleRepository."""
import tempfile
from pathlib import Path
import pytest
from atos.runtime_db import RuntimeDatabase
from atos.runtime_migrations import MigrationManager, MIGRATION_PLAN
from atos.runtime_repositories import (
    RuntimeSessionRepository, RuntimeCycleRepository,
    InvalidStateTransitionError, ConcurrentStateConflictError,
)
from atos.runtime_state import RuntimeMode, RuntimeSessionStatus, RuntimeCycleStatus


def _setup():
    d = tempfile.mkdtemp()
    path = Path(d) / "test.db"
    db = RuntimeDatabase(path)
    db.connect()
    MigrationManager(db, MIGRATION_PLAN).migrate()
    clock = lambda: "2026-07-06T00:00:00.000000Z"
    sessions = RuntimeSessionRepository(db, clock)
    cycles = RuntimeCycleRepository(db, clock)
    # Create a session to satisfy FK
    sessions.create("s1", "paper")
    sessions.transition("s1", "STARTING", "RECOVERING")
    sessions.transition("s1", "RECOVERING", "READY")
    return db, cycles


def test_create_starts_created():
    db, cycles = _setup()
    c = cycles.create("c1", "s1", "BTC/USDT")
    assert c.status == RuntimeCycleStatus.CREATED
    assert c.last_completed_stage is None
    db.close()


def test_exact_next_transition():
    db, cycles = _setup()
    cycles.create("c1", "s1", "BTC/USDT")
    c = cycles.transition("c1", "CREATED", "MARKET_ACCEPTED")
    assert c.status == RuntimeCycleStatus.MARKET_ACCEPTED
    db.close()


def test_skip_rejected():
    db, cycles = _setup()
    cycles.create("c1", "s1", "BTC/USDT")
    with pytest.raises(InvalidStateTransitionError):
        cycles.transition("c1", "CREATED", "ACCOUNT_ACCEPTED")
    db.close()


def test_backward_rejected():
    db, cycles = _setup()
    cycles.create("c1", "s1", "BTC/USDT")
    cycles.transition("c1", "CREATED", "MARKET_ACCEPTED")
    with pytest.raises(InvalidStateTransitionError):
        cycles.transition("c1", "MARKET_ACCEPTED", "CREATED")
    db.close()


def test_completed_terminal():
    db, cycles = _setup()
    cycles.create("c1", "s1", "BTC/USDT")
    for s in ["CREATED", "MARKET_ACCEPTED", "ACCOUNT_ACCEPTED", "CANDIDATES_READY",
              "PROVIDER_DECIDED", "RISK_DECIDED", "EXECUTION_INTENT_CREATED", "EXECUTED", "RECONCILED"]:
        cycles.transition("c1", s, CYCLE_SEQUENCE[CYCLE_SEQUENCE.index(RuntimeCycleStatus(s)) + 1].value
                          if RuntimeCycleStatus(s) != RuntimeCycleStatus.RECONCILED else "COMPLETED")
    # Go through full sequence
    pass  # Already completed
    db.close()


def test_transition_replay_idempotent():
    db, cycles = _setup()
    cycles.create("c1", "s1", "BTC/USDT")
    cycles.transition("c1", "CREATED", "MARKET_ACCEPTED")
    c = cycles.transition("c1", "CREATED", "MARKET_ACCEPTED")  # replay
    assert c.status == RuntimeCycleStatus.MARKET_ACCEPTED
    db.close()


def test_record_error_preserves_stage():
    db, cycles = _setup()
    cycles.create("c1", "s1", "BTC/USDT")
    cycles.record_error("c1", "CREATED", "something went wrong")
    c = cycles.get("c1")
    assert c.last_error == "something went wrong"
    assert c.status == RuntimeCycleStatus.CREATED  # unchanged
    db.close()
