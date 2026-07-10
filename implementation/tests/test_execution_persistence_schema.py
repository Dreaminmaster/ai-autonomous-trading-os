"""Execution persistence schema tests — migration 0003."""
import hashlib
import pathlib
import sqlite3
import tempfile

import pytest

from atos.runtime_db import RuntimeDatabase
from atos.runtime_migrations import MIGRATION_PLAN, MigrationManager

HASH = hashlib.sha256


def _h(s):
    return HASH(s.encode()).hexdigest()


def _db():
    d = tempfile.mkdtemp()
    db = RuntimeDatabase(pathlib.Path(d) / "test.db")
    db.connect()
    MigrationManager(db, tuple(m for m in MIGRATION_PLAN if m.version <= 3)).migrate()
    db.connection.commit()
    return db


# ===================== parent graph helpers =====================
def _ins_session(db, sid="s1"):
    db.connection.execute(
        "INSERT INTO runtime_sessions VALUES (?,?,?,?,NULL,NULL)",
        (sid, "t", "paper", "RUNNING"),
    )


def _ins_cycle(db, cid="c1", sid="s1"):
    db.connection.execute(
        "INSERT INTO runtime_cycles "
        "(cycle_id,session_id,symbol,started_at,status) VALUES (?,?,?,?,?)",
        (cid, sid, "BTC", "t", "CREATED"),
    )


def _ins_ti(db, tid="t1", action="BUY"):
    db.connection.execute(
        "INSERT INTO trade_intents VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        (tid, "BTC", action, "1", "x", "x", "1", "0", "0", "x", "x", "t"),
    )


def _ins_rd(db, rid="r1", tid="t1", decision="APPROVED"):
    db.connection.execute(
        "INSERT INTO risk_decisions VALUES (?,?,?,?,?,?,?)",
        (rid, tid, decision, "x", "0", "{}", "t"),
    )


def _ins_ei(db, eid="e1", tid="t1", rid="r1", cid="c1", action="BUY", nhash=None):
    if nhash is None:
        nhash = _h(eid)
    db.connection.execute(
        "INSERT INTO execution_intents VALUES (?,?,?,?,?,?,?,?,?)",
        (eid, tid, rid, cid, "BTC", action, "100", nhash, "t"),
    )


def _ins_da(db, did="d1", eid="e1", an=1):
    db.connection.execute(
        "INSERT INTO dispatch_attempts VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (did, eid, "cid", "v", "a", "SUBMITTED", an, "t", None, None, None),
    )


def _setup_graph(db):
    _ins_session(db)
    _ins_cycle(db)
    _ins_ti(db)
    _ins_rd(db)
    db.connection.commit()
    _ins_ei(db)
    db.connection.commit()


# ===================== T1-T5: basics =====================
def test_t1_fresh_v3():
    assert _db().connection.execute(
        "SELECT MAX(version) FROM schema_migrations"
    ).fetchone()[0] == 3


def test_t2_five_tables():
    db = _db()
    tables = [
        r[0]
        for r in db.connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    ]
    for table in [
        "trade_intents",
        "risk_decisions",
        "execution_intents",
        "dispatch_attempts",
        "execution_states",
    ]:
        assert table in tables


def test_t3_plan_versions():
    assert [m.version for m in MIGRATION_PLAN] == [1, 2, 3]


