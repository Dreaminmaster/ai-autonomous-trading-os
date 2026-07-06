"""Atomic CAS session transition tests."""
import tempfile
from pathlib import Path
import pytest
from atos.runtime_db import RuntimeDatabase, RuntimePersistenceError
from atos.runtime_migrations import MigrationManager, MIGRATION_PLAN
from atos.runtime_state import RuntimeSessionStatus, RuntimeCycleStatus, RecoveryStatus
from atos.runtime_state_reader import RuntimeStateReader
from atos.runtime_state_writer import RuntimeStateWriter, ConcurrentStateTransitionError, RuntimeStateWriteError
from atos.runtime_state_transitions import InvalidStateTransitionError
S = RuntimeSessionStatus; C = RuntimeCycleStatus; R = RecoveryStatus

def _db():
    d = tempfile.mkdtemp()
    db = RuntimeDatabase(Path(d) / "test.db")
    db.connect()
    MigrationManager(db, MIGRATION_PLAN).migrate()
    db.connection.commit()
    return db

# ══════════════════ Session ══════════════════

def test_session_utc():
    db=_db(); w=RuntimeStateWriter(db)
    db.connection.execute("INSERT INTO runtime_sessions VALUES ('s1','t','paper','STARTING',NULL,NULL)")
    db.connection.commit()
    s=w.transition_session("s1",S.STARTING,S.RECOVERING,at_utc="2026-07-01T00:00:10Z")
    assert s.status==S.RECOVERING

def test_session_non_utc():
    db=_db(); w=RuntimeStateWriter(db)
    db.connection.execute("INSERT INTO runtime_sessions VALUES ('s1','t','paper','STARTING',NULL,NULL)")
    db.connection.commit()
    with pytest.raises(RuntimeStateWriteError): w.transition_session("s1",S.STARTING,S.RECOVERING,at_utc="bad")

def test_session_concurrent():
    db=_db(); w=RuntimeStateWriter(db)
    db.connection.execute("INSERT INTO runtime_sessions VALUES ('s1','t','paper','READY',NULL,NULL)")
    db.connection.commit()
    with pytest.raises(ConcurrentStateTransitionError): w.transition_session("s1",S.STARTING,S.RECOVERING,at_utc="2026-07-01T00:00:10Z")

def test_session_policy():
    db=_db(); w=RuntimeStateWriter(db)
    db.connection.execute("INSERT INTO runtime_sessions VALUES ('s1','t','paper','STARTING',NULL,NULL)")
    db.connection.commit()
    with pytest.raises(InvalidStateTransitionError): w.transition_session("s1",S.STARTING,S.RUNNING,at_utc="2026-07-01T00:00:10Z")

def test_session_rollback():
    db=_db(); w=RuntimeStateWriter(db)
    db.connection.execute("INSERT INTO runtime_sessions VALUES ('s1','t','paper','STARTING',NULL,NULL)")
    db.connection.commit()
    try: w.transition_session("s1",S.STARTING,S.RUNNING,at_utc="2026-07-01T00:00:10Z")
    except InvalidStateTransitionError: pass
    s=RuntimeStateReader(db).get_session("s1"); assert s.status==S.STARTING

def test_session_not_found():
    db=_db(); w=RuntimeStateWriter(db)
    with pytest.raises(RuntimeStateWriteError): w.transition_session("x",S.STARTING,S.RECOVERING,at_utc="2026-07-01T00:00:10Z")

def test_session_stop():
    db=_db(); w=RuntimeStateWriter(db)
    db.connection.execute("INSERT INTO runtime_sessions VALUES ('s1','t','paper','STARTING',NULL,NULL)")
    db.connection.commit()
    s=w.transition_session("s1",S.STARTING,S.STOPPED,at_utc="2026-07-01T00:00:10Z",stop_reason="manual")
    assert s.stop_reason=="manual"

# ══════════════════ Cycle ══════════════════

def test_cycle_transition():
    db=_db(); w=RuntimeStateWriter(db)
    db.connection.execute("INSERT INTO runtime_sessions VALUES ('s1','t','paper','RUNNING',NULL,NULL)")
    db.connection.execute("INSERT INTO runtime_cycles (cycle_id,session_id,symbol,started_at,status) VALUES ('c1','s1','BTC','t','CREATED')")
    db.connection.commit()
    c=w.transition_cycle("c1",C.CREATED,C.MARKET_ACCEPTED,at_utc="2026-07-01T00:00:10Z")
    assert c.status==C.MARKET_ACCEPTED

def test_cycle_concurrent():
    db=_db(); w=RuntimeStateWriter(db)
    db.connection.execute("INSERT INTO runtime_sessions VALUES ('s1','t','paper','RUNNING',NULL,NULL)")
    db.connection.execute("INSERT INTO runtime_cycles (cycle_id,session_id,symbol,started_at,status) VALUES ('c1','s1','BTC','t','EXECUTED')")
    db.connection.commit()
    with pytest.raises(ConcurrentStateTransitionError): w.transition_cycle("c1",C.CREATED,C.MARKET_ACCEPTED,at_utc="2026-07-01T00:00:10Z")

# ══════════════════ Recovery ══════════════════

def test_recovery_transition():
    db=_db(); w=RuntimeStateWriter(db)
    db.connection.execute("INSERT INTO runtime_sessions VALUES ('s1','t','paper','RUNNING',NULL,NULL)")
    db.connection.execute("INSERT INTO recovery_states (recovery_id,session_id,status,unresolved_items,started_at) VALUES ('r1','s1','PENDING','[]','t')")
    db.connection.commit()
    r=w.transition_recovery("r1",R.PENDING,R.IN_PROGRESS,at_utc="2026-07-01T00:00:10Z")
    assert r.status==R.IN_PROGRESS

# ══════════════════ Exception hierarchy ══════════════════

def test_exception_hierarchy():
    assert issubclass(RuntimeStateWriteError,RuntimePersistenceError)
    assert issubclass(ConcurrentStateTransitionError,RuntimeStateWriteError)
    assert not issubclass(InvalidStateTransitionError,RuntimeStateWriteError)
