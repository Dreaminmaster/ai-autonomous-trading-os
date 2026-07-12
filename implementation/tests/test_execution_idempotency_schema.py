"""B5B migration V5 execution-idempotency schema contract tests."""
from __future__ import annotations

import hashlib
import pathlib
import sqlite3
import tempfile

import pytest

from atos.execution_idempotency_types import (
    derive_client_order_id,
    derive_idempotency_key,
)
from atos.lifecycle_types import OrderSide
from atos.runtime_db import RuntimeDatabase
from atos.runtime_migrations import (
    MIGRATION_PLAN,
    Migration,
    MigrationApplyError,
    MigrationManager,
)

FROZEN_V1_V4_CHECKSUMS = (
    "b039c238f7d11bcd2fe09e33422a32ad0728147d01c34ffef759fae32fba0b1d",
    "f2e8d13f91b7681f4a379c1fb7cff3b5cb12726dd3ebbdd93063b30fda192cca",
    "e3efc7c169d46546e43473c7700a026c67f7ea3d272f3baa6cf36751bc7d257f",
    "ee8564250fbe02efeb1ae14eea49ec11d5e61f07f65a76d2a0c5e54a93787e82",
)


def make_db(
    version: int = 5, path: pathlib.Path | None = None
) -> RuntimeDatabase:
    db = RuntimeDatabase(path or pathlib.Path(tempfile.mkdtemp()) / "runtime.db")
    db.connect()
    plan = tuple(migration for migration in MIGRATION_PLAN if migration.version <= version)
    MigrationManager(db, plan).migrate()
    return db


def insert_parent_graph(
    db: RuntimeDatabase,
    suffix: str = "1",
    *,
    symbol: str = "BTC/USDT",
    action: str = "BUY",
    decision: str = "APPROVED",
    normalized_intent_hash: str | None = None,
) -> dict[str, str]:
    normalized_intent_hash = normalized_intent_hash or hashlib.sha256(
        f"intent-{suffix}".encode()
    ).hexdigest()
    graph = {
        "session_id": f"session-{suffix}",
        "cycle_id": f"cycle-{suffix}",
        "trade_intent_id": f"trade-{suffix}",
        "risk_decision_id": f"risk-{suffix}",
        "execution_intent_id": f"execution-{suffix}",
        "symbol": symbol,
        "action": action,
        "normalized_intent_hash": normalized_intent_hash,
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
            decision,
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
            normalized_intent_hash,
            "t3",
        ),
    )
    db.connection.commit()
    return graph


def claim_values(
    graph: dict[str, str],
    *,
    venue: str = "okx_paper",
    account_scope: str = "spot-main",
) -> dict[str, str]:
    key = derive_idempotency_key(
        venue=venue,
        account_scope=account_scope,
        symbol=graph["symbol"],
        action=OrderSide(graph["action"]),
        normalized_intent_hash=graph["normalized_intent_hash"],
    )
    return {
        "idempotency_key": key,
        "execution_intent_id": graph["execution_intent_id"],
        "venue": venue,
        "account_scope": account_scope,
        "symbol": graph["symbol"],
        "action": graph["action"],
        "normalized_intent_hash": graph["normalized_intent_hash"],
        "client_order_id": derive_client_order_id(key),
        "created_at": "2026-07-12T18:00:00Z",
    }


def insert_claim(db: RuntimeDatabase, values: dict[str, str]) -> None:
    db.connection.execute(
        "INSERT INTO execution_idempotency_claims VALUES (?,?,?,?,?,?,?,?,?)",
        (
            values["idempotency_key"],
            values["execution_intent_id"],
            values["venue"],
            values["account_scope"],
            values["symbol"],
            values["action"],
            values["normalized_intent_hash"],
            values["client_order_id"],
            values["created_at"],
        ),
    )


def insert_attempt(
    db: RuntimeDatabase,
    claim: dict[str, str],
    *,
    attempt_id: str = "attempt-1",
    attempt_no: int = 1,
    client_order_id: str | None = None,
    venue: str | None = None,
    account_scope: str | None = None,
) -> None:
    db.connection.execute(
        "INSERT INTO dispatch_attempts VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (
            attempt_id,
            claim["execution_intent_id"],
            client_order_id or claim["client_order_id"],
            venue or claim["venue"],
            account_scope or claim["account_scope"],
            "PRE_DISPATCH_PROVEN",
            attempt_no,
            "2026-07-12T18:01:00Z",
            None,
            None,
            None,
        ),
    )


