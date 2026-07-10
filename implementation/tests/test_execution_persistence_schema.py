"""Execution persistence schema tests — migration 0003."""
import tempfile, pathlib, hashlib, sqlite3, pytest
from atos.runtime_db import RuntimeDatabase
from atos.runtime_migrations import MigrationManager, MIGRATION_PLAN

HASH = hashlib.sha256
def _h(s): return HASH(s.encode()).hexdigest()

def _db():
    d=tempfile.mkdtemp()
    db=RuntimeDatabase(pathlib.Path(d)/"test.db")
    db.connect()
    MigrationManager(db,tuple(m for m in MIGRATION_PLAN if m.version<=3)).migrate()
    db.connection.commit()
    return db

# ===================== parent graph helpers =====================
def _ins_session(db, sid="s1"):
    db.connection.execute("INSERT INTO runtime_sessions VALUES (?,?,?,?,NULL,NULL)",(sid,"t","paper","RUNNING"))

def _ins_cycle(db, cid="c1", sid="s1"):
    db.connection.execute("INSERT INTO runtime_cycles (cycle_id,session_id,symbol,started_at,status) VALUES (?,?,?,?,?)",(cid,sid,"BTC","t","CREATED"))

def _ins_ti(db, tid="t1", action="BUY"):
    db.connection.execute("INSERT INTO trade_intents VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",(tid,"BTC",action,"1","x","x","1","0","0","x","x","t"))

def _ins_rd(db, rid="r1", tid="t1", decision="APPROVED"):
    db.connection.execute("INSERT INTO risk_decisions VALUES (?,?,?,?,?,?,?)",(rid,tid,decision,"x","0","{}","t"))

def _ins_ei(db, eid="e1", tid="t1", rid="r1", cid="c1", action="BUY", nhash=None):
    if nhash is None: nhash = _h(eid)
    db.connection.execute("INSERT INTO execution_intents VALUES (?,?,?,?,?,?,?,?,?)",(eid,tid,rid,cid,"BTC",action,"100",nhash,"t"))

def _ins_da(db, did="d1", eid="e1", an=1):
    db.connection.execute("INSERT INTO dispatch_attempts VALUES (?,?,?,?,?,?,?,?,?,?,?)",(did,eid,"cid","v","a","SUBMITTED",an,"t",None,None,None))

def _setup_graph(db):
    _ins_session(db); _ins_cycle(db); _ins_ti(db); _ins_rd(db); db.connection.commit()
    _ins_ei(db); db.connection.commit()

# ===================== T1-T5: basics =====================
def test_t1_fresh_v3(): assert _db().connection.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0]==3

