import tempfile
from pathlib import Path
import pytest
from atos.runtime_db import RuntimeDatabase, RuntimePersistenceError
from atos.runtime_migrations import MigrationManager, MIGRATION_PLAN
from atos.runtime_state import RuntimeSessionStatus
from atos.runtime_state_reader import RuntimeStateReader, StateRecordNotFoundError
from atos.runtime_state_writer import RuntimeStateWriter, ConcurrentStateTransitionError, RuntimeStateWriteError
from atos.runtime_state_transitions import InvalidStateTransitionError
S=RuntimeSessionStatus

def _db():
    d=tempfile.mkdtemp(); db=RuntimeDatabase(Path(d)/"test.db"); db.connect()
    MigrationManager(db,MIGRATION_PLAN).migrate()
    db.connection.commit(); return db

def _s(db,sid="s1",status=S.STARTING):
    db.connection.execute("INSERT INTO runtime_sessions (session_id,started_at,mode,status) VALUES (?,?,?,?)",(sid,"t","paper",status.value))

def test_utc():
    db=_db();w=RuntimeStateWriter(db);_s(db)
    s=w.transition_session("s1",S.STARTING,S.RECOVERING,at_utc="2026-07-01T00:00:10Z");assert s.status==S.RECOVERING

def test_non_utc():
    db=_db();w=RuntimeStateWriter(db);_s(db)
    with pytest.raises(RuntimeStateWriteError):w.transition_session("s1",S.STARTING,S.RECOVERING,at_utc="bad")

def test_concurrent():
    db=_db();w=RuntimeStateWriter(db);_s(db,S.READY)
    with pytest.raises(ConcurrentStateTransitionError):w.transition_session("s1",S.STARTING,S.RECOVERING,at_utc="2026-07-01T00:00:10Z")

def test_policy():
    db=_db();w=RuntimeStateWriter(db);_s(db)
    with pytest.raises(InvalidStateTransitionError):w.transition_session("s1",S.STARTING,S.RUNNING,at_utc="2026-07-01T00:00:10Z")

def test_rollback():
    db=_db();w=RuntimeStateWriter(db);_s(db)
    try:w.transition_session("s1",S.STARTING,S.RUNNING,at_utc="2026-07-01T00:00:10Z")
    except InvalidStateTransitionError:pass
    s=RuntimeStateReader(db).get_session("s1");assert s.status==S.STARTING

def test_not_found():
    db=_db();w=RuntimeStateWriter(db)
    with pytest.raises(StateRecordNotFoundError):w.transition_session("x",S.STARTING,S.RECOVERING,at_utc="2026-07-01T00:00:10Z")

def test_stop():
    db=_db();w=RuntimeStateWriter(db);_s(db)
    s=w.transition_session("s1",S.STARTING,S.STOPPED,at_utc="2026-07-01T00:00:10Z",stop_reason="manual");assert s.stop_reason=="manual"

def test_exception():
    assert issubclass(RuntimeStateWriteError,RuntimePersistenceError)
    assert issubclass(ConcurrentStateTransitionError,RuntimeStateWriteError)
    assert not issubclass(InvalidStateTransitionError,RuntimeStateWriteError)
