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

LEGACY_CHECKSUMS = (
    "b039c238f7d11bcd2fe09e33422a32ad0728147d01c34ffef759fae32fba0b1d",
    "f2e8d13f91b7681f4a379c1fb7cff3b5cb12726dd3ebbdd93063b30fda192cca",
    "e3efc7c169d46546e43473c7700a026c67f7ea3d272f3baa6cf36751bc7d257f",
)


def make_db(version: int = 4) -> RuntimeDatabase:
    db = RuntimeDatabase(pathlib.Path(tempfile.mkdtemp()) / "runtime.db")
    db.connect()
    MigrationManager(
        db, tuple(m for m in MIGRATION_PLAN if m.version <= version)
    ).migrate()
    return db


def insert_graph(
    db: RuntimeDatabase,
    suffix: str,
    *,
    venue: str = "okx_paper",
    account_scope: str = "spot-main",
    client_order_id: str | None = None,
) -> dict[str, str]:
    ids = {
        "session_id": f"s{suffix}",
        "cycle_id": f"c{suffix}",
        "trade_intent_id": f"t{suffix}",
        "risk_decision_id": f"r{suffix}",
        "execution_intent_id": f"e{suffix}",
        "attempt_id": f"a{suffix}",
        "client_order_id": client_order_id or f"client-{suffix}",
        "venue": venue,
        "account_scope": account_scope,
    }
    db.connection.execute(
        "INSERT INTO runtime_sessions VALUES (?,?,?,?,NULL,NULL)",
        (ids["session_id"], "t0", "paper", "RUNNING"),
    )
    db.connection.execute(
        "INSERT INTO runtime_cycles "
        "(cycle_id,session_id,symbol,started_at,status) VALUES (?,?,?,?,?)",
        (ids["cycle_id"], ids["session_id"], "BTC/USDT", "t0", "CREATED"),
    )
    db.connection.execute(
        "INSERT INTO trade_intents VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            ids["trade_intent_id"],
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
            "t1",
        ),
    )
    db.connection.execute(
        "INSERT INTO risk_decisions VALUES (?,?,?,?,?,?,?)",
        (
            ids["risk_decision_id"],
            ids["trade_intent_id"],
            "APPROVED",
            "[]",
            "0.1",
            "{}",
            "t2",
        ),
    )
    db.connection.execute(
        "INSERT INTO execution_intents VALUES (?,?,?,?,?,?,?,?,?)",
        (
            ids["execution_intent_id"],
            ids["trade_intent_id"],
            ids["risk_decision_id"],
            ids["cycle_id"],
            "BTC/USDT",
            "BUY",
            "100",
            "a" * 63 + suffix[-1].lower() if suffix[-1].lower() in "0123456789abcdef" else "a" * 64,
            "t3",
        ),
    )
    db.connection.execute(
        "INSERT INTO dispatch_attempts VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (
            ids["attempt_id"],
            ids["execution_intent_id"],
            ids["client_order_id"],
            venue,
            account_scope,
            "ACCEPTED",
            1,
            "t4",
            "t4",
            "t5",
            None,
        ),
    )
    db.connection.commit()
    return ids


def insert_order(
    db: RuntimeDatabase,
    graph: dict[str, str],
    *,
    order_id: str = "order-1",
    client_order_id: str | None = None,
) -> None:
    db.connection.execute(
        "INSERT INTO order_states VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
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
            "OPEN",
            "t6",
            "t6",
        ),
    )


def insert_fill(
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
            "t7",
        ),
    )


def insert_position(
    db: RuntimeDatabase,
    position_id: str = "position-1",
    *,
    venue: str = "okx_paper",
    account_scope: str = "spot-main",
    status: str = "OPEN",
) -> None:
    db.connection.execute(
        "INSERT INTO position_states VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            position_id,
            venue,
            account_scope,
            "BTC/USDT",
            "LONG",
            "0.01" if status == "OPEN" else "0",
            "100000",
            "0",
            "0",
            status,
            "t7",
            None if status == "OPEN" else "t8",
            "t7",
        ),
    )


def insert_event(
    db: RuntimeDatabase,
    event_id: str,
    event_no: int,
    *,
    event_type: str = "OPEN",
    position_id: str = "position-1",
    venue: str = "okx_paper",
    account_scope: str = "spot-main",
    fill_id: str = "fill-1",
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
            "t7",
        ),
    )


def table_info(db: RuntimeDatabase, table: str) -> list[tuple]:
    return [tuple(row) for row in db.connection.execute(f"PRAGMA table_info({table})")]


def index_columns(db: RuntimeDatabase, index: str) -> tuple[str, ...]:
    return tuple(
        row[2] for row in db.connection.execute(f"PRAGMA index_info({index})")
    )


