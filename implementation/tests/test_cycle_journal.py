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
    plan = [m for m in MIGRATION_PLAN if m.version <= 2]
    MigrationManager(db, tuple(plan)).migrate()
    db.connection.commit()
    return db

def _cycle(db, n=1):
    sid = f"s{n}"; cid = f"c{n}"
    db.connection.execute("INSERT INTO runtime_sessions VALUES (?,?,?,?,NULL,NULL)",(sid,"t","paper","RUNNING"))
    db.connection.execute("INSERT INTO runtime_cycles (cycle_id,session_id,symbol,started_at,status) VALUES (?,?,?,?,?)",(cid,sid,"BTC/USDT","t","CREATED"))
    db.connection.commit()
    return sid, cid

def test_journal_from_state():
    db=_db2();sid,cid=_cycle(db)
    w=RuntimeStateWriter(db)
    w.transition_cycle(cid,C.CREATED,C.MARKET_ACCEPTED,at_utc="2026-07-01T00:00:10Z")
    repo=CycleJournalRepository(db)
    j=repo.get_journal(cid)
    assert len(j)==1
    assert j[0].from_state==C.CREATED
    assert j[0].to_state==C.MARKET_ACCEPTED

def test_journal_ordered():
    db=_db2();sid,cid=_cycle(db)
    w=RuntimeStateWriter(db)
    w.transition_cycle(cid,C.CREATED,C.MARKET_ACCEPTED,at_utc="2026-07-01T00:00:10Z")
    w.transition_cycle(cid,C.MARKET_ACCEPTED,C.ACCOUNT_ACCEPTED,at_utc="2026-07-01T00:00:20Z")
    repo=CycleJournalRepository(db)
    j=repo.get_journal(cid)
    assert len(j)==2

def test_journal_rollback():
    db=_db2();sid,cid=_cycle(db)
    w=RuntimeStateWriter(db)
    try:w.transition_cycle(cid,C.CREATED,C.ACCOUNT_ACCEPTED,at_utc="2026-07-01T00:00:10Z")
    except:pass
    assert len(CycleJournalRepository(db).get_journal(cid))==0

def test_frozen_record():
    j=JournalRecord(1,"c1",C.CREATED,C.MARKET_ACCEPTED,"2026-01-01")
    with pytest.raises(Exception): j.from_state=C.EXECUTED

def test_get_unreconciled():
    db=_db2();s1,_=_cycle(db,1)
    db.connection.execute("INSERT INTO runtime_cycles (cycle_id,session_id,symbol,started_at,status) VALUES (?,?,?,?,?)",("c2","s1","ETH/USDT","t","CREATED"))
    db.connection.commit()
    w=RuntimeStateWriter(db)
    w.transition_cycle("c1",C.CREATED,C.MARKET_ACCEPTED,at_utc="2026-07-01T00:00:10Z")
    repo=CycleJournalRepository(db)
    rows=repo.get_unreconciled_cycles_for_session("s1")
    assert len(rows)>=1
