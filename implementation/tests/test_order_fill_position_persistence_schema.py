"""B4.3A order/fill/position persistence schema contract tests."""
from __future__ import annotations

import pathlib
import sqlite3
import tempfile

import pytest

from atos.runtime_db import RuntimeDatabase
from atos.runtime_migrations import (
    MIGRATION_PLAN,
    Migration,
    MigrationApplyError,
    MigrationManager,
)


EXPECTED_LEGACY_CHECKSUMS = (
    "b039c238f7d11bcd2fe09e33422a32ad0728147d01c34ffef759fae32fba0b1d",
    "f2e8d13f91b7681f4a379c1fb7cff3b5cb12726dd3ebbdd93063b30fda192cca",
    "e3efc7c169d46546e43473c7700a026c67f7ea3d272f3baa6cf36751bc7d257f",
)


def _db(version: int = 4) -> RuntimeDatabase:
    path = pathlib.Path(tempfile.mkdtemp()) / "runtime.db"
    db = RuntimeDatabase(path)
    db.connect()
    plan = tuple(m for m in MIGRATION_PLAN if m.version <= version)
    MigrationManager(db, plan).migrate()
    return db


def _insert_execution_graph(
    db: RuntimeDatabase,
    *,
    suffix: str = "1",
    venue: str = "okx_paper",
    account_scope: str = "spot-main",
    client_order_id: str | None = None,
) -> dict[str, str]:
    sid = f"s{suffix}"
    cid = f"c{suffix}"
    tid = f"t{suffix}"
    rid = f"r{suffix}"
    eid = f"e{suffix}"
    aid = f"a{suffix}"
    client = client_order_id or f"client-{suffix}"
    db.connection.execute(
        "INSERT INTO runtime_sessions VALUES (?,?,?,?,NULL,NULL)",
        (sid, "2026-01-01T00:00:00Z", "paper", "RUNNING"),
    )
    db.connection.execute(
        "INSERT INTO runtime_cycles "
        "(cycle_id,session_id,symbol,started_at,status) VALUES (?,?,?,?,?)",
        (cid, sid, "BTC/USDT", "2026-01-01T00:00:00Z", "CREATED"),
    )
    db.connection.execute(
        "INSERT INTO trade_intents VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            tid,
            "BTC/USDT",
            "BUY",
            "0.9",
            "thesis",
            "{}",
            "0.1",
            "0.02",
            "0.04",
            "[]",
            "[]",
            "2026-01-01T00:00:00Z",
        ),
    )
    db.connection.execute(
        "INSERT INTO risk_decisions VALUES (?,?,?,?,?,?,?)",
        (rid, tid, "APPROVED", "[]", "0.1", "{}", "2026-01-01T00:00:01Z"),
    )
    db.connection.execute(
        "INSERT INTO execution_intents VALUES (?,?,?,?,?,?,?,?,?)",
        (
            eid,
            tid,
            rid,
            cid,
            "BTC/USDT",
            "BUY",
            "100",
            suffix[-1] * 64 if suffix[-1] in "0123456789abcdef" else "a" * 64,
            "2026-01-01T00:00:02Z",
        ),
    )
    db.connection.execute(
        "INSERT INTO dispatch_attempts VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (
            aid,
            eid,
            client,
            venue,
            account_scope,
            "ACCEPTED",
            1,
            "2026-01-01T00:00:03Z",
            "2026-01-01T00:00:03Z",
            "2026-01-01T00:00:04Z",
            None,
        ),
    )
    db.connection.commit()
    return {
        "session_id": sid,
        "cycle_id": cid,
        "trade_intent_id": tid,
        "risk_decision_id": rid,
        "execution_intent_id": eid,
        "attempt_id": aid,
        "client_order_id": client,
        "venue": venue,
        "account_scope": account_scope,
    }


def _insert_order(
    db: RuntimeDatabase,
    graph: dict[str, str],
    *,
    order_id: str = "order-1",
    status: str = "OPEN",
    client_order_id: str | None = None,
) -> None:
    db.connection.execute(
        "INSERT INTO order_states VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            graph["venue"],
            graph["account_scope"],
            order_id,
            graph["execution_intent_id"],
            graph["attempt_id"],
            client_order_id or graph["client_order_id"],
            "BTC/USDT",
            "BUY",
            "0.01",
            "100000",
            "LIMIT",
            status,
            "2026-01-01T00:00:05Z",
            "2026-01-01T00:00:05Z",
        ),
    )


