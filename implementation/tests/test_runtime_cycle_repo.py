"""Tests for RuntimeCycleRepository."""
import tempfile
from pathlib import Path
from atos.runtime_db import RuntimeDatabase
from atos.runtime_migrations import MigrationManager, MIGRATION_PLAN
from atos.runtime_repositories import RuntimeSessionRepository, RuntimeCycleRepository

def _setup():
    d = tempfile.mkdtemp()
    path = Path(d) / "test.db"
    db = RuntimeDatabase(path)
    db.connect()
    MigrationManager(db, MIGRATION_PLAN).migrate()
    clock = lambda: "2026-07-06T00:00:00.000000Z"
    sessions = RuntimeSessionRepository(db, clock)
    cycles = RuntimeCycleRepository(db, clock)
    sessions.create("s1", "paper")
    sessions.transition("s1", "STARTING", "RECOVERING")
    sessions.transition("s1", "RECOVERING", "READY")
    return db, cycles

def test_create():
    db, cycles = _setup()
    c = cycles.create("c1", "s1", "BTC/USDT")
    assert c.status.value == "CREATED"

def test_exact_transition():
    db, cycles = _setup()
    cycles.create("c1", "s1", "BTC/USDT")
    c = cycles.transition("c1", "CREATED", "MARKET_ACCEPTED")
    assert c.status.value == "MARKET_ACCEPTED"

def test_record_error():
    db, cycles = _setup()
    cycles.create("c1", "s1", "BTC/USDT")
    cycles.record_error("c1", "CREATED", "something failed")
    c = cycles.get("c1")
    assert c.last_error == "something failed"
    assert c.status.value == "CREATED"

def test_wrong_expected_raises():
    db, cycles = _setup()
    cycles.create("c1", "s1", "BTC/USDT")
    try:
        cycles.transition("c1", "WRONG", "MARKET_ACCEPTED")
        assert False
    except ValueError:
        pass
