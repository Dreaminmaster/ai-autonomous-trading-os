"""Execution persistence schema contract tests — migration 0003."""
import tempfile, pathlib, hashlib, pytest
from atos.runtime_db import RuntimeDatabase
from atos.runtime_migrations import MigrationManager, MIGRATION_PLAN

def _db():
    d=tempfile.mkdtemp()
    db=RuntimeDatabase(pathlib.Path(d)/"test.db")
    db.connect()
    MigrationManager(db,tuple(m for m in MIGRATION_PLAN if m.version<=3)).migrate()
    db.connection.commit()
    return db

def _db_v2():
    d=tempfile.mkdtemp()
    db=RuntimeDatabase(pathlib.Path(d)/"test.db")
    db.connect()
    MigrationManager(db,tuple(m for m in MIGRATION_PLAN if m.version<=2)).migrate()
    db.connection.commit()
    return db

# T1+T2+T3: Schema basics
def test_t1_fresh_migrates():
    db=_db()
    v=db.connection.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0]
    assert v==3

def test_t2_five_tables():
    db=_db()
    tables=[r[0] for r in db.connection.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
    for t in ['trade_intents','risk_decisions','execution_intents','dispatch_attempts','execution_states']:
        assert t in tables

def test_t3_plan_versions():
    assert [m.version for m in MIGRATION_PLAN]==[1,2,3]

# T4: real v2→v3 upgrade
def test_t4_v2_v3_upgrade():
    db=_db_v2()
    db.connection.execute("INSERT INTO runtime_sessions VALUES ('s1','t','paper','STARTING',NULL,NULL)")
    db.connection.execute("INSERT INTO runtime_cycles (cycle_id,session_id,symbol,started_at,status) VALUES ('cx','sx','BTC','t','CREATED')")
    db.connection.execute("INSERT INTO recovery_states (recovery_id,session_id,status,unresolved_items,started_at) VALUES ('r1','s1','PENDING','[]','t')")
    db.connection.execute("INSERT INTO cycle_journal (cycle_id, from_state, to_state, recorded_at) VALUES ('c1','CREATED','MARKET_ACCEPTED','2026-07-01T00:00:00Z')")
    path=db.conn
    db.close()
    db2=RuntimeDatabase(path); db2.connect()
    MigrationManager(db2,tuple(m for m in MIGRATION_PLAN if m.version<=3)).migrate()
    db2.connection.commit()
    assert db2.connection.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0]==3
    assert db2.connection.execute("SELECT session_id FROM runtime_sessions WHERE session_id='s1'").fetchone() is not None
    assert db2.connection.execute("SELECT cycle_id FROM runtime_cycles WHERE cycle_id='c1'").fetchone() is not None
    assert db2.connection.execute("SELECT recovery_id FROM recovery_states WHERE recovery_id='r1'").fetchone() is not None
    assert db2.connection.execute("SELECT journal_id FROM cycle_journal WHERE cycle_id='c1'").fetchone() is not None

# T5: no-op second migrate
def test_t5_noop():
    db=_db()
    r=MigrationManager(db,tuple(m for m in MIGRATION_PLAN if m.version<=3)).migrate()
    assert r==0

# T6-T7: TradeIntent constraints
def test_t6_invalid_action():
    with pytest.raises(Exception):
        _db().connection.execute("INSERT INTO trade_intents VALUES ('t1','BTC','RUN','0.5','','','0','0','0','','','t')")

def test_t7_hold_accepted():
    db=_db()
    db.connection.execute("INSERT INTO trade_intents VALUES ('t1','BTC','HOLD','0.5','x','x','0','0','0','x','x','t')")

# T8-T9: RiskDecision constraints
def test_t8_invalid_decision():
    with pytest.raises(Exception):
        _db().connection.execute("INSERT INTO risk_decisions VALUES ('r1','t1','MAYBE','','0','{}','t')")

def test_t9_missing_fk():
    with pytest.raises(Exception):
        _db().connection.execute("INSERT INTO risk_decisions VALUES ('r1','nonexistent','APPROVED','','0','{}','t')")

