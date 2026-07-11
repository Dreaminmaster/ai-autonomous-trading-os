"""B4.3A V1.2 authority-consistent lifecycle persistence schema tests."""
from __future__ import annotations

import hashlib
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


def make_db(version: int = 4, path: pathlib.Path | None = None) -> RuntimeDatabase:
    db = RuntimeDatabase(path or pathlib.Path(tempfile.mkdtemp()) / "runtime.db")
    db.connect()
    MigrationManager(
        db, tuple(m for m in MIGRATION_PLAN if m.version <= version)
    ).migrate()
    return db


def insert_graph(
    db: RuntimeDatabase,
    suffix: str,
    *,
    symbol: str = "BTC/USDT",
    action: str = "BUY",
    venue: str = "okx_paper",
    account_scope: str = "spot-main",
    client_order_id: str | None = None,
) -> dict[str, str]:
    graph = {
        "session_id": f"session-{suffix}",
        "cycle_id": f"cycle-{suffix}",
        "trade_intent_id": f"trade-{suffix}",
        "risk_decision_id": f"risk-{suffix}",
        "execution_intent_id": f"execution-{suffix}",
        "attempt_id": f"attempt-{suffix}",
        "client_order_id": client_order_id or f"client-{suffix}",
        "symbol": symbol,
        "action": action,
        "venue": venue,
        "account_scope": account_scope,
    }
    db.connection.execute(
        "INSERT INTO runtime_sessions VALUES (?,?,?,?,NULL,NULL)",
        (graph["session_id"], "t0", "paper", "RUNNING"),
    )
    db.connection.execute(
        "INSERT INTO runtime_cycles "
        "(cycle_id,session_id,symbol,started_at,status) VALUES (?,?,?,?,?)",
        (graph["cycle_id"], graph["session_id"], symbol, "t0", "CREATED"),
    )
    db.connection.execute(
        "INSERT INTO trade_intents VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            graph["trade_intent_id"],
            symbol,
            action,
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
            graph["risk_decision_id"],
            graph["trade_intent_id"],
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
            graph["execution_intent_id"],
            graph["trade_intent_id"],
            graph["risk_decision_id"],
            graph["cycle_id"],
            symbol,
            action,
            "100",
            hashlib.sha256(suffix.encode()).hexdigest(),
            "t3",
        ),
    )
    db.connection.execute(
        "INSERT INTO dispatch_attempts VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (
            graph["attempt_id"],
            graph["execution_intent_id"],
            graph["client_order_id"],
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
    return graph


def insert_order(
    db: RuntimeDatabase,
    graph: dict[str, str],
    *,
    order_id: str = "order-1",
    client_order_id: str | None = None,
    symbol: str | None = None,
    side: str | None = None,
    order_type: str = "LIMIT",
    status: str = "OPEN",
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
            symbol or graph["symbol"],
            side or graph["action"],
            "0.01",
            "100000",
            order_type,
            status,
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
    symbol: str | None = None,
) -> None:
    db.connection.execute(
        "INSERT INTO fill_states VALUES (?,?,?,?,?,?,?,?,?,?)",
        (
            graph["venue"],
            graph["account_scope"],
            fill_id,
            order_id,
            symbol or graph["symbol"],
            "0.01",
            "100000",
            "1.5",
            "USDT",
            "t7",
        ),
    )


def insert_position(
    db: RuntimeDatabase,
    position_id: str,
    *,
    venue: str = "okx_paper",
    account_scope: str = "spot-main",
    symbol: str = "BTC/USDT",
    side: str = "LONG",
    status: str = "OPEN",
    closed_at: str | None = None,
) -> None:
    if status == "CLOSED" and closed_at is None:
        closed_at = "t8"
    db.connection.execute(
        "INSERT INTO position_states VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            position_id,
            venue,
            account_scope,
            symbol,
            side,
            "0.01" if status == "OPEN" else "0",
            "100000",
            "0",
            "0",
            status,
            "t7",
            closed_at,
            "t7",
        ),
    )