def _insert_fill(
    db: RuntimeDatabase,
    graph: dict[str, str],
    *,
    fill_id: str = "fill-1",
    order_id: str = "order-1",
) -> None:
    db.connection.execute(
        "INSERT INTO fill_states VALUES (?,?,?,?,?,?,?,?,?)",
        (
            graph["venue"],
            graph["account_scope"],
            fill_id,
            order_id,
            "0.01",
            "100000",
            "1.5",
            "USDT",
            "2026-01-01T00:00:06Z",
        ),
    )


def _insert_position(
    db: RuntimeDatabase,
    *,
    position_id: str = "position-1",
    venue: str = "okx_paper",
    account_scope: str = "spot-main",
    side: str = "LONG",
    status: str = "OPEN",
) -> None:
    closed_at = None if status == "OPEN" else "2026-01-01T00:01:00Z"
    db.connection.execute(
        "INSERT INTO position_states VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            position_id,
            venue,
            account_scope,
            "BTC/USDT",
            side,
            "0.01" if status == "OPEN" else "0",
            "100000",
            "0",
            "0",
            status,
            "2026-01-01T00:00:06Z",
            closed_at,
            "2026-01-01T00:00:06Z",
        ),
    )


def _insert_accounting(
    db: RuntimeDatabase,
    *,
    event_id: str,
    position_id: str = "position-1",
    venue: str = "okx_paper",
    account_scope: str = "spot-main",
    fill_id: str = "fill-1",
    event_no: int = 1,
    event_type: str = "OPEN",
) -> None:
    db.connection.execute(
        "INSERT INTO position_accounting_details VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            event_id,
            position_id,
            venue,
            account_scope,
            fill_id,
            event_no,
            event_type,
            "0.01",
            "100000",
            "1.5",
            "0",
            "2026-01-01T00:00:06Z",
        ),
    )


def _table_info(db: RuntimeDatabase, table: str) -> list[tuple]:
    return [tuple(row) for row in db.connection.execute(f"PRAGMA table_info({table})")]


def _index_columns(db: RuntimeDatabase, index: str) -> tuple[str, ...]:
    rows = db.connection.execute(f"PRAGMA index_info({index})").fetchall()
    return tuple(row[2] for row in rows)


def _find_unique_index(
    db: RuntimeDatabase,
    table: str,
    columns: tuple[str, ...],
    *,
    partial: int | None = None,
) -> str:
    for row in db.connection.execute(f"PRAGMA index_list({table})"):
        if row[2] != 1:
            continue
        if partial is not None and row[4] != partial:
            continue
        if _index_columns(db, row[1]) == columns:
            return row[1]
    raise AssertionError(f"unique index not found: {table} {columns}")


def _fk_groups(db: RuntimeDatabase, table: str) -> set[tuple]:
    groups: dict[int, list] = {}
    for row in db.connection.execute(f"PRAGMA foreign_key_list({table})"):
        groups.setdefault(row[0], []).append(row)
    result = set()
    for rows in groups.values():
        ordered = sorted(rows, key=lambda row: row[1])
        result.add(
            (
                ordered[0][2],
                tuple((row[3], row[4]) for row in ordered),
                ordered[0][6],
            )
        )
    return result


def test_fresh_v4_and_plan() -> None:
    db = _db()
    assert [m.version for m in MIGRATION_PLAN] == [1, 2, 3, 4]
    assert db.connection.execute(
        "SELECT MAX(version) FROM schema_migrations"
    ).fetchone()[0] == 4
    tables = {
        row[0]
        for row in db.connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
    }
    assert {
        "order_states",
        "fill_states",
        "position_states",
        "position_accounting_details",
    }.issubset(tables)


def test_legacy_migration_checksums_are_unchanged() -> None:
    assert tuple(m.checksum for m in MIGRATION_PLAN[:3]) == EXPECTED_LEGACY_CHECKSUMS


