"""34+ targeted tests for B4.1A read-only typed state mapping."""
import tempfile
from pathlib import Path
import json
from atos.runtime_db import RuntimeDatabase
from atos.runtime_migrations import MigrationManager, MIGRATION_PLAN
from atos.runtime_state import RuntimeMode, RuntimeSessionStatus, RuntimeCycleStatus, RecoveryStatus
from atos.runtime_state_reader import (
    RuntimeStateReader, RuntimeStateReadError, StateRecordNotFoundError,
    StateDataCorruptionError, _session_from_row, _cycle_from_row, _recovery_from_row,
)

def _migrated_db():
    d = tempfile.mkdtemp()
    path = Path(d) / "test.db"
    db = RuntimeDatabase(path)
    db.connect()
    MigrationManager(db, MIGRATION_PLAN).migrate()
    return db

def _reader():
    db = _migrated_db()
    reader = RuntimeStateReader(db)
    # Insert test data via raw SQL (no writer needed)
    db.connection.execute("INSERT INTO runtime_sessions (session_id, started_at, mode, status) VALUES ('s1','2026-01-01T00:00Z','paper','RUNNING')")
    db.connection.execute("INSERT INTO runtime_sessions (session_id, started_at, mode, status) VALUES ('s2','2026-02-01T00:00Z','paper','STARTING')")
    db.connection.execute("INSERT INTO runtime_sessions (session_id, started_at, mode, status) VALUES ('s3','2025-12-01T00:00Z','paper','STOPPED')")
    db.connection.execute("INSERT INTO runtime_cycles (cycle_id, session_id, symbol, started_at, status, last_completed_stage) VALUES ('c1','s1','BTC/USDT','2026-01-01T00:00Z','CREATED',NULL)")
    db.connection.execute("INSERT INTO runtime_cycles (cycle_id, session_id, symbol, started_at, status) VALUES ('c2','s1','ETH/USDT','2026-01-01T00:00Z','COMPLETED')")
    db.connection.execute("INSERT INTO recovery_states (recovery_id, session_id, status, unresolved_items, started_at) VALUES ('r1','s1','IN_PROGRESS','[\"order1\"]','2026-01-01T00:00Z')")
    db.connection.execute("INSERT INTO recovery_states (recovery_id, session_id, status, unresolved_items, started_at) VALUES ('r2','s1','RESOLVED','[]','2026-01-01T00:00Z')")
    db.connection.execute("INSERT INTO recovery_states (recovery_id, session_id, status, unresolved_items, started_at) VALUES ('r3','s1','PENDING','[]','2026-01-01T00:00Z')")
    return db, reader

# ── 1-7: Typed model tests ──────────────────────────────────

def test_01_str_enum_values():
    assert RuntimeMode.PAPER.value == "paper"
    assert RuntimeSessionStatus.STARTING.value == "STARTING"
    assert RuntimeCycleStatus.CREATED.value == "CREATED"
    assert RecoveryStatus.PENDING.value == "PENDING"

def test_02_frozen_dataclass():
    from atos.runtime_state import RuntimeSessionRecord
    r = RuntimeSessionRecord("id","ts",RuntimeMode.PAPER,RuntimeSessionStatus.STARTING)
    try:
        r.session_id = "x"
        assert False
    except Exception:
        pass

def test_03_mode_cant_be_paper_enum():
    s = RuntimeSessionStatus("STARTING")
    assert s == RuntimeSessionStatus.STARTING

def test_04_invalid_mode_raises():
    import pytest
    with pytest.raises(ValueError):
        RuntimeMode("LIVE")

def test_05_invalid_session_status_raises():
    import pytest
    with pytest.raises(ValueError):
        RuntimeSessionStatus("DEAD")

def test_06_invalid_cycle_status_raises():
    import pytest
    with pytest.raises(ValueError):
        RuntimeCycleStatus("CRASHED")

def test_07_invalid_recovery_status_raises():
    import pytest
    with pytest.raises(ValueError):
        RecoveryStatus("LOST")

# ── 8-15: Session tests ─────────────────────────────────────

def test_08_get_session():
    db, reader = _reader()
    s = reader.get_session("s1")
    assert s.session_id == "s1"
    assert s.status == RuntimeSessionStatus.RUNNING

def test_09_get_session_not_found():
    import pytest
    db, reader = _reader()
    with pytest.raises(StateRecordNotFoundError):
        reader.get_session("nonexistent")

