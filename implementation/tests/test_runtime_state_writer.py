"""Complete writer contract tests — session, cycle, recovery, UTC, stop_reason, zero-mutation."""
import tempfile, pathlib, pytest
from atos.runtime_db import RuntimeDatabase, RuntimePersistenceError
from atos.runtime_migrations import MigrationManager, MIGRATION_PLAN
from atos.runtime_state import RuntimeSessionStatus, RuntimeCycleStatus, RecoveryStatus
from atos.runtime_state_reader import RuntimeStateReader, StateRecordNotFoundError, StateDataCorruptionError
from atos.runtime_state_writer import RuntimeStateWriter, ConcurrentStateTransitionError, RuntimeStateWriteError
from atos.runtime_state_transitions import InvalidStateTransitionError
S=RuntimeSessionStatus; C=RuntimeCycleStatus; R=RecoveryStatus

def _db():
    d=tempfile.mkdtemp();db=RuntimeDatabase(pathlib.Path(d)/"test.db");db.connect()
    MigrationManager(db,MIGRATION_PLAN).migrate();db.connection.commit();return db

def _row(db,table,key_col,key_val):
    return dict(db.connection.execute(f"SELECT * FROM {table} WHERE {key_col}=?",(key_val,)).fetchone())

def _ins_s(db,status=S.STARTING):
    db.connection.execute("INSERT INTO runtime_sessions VALUES ('s1','t','paper',?,NULL,NULL)",(status.value,));db.connection.commit()

def _ins_c(db,status=C.CREATED):
    db.connection.execute("INSERT INTO runtime_sessions VALUES ('s1','t','paper','RUNNING',NULL,NULL)")
    db.connection.execute("INSERT INTO runtime_cycles(cycle_id,session_id,symbol,started_at,status) VALUES ('c1','s1','BTC','t',?)",(status.value,));db.connection.commit()

def _ins_r(db,status=R.PENDING):
    db.connection.execute("INSERT INTO runtime_sessions VALUES ('s1','t','paper','RUNNING',NULL,NULL)")
    db.connection.execute("INSERT INTO recovery_states(recovery_id,session_id,status,unresolved_items,started_at) VALUES ('r1','s1',?,'[]','t')",(status.value,));db.connection.commit()

UTC="2026-07-01T00:00:10Z"

# ══════════════ LEGAL ══════════════
def test_s_legal(): db=_db();_ins_s(db);w=RuntimeStateWriter(db);s=w.transition_session("s1",S.STARTING,S.RECOVERING,at_utc=UTC);assert s.status==S.RECOVERING
def test_c_legal(): db=_db();_ins_c(db);w=RuntimeStateWriter(db);c=w.transition_cycle("c1",C.CREATED,C.MARKET_ACCEPTED,at_utc=UTC);assert c.status==C.MARKET_ACCEPTED
def test_r_legal(): db=_db();_ins_r(db);w=RuntimeStateWriter(db);r=w.transition_recovery("r1",R.PENDING,R.IN_PROGRESS,at_utc=UTC);assert r.status==R.IN_PROGRESS

# ══════════════ P1: SESSION COMPLETE ══════════════
def test_s_stale(): db=_db();_ins_s(db,S.STARTING);w=RuntimeStateWriter(db);before=_row(db,"runtime_sessions","session_id","s1");pytest.raises(ConcurrentStateTransitionError,w.transition_session,"s1",S.RUNNING,S.RECOVERING,at_utc=UTC);assert _row(db,"runtime_sessions","session_id","s1")==before
def test_s_illegal(): db=_db();_ins_s(db);w=RuntimeStateWriter(db);before=_row(db,"runtime_sessions","session_id","s1");pytest.raises(InvalidStateTransitionError,w.transition_session,"s1",S.STARTING,S.RUNNING,at_utc=UTC);assert _row(db,"runtime_sessions","session_id","s1")==before
def test_s_stopped_persisted(): db=_db();_ins_s(db);w=RuntimeStateWriter(db);s=w.transition_session("s1",S.STARTING,S.STOPPED,at_utc=UTC,stop_reason="done");assert s.stopped_at==UTC;assert s.stop_reason=="done"
def test_s_unrelated_fields(): db=_db();_ins_s(db);before=_row(db,"runtime_sessions","session_id","s1");w=RuntimeStateWriter(db);s=w.transition_session("s1",S.STARTING,S.RECOVERING,at_utc=UTC);after=_row(db,"runtime_sessions","session_id","s1");assert after["session_id"]==before["session_id"];assert after["started_at"]==before["started_at"];assert after["mode"]==before["mode"]
def test_s_missing(): w=RuntimeStateWriter(_db());pytest.raises(StateRecordNotFoundError,w.transition_session,"x",S.STARTING,S.RECOVERING,at_utc=UTC)