def test_exact_table_info() -> None:
    db = _db()
    assert _table_info(db, "order_states") == [
        (0, "venue", "TEXT", 1, None, 1),
        (1, "account_scope", "TEXT", 1, None, 2),
        (2, "order_id", "TEXT", 1, None, 3),
        (3, "execution_intent_id", "TEXT", 1, None, 0),
        (4, "attempt_id", "TEXT", 1, None, 0),
        (5, "client_order_id", "TEXT", 1, None, 0),
        (6, "symbol", "TEXT", 1, None, 0),
        (7, "side", "TEXT", 1, None, 0),
        (8, "quantity", "TEXT", 1, None, 0),
        (9, "price", "TEXT", 1, None, 0),
        (10, "order_type", "TEXT", 1, None, 0),
        (11, "status", "TEXT", 1, None, 0),
        (12, "created_at", "TEXT", 1, None, 0),
        (13, "updated_at", "TEXT", 1, None, 0),
    ]
    assert _table_info(db, "fill_states") == [
        (0, "venue", "TEXT", 1, None, 1),
        (1, "account_scope", "TEXT", 1, None, 2),
        (2, "fill_id", "TEXT", 1, None, 3),
        (3, "order_id", "TEXT", 1, None, 0),
        (4, "quantity", "TEXT", 1, None, 0),
        (5, "price", "TEXT", 1, None, 0),
        (6, "fee", "TEXT", 1, None, 0),
        (7, "fee_currency", "TEXT", 1, None, 0),
        (8, "timestamp", "TEXT", 1, None, 0),
    ]
    assert _table_info(db, "position_states") == [
        (0, "position_id", "TEXT", 0, None, 1),
        (1, "venue", "TEXT", 1, None, 0),
        (2, "account_scope", "TEXT", 1, None, 0),
        (3, "symbol", "TEXT", 1, None, 0),
        (4, "side", "TEXT", 1, None, 0),
        (5, "quantity", "TEXT", 1, None, 0),
        (6, "avg_entry_price", "TEXT", 1, None, 0),
        (7, "realized_pnl", "TEXT", 1, None, 0),
        (8, "unrealized_pnl", "TEXT", 1, None, 0),
        (9, "status", "TEXT", 1, None, 0),
        (10, "opened_at", "TEXT", 1, None, 0),
        (11, "closed_at", "TEXT", 0, None, 0),
        (12, "updated_at", "TEXT", 1, None, 0),
    ]
    assert _table_info(db, "position_accounting_details") == [
        (0, "event_id", "TEXT", 0, None, 1),
        (1, "position_id", "TEXT", 1, None, 0),
        (2, "source_fill_venue", "TEXT", 1, None, 0),
        (3, "source_fill_account_scope", "TEXT", 1, None, 0),
        (4, "source_fill_id", "TEXT", 1, None, 0),
        (5, "source_fill_event_no", "INTEGER", 1, None, 0),
        (6, "event_type", "TEXT", 1, None, 0),
        (7, "delta_qty", "TEXT", 1, None, 0),
        (8, "price", "TEXT", 1, None, 0),
        (9, "fee", "TEXT", 1, None, 0),
        (10, "realized_pnl", "TEXT", 1, None, 0),
        (11, "timestamp", "TEXT", 1, None, 0),
    ]


def test_exact_foreign_key_ownership() -> None:
    db = _db()
    assert _fk_groups(db, "order_states") == {
        (
            "dispatch_attempts",
            (
                ("execution_intent_id", "execution_intent_id"),
                ("attempt_id", "attempt_id"),
                ("venue", "venue"),
                ("account_scope", "account_scope"),
            ),
            "RESTRICT",
        )
    }
    assert _fk_groups(db, "fill_states") == {
        (
            "order_states",
            (
                ("venue", "venue"),
                ("account_scope", "account_scope"),
                ("order_id", "order_id"),
            ),
            "RESTRICT",
        )
    }
    assert _fk_groups(db, "position_accounting_details") == {
        (
            "fill_states",
            (
                ("source_fill_venue", "venue"),
                ("source_fill_account_scope", "account_scope"),
                ("source_fill_id", "fill_id"),
            ),
            "RESTRICT",
        ),
        (
            "position_states",
            (("position_id", "position_id"),),
            "RESTRICT",
        ),
    }


def test_named_indexes_and_unique_backing() -> None:
    db = _db()
    expected = {
        "uq_dispatch_attempts_owner_scope": (
            "execution_intent_id",
            "attempt_id",
            "venue",
            "account_scope",
        ),
        "idx_order_states_execution": ("execution_intent_id", "attempt_id"),
        "idx_order_states_client_order": ("client_order_id",),
        "idx_order_states_status": ("status",),
        "idx_fill_states_order_time": (
            "venue",
            "account_scope",
            "order_id",
            "timestamp",
        ),
        "uq_position_states_one_open": (
            "venue",
            "account_scope",
            "symbol",
            "side",
        ),
        "idx_position_states_scope_symbol": (
            "venue",
            "account_scope",
            "symbol",
            "side",
        ),
        "idx_position_states_status": ("status",),
        "idx_position_accounting_position_time": ("position_id", "timestamp"),
        "idx_position_accounting_fill": (
            "source_fill_venue",
            "source_fill_account_scope",
            "source_fill_id",
            "source_fill_event_no",
        ),
    }
    for name, columns in expected.items():
        assert _index_columns(db, name) == columns
    _find_unique_index(
        db,
        "dispatch_attempts",
        ("execution_intent_id", "attempt_id", "venue", "account_scope"),
    )
    _find_unique_index(
        db,
        "order_states",
        ("venue", "account_scope", "client_order_id"),
    )
    _find_unique_index(
        db,
        "position_states",
        ("venue", "account_scope", "symbol", "side"),
        partial=1,
    )
    _find_unique_index(
        db,
        "position_accounting_details",
        (
            "source_fill_venue",
            "source_fill_account_scope",
            "source_fill_id",
            "source_fill_event_no",
        ),
    )


