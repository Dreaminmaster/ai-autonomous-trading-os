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

# R2: exact v2->v3 row preservation
def test_t4b_exact_row_preservation():
    d=tempfile.mkdtemp();p=pathlib.Path(d)/"test.db"
    db=RuntimeDatabase(p);db.connect()
    MigrationManager(db,tuple(m for m in MIGRATION_PLAN if m.version<=2)).migrate()
    db.connection.execute("INSERT INTO runtime_sessions VALUES ('s1','t','paper','STARTING',NULL,NULL)")
    db.connection.execute("INSERT INTO runtime_cycles VALUES ('c1','s1','BTC','t',NULL,'CREATED',NULL,NULL)")
    db.connection.execute("INSERT INTO recovery_states VALUES ('r1','s1','PENDING','[]','t',NULL)")
    db.connection.execute("INSERT INTO cycle_journal (cycle_id,from_state,to_state,recorded_at) VALUES ('c1','CREATED','MARKET_ACCEPTED','2026-01-01T00:00:00Z')")
    db.connection.commit()
    s_b=db.connection.execute("SELECT * FROM runtime_sessions WHERE session_id='s1'").fetchone()
    c_b=db.connection.execute("SELECT * FROM runtime_cycles WHERE cycle_id='c1'").fetchone()
    r_b=db.connection.execute("SELECT * FROM recovery_states WHERE recovery_id='r1'").fetchone()
    j_b=db.connection.execute("SELECT * FROM cycle_journal WHERE cycle_id='c1'").fetchone()
    db.close()
    db2=RuntimeDatabase(p);db2.connect()
    MigrationManager(db2,tuple(m for m in MIGRATION_PLAN if m.version<=3)).migrate();db2.connection.commit()
    assert db2.connection.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0]==3
    assert tuple(db2.connection.execute("SELECT * FROM runtime_sessions WHERE session_id='s1'").fetchone())==tuple(s_b)
    assert tuple(db2.connection.execute("SELECT * FROM runtime_cycles WHERE cycle_id='c1'").fetchone())==tuple(c_b)
    assert tuple(db2.connection.execute("SELECT * FROM recovery_states WHERE recovery_id='r1'").fetchone())==tuple(r_b)
    assert tuple(db2.connection.execute("SELECT * FROM cycle_journal WHERE cycle_id='c1'").fetchone())==tuple(j_b)


def test_t31a_ti_columns():
    db=_db();cols=db.connection.execute("PRAGMA table_info(trade_intents)").fetchall()
    expected=[("trade_intent_id",0,1),("symbol",1,0),("action",1,0),("confidence",1,0),("thesis",1,0),("evidence",1,0),("position_size_pct",1,0),("stop_loss_pct",1,0),("take_profit_pct",1,0),("invalidation_conditions",1,0),("selected_strategy_ids",1,0),("created_at",1,0)]
    assert [(c[1],c[3],c[5]) for c in cols]==expected

def test_t31b_rd_columns():
    db=_db();cols=db.connection.execute("PRAGMA table_info(risk_decisions)").fetchall()
    expected=[("risk_decision_id",0,1),("trade_intent_id",1,0),("decision",1,0),("reasons",1,0),("risk_score",1,0),("checks_json",1,0),("created_at",1,0)]
    assert [(c[1],c[3],c[5]) for c in cols]==expected

def test_t31c_ei_columns():
    db=_db();cols=db.connection.execute("PRAGMA table_info(execution_intents)").fetchall()
    expected=[("execution_intent_id",0,1),("trade_intent_id",1,0),("risk_decision_id",1,0),("cycle_id",1,0),("symbol",1,0),("action",1,0),("notional",1,0),("normalized_intent_hash",1,0),("created_at",1,0)]
    assert [(c[1],c[3],c[5]) for c in cols]==expected

def test_t31d_da_columns():
    db=_db();cols=db.connection.execute("PRAGMA table_info(dispatch_attempts)").fetchall()
    expected=[("attempt_id",0,1),("execution_intent_id",1,0),("client_order_id",1,0),("venue",1,0),("account_scope",1,0),("status",1,0),("attempt_no",1,0),("created_at",1,0),("dispatch_started_at",0,0),("response_received_at",0,0),("error_class",0,0)]
    assert [(c[1],c[3],c[5]) for c in cols]==expected