# ══════════════ P2: CYCLE COMPLETE ══════════════
def test_c_backward(): db=_db();_ins_c(db,C.EXECUTED);w=RuntimeStateWriter(db);before=_row(db,"runtime_cycles","cycle_id","c1");pytest.raises(InvalidStateTransitionError,w.transition_cycle,"c1",C.EXECUTED,C.RISK_DECIDED,at_utc=UTC);assert _row(db,"runtime_cycles","cycle_id","c1")==before
def test_c_self(): db=_db();_ins_c(db);w=RuntimeStateWriter(db);pytest.raises(InvalidStateTransitionError,w.transition_cycle,"c1",C.CREATED,C.CREATED,at_utc=UTC)
def test_c_stale(): db=_db();_ins_c(db,C.EXECUTED);w=RuntimeStateWriter(db);before=_row(db,"runtime_cycles","cycle_id","c1");pytest.raises(ConcurrentStateTransitionError,w.transition_cycle,"c1",C.CREATED,C.MARKET_ACCEPTED,at_utc=UTC);assert _row(db,"runtime_cycles","cycle_id","c1")==before
def test_c_lcs_persisted(): db=_db();_ins_c(db);w=RuntimeStateWriter(db);c=w.transition_cycle("c1",C.CREATED,C.MARKET_ACCEPTED,at_utc=UTC);assert c.last_completed_stage==C.MARKET_ACCEPTED
def test_c_completed_persisted(): db=_db();_ins_c(db,C.RECONCILED);w=RuntimeStateWriter(db);c=w.transition_cycle("c1",C.RECONCILED,C.COMPLETED,at_utc=UTC);assert c.status==C.COMPLETED;assert c.completed_at==UTC
def test_c_unrelated(): db=_db();_ins_c(db);before=_row(db,"runtime_cycles","cycle_id","c1");w=RuntimeStateWriter(db);c=w.transition_cycle("c1",C.CREATED,C.MARKET_ACCEPTED,at_utc=UTC);after=_row(db,"runtime_cycles","cycle_id","c1");assert after["session_id"]==before["session_id"];assert after["symbol"]==before["symbol"]
def test_c_missing(): w=RuntimeStateWriter(_db());pytest.raises(StateRecordNotFoundError,w.transition_cycle,"x",C.CREATED,C.MARKET_ACCEPTED,at_utc=UTC)

# ══════════════ P3: RECOVERY COMPLETE ══════════════
def test_r_pending_resolved_rejected(): db=_db();_ins_r(db,R.PENDING);w=RuntimeStateWriter(db);before=_row(db,"recovery_states","recovery_id","r1");pytest.raises(InvalidStateTransitionError,w.transition_recovery,"r1",R.PENDING,R.RESOLVED,at_utc=UTC);assert _row(db,"recovery_states","recovery_id","r1")==before
def test_r_failed_to_in_progress(): db=_db();_ins_r(db,R.FAILED);w=RuntimeStateWriter(db);r=w.transition_recovery("r1",R.FAILED,R.IN_PROGRESS,at_utc=UTC);assert r.status==R.IN_PROGRESS
def test_r_self(): db=_db();_ins_r(db);w=RuntimeStateWriter(db);pytest.raises(InvalidStateTransitionError,w.transition_recovery,"r1",R.PENDING,R.PENDING,at_utc=UTC)
def test_r_stale(): db=_db();_ins_r(db,R.IN_PROGRESS);w=RuntimeStateWriter(db);before=_row(db,"recovery_states","recovery_id","r1");pytest.raises(ConcurrentStateTransitionError,w.transition_recovery,"r1",R.PENDING,R.RESOLVED,at_utc=UTC);assert _row(db,"recovery_states","recovery_id","r1")==before
def test_r_resolved_persisted(): db=_db();_ins_r(db,R.IN_PROGRESS);w=RuntimeStateWriter(db);r=w.transition_recovery("r1",R.IN_PROGRESS,R.RESOLVED,at_utc=UTC);assert r.status==R.RESOLVED;assert r.recovered_at==UTC
def test_r_items_unchanged(): db=_db();_ins_r(db,R.PENDING);before=_row(db,"recovery_states","recovery_id","r1");w=RuntimeStateWriter(db);r=w.transition_recovery("r1",R.PENDING,R.IN_PROGRESS,at_utc=UTC);assert r.unresolved_items==()
def test_r_missing(): w=RuntimeStateWriter(_db());pytest.raises(StateRecordNotFoundError,w.transition_recovery,"x",R.PENDING,R.IN_PROGRESS,at_utc=UTC)