def test_order_identity_is_venue_and_account_scoped() -> None:
    db = _db()
    g1 = _insert_execution_graph(db, suffix="1", account_scope="account-a")
    g2 = _insert_execution_graph(db, suffix="2", account_scope="account-b")
    _insert_order(db, g1, order_id="same-order")
    _insert_order(db, g2, order_id="same-order")
    assert db.connection.execute("SELECT COUNT(*) FROM order_states").fetchone()[0] == 2


def test_order_requires_exact_dispatch_ownership() -> None:
    db = _db()
    graph = _insert_execution_graph(db)
    wrong = dict(graph)
    wrong["account_scope"] = "wrong-account"
    with pytest.raises(sqlite3.IntegrityError):
        _insert_order(db, wrong)


def test_client_order_id_is_unique_only_within_scope() -> None:
    db = _db()
    g1 = _insert_execution_graph(db, suffix="1", account_scope="account-a", client_order_id="stable")
    g2 = _insert_execution_graph(db, suffix="2", account_scope="account-a", client_order_id="stable")
    g3 = _insert_execution_graph(db, suffix="3", account_scope="account-b", client_order_id="stable")
    _insert_order(db, g1, order_id="o1")
    with pytest.raises(sqlite3.IntegrityError):
        _insert_order(db, g2, order_id="o2")
    db.connection.rollback()
    _insert_order(db, g3, order_id="o3")


def test_fill_identity_and_order_scope() -> None:
    db = _db()
    g1 = _insert_execution_graph(db, suffix="1", account_scope="account-a")
    g2 = _insert_execution_graph(db, suffix="2", account_scope="account-b")
    _insert_order(db, g1, order_id="order")
    _insert_order(db, g2, order_id="order")
    _insert_fill(db, g1, fill_id="same-fill", order_id="order")
    _insert_fill(db, g2, fill_id="same-fill", order_id="order")
    wrong = dict(g1)
    wrong["account_scope"] = "missing"
    with pytest.raises(sqlite3.IntegrityError):
        _insert_fill(db, wrong, fill_id="bad", order_id="order")


def test_position_open_uniqueness_and_closed_at_contract() -> None:
    db = _db()
    _insert_position(db, position_id="p1")
    with pytest.raises(sqlite3.IntegrityError):
        _insert_position(db, position_id="p2")
    db.connection.rollback()
    _insert_position(db, position_id="p3", status="CLOSED")
    with pytest.raises(sqlite3.IntegrityError):
        db.connection.execute(
            "INSERT INTO position_states VALUES "
            "('p4','okx_paper','spot-main','BTC/USDT','LONG','0','1','0','0','CLOSED','t',NULL,'t')"
        )


def test_fill_event_sequence_is_idempotent_and_supports_zero_crossing() -> None:
    db = _db()
    graph = _insert_execution_graph(db)
    _insert_order(db, graph)
    _insert_fill(db, graph)
    _insert_position(db)
    _insert_accounting(db, event_id="ev1", event_no=1, event_type="CLOSE")
    _insert_accounting(db, event_id="ev2", event_no=2, event_type="OPEN")
    with pytest.raises(sqlite3.IntegrityError):
        _insert_accounting(db, event_id="ev3", event_no=1)
    db.connection.rollback()
    with pytest.raises(sqlite3.IntegrityError):
        _insert_accounting(db, event_id="ev0", event_no=0)


def test_order_payload_immutable_but_status_mutable() -> None:
    db = _db()
    graph = _insert_execution_graph(db)
    _insert_order(db, graph)
    db.connection.execute(
        "UPDATE order_states SET status='PARTIALLY_FILLED', updated_at='later' "
        "WHERE venue=? AND account_scope=? AND order_id='order-1'",
        (graph["venue"], graph["account_scope"]),
    )
    with pytest.raises(sqlite3.IntegrityError):
        db.connection.execute(
            "UPDATE order_states SET quantity='999' "
            "WHERE venue=? AND account_scope=? AND order_id='order-1'",
            (graph["venue"], graph["account_scope"]),
        )
    with pytest.raises(sqlite3.IntegrityError):
        db.connection.execute("DELETE FROM order_states")


