"""Tests for RuntimeSessionRepository."""
import tempfile
from pathlib import Path
from atos.runtime_db import RuntimeDatabase
from atos.runtime_migrations import MigrationManager, MIGRATION_PLAN
from atos.runtime_repositories import RuntimeSessionRepository, IdempotencyConflictError

def _setup():
    d = tempfile.mkdtemp()
    path = Path(d) / "test.db"
    db = RuntimeDatabase(path)
    db.connect()
    MigrationManager(db, MIGRATION_PLAN).migrate()
    clock = lambda: "2026-07-06T00:00:00.000000Z"
    repo = RuntimeSessionRepository(db, clock)
    return db, repo

def test_create_and_get():
    db, repo = _setup()
    s = repo.create("s1", "paper")
    assert s.session_id == "s1"
    assert s.mode.value == "paper"
    assert s.status.value == "STARTING"

def test_idempotent_create():
    db, repo = _setup()
    s1 = repo.create("s1", "paper")
    s2 = repo.create("s1", "paper", s1.started_at)
    assert s1.started_at == s2.started_at

def test_idempotent_mismatch_conflicts():
    db, repo = _setup()
    repo.create("s1", "paper")
    try:
        repo.create("s1", "shadow")
        assert False
    except IdempotencyConflictError:
        pass