# T10-T13: ExecutionIntent constraints
def test_t10_ei_missing_cycle():
    db=_db()
    db.connection.execute("INSERT INTO trade_intents VALUES ('t1','BTC','BUY','1','x','x','1','0','0','x','x','t')")
    db.connection.execute("INSERT INTO risk_decisions VALUES ('r1','t1','APPROVED','x','0','{}','t')")
    with pytest.raises(Exception):
        db.connection.execute("INSERT INTO execution_intents VALUES ('e1','t1','r1','nonexistent','BTC','BUY','100','a'*64,'t')")

def test_t11_ei_missing_ti():
    with pytest.raises(Exception):
        _db().connection.execute("INSERT INTO execution_intents VALUES ('e1','nonexistent','r1','c1','BTC','BUY','100','a'*64,'t')")

def test_t12_ei_mismatched_rd():
    db=_db()
    db.connection.execute("INSERT INTO trade_intents VALUES ('t1','BTC','BUY','1','x','x','1','0','0','x','x','t')")
    db.connection.execute("INSERT INTO runtime_sessions VALUES ('sx','t','paper','RUNNING',NULL,NULL)")
    db.connection.execute("INSERT INTO runtime_cycles (cycle_id,session_id,symbol,started_at,status) VALUES ('cx','sx','BTC','t','CREATED')")
    db.connection.commit()
    with pytest.raises(Exception):
        db.connection.execute("INSERT INTO execution_intents VALUES ('e1','t1','r1','cx','BTC','BUY','100','a'*64,'t')")

def test_t13_ei_hold_rejected():
    db=_db()
    db.connection.execute("INSERT INTO trade_intents VALUES ('t1','BTC','HOLD','1','x','x','1','0','0','x','x','t')")
    with pytest.raises(Exception):
        db.connection.execute("INSERT INTO execution_intents VALUES ('e1','t1','r1','cx','BTC','HOLD','100','a'*64,'t')")

# T14-T16: hash constraints
def _insert_ti_rd(db):
    db.connection.execute("INSERT INTO trade_intents VALUES ('t1','BTC','BUY','1','x','x','1','0','0','x','x','t')")
    db.connection.execute("INSERT INTO risk_decisions VALUES ('r1','t1','APPROVED','x','0','{}','t')")
    db.connection.execute("INSERT INTO runtime_sessions VALUES ('sx','t','paper','RUNNING',NULL,NULL)")
    db.connection.execute("INSERT INTO runtime_cycles (cycle_id,session_id,symbol,started_at,status) VALUES ('cx','sx','BTC','t','CREATED')")
    db.connection.commit()

def test_t14_hash_wrong_length():
    db=_db();_insert_ti_rd(db)
    with pytest.raises(Exception):
        db.connection.execute("INSERT INTO execution_intents VALUES ('e1','t1','r1','cx','BTC','BUY','100','abc','t')")

def test_t15_hash_non_lower_hex():
    db=_db();_insert_ti_rd(db)
    with pytest.raises(Exception):
        db.connection.execute("INSERT INTO execution_intents VALUES ('e1','t1','r1','cx','BTC','BUY','100','A'+'a'*63,'t')")

def test_t16_identical_hash_ok():
    db=_db();_insert_ti_rd(db)
    db.connection.execute("INSERT INTO execution_intents VALUES ('e1','t1','r1','cx','BTC','BUY','100','a'*64,'t')")
    db.connection.execute("INSERT INTO execution_intents VALUES ('e2','t1','r1','cx','BTC','BUY','100','a'*64,'t')")

# T17-T20: dispatch_attempts
def _setup_ei(db):
    _insert_ti_rd(db)
    db.connection.execute("INSERT INTO execution_intents VALUES ('e1','t1','r1','cx','BTC','BUY','100','a'*64,'t')")
    db.connection.commit()

def test_t17_invalid_status():
    db=_db();_setup_ei(db)
    with pytest.raises(Exception):
        db.connection.execute("INSERT INTO dispatch_attempts VALUES ('d1','e1','cid','v','a','BOGUS',1,'t',NULL,NULL,NULL)")

def test_t18_attempt_no_lt_1():
    db=_db();_setup_ei(db)
    with pytest.raises(Exception):
        db.connection.execute("INSERT INTO dispatch_attempts VALUES ('d1','e1','cid','v','a','SUBMITTED',0,'t',NULL,NULL,NULL)")

