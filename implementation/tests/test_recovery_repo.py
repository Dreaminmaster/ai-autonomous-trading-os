"""Tests for RecoveryStateRepository."""
import tempfile
from pathlib import Path
from atos.runtime_db import RuntimeDatabase
from atos.runtime_migrations import MigrationManager, MIGRATION_PLAN
from atos.runtime_repositories import RuntimeSessionRepository, RecoveryStateRepository

def _setup():
    d = tempfile.mkdtemp()
    path = Path(d) / "test.db"
    db = RuntimeDatabase(path)
    db.connect()
    MigrationManager(db, MIGRATION_PLAN).migrate()
    clock = lambda: "2026-07-06T00:00:00.000000Z"
    sessions = RuntimeSessionRepository(db, clock)
    recovery = RecoveryStateRepository(db, clock)
    sessions.create("s1", "paper")
    sessions.transition("s1", "STARTING", "RECOVERING")
    sessions.transition("s1", "RECOVERING", "READY")
    return db, recovery

def test_create():
    db, recovery = _setup()
    r = recovery.create("r1", "s1")
    assert r.status.value == "PENDING"

def test_create_with_items():
    db, recovery = _setup()
    r = recovery.create("r1", "s1", items=["order1", "intent2"])
    assert len(r.unresolved_items) == 2

def test_items_must_be_list():
    db, recovery = _setup()
    try:
        recovery.create("r1", "s1", items="not_a_list")
        assert False
    except Exception:
        pass