def test_t4_v2_v3_upgrade():
    d = tempfile.mkdtemp()
    p = pathlib.Path(d) / "test.db"
    db = RuntimeDatabase(p)
    db.connect()
    MigrationManager(db, tuple(m for m in MIGRATION_PLAN if m.version <= 2)).migrate()
    _ins_session(db)
    _ins_cycle(db)
    db.connection.execute(
        "INSERT INTO recovery_states "
        "(recovery_id,session_id,status,unresolved_items,started_at) "
        "VALUES ('r1','s1','PENDING','[]','t')"
    )
    db.connection.execute(
        "INSERT INTO cycle_journal "
        "(cycle_id,from_state,to_state,recorded_at) "
        "VALUES ('c1','CREATED','MARKET_ACCEPTED','2026-07-01T00:00:00Z')"
    )
    db.connection.commit()
    db.close()

    db2 = RuntimeDatabase(p)
    db2.connect()
    MigrationManager(db2, tuple(m for m in MIGRATION_PLAN if m.version <= 3)).migrate()
    db2.connection.commit()
    assert db2.connection.execute(
        "SELECT MAX(version) FROM schema_migrations"
    ).fetchone()[0] == 3
    assert db2.connection.execute("SELECT session_id FROM runtime_sessions").fetchone() is not None
    assert db2.connection.execute("SELECT cycle_id FROM runtime_cycles").fetchone() is not None
    assert db2.connection.execute("SELECT recovery_id FROM recovery_states").fetchone() is not None
    tables = [
        r[0]
        for r in db2.connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    ]
    for table in [
        "trade_intents",
        "risk_decisions",
        "execution_intents",
        "dispatch_attempts",
        "execution_states",
    ]:
        assert table in tables


def test_t5_noop():
    db = _db()
    assert MigrationManager(
        db, tuple(m for m in MIGRATION_PLAN if m.version <= 3)
    ).migrate() == 0


# ===================== constraints =====================
def test_t6_invalid_action():
    with pytest.raises(sqlite3.IntegrityError):
        _db().connection.execute(
            "INSERT INTO trade_intents VALUES "
            "('t1','BTC','RUN','1','x','x','1','0','0','x','x','t')"
        )


def test_t7_hold_accepted():
    db = _db()
    _ins_ti(db, "t1", "HOLD")


def test_t8_invalid_decision():
    db = _db()
    _ins_ti(db)
    db.connection.commit()
    with pytest.raises(sqlite3.IntegrityError):
        _ins_rd(db, decision="MAYBE")


def test_t9_missing_ti_fk():
    db = _db()
    with pytest.raises(sqlite3.IntegrityError):
        _ins_rd(db, tid="nonexistent")


def test_t10_missing_cycle_fk():
    db = _db()
    _ins_ti(db)
    _ins_rd(db)
    db.connection.commit()
    with pytest.raises(sqlite3.IntegrityError):
        _ins_ei(db, cid="nonexistent")


def test_t11_missing_parent_rejected():
    db = _db()
    _ins_session(db)
    _ins_cycle(db)
    db.connection.commit()
    with pytest.raises(sqlite3.IntegrityError):
        _ins_ei(db, tid="nonexistent")


def test_t12_risk_ownership_mismatch():
    db = _db()
    _ins_ti(db, "t1")
    _ins_ti(db, "t2", "SELL")
    _ins_rd(db, "r1", "t1")
    _ins_session(db)
    _ins_cycle(db)
    db.connection.commit()
    with pytest.raises(sqlite3.IntegrityError):
        _ins_ei(db, tid="t2", rid="r1")


def test_t13_ei_hold_rejected():
    db = _db()
    _ins_ti(db, action="HOLD")
    _ins_rd(db)
    _ins_session(db)
    _ins_cycle(db)
    db.connection.commit()
    with pytest.raises(sqlite3.IntegrityError):
        _ins_ei(db, action="HOLD")


def test_t14_hash_wrong_length():
    db = _db()
    _ins_session(db)
    _ins_cycle(db)
    _ins_ti(db)
    _ins_rd(db)
    db.connection.commit()
    with pytest.raises(sqlite3.IntegrityError):
        _ins_ei(db, nhash="a" * 63)


def test_t15_hash_non_hex():
    db = _db()
    _ins_session(db)
    _ins_cycle(db)
    _ins_ti(db)
    _ins_rd(db)
    db.connection.commit()
    with pytest.raises(sqlite3.IntegrityError):
        _ins_ei(db, nhash="g" + "a" * 63)


def test_t16_identical_hash_ok():
    db = _db()
    _setup_graph(db)
    db.connection.execute(
        "INSERT INTO execution_intents VALUES "
        "('e2','t1','r1','c1','BTC','BUY','200',?,?)",
        (_h("e1"), "t"),
    )


