import tempfile, pathlib, pytest
from atos.runtime_db import RuntimeDatabase
from atos.runtime_migrations import MigrationManager, MIGRATION_PLAN
from atos.runtime_state import RuntimeCycleStatus, JournalRecord
from atos.runtime_state_writer import RuntimeStateWriter, CycleJournalRepository
C = RuntimeCycleStatus

def _db2():
    d = tempfile.mkdtemp()
    db = RuntimeDatabase(pathlib.Path(d) / "test.db")
    db.connect()
    plan = tuple(m for m in MIGRATION_PLAN if m.version <= 2)
    MigrationManager(db, plan).migrate()
    db.connection.commit()
    return db

def _cy(db, n=1):
    sid = "s%d" % n; cid = "c%d" % n
    db.connection.execute("INSERT INTO runtime_sessions VALUES (?,?,?,?,NULL,NULL)", (sid,"t","paper","RUNNING"))
    db.connection.execute("INSERT INTO runtime_cycles (cycle_id,session_id,symbol,started_at,status) VALUES (?,?,?,?,?)", (cid,sid,"BTC/USDT","t","CREATED"))
    db.connection.commit()
    return sid, cid

# T1-T4: from_state/ordered
def test_t1_from_to_state():
    db=_db2();sid,cid=_cy(db)
    w=RuntimeStateWriter(db)
    w.transition_cycle(cid,C.CREATED,C.MARKET_ACCEPTED,at_utc="2026-07-01T00:00:10Z")
    j=CycleJournalRepository(db).get_journal(cid)
    assert len(j)==1
    assert j[0].from_state==C.CREATED
    assert j[0].to_state==C.MARKET_ACCEPTED
    assert isinstance(j[0],JournalRecord)

def test_t5_ordered():
    db=_db2();sid,cid=_cy(db)
    w=RuntimeStateWriter(db)
    w.transition_cycle(cid,C.CREATED,C.MARKET_ACCEPTED,at_utc="2026-07-01T00:00:10Z")
    w.transition_cycle(cid,C.MARKET_ACCEPTED,C.ACCOUNT_ACCEPTED,at_utc="2026-07-01T00:00:20Z")
    j=CycleJournalRepository(db).get_journal(cid)
    assert len(j)==2
    assert j[0].to_state==C.MARKET_ACCEPTED
    assert j[1].to_state==C.ACCOUNT_ACCEPTED

# T6: invalid transition zero journal
def test_t6_rollback_invalid():
    db=_db2();sid,cid=_cy(db)
    w=RuntimeStateWriter(db)
    try: w.transition_cycle(cid,C.CREATED,C.ACCOUNT_ACCEPTED,at_utc="2026-07-01T00:00:10Z")
    except: pass
    assert len(CycleJournalRepository(db).get_journal(cid))==0

# T7: CAS loser zero journal  
def test_t7_cas_loser_zero():
    db=_db2()
    db.connection.execute("INSERT INTO runtime_sessions VALUES ('s1','t','paper','RUNNING',NULL,NULL)")
    db.connection.execute("INSERT INTO runtime_cycles (cycle_id,session_id,symbol,started_at,status) VALUES ('c1','s1','BTC/USDT','t','EXECUTED')")
    db.connection.commit()
    w=RuntimeStateWriter(db)
    try: w.transition_cycle("c1",C.CREATED,C.MARKET_ACCEPTED,at_utc="2026-07-01T00:00:10Z")
    except: pass
    assert len(CycleJournalRepository(db).get_journal("c1"))==0

# T12: restart persistence
def test_t12_persistence():
    d = tempfile.mkdtemp()
    path = pathlib.Path(d) / "test.db"
    db=RuntimeDatabase(path)
    db.connect()
    plan = tuple(m for m in MIGRATION_PLAN if m.version <= 2)
    MigrationManager(db, plan).migrate()
    db.connection.commit()
    sid="s1";cid="c1"
    db.connection.execute("INSERT INTO runtime_sessions VALUES (?,?,?,?,NULL,NULL)",(sid,"t","paper","RUNNING"))
    db.connection.execute("INSERT INTO runtime_cycles (cycle_id,session_id,symbol,started_at,status) VALUES (?,?,?,?,?)",(cid,sid,"BTC/USDT","t","CREATED"))
    db.connection.commit()
    w=RuntimeStateWriter(db)
    w.transition_cycle(cid,C.CREATED,C.MARKET_ACCEPTED,at_utc="2026-07-01T00:00:10Z")
    db.close()
    # Reopen
    db2=RuntimeDatabase(path)
    db2.connect()
    MigrationManager(db2, plan).migrate()
    repo2=CycleJournalRepository(db2)
    j=repo2.get_journal(cid)
    assert len(j)==1
    assert j[0].to_state==C.MARKET_ACCEPTED