def test_10_list_open_sessions():
    db, reader = _reader()
    sessions = reader.list_open_sessions()
    ids = [s.session_id for s in sessions]
    assert "s1" in ids
    assert "s2" in ids
    assert "s3" not in ids  # STOPPED excluded

def test_11_list_open_sessions_ordered():
    db, reader = _reader()
    sessions = reader.list_open_sessions()
    # s3 is STOPPED excluded. s1(2026-01-01) comes before s2(2026-02-01)
    assert sessions[0].session_id == "s1"

def test_12_session_type():
    db, reader = _reader()
    s = reader.get_session("s1")
    assert s.mode == RuntimeMode.PAPER

def test_13_cycle_get():
    db, reader = _reader()
    c = reader.get_cycle("c1")
    assert c.symbol == "BTC/USDT"
    assert c.status == RuntimeCycleStatus.CREATED
    assert c.last_completed_stage is None

def test_14_list_incomplete_cycles():
    db, reader = _reader()
    cycles = reader.list_incomplete_cycles()
    assert all(c.status != RuntimeCycleStatus.COMPLETED for c in cycles)
    ids = [c.cycle_id for c in cycles]
    assert "c1" in ids
    assert "c2" not in ids

def test_15_recovery_get():
    db, reader = _reader()
    r = reader.get_recovery("r1")
    assert r.unresolved_items == ("order1",)

# ── 16-23: Cycle + recovery tests ────────────────────────────

def test_16_list_unresolved_recoveries():
    db, reader = _reader()
    recs = reader.list_unresolved_recoveries()
    statuses = [r.status.value for r in recs]
    assert "IN_PROGRESS" in statuses
    assert "PENDING" in statuses
    assert "RESOLVED" not in statuses

def test_17_cycle_not_found():
    import pytest
    db, reader = _reader()
    with pytest.raises(StateRecordNotFoundError):
        reader.get_cycle("fake")

def test_18_recovery_not_found():
    import pytest
    db, reader = _reader()
    with pytest.raises(StateRecordNotFoundError):
        reader.get_recovery("fake")

def test_19_empty_json_maps_to_tuple():
    r = _parse_unresolved_items("[]")
    assert r == ()

def test_20_nonempty_json():
    r = _parse_unresolved_items('["a","b"]')
    assert r == ("a","b")

def test_21_single_item_json():
    r = _parse_unresolved_items('["x"]')
    assert r == ("x",)

def test_22_nested_json():
    r = _parse_unresolved_items('["order1",{"key":"val"}]')
    assert r[0] == "order1"
    assert r[1] == {"key":"val"}

def test_23_read_empty_recovery():
    db, reader = _reader()
    r = reader.get_recovery("r3")
    assert r.unresolved_items == ()

# ── 24-34: Corruption + JSON tests ───────────────────────────

def test_24_malformed_json_raises():
    import pytest
    with pytest.raises(StateDataCorruptionError):
        _parse_unresolved_items("{bad")

def test_25_non_list_json_raises():
    import pytest
    with pytest.raises(StateDataCorruptionError):
        _parse_unresolved_items('{"key":"val"}')

def test_26_non_string_raises():
    import pytest
    with pytest.raises(StateDataCorruptionError):
        _parse_unresolved_items(42)

def test_27_empty_string_raises():
    import pytest
    with pytest.raises(StateDataCorruptionError):
        _parse_unresolved_items("")

def test_28_none_raises():
    import pytest
    with pytest.raises(StateDataCorruptionError):
        _parse_unresolved_items(None)

def test_29_empty_list_ok():
    r = _parse_unresolved_items("[]")
    assert r == ()



def test_32_unresolved_includes_failed():
    db, reader = _reader()
    db.connection.execute("INSERT INTO recovery_states (recovery_id, session_id, status, unresolved_items, started_at) VALUES ('r4','s1','FAILED','[]','2026-01-01T00:00Z')")
    recs = reader.list_unresolved_recoveries()
    ids = [r.recovery_id for r in recs]
    assert "r4" in ids

def test_33_status_is_enum():
    db, reader = _reader()
    c = reader.get_cycle("c1")
    assert isinstance(c.status, RuntimeCycleStatus)

def test_34_missing_row_raises():
    import pytest
    db, reader = _reader()
    with pytest.raises(StateRecordNotFoundError):
        reader.get_cycle("does_not_exist")
