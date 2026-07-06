"""B4.1A reader tests — scoped queries, production-path corruption only."""
import tempfile
from pathlib import Path
import sqlite3
import pytest
from atos.runtime_db import RuntimeDatabase
from atos.runtime_state import RuntimeMode, RuntimeSessionStatus, RuntimeCycleStatus, RecoveryStatus
from atos.runtime_state_reader import (
    RuntimeStateReader, StateRecordNotFoundError, StateDataCorruptionError,
)

# ═══════════════════════════════════════════════════════════════
# Tampered legacy DB
# ═══════════════════════════════════════════════════════════════

def _tampered_db():
    d = tempfile.mkdtemp()
    path = Path(d) / "test.db"
    db = RuntimeDatabase(path)
    db.connect()
    db.connection.executescript("""
        PRAGMA foreign_keys = OFF;
        CREATE TABLE runtime_sessions (
            session_id   TEXT PRIMARY KEY, started_at TEXT NOT NULL,
            mode TEXT NOT NULL, status TEXT NOT NULL, stopped_at TEXT, stop_reason TEXT);
        CREATE TABLE runtime_cycles (
            cycle_id TEXT PRIMARY KEY, session_id TEXT NOT NULL, symbol TEXT NOT NULL,
            started_at TEXT NOT NULL, completed_at TEXT, status TEXT NOT NULL,
            last_completed_stage TEXT, last_error TEXT);
        CREATE TABLE recovery_states (
            recovery_id TEXT PRIMARY KEY, session_id TEXT NOT NULL, status TEXT NOT NULL,
            unresolved_items TEXT NOT NULL, started_at TEXT NOT NULL, recovered_at TEXT);
    """)
    db.connection.execute("PRAGMA foreign_keys = ON")
    return db

# ══════ P0: connection not public ══════

def test_reader_has_no_public_connection():
    db = _tampered_db(); r = RuntimeStateReader(db)
    assert not hasattr(r, "connection")
    assert hasattr(r, "_connection")

# ══════ Session ══════

def test_session_not_found():
    db = _tampered_db(); r = RuntimeStateReader(db)
    with pytest.raises(StateRecordNotFoundError): r.get_session("nope")

def test_get_session_valid_typed():
    db = _tampered_db()
    db.connection.execute("INSERT INTO runtime_sessions VALUES ('s1','t','paper','RUNNING',NULL,NULL)")
    r = RuntimeStateReader(db)
    s = r.get_session("s1")
    assert isinstance(s.mode, RuntimeMode); assert s.mode == RuntimeMode.PAPER
    assert isinstance(s.status, RuntimeSessionStatus); assert s.status == RuntimeSessionStatus.RUNNING

def test_list_open_excludes_stopped():
    db = _tampered_db()
    db.connection.execute("INSERT INTO runtime_sessions VALUES ('s1','t','paper','RUNNING',NULL,NULL)")
    db.connection.execute("INSERT INTO runtime_sessions VALUES ('s2','t','paper','STOPPED',NULL,NULL)")
    r = RuntimeStateReader(db)
    ids = [s.session_id for s in r.list_open_sessions()]
    assert 's1' in ids; assert 's2' not in ids

def test_list_open_ordering():
    db = _tampered_db()
    db.connection.execute("INSERT INTO runtime_sessions VALUES ('sB','t','paper','RUNNING',NULL,NULL)")
    db.connection.execute("INSERT INTO runtime_sessions VALUES ('sA','t','paper','RUNNING',NULL,NULL)")
    db.connection.execute("INSERT INTO runtime_sessions VALUES ('s0','2025-01-01','paper','RUNNING',NULL,NULL)")
    r = RuntimeStateReader(db)
    ids = [s.session_id for s in r.list_open_sessions()]
    assert ids == ['s0','sA','sB']

# ══════ Cycle ══════

def test_cycle_not_found():
    db = _tampered_db(); r = RuntimeStateReader(db)
    with pytest.raises(StateRecordNotFoundError): r.get_cycle("no")