def table_info(db: RuntimeDatabase, table: str) -> list[tuple]:
    return [tuple(row) for row in db.connection.execute(f"PRAGMA table_info({table})")]


def index_columns(db: RuntimeDatabase, index: str) -> tuple[str, ...]:
    return tuple(row[2] for row in db.connection.execute(f"PRAGMA index_info({index})"))


def unique_indexes(db: RuntimeDatabase, table: str) -> set[tuple[str, ...]]:
    result = set()
    for row in db.connection.execute(f"PRAGMA index_list({table})"):
        if row[2] == 1:
            result.add(index_columns(db, row[1]))
    return result


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


def test_plan_appends_v5_without_legacy_checksum_drift():
    assert [migration.version for migration in MIGRATION_PLAN] == [1, 2, 3, 4, 5]
    assert [migration.name for migration in MIGRATION_PLAN] == [
        "runtime_session_cycle_recovery",
        "cycle_journal",
        "execution_transaction_persistence",
        "order_fill_position_persistence",
        "execution_idempotency_claims",
    ]
    assert tuple(migration.checksum for migration in MIGRATION_PLAN[:4]) == (
        FROZEN_V1_V4_CHECKSUMS
    )


def test_fresh_v5_schema_and_exact_claim_shape():
    db = make_db()
    assert db.connection.execute(
        "SELECT MAX(version) FROM schema_migrations"
    ).fetchone()[0] == 5
    assert table_info(db, "execution_idempotency_claims") == [
        (0, "idempotency_key", "TEXT", 0, None, 1),
        (1, "execution_intent_id", "TEXT", 1, None, 0),
        (2, "venue", "TEXT", 1, None, 0),
        (3, "account_scope", "TEXT", 1, None, 0),
        (4, "symbol", "TEXT", 1, None, 0),
        (5, "action", "TEXT", 1, None, 0),
        (6, "normalized_intent_hash", "TEXT", 1, None, 0),
        (7, "client_order_id", "TEXT", 1, None, 0),
        (8, "created_at", "TEXT", 1, None, 0),
    ]


def test_exact_unique_ownership_and_parent_foreign_key():
    db = make_db()
    claim_indexes = unique_indexes(db, "execution_idempotency_claims")
    assert ("idempotency_key",) in claim_indexes
    assert ("execution_intent_id",) in claim_indexes
    assert (
        "venue",
        "account_scope",
        "symbol",
        "action",
        "normalized_intent_hash",
    ) in claim_indexes
    assert ("venue", "account_scope", "client_order_id") in claim_indexes
    assert (
        "execution_intent_id",
        "venue",
        "account_scope",
        "client_order_id",
    ) in claim_indexes
    assert index_columns(db, "uq_execution_intents_idempotency_owner") == (
        "execution_intent_id",
        "symbol",
        "action",
        "normalized_intent_hash",
    )
    assert (
        "execution_intents",
        (
            ("execution_intent_id", "execution_intent_id"),
            ("symbol", "symbol"),
            ("action", "action"),
            ("normalized_intent_hash", "normalized_intent_hash"),
        ),
        "RESTRICT",
    ) in fk_groups(db, "execution_idempotency_claims")


def test_valid_claim_and_foreign_key_check():
    db = make_db()
    graph = insert_parent_graph(db)
    values = claim_values(graph)
    insert_claim(db, values)
    db.connection.commit()
    row = db.connection.execute(
        "SELECT * FROM execution_idempotency_claims"
    ).fetchone()
    assert dict(row) == values
    assert db.connection.execute("PRAGMA foreign_key_check").fetchall() == []