def test_t19_duplicate_attempt_no():
    db=_db();_setup_ei(db)
    db.connection.execute("INSERT INTO dispatch_attempts VALUES ('d1','e1','cid','v','a','SUBMITTED',1,'t',NULL,NULL,NULL)")
    with pytest.raises(Exception):
        db.connection.execute("INSERT INTO dispatch_attempts VALUES ('d2','e1','cid','v','a','SUBMITTED',1,'t',NULL,NULL,NULL)")

def test_t20_same_client_order_ok():
    db=_db();_setup_ei(db)
    db.connection.execute("INSERT INTO dispatch_attempts VALUES ('d1','e1','cid','v','a','SUBMITTED',1,'t',NULL,NULL,NULL)")
    db.connection.execute("INSERT INTO dispatch_attempts VALUES ('d2','e1','cid','v','a','SUBMITTED',2,'t',NULL,NULL,NULL)")

# T21-T24: execution_states
def test_t21_es_invalid_status():
    db=_db();_setup_ei(db)
    with pytest.raises(Exception):
        db.connection.execute("INSERT INTO execution_states VALUES ('e1','BOGUS',NULL,0,'t','t')")

def test_t22_es_negative_retry():
    db=_db();_setup_ei(db)
    with pytest.raises(Exception):
        db.connection.execute("INSERT INTO execution_states VALUES ('e1','PREPARED',NULL,-1,'t','t')")

def test_t23_es_wrong_attempt():
    db=_db();_setup_ei(db)
    db.connection.execute("INSERT INTO execution_intents VALUES ('e2','t1','r1','cx','BTC','BUY','100','b'*64,'t')")
    db.connection.execute("INSERT INTO dispatch_attempts VALUES ('d1','e2','cid','v','a','SUBMITTED',1,'t',NULL,NULL,NULL)")
    db.connection.commit()
    with pytest.raises(Exception):
        db.connection.execute("INSERT INTO execution_states VALUES ('e1','PREPARED','d1',0,'t','t')")

def test_t24_es_correct_attempt_accepted():
    db=_db();_setup_ei(db)
    db.connection.execute("INSERT INTO dispatch_attempts VALUES ('d1','e1','cid','v','a','SUBMITTED',1,'t',NULL,NULL,NULL)")
    db.connection.execute("INSERT INTO execution_states VALUES ('e1','PREPARED','d1',0,'t','t')")

# T25-T30: immutability
def _ti(db):
    db.connection.execute("INSERT INTO runtime_sessions VALUES ('sx','t','paper','RUNNING',NULL,NULL)")
    db.connection.execute("INSERT INTO runtime_cycles (cycle_id,session_id,symbol,started_at,status) VALUES ('cx','sx','BTC','t','CREATED')")
    db.connection.commit()
    db.connection.execute("INSERT INTO trade_intents VALUES ('t99','BTC','BUY','1','x','x','1','0','0','x','x','t')")
    db.connection.commit()

def test_t25_ti_update(): db=_db();_ti(db);pytest.raises(Exception,db.connection.execute,"UPDATE trade_intents SET symbol='ETH' WHERE trade_intent_id='t99'")
def test_t26_ti_delete(): db=_db();_ti(db);pytest.raises(Exception,db.connection.execute,"DELETE FROM trade_intents WHERE trade_intent_id='t99'")
def test_t27_rd_update(): db=_db();_ti(db);db.connection.execute("INSERT INTO risk_decisions VALUES ('r99','t99','APPROVED','x','0','{}','t')");db.connection.commit();pytest.raises(Exception,db.connection.execute,"UPDATE risk_decisions SET decision='REJECTED' WHERE risk_decision_id='r99'")
def test_t28_rd_delete(): db=_db();_ti(db);db.connection.execute("INSERT INTO risk_decisions VALUES ('r99','t99','APPROVED','x','0','{}','t')");db.connection.commit();pytest.raises(Exception,db.connection.execute,"DELETE FROM risk_decisions WHERE risk_decision_id='r99'")
def test_t29_ei_update(): db=_db();_setup_ei(db);pytest.raises(Exception,db.connection.execute,"UPDATE execution_intents SET symbol='ETH' WHERE execution_intent_id='e1'")
def test_t30_ei_delete(): db=_db();_setup_ei(db);pytest.raises(Exception,db.connection.execute,"DELETE FROM execution_intents WHERE execution_intent_id='e1'")
