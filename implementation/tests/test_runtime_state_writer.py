"""Atomic CAS session transition tests."""
import tempfile
from pathlib import Path
import pytest
from atos.runtime_db import RuntimeDatabase, RuntimePersistenceError
from atos.runtime_migrations import MigrationManager, MIGRATION_PLAN
from atos.runtime_state import RuntimeSessionStatus
from atos.runtime_state_reader import RuntimeStateReader
from atos.runtime_state_writer import RuntimeStateWriter, ConcurrentStateTransitionError, RuntimeStateWriteError
from atos.runtime_state_transitions import InvalidStateTransitionError
S = RuntimeSessionStatus

def _db():
    d = tempfile.mkdtemp()
    db = RuntimeDatabase(Path(d) / "test.db")
    db.connect()
    MigrationManager(db, MIGRATION_PLAN).migrate()
    db.connection.commit()
    return db

def test_utc():
    db = _db(); w = RuntimeStateWriter(db)
    db.connection.execute("INSERT INTO runtime_sessions VALUES ('s1','t','paper','STARTING',NULL,NULL)")
    db.connection.commit()
    s = w.transition_session("s1", S.STARTING, S.RECOVERING, at_utc="2026-07-01T00:00:10Z")
    assert s.status == S.RECOVERING

def test_non_utc():
    db = _db(); w = RuntimeStateWriter(db)
    db.connection.execute("INSERT INTO runtime_sessions VALUES ('s1','t','paper','STARTING',NULL,NULL)")
    db.connection.commit()
    with pytest.raises(RuntimeStateWriteError):
        w.transition_session("s1", S.STARTING, S.RECOVERING, at_utc="bad")

def test_same_state():
    db = _db(); w = RuntimeStateWriter(db)
    db.connection.execute("INSERT INTO runtime_sessions VALUES ('s1','t','paper','STARTING',NULL,NULL)")
    db.connection.commit()
    s = w.transition_session("s1", S.STARTING, S.STARTING, at_utc="2026-07-01T00:00:10Z")
    assert s.status == S.STARTING

def test_concurrent():
    db = _db(); w = RuntimeStateWriter(db)
    db.connection.execute("INSERT INTO runtime_sessions VALUES ('s1','t','paper','READY',NULL,NULL)")
    db.connection.commit()
    with pytest.raises(ConcurrentStateTransitionError):
        w.transition_session("s1", S.STARTING, S.RECOVERING, at_utc="2026-07-01T00:00:10Z")

def test_policy():
    db = _db(); w = RuntimeStateWriter(db)
    db.connection.execute("INSERT INTO runtime_sessions VALUES ('s1','t','paper','STARTING',NULL,NULL)")
    db.connection.commit()
    with pytest.raises(InvalidStateTransitionError):
        w.transition_session("s1", S.STARTING, S.RUNNING, at_utc="2026-07-01T00:00:10Z")

def test_rollback():
    db = _db(); w = RuntimeStateWriter(db)
    db.connection.execute("INSERT INTO runtime_sessions VALUES ('s1','t','paper','STARTING',NULL,NULL)")
    db.connection.commit()
    try:
        w.transition_session("s1", S.STARTING, S.RUNNING, at_utc="2026-07-01T00:00:10Z")
    except InvalidStateTransitionError:
        pass
    s = RuntimeStateReader(db).get_session("s1")
    assert s.status == S.STARTING

def test_not_found():
    db = _db(); w = RuntimeStateWriter(db)
    with pytest.raises(RuntimeStateWriteError):
        w.transition_session("x", S.STARTING, S.RECOVERING, at_utc="2026-07-01T00:00:10Z")

def test_stop():
    db = _db(); w = RuntimeStateWriter(db)
    db.connection.execute("INSERT INTO runtime_sessions VALUES ('s1','t','paper','STARTING',NULL,NULL)")
    db.connection.commit()
    s = w.transition_session("s1", S.STARTING, S.STOPPED, at_utc="2026-07-01T00:00:10Z", stop_reason="manual")
    assert s.stop_reason == "manual"

def test_exception():
    assert issubclass(RuntimeStateWriteError, RuntimePersistenceError)
    assert issubclass(ConcurrentStateTransitionError, RuntimeStateWriteError)
    assert not issubclass(InvalidStateTransitionError, RuntimeStateWriteError)
