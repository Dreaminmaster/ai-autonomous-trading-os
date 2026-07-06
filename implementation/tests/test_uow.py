"""Tests for RuntimeStateUnitOfWork."""
import tempfile
from pathlib import Path
from atos.runtime_db import RuntimeDatabase
from atos.runtime_migrations import MigrationManager, MIGRATION_PLAN
from atos.runtime_repositories import RuntimeStateUnitOfWork, RuntimeSessionRepository

def test_uow_create_commits():
    d = tempfile.mkdtemp()
    path = Path(d) / "test.db"
    db = RuntimeDatabase(path)
    db.connect()
    MigrationManager(db, MIGRATION_PLAN).migrate()
    clock = lambda: "2026-07-06T00:00:00.000000Z"
    with RuntimeStateUnitOfWork(db, clock) as uow:
        uow.sessions.create("s1", "paper")
    sessions = RuntimeSessionRepository(db, clock)
    s = sessions.get("s1")
    assert s.status.value == "STARTING"

def test_uow_rollback():
    d = tempfile.mkdtemp()
    path = Path(d) / "test.db"
    db = RuntimeDatabase(path)
    db.connect()
    MigrationManager(db, MIGRATION_PLAN).migrate()
    clock = lambda: "2026-07-06T00:00:00.000000Z"
    try:
        with RuntimeStateUnitOfWork(db, clock) as uow:
            uow.sessions.create("s1", "paper")
            raise ValueError("boom")
    except ValueError:
        pass
    sessions = RuntimeSessionRepository(db, clock)
    assert sessions._maybe_get("s1") is None