def unique_index(
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
        if index_columns(db, row[1]) == columns:
            return row[1]
    raise AssertionError((table, columns, partial))


def fk_groups(db: RuntimeDatabase, table: str) -> set[tuple]:
    grouped: dict[int, list] = {}
    for row in db.connection.execute(f"PRAGMA foreign_key_list({table})"):
        grouped.setdefault(row[0], []).append(row)
    return {
        (
            rows[0][2],
            tuple((row[3], row[4]) for row in sorted(rows, key=lambda row: row[1])),
            rows[0][6],
        )
        for rows in grouped.values()
    }


def test_plan_fresh_schema_and_legacy_checksums() -> None:
    db = make_db()
    assert [m.version for m in MIGRATION_PLAN] == [1, 2, 3, 4]
    assert tuple(m.checksum for m in MIGRATION_PLAN[:3]) == LEGACY_CHECKSUMS
    assert db.connection.execute(
        "SELECT MAX(version) FROM schema_migrations"
    ).fetchone()[0] == 4
    names = {
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
    }.issubset(names)


def test_exact_table_shapes() -> None:
    db = make_db()
    assert table_info(db, "order_states") == [
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
    assert table_info(db, "fill_states") == [
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
    assert table_info(db, "position_states") == [
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
    assert table_info(db, "position_accounting_details") == [
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


def test_exact_fk_graph() -> None:
    db = make_db()
    assert fk_groups(db, "order_states") == {
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
    assert fk_groups(db, "fill_states") == {
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
    assert fk_groups(db, "position_accounting_details") == {
        (
            "position_states",
            (("position_id", "position_id"),),
            "RESTRICT",
        ),
        (
            "fill_states",
            (
                ("source_fill_venue", "venue"),
                ("source_fill_account_scope", "account_scope"),
                ("source_fill_id", "fill_id"),
            ),
            "RESTRICT",
        ),
    }


def test_indexes_and_unique_backing() -> None:
    db = make_db()
    named = {
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
    for name, columns in named.items():
        assert index_columns(db, name) == columns
    unique_index(
        db,
        "dispatch_attempts",
        ("execution_intent_id", "attempt_id", "venue", "account_scope"),
    )
    unique_index(
        db,
        "order_states",
        ("venue", "account_scope", "client_order_id"),
    )
    unique_index(
        db,
        "position_states",
        ("venue", "account_scope", "symbol", "side"),
        partial=1,
    )
    unique_index(
        db,
        "position_accounting_details",
        (
            "source_fill_venue",
            "source_fill_account_scope",
            "source_fill_id",
            "source_fill_event_no",
        ),
    )


def test_venue_scope_identity_and_exact_ownership() -> None:
    db = make_db()
    g1 = insert_graph(db, "1", account_scope="account-a")
    g2 = insert_graph(db, "2", account_scope="account-b")
    insert_order(db, g1, order_id="shared")
    insert_order(db, g2, order_id="shared")
    db.connection.commit()
    assert db.connection.execute("SELECT COUNT(*) FROM order_states").fetchone()[0] == 2

    wrong = dict(g1)
    wrong["account_scope"] = "missing"
    with pytest.raises(sqlite3.IntegrityError):
        insert_order(db, wrong, order_id="bad")


def test_client_order_identity_is_scope_local() -> None:
    db = make_db()
    g1 = insert_graph(db, "1", account_scope="account-a", client_order_id="stable")
    g2 = insert_graph(db, "2", account_scope="account-a", client_order_id="stable")
    g3 = insert_graph(db, "3", account_scope="account-b", client_order_id="stable")
    insert_order(db, g1, order_id="o1")
    db.connection.commit()
    with pytest.raises(sqlite3.IntegrityError):
        insert_order(db, g2, order_id="o2")
    db.connection.rollback()
    insert_order(db, g3, order_id="o3")


def test_fill_scope_and_fill_identity() -> None:
    db = make_db()
    g1 = insert_graph(db, "1", account_scope="account-a")
    g2 = insert_graph(db, "2", account_scope="account-b")
    insert_order(db, g1, order_id="shared")
    insert_order(db, g2, order_id="shared")
    insert_fill(db, g1, fill_id="same", order_id="shared")
    insert_fill(db, g2, fill_id="same", order_id="shared")
    db.connection.commit()
    assert db.connection.execute("SELECT COUNT(*) FROM fill_states").fetchone()[0] == 2
    wrong = dict(g1)
    wrong["account_scope"] = "missing"
    with pytest.raises(sqlite3.IntegrityError):
        insert_fill(db, wrong, fill_id="bad", order_id="shared")


def test_open_position_uniqueness_and_timestamp_contract() -> None:
    db = make_db()
    insert_position(db, "p1")
    db.connection.commit()
    with pytest.raises(sqlite3.IntegrityError):
        insert_position(db, "p2")
    db.connection.rollback()
    insert_position(db, "p3", status="CLOSED")
    with pytest.raises(sqlite3.IntegrityError):
        db.connection.execute(
            "INSERT INTO position_states VALUES "
            "('p4','okx_paper','spot-main','BTC/USDT','LONG','0','1','0','0',"
            "'CLOSED','t',NULL,'t')"
        )


def test_fill_event_replay_and_zero_crossing_sequence() -> None:
    db = make_db()
    graph = insert_graph(db, "1")
    insert_order(db, graph)
    insert_fill(db, graph)
    insert_position(db)
    insert_event(db, "event-1", 1, event_type="CLOSE")
    insert_event(db, "event-2", 2, event_type="OPEN")
    db.connection.commit()
    assert db.connection.execute(
        "SELECT COUNT(*) FROM position_accounting_details"
    ).fetchone()[0] == 2
    with pytest.raises(sqlite3.IntegrityError):
        insert_event(db, "event-3", 1)
    db.connection.rollback()
    with pytest.raises(sqlite3.IntegrityError):
        insert_event(db, "event-0", 0)


def test_mutability_boundaries() -> None:
    db = make_db()
    graph = insert_graph(db, "1")
    insert_order(db, graph)
    insert_fill(db, graph)
    insert_position(db)
    insert_event(db, "event-1", 1)
    db.connection.commit()

    db.connection.execute(
        "UPDATE order_states SET status='PARTIALLY_FILLED',updated_at='later' "
        "WHERE venue='okx_paper' AND account_scope='spot-main' AND order_id='order-1'"
    )
    db.connection.execute(
        "UPDATE position_states SET quantity='0.02',unrealized_pnl='5',updated_at='later' "
        "WHERE position_id='position-1'"
    )
    with pytest.raises(sqlite3.IntegrityError):
        db.connection.execute("UPDATE order_states SET quantity='999'")
    with pytest.raises(sqlite3.IntegrityError):
        db.connection.execute("UPDATE fill_states SET fee='0'")
    with pytest.raises(sqlite3.IntegrityError):
        db.connection.execute("UPDATE position_states SET account_scope='other'")
    with pytest.raises(sqlite3.IntegrityError):
        db.connection.execute("UPDATE position_accounting_details SET fee='0'")
    with pytest.raises(sqlite3.IntegrityError):
        db.connection.execute("DELETE FROM order_states")
    with pytest.raises(sqlite3.IntegrityError):
        db.connection.execute("DELETE FROM fill_states")
    with pytest.raises(sqlite3.IntegrityError):
        db.connection.execute("DELETE FROM position_states")
    with pytest.raises(sqlite3.IntegrityError):
        db.connection.execute("DELETE FROM position_accounting_details")


def test_real_v3_to_v4_exact_preservation_and_noop() -> None:
    path = pathlib.Path(tempfile.mkdtemp()) / "upgrade.db"
    db = RuntimeDatabase(path)
    db.connect()
    MigrationManager(db, MIGRATION_PLAN[:3]).migrate()
    graph = insert_graph(db, "1")
    db.connection.execute(
        "INSERT INTO recovery_states VALUES (?,?,?,?,?,NULL)",
        ("recovery-1", graph["session_id"], "PENDING", "[]", "t0"),
    )
    db.connection.execute(
        "INSERT INTO cycle_journal (cycle_id,from_state,to_state,recorded_at) "
        "VALUES (?,?,?,?)",
        (graph["cycle_id"], "CREATED", "MARKET_ACCEPTED", "t1"),
    )
    db.connection.execute(
        "INSERT INTO execution_states VALUES (?,?,?,?,?,?)",
        (graph["execution_intent_id"], "ACKNOWLEDGED", graph["attempt_id"], 0, "t5", "t5"),
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
    upgraded.close()

    reopened = RuntimeDatabase(path)
    reopened.connect()
    for table in tables:
        assert [
            tuple(row) for row in reopened.connection.execute(f"SELECT * FROM {table}")
        ] == before[table]
    for table in (
        "order_states",
        "fill_states",
        "position_states",
        "position_accounting_details",
    ):
        assert reopened.connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0
    assert MigrationManager(reopened, MIGRATION_PLAN).migrate() == 0


def test_failed_0004_is_atomic() -> None:
    db = make_db(version=3)
    bad = Migration(
        4,
        "order_fill_position_persistence",
        MIGRATION_PLAN[3].sql + "\nCREATE TABLE incomplete (\n",
    )
    with pytest.raises(MigrationApplyError):
        MigrationManager(db, (*MIGRATION_PLAN[:3], bad)).migrate()
    assert db.connection.execute(
        "SELECT MAX(version) FROM schema_migrations"
    ).fetchone()[0] == 3
    names = {
        row[0]
        for row in db.connection.execute(
            "SELECT name FROM sqlite_master WHERE name IN ("
            "'order_states','fill_states','position_states',"
            "'position_accounting_details','uq_dispatch_attempts_owner_scope')"
        )
    }
    assert names == set()
