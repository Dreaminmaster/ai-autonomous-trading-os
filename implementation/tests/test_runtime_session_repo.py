"""Tests for RuntimeSessionRepository — create, transition, CAS, idempotent."""
import tempfile
from pathlib import Path
import pytest
from atos.runtime_db import RuntimeDatabase
from atos.runtime_migrations import MigrationManager, MIGRATION_PLAN
from atos.runtime_repositories import (
    RuntimeSessionRepository,
    IdempotencyConflictError, InvalidStateTransitionError, ConcurrentStateConflictError, RecordNotFoundError,
)
from atos.runtime_state import RuntimeMode, RuntimeSessionStatus

_clock = None

def _set_clock(t):
    global _clock
    _clock = t

def _setup():
    d = tempfile.mkdtemp()
    path = Path(d) / "test.db"
    db = RuntimeDatabase(path)
    db.connect()
    MigrationManager(db, MIGRATION_PLAN).migrate()
    clock = lambda: _clock or "2026-07-06T00:00:00.000000Z"
    repo = RuntimeSessionRepository(db, clock)
    return db, repo


def test_create_and_get():
    db, repo = _setup()
    s = repo.create("s1", "paper")
    assert s.session_id == "s1"
    assert s.mode == RuntimeMode.PAPER
    assert s.status == RuntimeSessionStatus.STARTING
    db.close()


def test_duplicate_create_same_identity_returns_existing():
    db, repo = _setup()
    s1 = repo.create("s1", "paper")
    s2 = repo.create("s1", "paper", s1.started_at)
    assert s2.session_id == "s1"
    assert s2.started_at == s1.started_at
    db.close()


def test_duplicate_create_different_identity_conflicts():
    db, repo = _setup()
    repo.create("s1", "paper")
    with pytest.raises(IdempotencyConflictError):
        repo.create("s1", "shadow")
    db.close()


def test_valid_transition():
    db, repo = _setup()
    repo.create("s1", "paper")
    s = repo.transition("s1", "STARTING", "RECOVERING")
    assert s.status == RuntimeSessionStatus.RECOVERING
    db.close()


def test_starting_to_running_rejected():
    db, repo = _setup()
    repo.create("s1", "paper")
    with pytest.raises(InvalidStateTransitionError):
        repo.transition("s1", "STARTING", "RUNNING")
    db.close()


def test_stopped_terminal():
    db, repo = _setup()
    repo.create("s1", "paper")
    repo.transition("s1", "STARTING", "RECOVERING")
    repo.transition("s1", "RECOVERING", "READY")
    repo.transition("s1", "READY", "RUNNING")
    s = repo.transition("s1", "RUNNING", "STOPPED", stop_reason="done")
    assert s.status == RuntimeSessionStatus.STOPPED
    assert s.stopped_at is not None
    assert s.stop_reason == "done"
    with pytest.raises(InvalidStateTransitionError):
        repo.transition("s1", "STOPPED", "RUNNING")
    db.close()


def test_stopped_requires_reason():
    db, repo = _setup()
    repo.create("s1", "paper")
    repo.transition("s1", "STARTING", "RECOVERING")
    repo.transition("s1", "RECOVERING", "READY")
    with pytest.raises(InvalidStateTransitionError):
        repo.transition("s1", "READY", "STOPPED")
    db.close()


def test_playback_idempotent():
    db, repo = _setup()
    repo.create("s1", "paper")
    repo.transition("s1", "STARTING", "RECOVERING")
    s = repo.transition("s1", "STARTING", "RECOVERING")  # replay
    assert s.status == RuntimeSessionStatus.RECOVERING
    db.close()


def test_stale_expected_conflict():
    db, repo = _setup()
    repo.create("s1", "paper")
    repo.transition("s1", "STARTING", "RECOVERING")
    with pytest.raises(ConcurrentStateConflictError):
        repo.transition("s1", "STARTING", "RUNNING")  # stale
    db.close()
