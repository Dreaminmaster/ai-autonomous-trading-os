import tempfile, pathlib, pytest
from atos.runtime_db import RuntimeDatabase
from atos.runtime_migrations import MigrationManager, MIGRATION_PLAN
from atos.runtime_state import RuntimeCycleStatus
from atos.runtime_state_writer import RuntimeStateWriter, CycleJournalRepository
C = RuntimeCycleStatus

def _db():
    d = tempfile.mkdtemp()
    db = RuntimeDatabase(pathlib.Path(d) / "test.db")
    db.connect()
    MigrationManager(db, MIGRATION_PLAN).migrate()
    db.connection.commit()
    return db

def _s(db, n=1):
    sid = "s%d"%n; cid = "c%d"%n
    db.connection.execute("INSERT INTO runtime_sessions VALUES (?,?,?,?,NULL,NULL)",(sid,"t","paper","RUNNING"))
    db.connection.execute("INSERT INTO runtime_cycles (cycle_id,session_id,symbol,started_at,status) VALUES (?,?,?,?,?)",(cid,sid,"BTC/USDT","t","CREATED"))
    db.connection.commit()
    return sid, cid

def test_journal_recorded_on_transition():
    db=_db();sid,cid=_s(db)
    w=RuntimeStateWriter(db)
    w.transition_cycle(cid,C.CREATED,C.MARKET_ACCEPTED,at_utc="2026-07-01T00:00:10Z")
    repo=CycleJournalRepository(db)
    rows=repo.get_journal(cid)
    assert len(rows)==1
    assert rows[0]["stage"]=="CREATED"

def test_journal_ordered():
    db=_db();sid,cid=_s(db)
    w=RuntimeStateWriter(db)
    w.transition_cycle(cid,C.CREATED,C.MARKET_ACCEPTED,at_utc="2026-07-01T00:00:10Z")
    w.transition_cycle(cid,C.MARKET_ACCEPTED,C.ACCOUNT_ACCEPTED,at_utc="2026-07-01T00:00:20Z")
    repo=CycleJournalRepository(db)
    rows=repo.get_journal(cid)
    assert len(rows)==2

def test_journal_rollback():
    db=_db();sid,cid=_s(db)
    w=RuntimeStateWriter(db)
    try:w.transition_cycle(cid,C.CREATED,C.ACCOUNT_ACCEPTED,at_utc="2026-07-01T00:00:10Z")
    except:pass
    repo=CycleJournalRepository(db)
    assert len(repo.get_journal(cid))==0

def test_session_timeline():
    db=_db();s1,c1=_s(db,1)
    db.connection.execute("INSERT INTO runtime_cycles (cycle_id,session_id,symbol,started_at,status) VALUES (?,?,?,?,?)",("c2","s1","ETH/USDT","t","CREATED"))
    db.connection.commit()
    w=RuntimeStateWriter(db)
    w.transition_cycle("c1",C.CREATED,C.MARKET_ACCEPTED,at_utc="2026-07-01T00:00:10Z")
    w.transition_cycle("c2",C.CREATED,C.MARKET_ACCEPTED,at_utc="2026-07-01T00:00:20Z")
    repo=CycleJournalRepository(db)
    rows=repo.get_session_timeline("s1")
    assert len(rows)==2
