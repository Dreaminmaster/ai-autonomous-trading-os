"""Complete writer contract tests."""
import tempfile, pathlib, pytest, types
from atos.runtime_db import RuntimeDatabase, RuntimePersistenceError
from atos.runtime_migrations import MigrationManager, MIGRATION_PLAN
from atos.runtime_state import RuntimeSessionStatus, RuntimeCycleStatus, RecoveryStatus
from atos.runtime_state_reader import RuntimeStateReader, StateRecordNotFoundError
from atos.runtime_state_writer import RuntimeStateWriter, ConcurrentStateTransitionError, RuntimeStateWriteError
from atos.runtime_state_transitions import InvalidStateTransitionError

S = RuntimeSessionStatus
C = RuntimeCycleStatus
R = RecoveryStatus

def _db_simple():
    d = tempfile.mkdtemp()
    db = RuntimeDatabase(pathlib.Path(d) / "test.db")
    db.connect()
    MigrationManager(db, MIGRATION_PLAN).migrate()
    db.connection.commit()
    return db

# ══════════════ LEGAL ══════════════
def test_session_legal():
    db=_db_simple(); w=RuntimeStateWriter(db)
    db.connection.execute("INSERT INTO runtime_sessions VALUES ('s1','t','paper','STARTING',NULL,NULL)"); db.connection.commit()
    s=w.transition_session("s1",S.STARTING,S.RECOVERING,at_utc="2026-07-01T00:00:10Z"); assert s.status==S.RECOVERING

def test_cycle_legal():
    db=_db_simple(); w=RuntimeStateWriter(db)
    db.connection.execute("INSERT INTO runtime_sessions VALUES ('s1','t','paper','RUNNING',NULL,NULL)")
    db.connection.execute("INSERT INTO runtime_cycles(cycle_id,session_id,symbol,started_at,status) VALUES ('c1','s1','BTC','t','CREATED')"); db.connection.commit()
    c=w.transition_cycle("c1",C.CREATED,C.MARKET_ACCEPTED,at_utc="2026-07-01T00:00:10Z"); assert c.status==C.MARKET_ACCEPTED

def test_recovery_legal():
    db=_db_simple(); w=RuntimeStateWriter(db)
    db.connection.execute("INSERT INTO runtime_sessions VALUES ('s1','t','paper','RUNNING',NULL,NULL)")
    db.connection.execute("INSERT INTO recovery_states(recovery_id,session_id,status,unresolved_items,started_at) VALUES ('r1','s1','PENDING','[]','t')"); db.connection.commit()
    r=w.transition_recovery("r1",R.PENDING,R.IN_PROGRESS,at_utc="2026-07-01T00:00:10Z"); assert r.status==R.IN_PROGRESS

# ══════════════ P0: real rollback — writer UPDATE then injected failure ══════════════
def test_real_rollback():
    db=_db_simple(); w=RuntimeStateWriter(db)
    db.connection.execute("INSERT INTO runtime_sessions VALUES ('s1','t','paper','STARTING',NULL,NULL)"); db.connection.commit()
    before=dict(db.connection.execute("SELECT status FROM runtime_sessions WHERE session_id='s1'").fetchone())
    original_get = w._reader.get_session
    try:
        # P0: inject failure AFTER UPDATE inside writer transaction
        def _bomb(*a,**kw):
            raise RuntimeError("injected after UPDATE")
        w._reader.get_session = _bomb
        w.transition_session("s1",S.STARTING,S.RECOVERING,at_utc="2026-07-01T00:00:10Z")
        assert False, "should have raised"
    except RuntimeError:
        pass
    finally:
        w._reader.get_session = original_get
    after=dict(db.connection.execute("SELECT status FROM runtime_sessions WHERE session_id='s1'").fetchone())
    assert after==before  # rolled back