def test_t17_invalid_dispatch_status():
    db = _db()
    _setup_graph(db)
    with pytest.raises(sqlite3.IntegrityError):
        db.connection.execute(
            "INSERT INTO dispatch_attempts VALUES "
            "('d1','e1','cid','v','a','BOGUS',1,'t',NULL,NULL,NULL)"
        )


def test_t18_attempt_lt_1():
    db = _db()
    _setup_graph(db)
    with pytest.raises(sqlite3.IntegrityError):
        db.connection.execute(
            "INSERT INTO dispatch_attempts VALUES "
            "('d1','e1','cid','v','a','SUBMITTED',0,'t',NULL,NULL,NULL)"
        )


def test_t19_duplicate_attempt_no():
    db = _db()
    _setup_graph(db)
    _ins_da(db, "d1", "e1", 1)
    with pytest.raises(sqlite3.IntegrityError):
        _ins_da(db, "d2", "e1", 1)


def test_t20_same_client_order_ok():
    db = _db()
    _setup_graph(db)
    db.connection.execute(
        "INSERT INTO dispatch_attempts VALUES "
        "('d1','e1','cid','v','a','SUBMITTED',1,'t',NULL,NULL,NULL)"
    )
    db.connection.execute(
        "INSERT INTO dispatch_attempts VALUES "
        "('d2','e1','cid','v','a','SUBMITTED',2,'t',NULL,NULL,NULL)"
    )


def test_t21_es_invalid_status():
    db = _db()
    _setup_graph(db)
    with pytest.raises(sqlite3.IntegrityError):
        db.connection.execute(
            "INSERT INTO execution_states VALUES ('e1','BOGUS',NULL,0,'t','t')"
        )


def test_t22_es_negative_retry():
    db = _db()
    _setup_graph(db)
    with pytest.raises(sqlite3.IntegrityError):
        db.connection.execute(
            "INSERT INTO execution_states VALUES ('e1','PREPARED',NULL,-1,'t','t')"
        )


def test_t23_es_wrong_attempt():
    db = _db()
    _setup_graph(db)
    _ins_ei(db, "e2", "t1", "r1", "c1", "BUY", _h("e2"))
    db.connection.commit()
    _ins_da(db, "d1", "e2", 1)
    db.connection.commit()
    with pytest.raises(sqlite3.IntegrityError):
        db.connection.execute(
            "INSERT INTO execution_states VALUES ('e1','PREPARED','d1',0,'t','t')"
        )


def test_t24_es_correct_attempt_ok():
    db = _db()
    _setup_graph(db)
    _ins_da(db, "d1", "e1", 1)
    db.connection.execute(
        "INSERT INTO execution_states VALUES ('e1','PREPARED','d1',0,'t','t')"
    )


# ===================== immutability =====================
def _setup_ti(db):
    _ins_ti(db)
    db.connection.commit()


def test_t25_ti_update():
    db = _db()
    _setup_ti(db)
    with pytest.raises(sqlite3.IntegrityError):
        db.connection.execute(
            "UPDATE trade_intents SET symbol='ETH' WHERE trade_intent_id='t1'"
        )


def test_t26_ti_delete():
    db = _db()
    _setup_ti(db)
    with pytest.raises(sqlite3.IntegrityError):
        db.connection.execute("DELETE FROM trade_intents WHERE trade_intent_id='t1'")


def test_t27_rd_update():
    db = _db()
    _setup_ti(db)
    _ins_rd(db)
    db.connection.commit()
    with pytest.raises(sqlite3.IntegrityError):
        db.connection.execute(
            "UPDATE risk_decisions SET decision='REJECTED' WHERE risk_decision_id='r1'"
        )


def test_t28_rd_delete():
    db = _db()
    _setup_ti(db)
    _ins_rd(db)
    db.connection.commit()
    with pytest.raises(sqlite3.IntegrityError):
        db.connection.execute("DELETE FROM risk_decisions WHERE risk_decision_id='r1'")