def test_fill_and_accounting_rows_are_immutable() -> None:
    db = _db()
    graph = _insert_execution_graph(db)
    _insert_order(db, graph)
    _insert_fill(db, graph)
    _insert_position(db)
    _insert_accounting(db, event_id="ev1")
    with pytest.raises(sqlite3.IntegrityError):
        db.connection.execute("UPDATE fill_states SET fee='0'")
    with pytest.raises(sqlite3.IntegrityError):
        db.connection.execute("DELETE FROM fill_states")
    with pytest.raises(sqlite3.IntegrityError):
        db.connection.execute("UPDATE position_accounting_details SET fee='0'")
    with pytest.raises(sqlite3.IntegrityError):
        db.connection.execute("DELETE FROM position_accounting_details")


def test_position_scope_immutable_but_accounting_fields_mutable() -> None:
    db = _db()
    _insert_position(db)
    db.connection.execute(
        "UPDATE position_states SET quantity='0.02', unrealized_pnl='5', updated_at='later' "
        "WHERE position_id='position-1'"
    )
    with pytest.raises(sqlite3.IntegrityError):
        db.connection.execute(
            "UPDATE position_states SET account_scope='other' WHERE position_id='position-1'"
        )
    with pytest.raises(sqlite3.IntegrityError):
        db.connection.execute("DELETE FROM position_states")


def test_real_v3_to_v4_preserves_all_existing_rows() -> None:
    path = pathlib.Path(tempfile.mkdtemp()) / "upgrade.db"
    db = RuntimeDatabase(path)
    db.connect()
    MigrationManager(db, tuple(m for m in MIGRATION_PLAN if m.version <= 3)).migrate()
    graph = _insert_execution_graph(db)
    db.connection.execute(
        "INSERT INTO recovery_states VALUES (?,?,?,?,?,NULL)",
        ("recovery-1", graph["session_id"], "PENDING", "[]", "2026-01-01T00:00:00Z"),
    )
    db.connection.execute(
        "INSERT INTO cycle_journal (cycle_id,from_state,to_state,recorded_at) "
        "VALUES (?,?,?,?)",
        (
            graph["cycle_id"],
            "CREATED",
            "MARKET_ACCEPTED",
            "2026-01-01T00:00:00Z",
        ),
    )
    db.connection.execute(
        "INSERT INTO execution_states VALUES (?,?,?,?,?,?)",
        (
            graph["execution_intent_id"],
            "ACKNOWLEDGED",
            graph["attempt_id"],
            0,
            "2026-01-01T00:00:04Z",
            "2026-01-01T00:00:04Z",
        ),
    )
    tables = (
        "runtime_sessions",
        "runtime_cycles",
        "recovery_states",
        "cycle_journal",
        "trade_intents",
        "risk_decisions",
        "execution_intents",
        "dispatch_attempts",
        "execution_states",
    )
    before = {
        table: [tuple(row) for row in db.connection.execute(f"SELECT * FROM {table}")]
        for table in tables
    }
    db.connection.commit()
    db.close()

    upgraded = RuntimeDatabase(path)
    upgraded.connect()
    assert MigrationManager(upgraded, MIGRATION_PLAN).migrate() == 1
    upgraded.connection.commit()
    upgraded.close()

    reopened = RuntimeDatabase(path)
    reopened.connect()
    for table in tables:
        after = [tuple(row) for row in reopened.connection.execute(f"SELECT * FROM {table}")]
        assert after == before[table]
    for table in (
        "order_states",
        "fill_states",
        "position_states",
        "position_accounting_details",
    ):
        assert reopened.connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0
    assert MigrationManager(reopened, MIGRATION_PLAN).migrate() == 0


def test_failed_migration_0004_rolls_back_every_object() -> None:
    db = _db(version=3)
    bad = Migration(
        version=4,
        name="order_fill_position_persistence",
        sql=MIGRATION_PLAN[3].sql + "\nCREATE TABLE incomplete (\n",
    )
    with pytest.raises(MigrationApplyError):
        MigrationManager(db, (*MIGRATION_PLAN[:3], bad)).migrate()
    assert db.connection.execute(
        "SELECT MAX(version) FROM schema_migrations"
    ).fetchone()[0] == 3
    objects = {
        row[0]
        for row in db.connection.execute(
            "SELECT name FROM sqlite_master WHERE name IN ("
            "'order_states','fill_states','position_states',"
            "'position_accounting_details','uq_dispatch_attempts_owner_scope')"
        )
    }
    assert objects == set()