# ══════════════ P1: re-read failure rollback ══════════════
def test_reread_failure_rollback():
    db=_db_simple(); w=RuntimeStateWriter(db)
    db.connection.execute("INSERT INTO runtime_sessions VALUES ('s1','t','paper','STARTING',NULL,NULL)"); db.connection.commit()
    before=dict(db.connection.execute("SELECT status FROM runtime_sessions WHERE session_id='s1'").fetchone())
    original = w._reader.get_session
    try:
        def _reread_bomb(sid):
            raise StateRecordNotFoundError("re-read lost")
        w._reader.get_session = _reread_bomb
        with pytest.raises((RuntimeStateWriteError, StateRecordNotFoundError)):
            w.transition_session("s1",S.STARTING,S.RECOVERING,at_utc="2026-07-01T00:00:10Z")
    finally:
        w._reader.get_session = original
    after=dict(db.connection.execute("SELECT status FROM runtime_sessions WHERE session_id='s1'").fetchone())
    assert after==before

# ══════════════ P2: real CAS rowcount=0 via BEFORE UPDATE trigger ══════════════
def test_cas_rowcount_zero():
    db=_db_simple()
    # Create BEFORE UPDATE trigger that silently suppresses the UPDATE
    db.connection.execute('''CREATE TRIGGER IF NOT EXISTS suppress_session BEFORE UPDATE ON runtime_sessions BEGIN SELECT RAISE(IGNORE); END;''')
    db.connection.execute("INSERT INTO runtime_sessions VALUES ('s1','t','paper','STARTING',NULL,NULL)"); db.connection.commit()
    w=RuntimeStateWriter(db)
    with pytest.raises(ConcurrentStateTransitionError):
        w.transition_session("s1",S.STARTING,S.RECOVERING,at_utc="2026-07-01T00:00:10Z")

# ══════════════ P0: missing → StateRecordNotFoundError ══════════════
def test_session_missing():
    w=RuntimeStateWriter(_db_simple()); pytest.raises(StateRecordNotFoundError,w.transition_session,"x",S.STARTING,S.RECOVERING,at_utc="2026-07-01T00:00:10Z")
def test_cycle_missing():
    w=RuntimeStateWriter(_db_simple()); pytest.raises(StateRecordNotFoundError,w.transition_cycle,"x",C.CREATED,C.MARKET_ACCEPTED,at_utc="2026-07-01T00:00:10Z")
def test_recovery_missing():
    w=RuntimeStateWriter(_db_simple()); pytest.raises(StateRecordNotFoundError,w.transition_recovery,"x",R.PENDING,R.IN_PROGRESS,at_utc="2026-07-01T00:00:10Z")

# ══════════════ P3: complete invalid-type matrix (session,cycle,recovery) ══════════════
def _ins_s(db): db.connection.execute("INSERT INTO runtime_sessions VALUES ('s1','t','paper','STARTING',NULL,NULL)"); db.connection.commit()
def test_s_raw_expected(): db=_db_simple();_ins_s(db);pytest.raises(RuntimeStateWriteError,RuntimeStateWriter(db).transition_session,"s1","STARTING",S.RECOVERING,at_utc="2026-07-01T00:00:10Z")
def test_s_raw_target(): db=_db_simple();_ins_s(db);pytest.raises(RuntimeStateWriteError,RuntimeStateWriter(db).transition_session,"s1",S.STARTING,"RECOVERING",at_utc="2026-07-01T00:00:10Z")
def test_s_cross_expected(): db=_db_simple();_ins_s(db);pytest.raises(RuntimeStateWriteError,RuntimeStateWriter(db).transition_session,"s1",C.CREATED,S.RECOVERING,at_utc="2026-07-01T00:00:10Z")
def test_s_cross_target(): db=_db_simple();_ins_s(db);pytest.raises(RuntimeStateWriteError,RuntimeStateWriter(db).transition_session,"s1",S.STARTING,C.CREATED,at_utc="2026-07-01T00:00:10Z")