def insert_event(
    db: RuntimeDatabase,
    graph: dict[str, str],
    *,
    event_id: str,
    event_no: int,
    position_id: str,
    fill_id: str = "fill-1",
    symbol: str | None = None,
    event_type: str = "OPEN",
) -> None:
    db.connection.execute(
        "INSERT INTO position_accounting_details VALUES "
        "(?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            event_id,
            position_id,
            graph["venue"],
            graph["account_scope"],
            fill_id,
            symbol or graph["symbol"],
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
        (4, "symbol", "TEXT", 1, None, 0),
        (5, "quantity", "TEXT", 1, None, 0),
        (6, "price", "TEXT", 1, None, 0),
        (7, "fee", "TEXT", 1, None, 0),
        (8, "fee_currency", "TEXT", 1, None, 0),
        (9, "timestamp", "TEXT", 1, None, 0),
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
        (5, "source_fill_symbol", "TEXT", 1, None, 0),
        (6, "source_fill_event_no", "INTEGER", 1, None, 0),
        (7, "event_type", "TEXT", 1, None, 0),
        (8, "delta_qty", "TEXT", 1, None, 0),
        (9, "price", "TEXT", 1, None, 0),
        (10, "fee", "TEXT", 1, None, 0),
        (11, "realized_pnl", "TEXT", 1, None, 0),
        (12, "timestamp", "TEXT", 1, None, 0),
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
                ("client_order_id", "client_order_id"),
            ),
            "RESTRICT",
        ),
        (
            "execution_intents",
            (
                ("execution_intent_id", "execution_intent_id"),
                ("symbol", "symbol"),
                ("side", "action"),
            ),
            "RESTRICT",
        ),
    }
    assert fk_groups(db, "fill_states") == {
        (
            "order_states",
            (
                ("venue", "venue"),
                ("account_scope", "account_scope"),
                ("order_id", "order_id"),
                ("symbol", "symbol"),
            ),
            "RESTRICT",
        )
    }
    assert fk_groups(db, "position_accounting_details") == {
        (
            "fill_states",
            (
                ("source_fill_venue", "venue"),
                ("source_fill_account_scope", "account_scope"),
                ("source_fill_id", "fill_id"),
                ("source_fill_symbol", "symbol"),
            ),
            "RESTRICT",
        ),
        (
            "position_states",
            (
                ("position_id", "position_id"),
                ("source_fill_venue", "venue"),
                ("source_fill_account_scope", "account_scope"),
                ("source_fill_symbol", "symbol"),
            ),
            "RESTRICT",
        ),
    }