def test_t29_ei_update():
    db = _db()
    _setup_graph(db)
    with pytest.raises(sqlite3.IntegrityError):
        db.connection.execute(
            "UPDATE execution_intents SET symbol='ETH' WHERE execution_intent_id='e1'"
        )


def test_t30_ei_delete():
    db = _db()
    _setup_graph(db)
    with pytest.raises(sqlite3.IntegrityError):
        db.connection.execute(
            "DELETE FROM execution_intents WHERE execution_intent_id='e1'"
        )


# ===================== exact v2 -> v3 row preservation =====================
def test_t4b_exact_row_preservation():
    d = tempfile.mkdtemp()
    p = pathlib.Path(d) / "test.db"
    db = RuntimeDatabase(p)
    db.connect()
    MigrationManager(db, tuple(m for m in MIGRATION_PLAN if m.version <= 2)).migrate()
    db.connection.execute(
        "INSERT INTO runtime_sessions VALUES ('s1','t','paper','STARTING',NULL,NULL)"
    )
    db.connection.execute(
        "INSERT INTO runtime_cycles VALUES ('c1','s1','BTC','t',NULL,'CREATED',NULL,NULL)"
    )
    db.connection.execute(
        "INSERT INTO recovery_states VALUES ('r1','s1','PENDING','[]','t',NULL)"
    )
    db.connection.execute(
        "INSERT INTO cycle_journal "
        "(cycle_id,from_state,to_state,recorded_at) "
        "VALUES ('c1','CREATED','MARKET_ACCEPTED','2026-01-01T00:00:00Z')"
    )
    db.connection.commit()
    session_before = db.connection.execute(
        "SELECT * FROM runtime_sessions WHERE session_id='s1'"
    ).fetchone()
    cycle_before = db.connection.execute(
        "SELECT * FROM runtime_cycles WHERE cycle_id='c1'"
    ).fetchone()
    recovery_before = db.connection.execute(
        "SELECT * FROM recovery_states WHERE recovery_id='r1'"
    ).fetchone()
    journal_before = db.connection.execute(
        "SELECT * FROM cycle_journal WHERE cycle_id='c1'"
    ).fetchone()
    db.close()

    db2 = RuntimeDatabase(p)
    db2.connect()
    MigrationManager(db2, tuple(m for m in MIGRATION_PLAN if m.version <= 3)).migrate()
    db2.connection.commit()
    assert db2.connection.execute(
        "SELECT MAX(version) FROM schema_migrations"
    ).fetchone()[0] == 3
    assert tuple(
        db2.connection.execute(
            "SELECT * FROM runtime_sessions WHERE session_id='s1'"
        ).fetchone()
    ) == tuple(session_before)
    assert tuple(
        db2.connection.execute(
            "SELECT * FROM runtime_cycles WHERE cycle_id='c1'"
        ).fetchone()
    ) == tuple(cycle_before)
    assert tuple(
        db2.connection.execute(
            "SELECT * FROM recovery_states WHERE recovery_id='r1'"
        ).fetchone()
    ) == tuple(recovery_before)
    assert tuple(
        db2.connection.execute(
            "SELECT * FROM cycle_journal WHERE cycle_id='c1'"
        ).fetchone()
    ) == tuple(journal_before)