def test_get_cycle_valid_typed():
    db = _tampered_db()
    db.connection.execute("INSERT INTO runtime_cycles VALUES ('c1','s1','BTC','t',NULL,'EXECUTED','RISK_DECIDED',NULL)")
    r = RuntimeStateReader(db)
    c = r.get_cycle("c1")
    assert c.status == RuntimeCycleStatus.EXECUTED
    assert c.last_completed_stage == RuntimeCycleStatus.RISK_DECIDED

def test_get_cycle_valid_none_lcs():
    db = _tampered_db()
    db.connection.execute("INSERT INTO runtime_cycles VALUES ('c1','s1','BTC','t',NULL,'CREATED',NULL,NULL)")
    r = RuntimeStateReader(db)
    c = r.get_cycle("c1")
    assert c.last_completed_stage is None

def test_list_incomplete_cross_session():
    db = _tampered_db()
    db.connection.execute("INSERT INTO runtime_cycles VALUES ('c1','s1','BTC','t',NULL,'CREATED',NULL,NULL)")
    db.connection.execute("INSERT INTO runtime_cycles VALUES ('c2','s2','ETH','t',NULL,'CREATED',NULL,NULL)")
    db.connection.execute("INSERT INTO runtime_cycles VALUES ('c3','s1','SOL','t',NULL,'COMPLETED',NULL,NULL)")
    r = RuntimeStateReader(db)
    cycles = r.list_incomplete_cycles("s1")
    ids = [c.cycle_id for c in cycles]
    assert 'c1' in ids; assert 'c2' not in ids; assert 'c3' not in ids; assert len(cycles) == 1

def test_cycle_tie_break():
    db = _tampered_db()
    db.connection.execute("INSERT INTO runtime_cycles VALUES ('cA','s1','X','t',NULL,'CREATED',NULL,NULL)")
    db.connection.execute("INSERT INTO runtime_cycles VALUES ('cB','s1','Y','t',NULL,'CREATED',NULL,NULL)")
    r = RuntimeStateReader(db)
    cycles = r.list_incomplete_cycles("s1")
    assert cycles[0].cycle_id == 'cA'; assert cycles[1].cycle_id == 'cB'

# ══════ Recovery ══════

def test_recovery_not_found():
    db = _tampered_db(); r = RuntimeStateReader(db)
    with pytest.raises(StateRecordNotFoundError): r.get_recovery("no")

def test_get_recovery_valid_typed():
    db = _tampered_db()
    db.connection.execute("INSERT INTO runtime_sessions VALUES ('s1','t','paper','RUNNING',NULL,NULL)")
    db.connection.execute("INSERT INTO recovery_states VALUES ('r1','s1','PENDING','[\"o1\",\"o2\"]','t',NULL)")
    r = RuntimeStateReader(db)
    rec = r.get_recovery("r1")
    assert rec.status == RecoveryStatus.PENDING
    assert rec.unresolved_items == ("o1","o2")

def test_recovery_cross_session():
    db = _tampered_db()
    db.connection.execute("INSERT INTO recovery_states VALUES ('r1','s1','PENDING','[]','t',NULL)")
    db.connection.execute("INSERT INTO recovery_states VALUES ('r2','s1','FAILED','[]','t',NULL)")
    db.connection.execute("INSERT INTO recovery_states VALUES ('r3','s1','RESOLVED','[]','t',NULL)")
    db.connection.execute("INSERT INTO recovery_states VALUES ('r4','s2','PENDING','[]','t',NULL)")
    r = RuntimeStateReader(db)
    recs = r.list_unresolved_recoveries("s1")
    ids = [x.recovery_id for x in recs]
    assert 'r1' in ids; assert 'r2' in ids; assert 'r3' not in ids; assert 'r4' not in ids; assert len(recs) == 2

