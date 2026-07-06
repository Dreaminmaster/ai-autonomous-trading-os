"""Tests for RecoveryStateRepository."""
import tempfile
from pathlib import Path
import pytest
from atos.runtime_db import RuntimeDatabase
from atos.runtime_migrations import MigrationManager, MIGRATION_PLAN
from atos.runtime_repositories import (
    RuntimeSessionRepository, RecoveryStateRepository, InvalidStateTransitionError,
)
from atos.runtime_state import RecoveryStatus


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
    assert r.status == RecoveryStatus.PENDING
    assert r.unresolved_items == tuple()
    db.close()


def test_pending_to_in_progress():
    db, recovery = _setup()
    recovery.create("r1", "s1")
    r = recovery.transition("r1", "PENDING", "IN_PROGRESS")
    assert r.status == RecoveryStatus.IN_PROGRESS
    db.close()


def test_resolve():
    db, recovery = _setup()
    recovery.create("r1", "s1")
    recovery.transition("r1", "PENDING", "IN_PROGRESS")
    r = recovery.resolve("r1", "IN_PROGRESS")
    assert r.status == RecoveryStatus.RESOLVED
    assert r.recovered_at is not None
    db.close()


def test_resolved_terminal():
    db, recovery = _setup()
    recovery.create("r1", "s1")
    recovery.transition("r1", "PENDING", "IN_PROGRESS")
    recovery.resolve("r1", "IN_PROGRESS")
    with pytest.raises(InvalidStateTransitionError):
        recovery.transition("r1", "RESOLVED", "IN_PROGRESS")
    db.close()


def test_failed_terminal():
    db, recovery = _setup()
    recovery.create("r1", "s1")
    recovery.fail("r1", "PENDING")
    with pytest.raises(InvalidStateTransitionError):
        recovery.transition("r1", "FAILED", "IN_PROGRESS")
    db.close()


def test_stale_expected_conflicts():
    db, recovery = _setup()
    recovery.create("r1", "s1")
    recovery.transition("r1", "PENDING", "IN_PROGRESS")
    from atos.runtime_repositories import ConcurrentStateConflictError
    with pytest.raises(ConcurrentStateConflictError):
        recovery.transition("r1", "PENDING", "IN_PROGRESS")
    db.close()
