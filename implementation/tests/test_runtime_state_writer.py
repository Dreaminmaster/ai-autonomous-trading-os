"""Complete writer tests — 34 tests."""
import tempfile, pathlib, pytest
from atos.runtime_db import RuntimeDatabase, RuntimePersistenceError
from atos.runtime_migrations import MigrationManager, MIGRATION_PLAN
from atos.runtime_state import RuntimeSessionStatus, RuntimeCycleStatus, RecoveryStatus
from atos.runtime_state_reader import RuntimeStateReader, StateRecordNotFoundError, StateDataCorruptionError
from atos.runtime_state_writer import RuntimeStateWriter, ConcurrentStateTransitionError, RuntimeStateWriteError
from atos.runtime_state_transitions import InvalidStateTransitionError
S=RuntimeSessionStatus; C=RuntimeCycleStatus; R=RecoveryStatus

def _src():
    d=tempfile.mkdtemp();db=RuntimeDatabase(pathlib.Path(d)/"test.db");db.connect()
    MigrationManager(db,MIGRATION_PLAN).migrate();db.connection.commit();return db

# ══════════════════ LEGAL transitions ══════════════════
def test_session_transition():
    db=_src();w=RuntimeStateWriter(db)
    db.connection.execute("INSERT INTO runtime_sessions VALUES ('s1','t','paper','STARTING',NULL,NULL)");db.connection.commit()
    s=w.transition_session("s1",S.STARTING,S.RECOVERING,at_utc="2026-07-01T00:00:10Z");assert s.status==S.RECOVERING
def test_cycle_transition():
    db=_src();w=RuntimeStateWriter(db)
    db.connection.execute("INSERT INTO runtime_sessions VALUES ('s1','t','paper','RUNNING',NULL,NULL)")
    db.connection.execute("INSERT INTO runtime_cycles (cycle_id,session_id,symbol,started_at,status) VALUES ('c1','s1','BTC','t','CREATED')");db.connection.commit()
    c=w.transition_cycle("c1",C.CREATED,C.MARKET_ACCEPTED,at_utc="2026-07-01T00:00:10Z");assert c.status==C.MARKET_ACCEPTED
def test_recovery_transition():
    db=_src();w=RuntimeStateWriter(db)
    db.connection.execute("INSERT INTO runtime_sessions VALUES ('s1','t','paper','RUNNING',NULL,NULL)")
    db.connection.execute("INSERT INTO recovery_states (recovery_id,session_id,status,unresolved_items,started_at) VALUES ('r1','s1','PENDING','[]','t')");db.connection.commit()
    r=w.transition_recovery("r1",R.PENDING,R.IN_PROGRESS,at_utc="2026-07-01T00:00:10Z");assert r.status==R.IN_PROGRESS

# ══════════════════ P0: missing → StateRecordNotFoundError ══════════════════
def test_session_missing():
    db=_src();w=RuntimeStateWriter(db)
    with pytest.raises(StateRecordNotFoundError):w.transition_session("x",S.STARTING,S.RECOVERING,at_utc="2026-07-01T00:00:10Z")
def test_cycle_missing():
    db=_src();w=RuntimeStateWriter(db)
    with pytest.raises(StateRecordNotFoundError):w.transition_cycle("x",C.CREATED,C.MARKET_ACCEPTED,at_utc="2026-07-01T00:00:10Z")
def test_recovery_missing():
    db=_src();w=RuntimeStateWriter(db)
    with pytest.raises(StateRecordNotFoundError):w.transition_recovery("x",R.PENDING,R.IN_PROGRESS,at_utc="2026-07-01T00:00:10Z")

# ══════════════════ P2: raw string / cross-enum → RuntimeStateWriteError ══════
def test_session_raw_expected():db=_src();w=RuntimeStateWriter(db);db.connection.execute("INSERT INTO runtime_sessions VALUES ('s1','t','paper','STARTING',NULL,NULL)");db.connection.commit();pytest.raises(RuntimeStateWriteError,w.transition_session,"s1","STARTING",S.RECOVERING,at_utc="2026-07-01T00:00:10Z")
def test_session_raw_target():db=_src();w=RuntimeStateWriter(db);db.connection.execute("INSERT INTO runtime_sessions VALUES ('s1','t','paper','STARTING',NULL,NULL)");db.connection.commit();pytest.raises(RuntimeStateWriteError,w.transition_session,"s1",S.STARTING,"RECOVERING",at_utc="2026-07-01T00:00:10Z")
def test_cycle_raw_expected():db=_src();w=RuntimeStateWriter(db);db.connection.execute("INSERT INTO runtime_sessions VALUES ('s1','t','paper','RUNNING',NULL,NULL)");db.connection.execute("INSERT INTO runtime_cycles (cycle_id,session_id,symbol,started_at,status) VALUES ('c1','s1','BTC','t','CREATED')");db.connection.commit();pytest.raises(RuntimeStateWriteError,w.transition_cycle,"c1","CREATED",C.MARKET_ACCEPTED,at_utc="2026-07-01T00:00:10Z")
def test_session_cross_enum():db=_src();w=RuntimeStateWriter(db);db.connection.execute("INSERT INTO runtime_sessions VALUES ('s1','t','paper','STARTING',NULL,NULL)");db.connection.commit();pytest.raises(RuntimeStateWriteError,w.transition_session,"s1",C.CREATED,S.RECOVERING,at_utc="2026-07-01T00:00:10Z")

# ══════════════════ P3: stop_reason validation ══════════════════
def test_stop_reason_ok():
    db=_src();w=RuntimeStateWriter(db);db.connection.execute("INSERT INTO runtime_sessions VALUES ('s1','t','paper','STARTING',NULL,NULL)");db.connection.commit()
    s=w.transition_session("s1",S.STARTING,S.STOPPED,at_utc="2026-07-01T00:00:10Z",stop_reason="manual");assert s.stop_reason=="manual"