def _ins_c(db): db.connection.execute("INSERT INTO runtime_sessions VALUES ('s1','t','paper','RUNNING',NULL,NULL)"); db.connection.execute("INSERT INTO runtime_cycles(cycle_id,session_id,symbol,started_at,status) VALUES ('c1','s1','BTC','t','CREATED')"); db.connection.commit()
def test_c_raw_expected(): db=_db_simple();_ins_c(db);pytest.raises(RuntimeStateWriteError,RuntimeStateWriter(db).transition_cycle,"c1","CREATED",C.MARKET_ACCEPTED,at_utc="2026-07-01T00:00:10Z")
def test_c_raw_target(): db=_db_simple();_ins_c(db);pytest.raises(RuntimeStateWriteError,RuntimeStateWriter(db).transition_cycle,"c1",C.CREATED,"MARKET_ACCEPTED",at_utc="2026-07-01T00:00:10Z")
def test_c_cross_expected(): db=_db_simple();_ins_c(db);pytest.raises(RuntimeStateWriteError,RuntimeStateWriter(db).transition_cycle,"c1",S.STARTING,C.MARKET_ACCEPTED,at_utc="2026-07-01T00:00:10Z")
def test_c_cross_target(): db=_db_simple();_ins_c(db);pytest.raises(RuntimeStateWriteError,RuntimeStateWriter(db).transition_cycle,"c1",C.CREATED,S.STARTING,at_utc="2026-07-01T00:00:10Z")

def _ins_r(db): db.connection.execute("INSERT INTO runtime_sessions VALUES ('s1','t','paper','RUNNING',NULL,NULL)"); db.connection.execute("INSERT INTO recovery_states(recovery_id,session_id,status,unresolved_items,started_at) VALUES ('r1','s1','PENDING','[]','t')"); db.connection.commit()
def test_r_raw_expected(): db=_db_simple();_ins_r(db);pytest.raises(RuntimeStateWriteError,RuntimeStateWriter(db).transition_recovery,"r1","PENDING",R.IN_PROGRESS,at_utc="2026-07-01T00:00:10Z")
def test_r_raw_target(): db=_db_simple();_ins_r(db);pytest.raises(RuntimeStateWriteError,RuntimeStateWriter(db).transition_recovery,"r1",R.PENDING,"IN_PROGRESS",at_utc="2026-07-01T00:00:10Z")
def test_r_cross_expected(): db=_db_simple();_ins_r(db);pytest.raises(RuntimeStateWriteError,RuntimeStateWriter(db).transition_recovery,"r1",C.CREATED,R.IN_PROGRESS,at_utc="2026-07-01T00:00:10Z")
def test_r_cross_target(): db=_db_simple();_ins_r(db);pytest.raises(RuntimeStateWriteError,RuntimeStateWriter(db).transition_recovery,"r1",R.PENDING,C.CREATED,at_utc="2026-07-01T00:00:10Z")

# ══════════════ P4: stop_reason complete ══════════════
def test_sr_null(): db=_db_simple();_ins_s(db);s=RuntimeStateWriter(db).transition_session("s1",S.STARTING,S.STOPPED,at_utc="2026-07-01T00:00:10Z",stop_reason=None);assert s.stop_reason is None
def test_sr_str(): db=_db_simple();_ins_s(db);s=RuntimeStateWriter(db).transition_session("s1",S.STARTING,S.STOPPED,at_utc="2026-07-01T00:00:10Z",stop_reason="x");assert s.stop_reason=="x"
def test_sr_int(): db=_db_simple();_ins_s(db);pytest.raises(RuntimeStateWriteError,RuntimeStateWriter(db).transition_session,"s1",S.STARTING,S.STOPPED,at_utc="2026-07-01T00:00:10Z",stop_reason=1)
def test_sr_list(): db=_db_simple();_ins_s(db);pytest.raises(RuntimeStateWriteError,RuntimeStateWriter(db).transition_session,"s1",S.STARTING,S.STOPPED,at_utc="2026-07-01T00:00:10Z",stop_reason=[])
def test_sr_dict(): db=_db_simple();_ins_s(db);pytest.raises(RuntimeStateWriteError,RuntimeStateWriter(db).transition_session,"s1",S.STARTING,S.STOPPED,at_utc="2026-07-01T00:00:10Z",stop_reason={})
def test_sr_bool(): db=_db_simple();_ins_s(db);pytest.raises(RuntimeStateWriteError,RuntimeStateWriter(db).transition_session,"s1",S.STARTING,S.STOPPED,at_utc="2026-07-01T00:00:10Z",stop_reason=True)