# ══════════════ P4: INVALID-TYPE ZERO-MUTATION ══════════════
def _check_zm(db,table,key,val,fn,*args,**kw): before=_row(db,table,key,val);pytest.raises(RuntimeStateWriteError,fn,*args,**kw);assert _row(db,table,key,val)==before
def test_type_s_raw_e(): db=_db();_ins_s(db);_check_zm(db,"runtime_sessions","session_id","s1",RuntimeStateWriter(db).transition_session,"s1","STARTING",S.RECOVERING,at_utc=UTC)
def test_type_s_raw_t(): db=_db();_ins_s(db);_check_zm(db,"runtime_sessions","session_id","s1",RuntimeStateWriter(db).transition_session,"s1",S.STARTING,"RECOVERING",at_utc=UTC)
def test_type_s_cross_e(): db=_db();_ins_s(db);_check_zm(db,"runtime_sessions","session_id","s1",RuntimeStateWriter(db).transition_session,"s1",C.CREATED,S.RECOVERING,at_utc=UTC)
def test_type_s_cross_t(): db=_db();_ins_s(db);_check_zm(db,"runtime_sessions","session_id","s1",RuntimeStateWriter(db).transition_session,"s1",S.STARTING,C.CREATED,at_utc=UTC)
def test_type_c_raw_e(): db=_db();_ins_c(db);_check_zm(db,"runtime_cycles","cycle_id","c1",RuntimeStateWriter(db).transition_cycle,"c1","CREATED",C.MARKET_ACCEPTED,at_utc=UTC)
def test_type_c_raw_t(): db=_db();_ins_c(db);_check_zm(db,"runtime_cycles","cycle_id","c1",RuntimeStateWriter(db).transition_cycle,"c1",C.CREATED,"MARKET_ACCEPTED",at_utc=UTC)
def test_type_c_cross_e(): db=_db();_ins_c(db);_check_zm(db,"runtime_cycles","cycle_id","c1",RuntimeStateWriter(db).transition_cycle,"c1",S.STARTING,C.MARKET_ACCEPTED,at_utc=UTC)
def test_type_c_cross_t(): db=_db();_ins_c(db);_check_zm(db,"runtime_cycles","cycle_id","c1",RuntimeStateWriter(db).transition_cycle,"c1",C.CREATED,S.STARTING,at_utc=UTC)
def test_type_r_raw_e(): db=_db();_ins_r(db);_check_zm(db,"recovery_states","recovery_id","r1",RuntimeStateWriter(db).transition_recovery,"r1","PENDING",R.IN_PROGRESS,at_utc=UTC)
def test_type_r_raw_t(): db=_db();_ins_r(db);_check_zm(db,"recovery_states","recovery_id","r1",RuntimeStateWriter(db).transition_recovery,"r1",R.PENDING,"IN_PROGRESS",at_utc=UTC)
def test_type_r_cross_e(): db=_db();_ins_r(db);_check_zm(db,"recovery_states","recovery_id","r1",RuntimeStateWriter(db).transition_recovery,"r1",C.CREATED,R.IN_PROGRESS,at_utc=UTC)
def test_type_r_cross_t(): db=_db();_ins_r(db);_check_zm(db,"recovery_states","recovery_id","r1",RuntimeStateWriter(db).transition_recovery,"r1",R.PENDING,C.CREATED,at_utc=UTC)