@pytest.mark.parametrize(
    ("field_name", "bad_value"),
    (
        ("idempotency_key", "a" * 63),
        ("idempotency_key", "A" * 64),
        ("idempotency_key", "g" + "a" * 63),
        ("normalized_intent_hash", "a" * 63),
        ("normalized_intent_hash", "A" * 64),
        ("client_order_id", "a5" + "a" * 27),
        ("client_order_id", "A5" + "a" * 28),
        ("client_order_id", "a5" + "_" * 28),
        ("action", "HOLD"),
    ),
)
def test_claim_shape_checks_fail_closed(field_name, bad_value):
    db = make_db()
    graph = insert_parent_graph(db)
    values = claim_values(graph)
    values[field_name] = bad_value
    with pytest.raises(sqlite3.IntegrityError):
        insert_claim(db, values)


def test_claim_parent_components_must_match_execution_intent():
    db = make_db()
    graph = insert_parent_graph(db)
    values = claim_values(graph)
    for field_name, bad_value in (
        ("symbol", "ETH/USDT"),
        ("action", "SELL"),
        ("normalized_intent_hash", "1" * 64),
    ):
        changed = dict(values)
        changed[field_name] = bad_value
        with pytest.raises(sqlite3.IntegrityError):
            insert_claim(db, changed)
        db.connection.rollback()


def test_claim_requires_existing_execution_intent():
    db = make_db()
    graph = {
        "execution_intent_id": "missing",
        "symbol": "BTC/USDT",
        "action": "BUY",
        "normalized_intent_hash": "0" * 64,
    }
    with pytest.raises(sqlite3.IntegrityError):
        insert_claim(db, claim_values(graph))


def test_claim_is_immutable_and_non_deletable():
    db = make_db()
    graph = insert_parent_graph(db)
    values = claim_values(graph)
    insert_claim(db, values)
    db.connection.commit()
    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        db.connection.execute(
            "UPDATE execution_idempotency_claims SET account_scope='other'"
        )
    db.connection.rollback()
    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        db.connection.execute("DELETE FROM execution_idempotency_claims")


def test_semantic_key_cannot_be_owned_by_two_execution_intents():
    db = make_db()
    first = insert_parent_graph(db, "1", normalized_intent_hash="0" * 64)
    second = insert_parent_graph(db, "2", normalized_intent_hash="0" * 64)
    first_values = claim_values(first)
    second_values = claim_values(second)
    assert first_values["idempotency_key"] == second_values["idempotency_key"]
    insert_claim(db, first_values)
    with pytest.raises(sqlite3.IntegrityError):
        insert_claim(db, second_values)


def test_execution_intent_cannot_own_two_claims():
    db = make_db()
    graph = insert_parent_graph(db)
    first = claim_values(graph)
    insert_claim(db, first)
    second = claim_values(graph, venue="another_venue")
    with pytest.raises(sqlite3.IntegrityError):
        insert_claim(db, second)


def test_client_order_projection_collision_fails_closed():
    db = make_db()
    first = insert_parent_graph(db, "1")
    second = insert_parent_graph(db, "2")
    first_values = claim_values(first)
    second_values = claim_values(second)
    second_values["client_order_id"] = first_values["client_order_id"]
    insert_claim(db, first_values)
    with pytest.raises(sqlite3.IntegrityError):
        insert_claim(db, second_values)


def test_dispatch_insert_requires_exact_matching_claim():
    db = make_db()
    graph = insert_parent_graph(db)
    values = claim_values(graph)
    with pytest.raises(sqlite3.IntegrityError, match="matching idempotency claim"):
        insert_attempt(db, values)
    insert_claim(db, values)
    insert_attempt(db, values)
    row = db.connection.execute("SELECT * FROM dispatch_attempts").fetchone()
    assert row["client_order_id"] == values["client_order_id"]


@pytest.mark.parametrize(
    "override",
    (
        {"client_order_id": "a5" + "0" * 28},
        {"venue": "other_venue"},
        {"account_scope": "other-account"},
    ),
)
def test_dispatch_owner_mismatch_rejected(override):
    db = make_db()
    graph = insert_parent_graph(db)
    values = claim_values(graph)
    insert_claim(db, values)
    with pytest.raises(sqlite3.IntegrityError, match="matching idempotency claim"):
        insert_attempt(db, values, **override)