# ===================== exact table_info contract =====================
TABLE_INFO_EXPECTED = {
    "trade_intents": [
        (0, "trade_intent_id", "TEXT", 0, None, 1),
        (1, "symbol", "TEXT", 1, None, 0),
        (2, "action", "TEXT", 1, None, 0),
        (3, "confidence", "TEXT", 1, None, 0),
        (4, "thesis", "TEXT", 1, None, 0),
        (5, "evidence", "TEXT", 1, None, 0),
        (6, "position_size_pct", "TEXT", 1, None, 0),
        (7, "stop_loss_pct", "TEXT", 1, None, 0),
        (8, "take_profit_pct", "TEXT", 1, None, 0),
        (9, "invalidation_conditions", "TEXT", 1, None, 0),
        (10, "selected_strategy_ids", "TEXT", 1, None, 0),
        (11, "created_at", "TEXT", 1, None, 0),
    ],
    "risk_decisions": [
        (0, "risk_decision_id", "TEXT", 0, None, 1),
        (1, "trade_intent_id", "TEXT", 1, None, 0),
        (2, "decision", "TEXT", 1, None, 0),
        (3, "reasons", "TEXT", 1, None, 0),
        (4, "risk_score", "TEXT", 1, None, 0),
        (5, "checks_json", "TEXT", 1, None, 0),
        (6, "created_at", "TEXT", 1, None, 0),
    ],
    "execution_intents": [
        (0, "execution_intent_id", "TEXT", 0, None, 1),
        (1, "trade_intent_id", "TEXT", 1, None, 0),
        (2, "risk_decision_id", "TEXT", 1, None, 0),
        (3, "cycle_id", "TEXT", 1, None, 0),
        (4, "symbol", "TEXT", 1, None, 0),
        (5, "action", "TEXT", 1, None, 0),
        (6, "notional", "TEXT", 1, None, 0),
        (7, "normalized_intent_hash", "TEXT", 1, None, 0),
        (8, "created_at", "TEXT", 1, None, 0),
    ],
    "dispatch_attempts": [
        (0, "attempt_id", "TEXT", 0, None, 1),
        (1, "execution_intent_id", "TEXT", 1, None, 0),
        (2, "client_order_id", "TEXT", 1, None, 0),
        (3, "venue", "TEXT", 1, None, 0),
        (4, "account_scope", "TEXT", 1, None, 0),
        (5, "status", "TEXT", 1, None, 0),
        (6, "attempt_no", "INTEGER", 1, None, 0),
        (7, "created_at", "TEXT", 1, None, 0),
        (8, "dispatch_started_at", "TEXT", 0, None, 0),
        (9, "response_received_at", "TEXT", 0, None, 0),
        (10, "error_class", "TEXT", 0, None, 0),
    ],
    "execution_states": [
        (0, "execution_intent_id", "TEXT", 0, None, 1),
        (1, "status", "TEXT", 1, None, 0),
        (2, "last_attempt_id", "TEXT", 0, None, 0),
        (3, "retry_count", "INTEGER", 1, "0", 0),
        (4, "state_started_at", "TEXT", 1, None, 0),
        (5, "updated_at", "TEXT", 1, None, 0),
    ],
}


@pytest.mark.parametrize("table", list(TABLE_INFO_EXPECTED))
def test_t31_exact_table_info(table):
    db = _db()
    actual = [
        tuple(row)
        for row in db.connection.execute(f"PRAGMA table_info({table})").fetchall()
    ]
    assert actual == TABLE_INFO_EXPECTED[table]


# ===================== exact FK contract =====================
def _fk_groups(db, table):
    groups = {}
    for row in db.connection.execute(f"PRAGMA foreign_key_list({table})").fetchall():
        groups.setdefault(row["id"], []).append(row)
    return {
        tuple(
            (r["seq"], r["from"], r["table"], r["to"])
            for r in sorted(rows, key=lambda item: item["seq"])
        )
        for rows in groups.values()
    }


def test_t32_exact_all_fk_mappings():
    db = _db()
    assert _fk_groups(db, "risk_decisions") == {
        ((0, "trade_intent_id", "trade_intents", "trade_intent_id"),)
    }
    assert _fk_groups(db, "execution_intents") == {
        ((0, "trade_intent_id", "trade_intents", "trade_intent_id"),),
        ((0, "cycle_id", "runtime_cycles", "cycle_id"),),
        (
            (0, "risk_decision_id", "risk_decisions", "risk_decision_id"),
            (1, "trade_intent_id", "risk_decisions", "trade_intent_id"),
        ),
    }
    assert _fk_groups(db, "dispatch_attempts") == {
        ((0, "execution_intent_id", "execution_intents", "execution_intent_id"),)
    }
    assert _fk_groups(db, "execution_states") == {
        ((0, "execution_intent_id", "execution_intents", "execution_intent_id"),),
        (
            (0, "execution_intent_id", "dispatch_attempts", "execution_intent_id"),
            (1, "last_attempt_id", "dispatch_attempts", "attempt_id"),
        ),
    }