def test_recovery_tie_break():
    db = _tampered_db()
    db.connection.execute("INSERT INTO recovery_states VALUES ('rX','s1','PENDING','[]','t',NULL)")
    db.connection.execute("INSERT INTO recovery_states VALUES ('rA','s1','PENDING','[]','t',NULL)")
    r = RuntimeStateReader(db)
    recs = r.list_unresolved_recoveries("s1")
    assert recs[0].recovery_id == 'rA'; assert recs[1].recovery_id == 'rX'

# ══════ 9 corruption cases ══════

def test_corrupt_mode():
    db = _tampered_db()
    db.connection.execute("INSERT INTO runtime_sessions VALUES ('s1','t','LIVE','RUNNING',NULL,NULL)")
    r = RuntimeStateReader(db)
    with pytest.raises(StateDataCorruptionError): r.get_session("s1")

def test_corrupt_session_status():
    db = _tampered_db()
    db.connection.execute("INSERT INTO runtime_sessions VALUES ('s1','t','paper','DEAD',NULL,NULL)")
    r = RuntimeStateReader(db)
    with pytest.raises(StateDataCorruptionError): r.get_session("s1")

def test_corrupt_cycle_status():
    db = _tampered_db()
    db.connection.execute("INSERT INTO runtime_cycles VALUES ('c1','s1','BTC','t',NULL,'CRASHED',NULL,NULL)")
    r = RuntimeStateReader(db)
    with pytest.raises(StateDataCorruptionError): r.get_cycle("c1")

def test_corrupt_lcs_empty():
    db = _tampered_db()
    db.connection.execute("INSERT INTO runtime_cycles VALUES ('c1','s1','BTC','t',NULL,'CREATED','',NULL)")
    r = RuntimeStateReader(db)
    with pytest.raises(StateDataCorruptionError): r.get_cycle("c1")

def test_corrupt_lcs_bogus():
    db = _tampered_db()
    db.connection.execute("INSERT INTO runtime_cycles VALUES ('c1','s1','BTC','t',NULL,'CREATED','BOGUS',NULL)")
    r = RuntimeStateReader(db)
    with pytest.raises(StateDataCorruptionError): r.get_cycle("c1")

def test_corrupt_malformed_json():
    db = _tampered_db()
    db.connection.execute("INSERT INTO runtime_sessions VALUES ('s1','t','paper','RUNNING',NULL,NULL)")
    db.connection.execute("INSERT INTO recovery_states VALUES ('r1','s1','PENDING','{bad','t',NULL)")
    r = RuntimeStateReader(db)
    with pytest.raises(StateDataCorruptionError): r.get_recovery("r1")

def test_corrupt_non_list_json():
    db = _tampered_db()
    db.connection.execute("INSERT INTO runtime_sessions VALUES ('s1','t','paper','RUNNING',NULL,NULL)")
    db.connection.execute("INSERT INTO recovery_states VALUES ('r1','s1','PENDING','{\"x\":1}','t',NULL)")
    r = RuntimeStateReader(db)
    with pytest.raises(StateDataCorruptionError): r.get_recovery("r1")

def test_corrupt_empty_string():
    db = _tampered_db()
    db.connection.execute("INSERT INTO runtime_sessions VALUES ('s1','t','paper','RUNNING',NULL,NULL)")
    db.connection.execute("INSERT INTO recovery_states VALUES ('r1','s1','PENDING','','t',NULL)")
    r = RuntimeStateReader(db)
    with pytest.raises(StateDataCorruptionError): r.get_recovery("r1")

def test_corrupt_blob_not_text():
    db = _tampered_db()
    db.connection.execute("INSERT INTO runtime_sessions VALUES ('s1','t','paper','RUNNING',NULL,NULL)")
    db.connection.execute("INSERT INTO recovery_states VALUES ('r1','s1','PENDING',?,?,NULL)", (sqlite3.Binary(b"[]"), "t"))
    # Verify raw is bytes
    raw = db.connection.execute("SELECT unresolved_items FROM recovery_states WHERE recovery_id='r1'").fetchone()[0]
    assert isinstance(raw, bytes)
    r = RuntimeStateReader(db)
    with pytest.raises(StateDataCorruptionError): r.get_recovery("r1")