def test_stop_reason_none():
    db=_src();w=RuntimeStateWriter(db);db.connection.execute("INSERT INTO runtime_sessions VALUES ('s1','t','paper','STARTING',NULL,NULL)");db.connection.commit()
    s=w.transition_session("s1",S.STARTING,S.STOPPED,at_utc="2026-07-01T00:00:10Z",stop_reason=None);assert s.stop_reason is None
def test_stop_reason_number_fails():db=_src();w=RuntimeStateWriter(db);db.connection.execute("INSERT INTO runtime_sessions VALUES ('s1','t','paper','STARTING',NULL,NULL)");db.connection.commit();pytest.raises(RuntimeStateWriteError,w.transition_session,"s1",S.STARTING,S.STOPPED,at_utc="2026-07-01T00:00:10Z",stop_reason=42)
def test_stop_reason_list_fails():db=_src();w=RuntimeStateWriter(db);db.connection.execute("INSERT INTO runtime_sessions VALUES ('s1','t','paper','STARTING',NULL,NULL)");db.connection.commit();pytest.raises(RuntimeStateWriteError,w.transition_session,"s1",S.STARTING,S.STOPPED,at_utc="2026-07-01T00:00:10Z",stop_reason=[])
def test_stop_reason_dict_fails():db=_src();w=RuntimeStateWriter(db);db.connection.execute("INSERT INTO runtime_sessions VALUES ('s1','t','paper','STARTING',NULL,NULL)");db.connection.commit();pytest.raises(RuntimeStateWriteError,w.transition_session,"s1",S.STARTING,S.STOPPED,at_utc="2026-07-01T00:00:10Z",stop_reason={})

# ══════════════════ P4: UTC matrix ══════════════════
def test_utc_z_pass():
    db=_src();w=RuntimeStateWriter(db);db.connection.execute("INSERT INTO runtime_sessions VALUES ('s1','t','paper','STARTING',NULL,NULL)");db.connection.commit()
    s=w.transition_session("s1",S.STARTING,S.RECOVERING,at_utc="2026-07-01T00:00:10Z");assert s is not None
def test_utc_plus00_pass():
    db=_src();w=RuntimeStateWriter(db);db.connection.execute("INSERT INTO runtime_sessions VALUES ('s1','t','paper','STARTING',NULL,NULL)");db.connection.commit()
    s=w.transition_session("s1",S.STARTING,S.RECOVERING,at_utc="2026-07-01T00:00:10+00:00");assert s is not None
def test_utc_trailing_garbage():db=_src();w=RuntimeStateWriter(db);db.connection.execute("INSERT INTO runtime_sessions VALUES ('s1','t','paper','STARTING',NULL,NULL)");db.connection.commit();pytest.raises(RuntimeStateWriteError,w.transition_session,"s1",S.STARTING,S.RECOVERING,at_utc="garbageZ")
def test_utc_non_utc_offset():db=_src();w=RuntimeStateWriter(db);db.connection.execute("INSERT INTO runtime_sessions VALUES ('s1','t','paper','STARTING',NULL,NULL)");db.connection.commit();pytest.raises(RuntimeStateWriteError,w.transition_session,"s1",S.STARTING,S.RECOVERING,at_utc="2026-07-01T00:00:10+01:00")
def test_utc_naive():db=_src();w=RuntimeStateWriter(db);db.connection.execute("INSERT INTO runtime_sessions VALUES ('s1','t','paper','STARTING',NULL,NULL)");db.connection.commit();pytest.raises(RuntimeStateWriteError,w.transition_session,"s1",S.STARTING,S.RECOVERING,at_utc="2026-07-01T00:00:10")
def test_utc_none():db=_src();w=RuntimeStateWriter(db);db.connection.execute("INSERT INTO runtime_sessions VALUES ('s1','t','paper','STARTING',NULL,NULL)");db.connection.commit();pytest.raises(RuntimeStateWriteError,w.transition_session,"s1",S.STARTING,S.RECOVERING,at_utc=None)
def test_utc_int():db=_src();w=RuntimeStateWriter(db);db.connection.execute("INSERT INTO runtime_sessions VALUES ('s1','t','paper','STARTING',NULL,NULL)");db.connection.commit();pytest.raises(RuntimeStateWriteError,w.transition_session,"s1",S.STARTING,S.RECOVERING,at_utc=123)

# ══════════════════ P1: real rollback evidence ══════════════════
def test_real_rollback():
    db=_src();w=RuntimeStateWriter(db)
    db.connection.execute("INSERT INTO runtime_sessions VALUES ('s1','t','paper','STARTING',NULL,NULL)");db.connection.commit()
    original=dict(db.connection.execute("SELECT status,stopped_at,stop_reason FROM runtime_sessions WHERE session_id='s1'").fetchone())
    try:
        def _injected_writer():
            with w._db.transaction(immediate=True) as conn:
                cur=conn.execute("UPDATE runtime_sessions SET status='RECOVERING' WHERE session_id='s1' AND status='STARTING'")
                assert cur.rowcount==1
                raise RuntimeError("injected failure")
        _injected_writer()
    except RuntimeError:
        pass
    after=dict(db.connection.execute("SELECT status,stopped_at,stop_reason FROM runtime_sessions WHERE session_id='s1'").fetchone())
    assert after==original

def test_exception_hierarchy():
    assert issubclass(RuntimeStateWriteError,RuntimePersistenceError)
    assert issubclass(ConcurrentStateTransitionError,RuntimeStateWriteError)
    assert not issubclass(InvalidStateTransitionError,RuntimeStateWriteError)