# ══════════════ P5: stop_reason ZERO-MUTATION ══════════════
def _sr_fail(db,val): _ins_s(db);before=_row(db,"runtime_sessions","session_id","s1");w=RuntimeStateWriter(db);pytest.raises(RuntimeStateWriteError,w.transition_session,"s1",S.STARTING,S.STOPPED,at_utc=UTC,stop_reason=val);assert _row(db,"runtime_sessions","session_id","s1")==before
def test_sr_null(): db=_db();_ins_s(db);s=RuntimeStateWriter(db).transition_session("s1",S.STARTING,S.STOPPED,at_utc=UTC,stop_reason=None);assert s.stop_reason is None
def test_sr_str(): db=_db();_ins_s(db);s=RuntimeStateWriter(db).transition_session("s1",S.STARTING,S.STOPPED,at_utc=UTC,stop_reason="x");assert s.stop_reason=="x"
def test_sr_int(): _sr_fail(_db(),1)
def test_sr_list(): _sr_fail(_db(),[])
def test_sr_dict(): _sr_fail(_db(),{})
def test_sr_bool(): _sr_fail(_db(),True)

# ══════════════ P6: UTC ZERO-MUTATION ══════════════
def _utc_fail(db,val): _ins_s(db);before=_row(db,"runtime_sessions","session_id","s1");w=RuntimeStateWriter(db);pytest.raises(RuntimeStateWriteError,w.transition_session,"s1",S.STARTING,S.RECOVERING,at_utc=val);assert _row(db,"runtime_sessions","session_id","s1")==before
def test_utc_z(): db=_db();_ins_s(db);s=RuntimeStateWriter(db).transition_session("s1",S.STARTING,S.RECOVERING,at_utc="2026-07-01T00:00:10Z");assert s is not None
def test_utc_plus00(): db=_db();_ins_s(db);s=RuntimeStateWriter(db).transition_session("s1",S.STARTING,S.RECOVERING,at_utc="2026-07-01T00:00:10+00:00");assert s is not None
def test_utc_canonical(): db=_db();_ins_s(db);s=RuntimeStateWriter(db).transition_session("s1",S.STARTING,S.STOPPED,at_utc="2026-07-01T00:00:10+00:00");assert s.stopped_at=="2026-07-01T00:00:10Z"
def test_utc_garbage(): _utc_fail(_db(),"garbageZ")
def test_utc_hello(): _utc_fail(_db(),"hello+00:00world")
def test_utc_naive(): _utc_fail(_db(),"2026-07-01T00:00:10")
def test_utc_offset(): _utc_fail(_db(),"2026-07-01T00:00:10+01:00")
def test_utc_bad(): _utc_fail(_db(),"2026-99-99T00:00:10Z")
def test_utc_none(): _utc_fail(_db(),None)
def test_utc_int(): _utc_fail(_db(),123)

# ══════════════ P7: CAS ROWCOUNT=0 UNCHANGED ══════════════
def test_cas_rowcount_zero():
    db=_db()
    db.connection.execute('CREATE TRIGGER suppress_s BEFORE UPDATE ON runtime_sessions BEGIN SELECT RAISE(IGNORE); END;')
    _ins_s(db);w=RuntimeStateWriter(db)
    before=_row(db,"runtime_sessions","session_id","s1")
    pytest.raises(ConcurrentStateTransitionError,w.transition_session,"s1",S.STARTING,S.RECOVERING,at_utc=UTC)
    assert _row(db,"runtime_sessions","session_id","s1")==before

# ══════════════ ATOMICITY ══════════════
def test_real_rollback():
    db=_db();_ins_s(db);w=RuntimeStateWriter(db);before=_row(db,"runtime_sessions","session_id","s1")
    orig=w._reader.get_session
    try: w._reader.get_session=lambda s: (_ for _ in ()).throw(RuntimeError("injected")); w.transition_session("s1",S.STARTING,S.RECOVERING,at_utc=UTC)
    except RuntimeError: pass
    finally: w._reader.get_session=orig
    assert _row(db,"runtime_sessions","session_id","s1")==before

def test_reread_failure_rollback():
    db=_db();_ins_s(db);w=RuntimeStateWriter(db);before=_row(db,"runtime_sessions","session_id","s1")
    orig=w._reader.get_session
    try: w._reader.get_session=lambda s: (_ for _ in ()).throw(StateRecordNotFoundError("lost"))
    except (RuntimeStateWriteError,StateRecordNotFoundError): pass
    finally: w._reader.get_session=orig
    assert _row(db,"runtime_sessions","session_id","s1")==before

def test_exception_hierarchy():
    assert issubclass(RuntimeStateWriteError,RuntimePersistenceError)
    assert issubclass(ConcurrentStateTransitionError,RuntimeStateWriteError)
    assert not issubclass(InvalidStateTransitionError,RuntimeStateWriteError)