def test_b5_v1_rejects_attempt_number_two():
    db = make_db()
    graph = insert_parent_graph(db)
    values = claim_values(graph)
    insert_claim(db, values)
    with pytest.raises(sqlite3.IntegrityError, match="exactly one"):
        insert_attempt(db, values, attempt_no=2)


def test_dispatch_identity_is_immutable_but_outcome_columns_remain_mutable():
    db = make_db()
    graph = insert_parent_graph(db)
    values = claim_values(graph)
    insert_claim(db, values)
    insert_attempt(db, values)
    db.connection.commit()
    with pytest.raises(sqlite3.IntegrityError, match="identity is immutable"):
        db.connection.execute(
            "UPDATE dispatch_attempts SET client_order_id=?",
            ("a5" + "0" * 28,),
        )
    db.connection.rollback()
    db.connection.execute(
        "UPDATE dispatch_attempts SET status='AMBIGUOUS',"
        "response_received_at='2026-07-12T18:02:00Z',"
        "error_class='TransportTimeout' WHERE attempt_id='attempt-1'"
    )
    row = db.connection.execute(
        "SELECT status,error_class FROM dispatch_attempts WHERE attempt_id='attempt-1'"
    ).fetchone()
    assert tuple(row) == ("AMBIGUOUS", "TransportTimeout")


def test_real_v4_to_v5_preserves_every_legacy_row_and_creates_no_fake_claim():
    path = pathlib.Path(tempfile.mkdtemp()) / "upgrade.db"
    db = make_db(version=4, path=path)
    graph = insert_parent_graph(db)
    historical_attempt = (
        "historical-attempt",
        graph["execution_intent_id"],
        "historical-client-order",
        "okx_paper",
        "spot-main",
        "AMBIGUOUS",
        3,
        "t4",
        "t4",
        "t5",
        "LegacyTimeout",
    )
    db.connection.execute(
        "INSERT INTO dispatch_attempts VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        historical_attempt,
    )
    db.connection.execute(
        "INSERT INTO execution_states VALUES (?,?,?,?,?,?)",
        (
            graph["execution_intent_id"],
            "AMBIGUOUS",
            "historical-attempt",
            2,
            "t5",
            "t5",
        ),
    )
    legacy_tables = (
        "runtime_sessions",
        "runtime_cycles",
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

    upgraded = make_db(version=5, path=path)
    for table in legacy_tables:
        assert [
            tuple(row) for row in upgraded.connection.execute(f"SELECT * FROM {table}")
        ] == before[table]
    assert upgraded.connection.execute(
        "SELECT COUNT(*) FROM execution_idempotency_claims"
    ).fetchone()[0] == 0
    assert upgraded.connection.execute("PRAGMA foreign_key_check").fetchall() == []
    assert MigrationManager(upgraded, MIGRATION_PLAN).migrate() == 0


def test_failed_v5_rolls_back_every_new_object():
    db = make_db(version=4)
    bad = Migration(
        version=5,
        name="execution_idempotency_claims",
        sql=MIGRATION_PLAN[4].sql + "\nCREATE TABLE incomplete (\n",
    )
    with pytest.raises(MigrationApplyError):
        MigrationManager(db, (*MIGRATION_PLAN[:4], bad)).migrate()
    assert db.connection.execute(
        "SELECT MAX(version) FROM schema_migrations"
    ).fetchone()[0] == 4
    names = {
        row[0]
        for row in db.connection.execute(
            "SELECT name FROM sqlite_master WHERE name IN ("
            "'execution_idempotency_claims',"
            "'uq_execution_intents_idempotency_owner',"
            "'trg_execution_idempotency_claims_no_update',"
            "'trg_execution_idempotency_claims_no_delete',"
            "'trg_dispatch_attempts_require_idempotency_claim',"
            "'trg_dispatch_attempts_identity_immutable')"
        )
    }
    assert names == set()


def test_v5_sql_contains_no_live_or_private_endpoint_capability():
    sql = MIGRATION_PLAN[4].sql.lower()
    assert "live" not in sql
    assert "api_key" not in sql
    assert "secret" not in sql
    assert "withdraw" not in sql
    assert "transfer" not in sql