def test_t31e_es_columns():
    db=_db();cols=db.connection.execute("PRAGMA table_info(execution_states)").fetchall()
    expected=[("execution_intent_id",0,1),("status",1,0),("last_attempt_id",0,0),("retry_count",1,0),("state_started_at",1,0),("updated_at",1,0)]
    assert [(c[1],c[3],c[5]) for c in cols]==expected
    assert cols[3]["dflt_value"]=="0"

def test_t32a_rd_fk():
    db=_db();fks=db.connection.execute("PRAGMA foreign_key_list(risk_decisions)").fetchall()
    fk=next(f for f in fks if f["from"]=="trade_intent_id")
    assert fk["table"]=="trade_intents" and fk["to"]=="trade_intent_id"

def test_t32b_ei_fks():
    db=_db();fks=db.connection.execute("PRAGMA foreign_key_list(execution_intents)").fetchall()
    by_src={f["from"]:f for f in fks}
    assert by_src["trade_intent_id"]["table"]=="trade_intents"
    assert by_src["cycle_id"]["table"]=="runtime_cycles"
    by_id={};[by_id.setdefault(f["id"],[]).append(f) for f in fks]
    comp=[g for g in by_id.values() if len(g)==2 and {f["from"] for f in g}=={"risk_decision_id","trade_intent_id"}]
    assert len(comp)==1
    g=sorted(comp[0],key=lambda f:f["seq"])
    assert g[0]["from"]=="risk_decision_id" and g[0]["to"]=="risk_decision_id"
    assert g[1]["from"]=="trade_intent_id" and g[1]["to"]=="trade_intent_id"

def test_t33_indexes():
    db=_db()
    ix=[r[0] for r in db.connection.execute("SELECT name FROM sqlite_master WHERE type='index'").fetchall()]
    for n in ['idx_risk_decisions_trade_intent','idx_execution_intents_cycle','idx_execution_intents_trade_intent','idx_dispatch_attempts_execution','idx_dispatch_attempts_client_order','idx_execution_states_status']:
        assert n in ix

def test_t34a_v1_checksum():
    import hashlib
    assert hashlib.sha256(MIGRATION_PLAN[0].sql.encode()).hexdigest()=="b039c238f7d11bcd2fe09e33422a32ad0728147d01c34ffef759fae32fba0b1d"

def test_t34b_v2_checksum():
    import hashlib
    assert hashlib.sha256(MIGRATION_PLAN[1].sql.encode()).hexdigest()=="f2e8d13f91b7681f4a379c1fb7cff3b5cb12726dd3ebbdd93063b30fda192cca"

def test_hash_64_lower():
    db=_db();_ins_session(db);_ins_cycle(db);_ins_ti(db);_ins_rd(db);db.connection.commit()
    db.connection.execute("INSERT INTO execution_intents VALUES ('eh1','t1','r1','c1','BTC','BUY','100','"+"a"*64+"','t')")

def test_hash_63_fail():
    db=_db();_ins_session(db);_ins_cycle(db);_ins_ti(db);_ins_rd(db);db.connection.commit()
    with pytest.raises(sqlite3.IntegrityError): db.connection.execute("INSERT INTO execution_intents VALUES ('eh2','t1','r1','c1','BTC','BUY','100','"+"a"*63+"','t')")

def test_hash_uppercase_fail():
    db=_db();_ins_session(db);_ins_cycle(db);_ins_ti(db);_ins_rd(db);db.connection.commit()
    with pytest.raises(sqlite3.IntegrityError): db.connection.execute("INSERT INTO execution_intents VALUES ('eh3','t1','r1','c1','BTC','BUY','100','"+"A"+"a"*63+"','t')")

def test_hash_g_char_fail():
    db=_db();_ins_session(db);_ins_cycle(db);_ins_ti(db);_ins_rd(db);db.connection.commit()
    with pytest.raises(sqlite3.IntegrityError): db.connection.execute("INSERT INTO execution_intents VALUES ('eh4','t1','r1','c1','BTC','BUY','100','"+"a"*63+"g"+"','t')")
