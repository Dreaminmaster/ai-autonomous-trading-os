import tempfile, pathlib, pytest
from atos.runtime_db import RuntimeDatabase
from atos.runtime_migrations import MigrationManager, MIGRATION_PLAN
from atos.runtime_state import RuntimeCycleStatus, JournalRecord
from atos.runtime_state_writer import RuntimeStateWriter, CycleJournalRepository, RuntimeStateWriteError
C = RuntimeCycleStatus

def _db2():
    d = tempfile.mkdtemp()
    db = RuntimeDatabase(pathlib.Path(d) / "test.db")
    db.connect()
    plan = tuple(m for m in MIGRATION_PLAN if m.version <= 2)
    MigrationManager(db, plan).migrate()
    db.connection.commit()
    return db

def _cycle(db, n=1):
    sid = "s%d" % n; cid = "c%d" % n
    db.connection.execute("INSERT INTO runtime_sessions VALUES (?,?,?,?,NULL,NULL)", (sid,"t","paper","RUNNING"))
    db.connection.execute("INSERT INTO runtime_cycles (cycle_id,session_id,symbol,started_at,status) VALUES (?,?,?,?,?)", (cid,sid,"BTC/USDT","t","CREATED"))
    db.connection.commit()
    return sid, cid

def test_journal_from_and_to_state():
    db=_db2();sid,cid=_cycle(db)
    w=RuntimeStateWriter(db)
    w.transition_cycle(cid,C.CREATED,C.MARKET_ACCEPTED,at_utc="2026-07-01T00:00:10Z")
    j=CycleJournalRepository(db).get_journal(cid)
    assert len(j)==1
    assert j[0].from_state==C.CREATED
    assert j[0].to_state==C.MARKET_ACCEPTED
    assert isinstance(j[0],JournalRecord)

def test_journal_ordered():
    db=_db2();sid,cid=_cycle(db)
    w=RuntimeStateWriter(db)
    w.transition_cycle(cid,C.CREATED,C.MARKET_ACCEPTED,at_utc="2026-07-01T00:00:10Z")
    w.transition_cycle(cid,C.MARKET_ACCEPTED,C.ACCOUNT_ACCEPTED,at_utc="2026-07-01T00:00:20Z")
    j=CycleJournalRepository(db).get_journal(cid)
    assert len(j)==2
    assert j[0].to_state==C.MARKET_ACCEPTED
    assert j[1].to_state==C.ACCOUNT_ACCEPTED

def test_journal_rollback():
    db=_db2();sid,cid=_cycle(db)
    w=RuntimeStateWriter(db)
    try: w.transition_cycle(cid,C.CREATED,C.ACCOUNT_ACCEPTED,at_utc="2026-07-01T00:00:10Z")
    except: pass
    assert len(CycleJournalRepository(db).get_journal(cid))==0

def test_frozen_record():
    j=JournalRecord(1,"c1",C.CREATED,C.MARKET_ACCEPTED,"2026-07-01T00:00:10Z")
    with pytest.raises(Exception): j.from_state=C.EXECUTED

def test_get_unreconciled():
    db=_db2();s1,_=_cycle(db,1)
    db.connection.execute("INSERT INTO runtime_cycles (cycle_id,session_id,symbol,started_at,status) VALUES (?,?,?,?,?)",("c2","s1","ETH/USDT","t","CREATED"))
    db.connection.commit()
    w=RuntimeStateWriter(db)
    w.transition_cycle("c1",C.CREATED,C.MARKET_ACCEPTED,at_utc="2026-07-01T00:00:10Z")
    rows=CycleJournalRepository(db).get_unreconciled_cycles_for_session("s1")
    assert len(rows)>=1