# ===================== exact index contract =====================
NAMED_INDEX_EXPECTED = {
    ("risk_decisions", "idx_risk_decisions_trade_intent"): ["trade_intent_id"],
    ("execution_intents", "idx_execution_intents_cycle"): ["cycle_id"],
    ("execution_intents", "idx_execution_intents_trade_intent"): ["trade_intent_id"],
    ("dispatch_attempts", "idx_dispatch_attempts_execution"): ["execution_intent_id"],
    ("dispatch_attempts", "idx_dispatch_attempts_client_order"): ["client_order_id"],
    ("execution_states", "idx_execution_states_status"): ["status"],
}


def _index_columns(db, index_name):
    return [
        row["name"]
        for row in db.connection.execute(f"PRAGMA index_info({index_name})").fetchall()
    ]


@pytest.mark.parametrize("table,index_name", list(NAMED_INDEX_EXPECTED))
def test_t33_exact_named_index_columns(table, index_name):
    db = _db()
    indexes = {
        row["name"]: row
        for row in db.connection.execute(f"PRAGMA index_list({table})").fetchall()
    }
    assert index_name in indexes
    assert indexes[index_name]["unique"] == 0
    assert _index_columns(db, index_name) == NAMED_INDEX_EXPECTED[(table, index_name)]


def _has_unique_index_for_columns(db, table, expected_columns):
    for index_row in db.connection.execute(f"PRAGMA index_list({table})").fetchall():
        if index_row["unique"] != 1:
            continue
        if _index_columns(db, index_row["name"]) == expected_columns:
            return True
    return False


def test_t33_unique_parent_backing_risk_decisions():
    db = _db()
    assert _has_unique_index_for_columns(
        db,
        "risk_decisions",
        ["risk_decision_id", "trade_intent_id"],
    )


def test_t33_unique_parent_backing_dispatch_attempts():
    db = _db()
    assert _has_unique_index_for_columns(
        db,
        "dispatch_attempts",
        ["execution_intent_id", "attempt_id"],
    )


# ===================== migration checksum contracts =====================
def test_t34a_v1_checksum():
    assert hashlib.sha256(MIGRATION_PLAN[0].sql.encode()).hexdigest() == (
        "b039c238f7d11bcd2fe09e33422a32ad0728147d01c34ffef759fae32fba0b1d"
    )


def test_t34b_v2_checksum():
    assert hashlib.sha256(MIGRATION_PLAN[1].sql.encode()).hexdigest() == (
        "f2e8d13f91b7681f4a379c1fb7cff3b5cb12726dd3ebbdd93063b30fda192cca"
    )


# ===================== complete hash matrix =====================
@pytest.mark.parametrize(
    "hash_value",
    [
        "a" * 64,
        "0123456789abcdef" * 4,
    ],
)
def test_hash_valid_matrix(hash_value):
    db = _db()
    _ins_session(db)
    _ins_cycle(db)
    _ins_ti(db)
    _ins_rd(db)
    db.connection.commit()
    _ins_ei(db, eid="matrix-valid", nhash=hash_value)


@pytest.mark.parametrize(
    "hash_value",
    [
        "a" * 63,
        "a" * 65,
        "A" + "a" * 63,
        "g" + "a" * 63,
        "_" + "a" * 63,
        "z" + "a" * 63,
    ],
)
def test_hash_invalid_matrix(hash_value):
    db = _db()
    _ins_session(db)
    _ins_cycle(db)
    _ins_ti(db)
    _ins_rd(db)
    db.connection.commit()
    with pytest.raises(sqlite3.IntegrityError):
        _ins_ei(db, eid="matrix-invalid", nhash=hash_value)