def test_frozen():
    j=JournalRecord(1,"c1",C.CREATED,C.MARKET_ACCEPTED,"2026-07-01T00:00:10Z")
    with pytest.raises(Exception): j.from_state=C.EXECUTED

def test_v1_to_v2_upgrade():
    import tempfile, pathlib
    from atos.runtime_db import RuntimeDatabase
    from atos.runtime_migrations import MigrationManager, MIGRATION_PLAN
    d=tempfile.mkdtemp()
    db=RuntimeDatabase(pathlib.Path(d)/"test.db")
    db.connect()
    plan_v1=(MIGRATION_PLAN[0],)
    MigrationManager(db,plan_v1).migrate()
    db.connection.execute("INSERT INTO runtime_sessions VALUES ('s1','t','paper','STARTING',NULL,NULL)")
    db.connection.execute("INSERT INTO runtime_cycles (cycle_id,session_id,symbol,started_at,status) VALUES ('c1','s1','BTC','t','CREATED')")
    db.connection.commit()
    db.close()
    db2=RuntimeDatabase(pathlib.Path(d)/"test.db")
    db2.connect()
    MigrationManager(db2,tuple(m for m in MIGRATION_PLAN if m.version<=2)).migrate()
    db2.connection.commit()
    s=db2.connection.execute("SELECT session_id FROM runtime_sessions WHERE session_id='s1'").fetchone()
    assert s is not None
    c=db2.connection.execute("SELECT cycle_id FROM runtime_cycles WHERE cycle_id='c1'").fetchone()
    assert c is not None
    tables=[r['name'] for r in db2.connection.execute("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE '%cycle_journal%'").fetchall()]
    assert any('cycle_journal' in t for t in tables)

def test_journal_append_failure_rollback():
    db=_db2();sid,cid=_cy(db)
    w=RuntimeStateWriter(db)
    orig=w._reader.get_cycle
    try:
        def _blow(*a,**kw):raise RuntimeError("injected")
        w._reader.get_cycle=_blow
        w.transition_cycle(cid,C.CREATED,C.MARKET_ACCEPTED,at_utc="2026-07-01T00:00:10Z")
        assert False
    except RuntimeError:pass
    finally:w._reader.get_cycle=orig
    assert len(CycleJournalRepository(db).get_journal(cid))==0

def test_commit_failure_no_partial():
    db=_db2();sid,cid=_cy(db)
    before=db.connection.execute("SELECT status FROM runtime_cycles WHERE cycle_id=?",(cid,)).fetchone()["status"]
    w=RuntimeStateWriter(db)
    orig=w._db.transaction
    def _bad(*a,**kw):
        class Bad: __enter__=lambda s: (_ for _ in ()).throw(RuntimeError("commit fail")); __exit__=lambda s,*_:None
        return Bad()
    try:
        w._db.transaction=_bad
        w.transition_cycle(cid,C.CREATED,C.MARKET_ACCEPTED,at_utc="2026-07-01T00:00:10Z")
        assert False
    except RuntimeError:pass
    finally:w._db.transaction=orig
    after=db.connection.execute("SELECT status FROM runtime_cycles WHERE cycle_id=?",(cid,)).fetchone()["status"]
    assert after==before
    assert len(CycleJournalRepository(db).get_journal(cid))==0

def test_concurrency_one_winner():
    db=_db2();sid,cid=_cy(db)
    w1=RuntimeStateWriter(db)
    w2=RuntimeStateWriter(db)
    w1.transition_cycle(cid,C.CREATED,C.MARKET_ACCEPTED,at_utc="2026-07-01T00:00:10Z")
    try:w2.transition_cycle(cid,C.CREATED,C.MARKET_ACCEPTED,at_utc="2026-07-01T00:00:10Z");assert False
    except:pass
    assert len(CycleJournalRepository(db).get_journal(cid))==1

def test_no_standalone_mutation():
    ci=CycleJournalRepository(_db2())
    assert not hasattr(ci,"record_transition")
    assert hasattr(ci,"_append_transition")