def test_t2_five_tables():
    db=_db()
    tables=[r[0] for r in db.connection.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
    for t in ["trade_intents","risk_decisions","execution_intents","dispatch_attempts","execution_states"]: assert t in tables

def test_t3_plan_versions(): assert [m.version for m in MIGRATION_PLAN]==[1,2,3]

def test_t4_v2_v3_upgrade():
    d=tempfile.mkdtemp(); p=pathlib.Path(d)/"test.db"
    db=RuntimeDatabase(p); db.connect()
    MigrationManager(db,tuple(m for m in MIGRATION_PLAN if m.version<=2)).migrate()
    _ins_session(db); _ins_cycle(db)
    db.connection.execute("INSERT INTO recovery_states (recovery_id,session_id,status,unresolved_items,started_at) VALUES ('r1','s1','PENDING','[]','t')")
    db.connection.execute("INSERT INTO cycle_journal (cycle_id, from_state, to_state, recorded_at) VALUES ('c1','CREATED','MARKET_ACCEPTED','2026-07-01T00:00:00Z')")
    db.connection.commit(); db.close()
    db2=RuntimeDatabase(p); db2.connect()
    MigrationManager(db2,tuple(m for m in MIGRATION_PLAN if m.version<=3)).migrate(); db2.connection.commit()
    assert db2.connection.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0]==3
    assert db2.connection.execute("SELECT session_id FROM runtime_sessions").fetchone() is not None
    assert db2.connection.execute("SELECT cycle_id FROM runtime_cycles").fetchone() is not None
    assert db2.connection.execute("SELECT recovery_id FROM recovery_states").fetchone() is not None
    tabs=[r[0] for r in db2.connection.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
    for t in ["trade_intents","risk_decisions","execution_intents","dispatch_attempts","execution_states"]: assert t in tabs

def test_t5_noop():
    db=_db()
    assert MigrationManager(db,tuple(m for m in MIGRATION_PLAN if m.version<=3)).migrate()==0

# ===================== constraints =====================
def test_t6_invalid_action():
    with pytest.raises(sqlite3.IntegrityError): _db().connection.execute("INSERT INTO trade_intents VALUES ('t1','BTC','RUN','1','x','x','1','0','0','x','x','t')")

def test_t7_hold_accepted():
    db=_db(); _ins_ti(db,"t1","HOLD")  # ok

def test_t8_invalid_decision():
    db=_db(); _ins_ti(db); db.connection.commit()
    with pytest.raises(sqlite3.IntegrityError): _ins_rd(db,decision="MAYBE")

def test_t9_missing_ti_fk():
    with pytest.raises(sqlite3.IntegrityError): _ins_rd(db:=_db(), tid="nonexistent")

def test_t10_missing_cycle_fk():
    db=_db(); _ins_ti(db); _ins_rd(db); db.connection.commit()
    with pytest.raises(sqlite3.IntegrityError): _ins_ei(db,cid="nonexistent")

def test_t11_missing_trade_intent_fk():
    db=_db(); _ins_session(db); _ins_cycle(db); db.connection.commit()
    with pytest.raises(sqlite3.IntegrityError): _ins_ei(db,tid="nonexistent")

def test_t12_risk_ownership_mismatch():
    db=_db()
    _ins_ti(db,"t1"); _ins_ti(db,"t2","SELL"); _ins_rd(db,"r1","t1"); _ins_session(db); _ins_cycle(db); db.connection.commit()
    with pytest.raises(sqlite3.IntegrityError): _ins_ei(db,tid="t2",rid="r1")

def test_t13_ei_hold_rejected():
    db=_db(); _ins_ti(db,action="HOLD"); _ins_rd(db); _ins_session(db); _ins_cycle(db); db.connection.commit()
    with pytest.raises(sqlite3.IntegrityError): _ins_ei(db, action="HOLD")

def test_t14_hash_wrong_length():
    db=_db(); _ins_session(db); _ins_cycle(db); _ins_ti(db); _ins_rd(db); db.connection.commit()
    with pytest.raises(sqlite3.IntegrityError): _ins_ei(db, nhash="a"*63)

def test_t15_hash_non_hex():
    db=_db(); _ins_session(db); _ins_cycle(db); _ins_ti(db); _ins_rd(db); db.connection.commit()
    with pytest.raises(sqlite3.IntegrityError): _ins_ei(db, nhash="g"+"a"*63)

def test_t16_identical_hash_ok():
    db=_db(); _setup_graph(db)
    db.connection.execute("INSERT INTO execution_intents VALUES ('e2','t1','r1','c1','BTC','BUY','200',?,?)",(_h("e1"),"t"))

def test_t17_invalid_dispatch_status():
    db=_db(); _setup_graph(db)
    with pytest.raises(sqlite3.IntegrityError): db.connection.execute("INSERT INTO dispatch_attempts VALUES ('d1','e1','cid','v','a','BOGUS',1,'t',NULL,NULL,NULL)")

def test_t18_attempt_lt_1():
    db=_db(); _setup_graph(db)
    with pytest.raises(sqlite3.IntegrityError): db.connection.execute("INSERT INTO dispatch_attempts VALUES ('d1','e1','cid','v','a','SUBMITTED',0,'t',NULL,NULL,NULL)")

def test_t19_duplicate_attempt_no():
    db=_db(); _setup_graph(db); _ins_da(db,"d1","e1",1)
    with pytest.raises(sqlite3.IntegrityError): _ins_da(db,"d2","e1",1)

def test_t20_same_client_order_ok():
    db=_db(); _setup_graph(db)
    db.connection.execute("INSERT INTO dispatch_attempts VALUES ('d1','e1','cid','v','a','SUBMITTED',1,'t',NULL,NULL,NULL)")
    db.connection.execute("INSERT INTO dispatch_attempts VALUES ('d2','e1','cid','v','a','SUBMITTED',2,'t',NULL,NULL,NULL)")

def test_t21_es_invalid_status():
    db=_db(); _setup_graph(db)
    with pytest.raises(sqlite3.IntegrityError): db.connection.execute("INSERT INTO execution_states VALUES ('e1','BOGUS',NULL,0,'t','t')")

def test_t22_es_negative_retry():
    db=_db(); _setup_graph(db)
    with pytest.raises(sqlite3.IntegrityError): db.connection.execute("INSERT INTO execution_states VALUES ('e1','PREPARED',NULL,-1,'t','t')")

def test_t23_es_wrong_attempt():
    db=_db(); _setup_graph(db)
    _ins_ei(db,"e2","t1","r1","c1","BUY",_h("e2")); db.connection.commit()
    _ins_da(db,"d1","e2",1); db.connection.commit()
    with pytest.raises(sqlite3.IntegrityError): db.connection.execute("INSERT INTO execution_states VALUES ('e1','PREPARED','d1',0,'t','t')")

def test_t24_es_correct_attempt_ok():
    db=_db(); _setup_graph(db); _ins_da(db,"d1","e1",1)
    db.connection.execute("INSERT INTO execution_states VALUES ('e1','PREPARED','d1',0,'t','t')")

# ===================== immutability =====================
def _setup_ti(db): _ins_ti(db); db.connection.commit()

def test_t25_ti_update(): db=_db(); _setup_ti(db); pytest.raises(sqlite3.IntegrityError, db.connection.execute, "UPDATE trade_intents SET symbol='ETH' WHERE trade_intent_id='t1'")
def test_t26_ti_delete(): db=_db(); _setup_ti(db); pytest.raises(sqlite3.IntegrityError, db.connection.execute, "DELETE FROM trade_intents WHERE trade_intent_id='t1'")
def test_t27_rd_update():
    db=_db(); _setup_ti(db); _ins_rd(db); db.connection.commit()
    pytest.raises(sqlite3.IntegrityError, db.connection.execute, "UPDATE risk_decisions SET decision='REJECTED' WHERE risk_decision_id='r1'")
def test_t28_rd_delete():
    db=_db(); _setup_ti(db); _ins_rd(db); db.connection.commit()
    pytest.raises(sqlite3.IntegrityError, db.connection.execute, "DELETE FROM risk_decisions WHERE risk_decision_id='r1'")
def test_t29_ei_update():
    db=_db(); _setup_graph(db)
    pytest.raises(sqlite3.IntegrityError, db.connection.execute, "UPDATE execution_intents SET symbol='ETH' WHERE execution_intent_id='e1'")
def test_t30_ei_delete():
    db=_db(); _setup_graph(db)
    pytest.raises(sqlite3.IntegrityError, db.connection.execute, "DELETE FROM execution_intents WHERE execution_intent_id='e1'")