def test_named_indexes_and_unique_parent_backing() -> None:
    db = make_db()
    named = {
        "uq_execution_intents_order_semantics": (
            "execution_intent_id",
            "symbol",
            "action",
        ),
        "uq_dispatch_attempts_order_owner": (
            "execution_intent_id",
            "attempt_id",
            "venue",
            "account_scope",
            "client_order_id",
        ),
        "uq_order_states_symbol_owner": (
            "venue",
            "account_scope",
            "order_id",
            "symbol",
        ),
        "idx_order_states_execution": ("execution_intent_id", "attempt_id"),
        "idx_order_states_client_order": ("client_order_id",),
        "idx_order_states_status": ("status",),
        "uq_fill_states_symbol_identity": (
            "venue",
            "account_scope",
            "fill_id",
            "symbol",
        ),
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
        "uq_position_states_account_symbol": (
            "position_id",
            "venue",
            "account_scope",
            "symbol",
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
    for table, columns, partial in (
        (
            "execution_intents",
            ("execution_intent_id", "symbol", "action"),
            None,
        ),
        (
            "dispatch_attempts",
            (
                "execution_intent_id",
                "attempt_id",
                "venue",
                "account_scope",
                "client_order_id",
            ),
            None,
        ),
        (
            "order_states",
            ("venue", "account_scope", "order_id", "symbol"),
            None,
        ),
        (
            "order_states",
            ("venue", "account_scope", "client_order_id"),
            None,
        ),
        (
            "fill_states",
            ("venue", "account_scope", "fill_id", "symbol"),
            None,
        ),
        (
            "position_states",
            ("position_id", "venue", "account_scope", "symbol"),
            None,
        ),
        (
            "position_states",
            ("venue", "account_scope", "symbol", "side"),
            1,
        ),
        (
            "position_accounting_details",
            (
                "source_fill_venue",
                "source_fill_account_scope",
                "source_fill_id",
                "source_fill_event_no",
            ),
            None,
        ),
    ):
        unique_index(db, table, columns, partial=partial)


def test_order_requires_exact_dispatch_client_identity() -> None:
    db = make_db()
    graph = insert_graph(db, "1")
    with pytest.raises(sqlite3.IntegrityError):
        insert_order(db, graph, client_order_id="wrong-client")
    insert_order(db, graph)


def test_order_requires_execution_symbol_and_side() -> None:
    db = make_db()
    graph = insert_graph(db, "1")
    with pytest.raises(sqlite3.IntegrityError):
        insert_order(db, graph, symbol="ETH/USDT")
    with pytest.raises(sqlite3.IntegrityError):
        insert_order(db, graph, side="SELL")
    insert_order(db, graph)


def test_order_and_client_identity_are_venue_account_scoped() -> None:
    db = make_db()
    g1 = insert_graph(db, "1", account_scope="account-a", client_order_id="stable")
    g2 = insert_graph(db, "2", account_scope="account-b", client_order_id="stable")
    insert_order(db, g1, order_id="shared")
    insert_order(db, g2, order_id="shared")
    db.connection.commit()
    assert db.connection.execute("SELECT COUNT(*) FROM order_states").fetchone()[0] == 2

    g3 = insert_graph(db, "3", account_scope="account-a", client_order_id="stable")
    with pytest.raises(sqlite3.IntegrityError):
        insert_order(db, g3, order_id="other")


def test_fill_requires_exact_order_symbol_and_scoped_identity() -> None:
    db = make_db()
    g1 = insert_graph(db, "1", account_scope="account-a")
    g2 = insert_graph(db, "2", account_scope="account-b")
    insert_order(db, g1, order_id="shared")
    insert_order(db, g2, order_id="shared")
    db.connection.commit()

    with pytest.raises(sqlite3.IntegrityError):
        insert_fill(db, g1, fill_id="bad", order_id="shared", symbol="ETH/USDT")
    insert_fill(db, g1, fill_id="same", order_id="shared")
    insert_fill(db, g2, fill_id="same", order_id="shared")
    db.connection.commit()
    assert db.connection.execute("SELECT COUNT(*) FROM fill_states").fetchone()[0] == 2


def test_position_open_uniqueness_and_closed_at_contract() -> None:
    db = make_db()
    insert_position(db, "open-1")
    db.connection.commit()
    with pytest.raises(sqlite3.IntegrityError):
        insert_position(db, "open-2")
    db.connection.rollback()
    insert_position(db, "closed-1", status="CLOSED")
    with pytest.raises(sqlite3.IntegrityError):
        db.connection.execute(
            "INSERT INTO position_states VALUES "
            "('bad-closed','okx_paper','spot-main','BTC/USDT','LONG','0','1',"
            "'0','0','CLOSED','t',NULL,'t')"
        )
    with pytest.raises(sqlite3.IntegrityError):
        db.connection.execute(
            "INSERT INTO position_states VALUES "
            "('bad-open','okx_paper','spot-main','ETH/USDT','LONG','1','1',"
            "'0','0','OPEN','t','not-null','t')"
        )


def test_accounting_rejects_cross_account_and_cross_symbol() -> None:
    db = make_db()
    graph = insert_graph(db, "1", account_scope="account-a")
    insert_order(db, graph)
    insert_fill(db, graph)
    insert_position(db, "wrong-account", account_scope="account-b")
    insert_position(db, "wrong-symbol", account_scope="account-a", symbol="ETH/USDT")
    db.connection.commit()

    with pytest.raises(sqlite3.IntegrityError):
        insert_event(
            db,
            graph,
            event_id="bad-account",
            event_no=1,
            position_id="wrong-account",
        )
    with pytest.raises(sqlite3.IntegrityError):
        insert_event(
            db,
            graph,
            event_id="bad-symbol",
            event_no=1,
            position_id="wrong-symbol",
        )
    with pytest.raises(sqlite3.IntegrityError):
        insert_event(
            db,
            graph,
            event_id="bad-fill-symbol",
            event_no=1,
            position_id="wrong-symbol",
            symbol="ETH/USDT",
        )


def test_fill_event_replay_and_zero_crossing_sequence() -> None:
    db = make_db()
    graph = insert_graph(db, "1", account_scope="account-a")
    insert_order(db, graph)
    insert_fill(db, graph)
    insert_position(
        db,
        "old-short",
        account_scope="account-a",
        side="SHORT",
        status="CLOSED",
    )
    insert_position(db, "new-long", account_scope="account-a", side="LONG")
    insert_event(
        db,
        graph,
        event_id="close-old",
        event_no=1,
        position_id="old-short",
        event_type="CLOSE",
    )
    insert_event(
        db,
        graph,
        event_id="open-new",
        event_no=2,
        position_id="new-long",
        event_type="OPEN",
    )
    db.connection.commit()
    assert db.connection.execute(
        "SELECT COUNT(*) FROM position_accounting_details"
    ).fetchone()[0] == 2

    with pytest.raises(sqlite3.IntegrityError):
        insert_event(
            db,
            graph,
            event_id="duplicate-event-no",
            event_no=1,
            position_id="new-long",
        )
    db.connection.rollback()
    with pytest.raises(sqlite3.IntegrityError):
        insert_event(
            db,
            graph,
            event_id="event-zero",
            event_no=0,
            position_id="new-long",
        )


@pytest.mark.parametrize(
    "mutator",
    [
        lambda db: db.connection.execute("UPDATE order_states SET quantity='999'"),
        lambda db: db.connection.execute("UPDATE fill_states SET fee='0'"),
        lambda db: db.connection.execute(
            "UPDATE position_states SET account_scope='other'"
        ),
        lambda db: db.connection.execute(
            "UPDATE position_accounting_details SET fee='0'"
        ),
        lambda db: db.connection.execute("DELETE FROM order_states"),
        lambda db: db.connection.execute("DELETE FROM fill_states"),
        lambda db: db.connection.execute("DELETE FROM position_states"),
        lambda db: db.connection.execute("DELETE FROM position_accounting_details"),
    ],
)
def test_immutable_boundaries(mutator) -> None:
    db = make_db()
    graph = insert_graph(db, "1")
    insert_order(db, graph)
    insert_fill(db, graph)
    insert_position(db, "position-1")
    insert_event(
        db,
        graph,
        event_id="event-1",
        event_no=1,
        position_id="position-1",
    )
    db.connection.commit()
    with pytest.raises(sqlite3.IntegrityError):
        mutator(db)


def test_lifecycle_columns_remain_mutable() -> None:
    db = make_db()
    graph = insert_graph(db, "1")
    insert_order(db, graph)
    insert_position(db, "position-1")
    db.connection.execute(
        "UPDATE order_states SET status='PARTIALLY_FILLED',updated_at='later'"
    )
    db.connection.execute(
        "UPDATE position_states SET quantity='0.02',unrealized_pnl='5',updated_at='later'"
    )


def test_enum_and_event_number_checks() -> None:
    db = make_db()
    graph = insert_graph(db, "1")
    for kwargs in (
        {"side": "HOLD"},
        {"order_type": "STOP"},
        {"status": "BROKEN"},
    ):
        with pytest.raises(sqlite3.IntegrityError):
            insert_order(db, graph, order_id=str(kwargs), **kwargs)
    insert_order(db, graph)
    insert_fill(db, graph)
    insert_position(db, "position-1")
    with pytest.raises(sqlite3.IntegrityError):
        insert_event(
            db,
            graph,
            event_id="bad-type",
            event_no=1,
            position_id="position-1",
            event_type="TRANSFER",
        )
    with pytest.raises(sqlite3.IntegrityError):
        insert_event(
            db,
            graph,
            event_id="bad-number",
            event_no=0,
            position_id="position-1",
        )


def test_real_v3_to_v4_exact_preservation_and_noop() -> None:
    path = pathlib.Path(tempfile.mkdtemp()) / "upgrade.db"
    db = make_db(version=3, path=path)
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
        (
            graph["execution_intent_id"],
            "ACKNOWLEDGED",
            graph["attempt_id"],
            0,
            "t5",
            "t5",
        ),
    )
    legacy_tables = (
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
        for table in legacy_tables
    }
    db.connection.commit()
    db.close()

    upgraded = make_db(version=4, path=path)
    upgraded.close()
    reopened = RuntimeDatabase(path)
    reopened.connect()
    for table in legacy_tables:
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


def test_failed_0004_rolls_back_every_object() -> None:
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
            "'position_accounting_details','uq_execution_intents_order_semantics',"
            "'uq_dispatch_attempts_order_owner')"
        )
    }
    assert names == set()