# ══════════════ P5: complete UTC matrix ══════════════
def test_utc_z(): db=_db_simple();_ins_s(db);s=RuntimeStateWriter(db).transition_session("s1",S.STARTING,S.RECOVERING,at_utc="2026-07-01T00:00:10Z");assert s is not None
def test_utc_plus00(): db=_db_simple();_ins_s(db);s=RuntimeStateWriter(db).transition_session("s1",S.STARTING,S.RECOVERING,at_utc="2026-07-01T00:00:10+00:00");assert s is not None
def test_utc_canonical_stopped_at(): db=_db_simple();_ins_s(db);s=RuntimeStateWriter(db).transition_session("s1",S.STARTING,S.STOPPED,at_utc="2026-07-01T00:00:10+00:00");assert s.stopped_at=="2026-07-01T00:00:10Z"
def test_utc_garbage(): db=_db_simple();_ins_s(db);pytest.raises(RuntimeStateWriteError,RuntimeStateWriter(db).transition_session,"s1",S.STARTING,S.RECOVERING,at_utc="garbageZ")
def test_utc_hello_world(): db=_db_simple();_ins_s(db);pytest.raises(RuntimeStateWriteError,RuntimeStateWriter(db).transition_session,"s1",S.STARTING,S.RECOVERING,at_utc="hello+00:00world")
def test_utc_naive(): db=_db_simple();_ins_s(db);pytest.raises(RuntimeStateWriteError,RuntimeStateWriter(db).transition_session,"s1",S.STARTING,S.RECOVERING,at_utc="2026-07-01T00:00:10")
def test_utc_offset(): db=_db_simple();_ins_s(db);pytest.raises(RuntimeStateWriteError,RuntimeStateWriter(db).transition_session,"s1",S.STARTING,S.RECOVERING,at_utc="2026-07-01T00:00:10+01:00")
def test_utc_bad_date(): db=_db_simple();_ins_s(db);pytest.raises(RuntimeStateWriteError,RuntimeStateWriter(db).transition_session,"s1",S.STARTING,S.RECOVERING,at_utc="2026-99-99T00:00:10Z")
def test_utc_none_val(): db=_db_simple();_ins_s(db);pytest.raises(RuntimeStateWriteError,RuntimeStateWriter(db).transition_session,"s1",S.STARTING,S.RECOVERING,at_utc=None)
def test_utc_int_val(): db=_db_simple();_ins_s(db);pytest.raises(RuntimeStateWriteError,RuntimeStateWriter(db).transition_session,"s1",S.STARTING,S.RECOVERING,at_utc=123)

# ══════════════ Additional evidence ══════════════
def test_session_self_rejected():
    db=_db_simple();_ins_s(db);pytest.raises(InvalidStateTransitionError,RuntimeStateWriter(db).transition_session,"s1",S.STARTING,S.STARTING,at_utc="2026-07-01T00:00:10Z")

def test_cycle_skip_rejected():
    db=_db_simple();_ins_c(db);pytest.raises(InvalidStateTransitionError,RuntimeStateWriter(db).transition_cycle,"c1",C.CREATED,C.ACCOUNT_ACCEPTED,at_utc="2026-07-01T00:00:10Z")

def test_exception_hierarchy():
    assert issubclass(RuntimeStateWriteError,RuntimePersistenceError)
    assert issubclass(ConcurrentStateTransitionError,RuntimeStateWriteError)
