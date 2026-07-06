"""Tests for UnitOfWork."""
import tempfile
from pathlib import Path
from atos.runtime_db import RuntimeDatabase
from atos.runtime_migrations import MigrationManager, MIGRATION_PLAN
from atos.runtime_repositories import (
    RuntimeSessionRepository, RuntimeCycleRepository, RecoveryStateRepository, RuntimeStateUnitOfWork,
)
from atos.runtime_state import RuntimeSessionStatus, RuntimeCycleStatus, RecoveryStatus


def _setup():
    d = tempfile.mkdtemp()
    path = Path(d) / "test.db"
    db = RuntimeDatabase(path)
    db.connect()
    MigrationManager(db, MIGRATION_PLAN).migrate()
    clock = lambda: "2026-07-06T00:00:00.000000Z"
    sessions = RuntimeSessionRepository(db, clock)
    return db, sessions


def test_uow_create_session_commits():
    db, sessions = _setup()
    with RuntimeStateUnitOfWork(db) as uow:
        uow.sessions.create("s1", "paper")
    s = sessions.get("s1")
    assert s.status == RuntimeSessionStatus.STARTING
    db.close()


def test_uow_rollback_on_exception():
    db, sessions = _setup()
    try:
        with RuntimeStateUnitOfWork(db) as uow:
            uow.sessions.create("s1", "paper")
            raise ValueError("boom")
    except ValueError:
        pass
    s = sessions.get("s1")
    assert s is None
    db.close()


def test_uow_multi_repo_atomic():
    d = tempfile.mkdtemp()
    path = Path(d) / "test.db"
    db = RuntimeDatabase(path)
    db.connect()
    MigrationManager(db, MIGRATION_PLAN).migrate()
    clock = lambda: "2026-07-06T00:00:00.000000Z"
    sessions = RuntimeSessionRepository(db, clock)
    cycles = RuntimeCycleRepository(db, clock)
    recovery = RecoveryStateRepository(db, clock)
    try:
        with RuntimeStateUnitOfWork(db) as uow:
            uow.sessions.create("s1", "paper")
            uow.sessions.transition("s1", "STARTING", "RECOVERING")
            uow.sessions.transition("s1", "RECOVERING", "READY")
            uow.cycles.create("c1", "s1", "BTC/USDT")
            uow.recovery.create("r1", "s1")
            raise ValueError("boom")
    except ValueError:
        pass
    assert sessions.get("s1") is None
    assert cycles.get("c1") is None
    assert recovery.get("r1") is None
    db.close()
