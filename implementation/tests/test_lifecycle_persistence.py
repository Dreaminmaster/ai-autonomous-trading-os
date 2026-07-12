"""B4.3B2 atomic SQLite lifecycle persistence contract tests."""
from __future__ import annotations

import ast
import hashlib
import inspect
import queue
import threading
from dataclasses import replace
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest

import atos.lifecycle_persistence as persistence_module
from atos.execution_idempotency_types import (
    derive_client_order_id,
    derive_idempotency_key,
)
from atos.lifecycle_persistence import SqliteLifecyclePersistence
from atos.lifecycle_types import (
    AccountingPlan,
    FillApplicationCommand,
    LifecycleConflictError,
    LifecycleInvariantError,
    LifecyclePersistenceError,
    LifecyclePreconditionError,
    LifecycleValidationError,
    OperationStats,
    OrderAcknowledgementCommand,
    OrderSide,
    OrderStatus,
    OrderType,
    PersistenceOutcome,
    PositionAccountingPolicy,
)
from atos.position_accounting import NettingPositionAccountingV1
from atos.runtime_db import RuntimeDatabase
from atos.runtime_migrations import MIGRATION_PLAN, MigrationManager

T0 = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)
T1 = datetime(2026, 1, 1, 0, 1, tzinfo=timezone.utc)
T2 = datetime(2026, 1, 1, 0, 2, tzinfo=timezone.utc)
T3 = datetime(2026, 1, 1, 0, 3, tzinfo=timezone.utc)


def make_db(path: Path) -> RuntimeDatabase:
    db = RuntimeDatabase(path)
    db.connect()
    MigrationManager(db, MIGRATION_PLAN).migrate()
    return db


def seed_execution_graph(
    db: RuntimeDatabase,
    suffix: str,
    *,
    action: str = "BUY",
    symbol: str = "BTC/USDT",
    venue: str = "okx_paper",
    account_scope: str = "spot-main",
    dispatch_status: str = "SUBMITTED",
    execution_status: str = "DISPATCHED",
) -> dict[str, str]:
    normalized_intent_hash = hashlib.sha256(suffix.encode()).hexdigest()
    idempotency_key = derive_idempotency_key(
        venue=venue,
        account_scope=account_scope,
        symbol=symbol,
        action=OrderSide(action),
        normalized_intent_hash=normalized_intent_hash,
    )
    graph = {
        "session_id": f"session-{suffix}",
        "cycle_id": f"cycle-{suffix}",
        "trade_intent_id": f"trade-{suffix}",
        "risk_decision_id": f"risk-{suffix}",
        "execution_intent_id": f"execution-{suffix}",
        "attempt_id": f"attempt-{suffix}",
        "idempotency_key": idempotency_key,
        "normalized_intent_hash": normalized_intent_hash,
        "client_order_id": derive_client_order_id(idempotency_key),
        "order_id": f"order-{suffix}",
        "symbol": symbol,
        "action": action,
        "venue": venue,
        "account_scope": account_scope,
    }
    c = db.connection
    c.execute(
        "INSERT INTO runtime_sessions VALUES (?,?,?,?,NULL,NULL)",
        (graph["session_id"], "2026-01-01T00:00:00Z", "paper", "RUNNING"),
    )
    c.execute(
        "INSERT INTO runtime_cycles "
        "(cycle_id,session_id,symbol,started_at,status) VALUES (?,?,?,?,?)",
        (
            graph["cycle_id"], graph["session_id"], symbol,
            "2026-01-01T00:00:00Z", "CREATED",
        ),
    )
    c.execute(
        "INSERT INTO trade_intents VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            graph["trade_intent_id"], symbol, action, "0.9", "thesis", "{}",
            "0.1", "0.02", "0.04", "[]", "[]", "2026-01-01T00:00:00Z",
        ),
    )
    c.execute(
        "INSERT INTO risk_decisions VALUES (?,?,?,?,?,?,?)",
        (
            graph["risk_decision_id"], graph["trade_intent_id"], "APPROVED",
            "[]", "0.1", "{}", "2026-01-01T00:00:00Z",
        ),
    )
    c.execute(
        "INSERT INTO execution_intents VALUES (?,?,?,?,?,?,?,?,?)",
        (
            graph["execution_intent_id"], graph["trade_intent_id"],
            graph["risk_decision_id"], graph["cycle_id"], symbol, action, "100",
            graph["normalized_intent_hash"],
            "2026-01-01T00:00:00Z",
        ),
    )
    c.execute(
        "INSERT INTO execution_idempotency_claims VALUES (?,?,?,?,?,?,?,?,?)",
        (
            graph["idempotency_key"], graph["execution_intent_id"],
            venue, account_scope, symbol, action,
            graph["normalized_intent_hash"], graph["client_order_id"],
            "2026-01-01T00:00:00Z",
        ),
    )
    c.execute(
        "INSERT INTO dispatch_attempts VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (
            graph["attempt_id"], graph["execution_intent_id"],
            graph["client_order_id"], venue, account_scope, dispatch_status, 1,
            "2026-01-01T00:00:00Z", "2026-01-01T00:00:00Z", None, None,
        ),
    )
    c.execute(
        "INSERT INTO execution_states VALUES (?,?,?,?,?,?)",
        (
            graph["execution_intent_id"], execution_status, graph["attempt_id"], 0,
            "2026-01-01T00:00:00Z", "2026-01-01T00:00:00Z",
        ),
    )
    c.commit()
    return graph


def order_command(
    graph: dict[str, str],
    *,
    quantity: Decimal = Decimal("2"),
    price: Decimal = Decimal("100"),
    acknowledged_at: datetime = T0,
) -> OrderAcknowledgementCommand:
    return OrderAcknowledgementCommand(
        venue=graph["venue"], account_scope=graph["account_scope"],
        order_id=graph["order_id"], execution_intent_id=graph["execution_intent_id"],
        attempt_id=graph["attempt_id"], client_order_id=graph["client_order_id"],
        symbol=graph["symbol"], side=OrderSide(graph["action"]),
        quantity=quantity, price=price, order_type=OrderType.LIMIT,
        acknowledged_at=acknowledged_at,
    )


def fill_command(
    graph: dict[str, str],
    fill_id: str,
    *,
    quantity: Decimal = Decimal("1"),
    price: Decimal = Decimal("100"),
    fee: Decimal = Decimal("0.1"),
    occurred_at: datetime = T1,
    recorded_at: datetime = T2,
    order_status_after: OrderStatus = OrderStatus.PARTIALLY_FILLED,
    symbol: str | None = None,
) -> FillApplicationCommand:
    return FillApplicationCommand(
        venue=graph["venue"], account_scope=graph["account_scope"],
        fill_id=fill_id, order_id=graph["order_id"], symbol=symbol or graph["symbol"],
        quantity=quantity, price=price, fee=fee, fee_currency="USDT",
        occurred_at=occurred_at, recorded_at=recorded_at,
        order_status_after=order_status_after,
    )


def make_adapter(db: RuntimeDatabase) -> SqliteLifecyclePersistence:
    return SqliteLifecyclePersistence(db, NettingPositionAccountingV1())


def acknowledge(db: RuntimeDatabase, graph: dict[str, str]) -> SqliteLifecyclePersistence:
    adapter = make_adapter(db)
    assert adapter.register_order_acknowledgement(
        order_command(graph)
    ).outcome is PersistenceOutcome.APPLIED
    return adapter


def scalar(db: RuntimeDatabase, sql: str, params: tuple = ()):
    row = db.connection.execute(sql, params).fetchone()
    return None if row is None else row[0]


class FailingAdapter(SqliteLifecyclePersistence):
    def __init__(self, db, policy, boundary: str) -> None:
        super().__init__(db, policy)
        self.boundary = boundary

    def _after_mutation(self, boundary, connection) -> None:
        del connection
        if boundary == self.boundary:
            raise RuntimeError("injected crash")


class BadScopePolicy(PositionAccountingPolicy):
    def __init__(self) -> None:
        self.inner = NettingPositionAccountingV1()

    def plan(self, *, command, order_side, open_positions) -> AccountingPlan:
        plan = self.inner.plan(
            command=command, order_side=order_side, open_positions=open_positions
        )
        bad = replace(plan.positions[0], venue="wrong-venue")
        return AccountingPlan(plan.events, (bad,) + plan.positions[1:])


class BadEventIdPolicy(PositionAccountingPolicy):
    def __init__(self) -> None:
        self.inner = NettingPositionAccountingV1()

    def plan(self, *, command, order_side, open_positions) -> AccountingPlan:
        plan = self.inner.plan(
            command=command, order_side=order_side, open_positions=open_positions
        )
        bad = replace(plan.events[0], event_id="not-deterministic")
        return AccountingPlan((bad,) + plan.events[1:], plan.positions)


class AlternatePositionIdPolicy(PositionAccountingPolicy):
    def __init__(self) -> None:
        self.inner = NettingPositionAccountingV1()

    def plan(self, *, command, order_side, open_positions) -> AccountingPlan:
        plan = self.inner.plan(
            command=command,
            order_side=order_side,
            open_positions=open_positions,
        )
        custom_id = f"policy-position-{command.fill_id}"
        event = replace(plan.events[0], position_id=custom_id)
        mutation = replace(plan.positions[0], position_id=custom_id)
        return AccountingPlan(
            (event,) + plan.events[1:],
            (mutation,) + plan.positions[1:],
        )


def test_adapter_requires_preconnected_database(tmp_path):
    db = RuntimeDatabase(tmp_path / "runtime.db")
    with pytest.raises(LifecycleValidationError):
        SqliteLifecyclePersistence(db, NettingPositionAccountingV1())
    assert db.conn is None


def test_adapter_rejects_closed_or_replaced_connection_without_reconnect(tmp_path):
    db = make_db(tmp_path / "runtime.db")
    graph = seed_execution_graph(db, "connection-replaced")
    adapter = make_adapter(db)
    original_identity = id(db.connection)

    db.close()
    with pytest.raises(LifecyclePreconditionError) as closed_error:
        adapter.register_order_acknowledgement(order_command(graph))
    assert closed_error.value.stats == OperationStats(
        0, 0, 0, 0, original_identity
    )
    assert db.conn is None

    db.connect()
    with pytest.raises(LifecyclePreconditionError) as replaced_error:
        adapter.register_order_acknowledgement(order_command(graph))
    assert replaced_error.value.stats.transaction_count == 0
    assert replaced_error.value.stats.db_connection_identity == original_identity


def test_order_acknowledgement_exact_three_mutation_transaction(tmp_path):
    db = make_db(tmp_path / "runtime.db")
    graph = seed_execution_graph(db, "ack")
    connection_id = id(db.connection)
    result = make_adapter(db).register_order_acknowledgement(order_command(graph))
    assert result.outcome is PersistenceOutcome.APPLIED
    assert result.stats == OperationStats(1, 3, 3, 1, connection_id)
    assert tuple(db.connection.execute(
        "SELECT status,response_received_at FROM dispatch_attempts WHERE attempt_id=?",
        (graph["attempt_id"],),
    ).fetchone()) == ("ACCEPTED", "2026-01-01T00:00:00Z")
    assert tuple(db.connection.execute(
        "SELECT status,created_at,updated_at,quantity,price FROM order_states"
    ).fetchone()) == (
        "OPEN", "2026-01-01T00:00:00Z", "2026-01-01T00:00:00Z", "2", "100",
    )
    assert tuple(db.connection.execute(
        "SELECT status,state_started_at,updated_at,retry_count "
        "FROM execution_states WHERE execution_intent_id=?",
        (graph["execution_intent_id"],),
    ).fetchone()) == (
        "ACKNOWLEDGED", "2026-01-01T00:00:00Z", "2026-01-01T00:00:00Z", 0,
    )


def test_order_ack_wrong_dispatch_precondition_rolls_back(tmp_path):
    db = make_db(tmp_path / "runtime.db")
    graph = seed_execution_graph(db, "wrong-dispatch", dispatch_status="ACCEPTED")
    with pytest.raises(LifecyclePreconditionError) as caught:
        make_adapter(db).register_order_acknowledgement(order_command(graph))
    assert caught.value.stats.committed_mutations == 0
    assert caught.value.stats.attempted_mutations == 1
    assert scalar(db, "SELECT COUNT(*) FROM order_states") == 0
    assert scalar(db, "SELECT status FROM execution_states") == "DISPATCHED"


def test_order_ack_wrong_execution_precondition_rolls_back_dispatch_and_order(tmp_path):
    db = make_db(tmp_path / "runtime.db")
    graph = seed_execution_graph(db, "wrong-execution", execution_status="PREPARED")
    with pytest.raises(LifecyclePreconditionError) as caught:
        make_adapter(db).register_order_acknowledgement(order_command(graph))
    assert caught.value.stats.attempted_mutations == 3
    assert caught.value.stats.committed_mutations == 0
    assert scalar(db, "SELECT status FROM dispatch_attempts") == "SUBMITTED"
    assert scalar(db, "SELECT COUNT(*) FROM order_states") == 0


@pytest.mark.parametrize("boundary", [
    "order_ack.dispatch_accept", "order_ack.order_insert",
    "order_ack.execution_acknowledge",
])
def test_order_ack_injected_failure_after_each_boundary_rolls_back(tmp_path, boundary):
    db = make_db(tmp_path / f"{boundary}.db")
    graph = seed_execution_graph(db, boundary)
    adapter = FailingAdapter(db, NettingPositionAccountingV1(), boundary)
    with pytest.raises(LifecycleInvariantError) as caught:
        adapter.register_order_acknowledgement(order_command(graph))
    assert caught.value.stats.committed_mutations == 0
    assert scalar(db, "SELECT COUNT(*) FROM order_states") == 0
    assert scalar(db, "SELECT status FROM dispatch_attempts") == "SUBMITTED"
    assert scalar(db, "SELECT status FROM execution_states") == "DISPATCHED"


def test_order_exact_replay_is_zero_mutation_and_does_not_regress_parents(tmp_path):
    db = make_db(tmp_path / "runtime.db")
    graph = seed_execution_graph(db, "order-replay")
    adapter = make_adapter(db)
    command = order_command(graph)
    adapter.register_order_acknowledgement(command)
    db.connection.execute("UPDATE execution_states SET status='FILLED'")
    db.connection.commit()
    result = adapter.register_order_acknowledgement(command)
    assert result.outcome is PersistenceOutcome.REPLAY_NOOP
    assert result.stats == OperationStats(1, 0, 0, 1, id(db.connection))
    assert scalar(db, "SELECT status FROM execution_states") == "FILLED"


def test_order_conflicting_replay_fails_closed(tmp_path):
    db = make_db(tmp_path / "runtime.db")
    graph = seed_execution_graph(db, "order-conflict")
    adapter = make_adapter(db)
    adapter.register_order_acknowledgement(order_command(graph))
    with pytest.raises(LifecycleConflictError) as caught:
        adapter.register_order_acknowledgement(order_command(graph, quantity=Decimal("3")))
    assert caught.value.stats == OperationStats(1, 0, 0, 1, id(db.connection))
    assert scalar(db, "SELECT quantity FROM order_states") == "2"


def test_nested_transaction_is_rejected_before_adapter_transaction(tmp_path):
    db = make_db(tmp_path / "runtime.db")
    graph = seed_execution_graph(db, "nested")
    adapter = make_adapter(db)
    with db.transaction():
        with pytest.raises(LifecyclePreconditionError) as caught:
            adapter.register_order_acknowledgement(order_command(graph))
        assert caught.value.stats.transaction_count == 0
        assert caught.value.stats.committed_mutations == 0


def test_one_event_fill_is_atomic_and_within_statement_budget(tmp_path):
    db = make_db(tmp_path / "runtime.db")
    graph = seed_execution_graph(db, "fill-open")
    result = acknowledge(db, graph).apply_fill(fill_command(graph, "fill-open"))
    assert result.outcome is PersistenceOutcome.APPLIED
    assert result.stats == OperationStats(3, 4, 4, 1, id(db.connection))
    assert scalar(db, "SELECT COUNT(*) FROM fill_states") == 1
    assert scalar(db, "SELECT status FROM order_states") == "PARTIALLY_FILLED"
    assert tuple(db.connection.execute(
        "SELECT event_type,delta_qty,fee,realized_pnl,timestamp "
        "FROM position_accounting_details"
    ).fetchone()) == (
        "OPEN", "1", "0.1", "0", "2026-01-01T00:01:00Z",
    )
    assert tuple(db.connection.execute(
        "SELECT side,quantity,avg_entry_price,realized_pnl,status FROM position_states"
    ).fetchone()) == ("LONG", "1", "100", "0", "OPEN")


def test_fill_increases_existing_position_with_weighted_average(tmp_path):
    db = make_db(tmp_path / "runtime.db")
    graph = seed_execution_graph(db, "increase")
    adapter = acknowledge(db, graph)
    adapter.apply_fill(fill_command(graph, "fill-1", price=Decimal("100")))
    result = adapter.apply_fill(fill_command(
        graph, "fill-2", price=Decimal("120"), occurred_at=T2, recorded_at=T3
    ))
    assert result.stats.committed_mutations == 4
    assert tuple(db.connection.execute(
        "SELECT quantity,avg_entry_price,realized_pnl FROM position_states "
        "WHERE status='OPEN'"
    ).fetchone()) == ("2", "110", "0")
    assert scalar(db, "SELECT event_type FROM position_accounting_details "
                      "WHERE source_fill_id='fill-2'") == "INCREASE"


def test_zero_crossing_fill_has_two_events_and_six_mutations(tmp_path):
    db = make_db(tmp_path / "runtime.db")
    buy = seed_execution_graph(db, "buy", action="BUY")
    adapter = acknowledge(db, buy)
    adapter.apply_fill(fill_command(
        buy, "fill-buy", quantity=Decimal("1"),
        order_status_after=OrderStatus.FILLED,
    ))
    sell = seed_execution_graph(db, "sell", action="SELL")
    adapter.register_order_acknowledgement(order_command(sell))
    result = adapter.apply_fill(fill_command(
        sell, "fill-cross", quantity=Decimal("1.5"), price=Decimal("110"),
        occurred_at=T2, recorded_at=T3,
        order_status_after=OrderStatus.FILLED,
    ))
    assert result.stats == OperationStats(3, 6, 6, 1, id(db.connection))
    events = db.connection.execute(
        "SELECT source_fill_event_no,event_type,delta_qty,fee,realized_pnl "
        "FROM position_accounting_details WHERE source_fill_id='fill-cross' "
        "ORDER BY source_fill_event_no"
    ).fetchall()
    assert [tuple(row) for row in events] == [
        (1, "CLOSE", "-1", "0.1", "10"),
        (2, "OPEN", "-0.5", "0", "0"),
    ]
    positions = db.connection.execute(
        "SELECT side,quantity,status,realized_pnl FROM position_states ORDER BY side"
    ).fetchall()
    assert [tuple(row) for row in positions] == [
        ("LONG", "0", "CLOSED", "10"),
        ("SHORT", "0.5", "OPEN", "0"),
    ]


def test_exact_fill_replay_ignores_recorded_at_and_stale_order_status(tmp_path):
    db = make_db(tmp_path / "runtime.db")
    graph = seed_execution_graph(db, "fill-replay")
    adapter = acknowledge(db, graph)
    original = fill_command(graph, "fill-replay", order_status_after=OrderStatus.FILLED)
    applied = adapter.apply_fill(original)
    original_updated_at = scalar(db, "SELECT updated_at FROM order_states")
    result = adapter.apply_fill(replace(
        original, recorded_at=T3, order_status_after=OrderStatus.PARTIALLY_FILLED
    ))
    assert result.outcome is PersistenceOutcome.REPLAY_NOOP
    assert result.event_ids == applied.event_ids
    assert result.position_ids == applied.position_ids
    assert result.stats == OperationStats(2, 0, 0, 1, id(db.connection))
    assert scalar(db, "SELECT status FROM order_states") == "FILLED"
    assert scalar(db, "SELECT updated_at FROM order_states") == original_updated_at


def test_conflicting_fill_replay_is_rejected_without_mutation(tmp_path):
    db = make_db(tmp_path / "runtime.db")
    graph = seed_execution_graph(db, "fill-conflict")
    adapter = acknowledge(db, graph)
    original = fill_command(graph, "same-fill")
    adapter.apply_fill(original)
    before = db.connection.total_changes
    with pytest.raises(LifecycleConflictError) as caught:
        adapter.apply_fill(replace(original, quantity=Decimal("1.1")))
    assert caught.value.stats.read_statements == 1
    assert caught.value.stats.committed_mutations == 0
    assert db.connection.total_changes == before


def test_incomplete_replay_accounting_sequence_is_invariant_failure(tmp_path):
    db = make_db(tmp_path / "runtime.db")
    graph = seed_execution_graph(db, "incomplete")
    acknowledge(db, graph)
    command = fill_command(graph, "fill-incomplete")
    db.connection.execute("INSERT INTO fill_states VALUES (?,?,?,?,?,?,?,?,?,?)", (
        command.venue, command.account_scope, command.fill_id, command.order_id,
        command.symbol, "1", "100", "0.1", "USDT", "2026-01-01T00:01:00Z",
    ))
    db.connection.commit()
    with pytest.raises(LifecycleInvariantError) as caught:
        make_adapter(db).apply_fill(command)
    assert caught.value.stats == OperationStats(2, 0, 0, 1, id(db.connection))


def test_non_deterministic_replay_event_identity_is_rejected(tmp_path):
    db = make_db(tmp_path / "runtime.db")
    graph = seed_execution_graph(db, "bad-event")
    acknowledge(db, graph)
    command = fill_command(graph, "fill-bad-event")
    db.connection.execute("INSERT INTO fill_states VALUES (?,?,?,?,?,?,?,?,?,?)", (
        command.venue, command.account_scope, command.fill_id, command.order_id,
        command.symbol, "1", "100", "0.1", "USDT", "2026-01-01T00:01:00Z",
    ))
    db.connection.execute("INSERT INTO position_states VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", (
        "pos-bad", command.venue, command.account_scope, command.symbol,
        "LONG", "1", "100", "0", "0", "OPEN",
        "2026-01-01T00:01:00Z", None, "2026-01-01T00:02:00Z",
    ))
    db.connection.execute(
        "INSERT INTO position_accounting_details VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", (
            "not-deterministic", "pos-bad", command.venue, command.account_scope,
            command.fill_id, command.symbol, 1, "OPEN", "1", "100", "0.1", "0",
            "2026-01-01T00:01:00Z",
        )
    )
    db.connection.commit()
    with pytest.raises(LifecycleInvariantError):
        make_adapter(db).apply_fill(command)


def test_alternate_policy_position_identity_is_not_hardcoded_in_adapter(tmp_path):
    db = make_db(tmp_path / "alternate-policy.db")
    graph = seed_execution_graph(db, "alternate-policy")
    acknowledge(db, graph)
    adapter = SqliteLifecyclePersistence(db, AlternatePositionIdPolicy())
    result = adapter.apply_fill(fill_command(graph, "alternate-policy-fill"))
    assert result.outcome is PersistenceOutcome.APPLIED
    assert result.position_ids == ("policy-position-alternate-policy-fill",)
    assert scalar(db, "SELECT position_id FROM position_states") == result.position_ids[0]


@pytest.mark.parametrize("policy", [BadScopePolicy(), BadEventIdPolicy()])
def test_invalid_injected_policy_is_rejected_before_first_mutation(tmp_path, policy):
    db = make_db(tmp_path / f"{type(policy).__name__}.db")
    graph = seed_execution_graph(db, type(policy).__name__)
    acknowledge(db, graph)
    adapter = SqliteLifecyclePersistence(db, policy)
    with pytest.raises(LifecycleInvariantError) as caught:
        adapter.apply_fill(fill_command(graph, f"fill-{type(policy).__name__}"))
    assert caught.value.stats == OperationStats(3, 0, 0, 1, id(db.connection))
    assert scalar(db, "SELECT COUNT(*) FROM fill_states") == 0
    assert scalar(db, "SELECT COUNT(*) FROM position_states") == 0
    assert scalar(db, "SELECT COUNT(*) FROM position_accounting_details") == 0
    assert scalar(db, "SELECT status FROM order_states") == "OPEN"


def test_sqlite_constraint_failure_rolls_back_all_prior_mutations(tmp_path):
    db = make_db(tmp_path / "constraint.db")
    graph = seed_execution_graph(db, "constraint")
    adapter = acknowledge(db, graph)
    db.connection.execute("""
        CREATE TRIGGER test_reject_position_insert
        BEFORE INSERT ON position_states
        BEGIN SELECT RAISE(ABORT,'injected position constraint'); END
    """)
    db.connection.commit()
    with pytest.raises(LifecycleInvariantError) as caught:
        adapter.apply_fill(fill_command(graph, "constraint-fill"))
    assert caught.value.stats.attempted_mutations == 4
    assert caught.value.stats.committed_mutations == 0
    assert scalar(db, "SELECT COUNT(*) FROM fill_states") == 0
    assert scalar(db, "SELECT COUNT(*) FROM position_states") == 0
    assert scalar(db, "SELECT COUNT(*) FROM position_accounting_details") == 0
    assert scalar(db, "SELECT status FROM order_states") == "OPEN"


def test_wrong_order_symbol_fails_before_mutation(tmp_path):
    db = make_db(tmp_path / "runtime.db")
    graph = seed_execution_graph(db, "wrong-symbol")
    adapter = acknowledge(db, graph)
    with pytest.raises(LifecyclePreconditionError) as caught:
        adapter.apply_fill(fill_command(graph, "fill-wrong", symbol="ETH/USDT"))
    assert caught.value.stats.attempted_mutations == 0
    assert scalar(db, "SELECT COUNT(*) FROM fill_states") == 0


def test_invalid_order_status_transition_fails_before_mutation(tmp_path):
    db = make_db(tmp_path / "runtime.db")
    graph = seed_execution_graph(db, "bad-status")
    adapter = acknowledge(db, graph)
    db.connection.execute("UPDATE order_states SET status='FILLED'")
    db.connection.commit()
    with pytest.raises(LifecyclePreconditionError) as caught:
        adapter.apply_fill(fill_command(graph, "after-filled"))
    assert caught.value.stats.attempted_mutations == 0
    assert scalar(db, "SELECT COUNT(*) FROM fill_states") == 0


@pytest.mark.parametrize("boundary", [
    "fill.fill_insert", "fill.order_update",
    "fill.accounting_event_1", "fill.position_1_insert",
])
def test_one_event_fill_failure_after_each_boundary_fully_rolls_back(tmp_path, boundary):
    db = make_db(tmp_path / f"{boundary}.db")
    graph = seed_execution_graph(db, boundary)
    acknowledge(db, graph)
    adapter = FailingAdapter(db, NettingPositionAccountingV1(), boundary)
    with pytest.raises(LifecycleInvariantError) as caught:
        adapter.apply_fill(fill_command(graph, f"fill-{boundary}"))
    assert caught.value.stats.committed_mutations == 0
    assert scalar(db, "SELECT COUNT(*) FROM fill_states") == 0
    assert scalar(db, "SELECT COUNT(*) FROM position_states") == 0
    assert scalar(db, "SELECT COUNT(*) FROM position_accounting_details") == 0
    assert scalar(db, "SELECT status FROM order_states") == "OPEN"


def test_same_connection_reused_across_hot_path_operations(tmp_path):
    db = make_db(tmp_path / "runtime.db")
    graph = seed_execution_graph(db, "connection")
    adapter = make_adapter(db)
    identity = id(db.connection)
    ack = adapter.register_order_acknowledgement(order_command(graph))
    fill = adapter.apply_fill(fill_command(graph, "connection-fill"))
    assert id(db.connection) == identity
    assert ack.stats.db_connection_identity == identity
    assert fill.stats.db_connection_identity == identity


def _concurrent_apply(path, command, barrier, output) -> None:
    db = RuntimeDatabase(path)
    try:
        db.connect()
        adapter = make_adapter(db)
        barrier.wait(timeout=10)
        try:
            output.put(("result", adapter.apply_fill(command).outcome))
        except LifecyclePersistenceError as exc:
            output.put(("error", type(exc), exc.stats))
    finally:
        db.close()


def _prepare_concurrent_db(path: Path, suffix: str) -> dict[str, str]:
    db = make_db(path)
    graph = seed_execution_graph(db, suffix)
    acknowledge(db, graph)
    db.close()
    return graph


def _run_two_threads(path, commands):
    barrier = threading.Barrier(2)
    output: queue.Queue = queue.Queue()
    threads = [
        threading.Thread(target=_concurrent_apply, args=(path, command, barrier, output))
        for command in commands
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=20)
        assert not thread.is_alive()
    return [output.get_nowait() for _ in range(2)]


def test_two_connection_concurrent_exact_duplicate_converges(tmp_path):
    path = tmp_path / "concurrent.db"
    graph = _prepare_concurrent_db(path, "concurrent-same")
    command = fill_command(graph, "concurrent-fill")
    results = _run_two_threads(path, [command, command])
    outcomes = sorted(item[1].value for item in results if item[0] == "result")
    assert outcomes == ["APPLIED", "REPLAY_NOOP"]


def test_two_connection_concurrent_conflict_is_one_applied_one_conflict(tmp_path):
    path = tmp_path / "concurrent-conflict.db"
    graph = _prepare_concurrent_db(path, "concurrent-conflict")
    results = _run_two_threads(path, [
        fill_command(graph, "same-id", quantity=Decimal("1")),
        fill_command(graph, "same-id", quantity=Decimal("1.25")),
    ])
    assert sum(1 for item in results
               if item[0] == "result" and item[1] is PersistenceOutcome.APPLIED) == 1
    assert sum(1 for item in results
               if item[0] == "error" and item[1] is LifecycleConflictError) == 1


def test_module_has_no_forbidden_hot_path_dependencies():
    source = inspect.getsource(persistence_module)
    tree = ast.parse(source)
    imported_roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_roots.update(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_roots.add(node.module.split(".", 1)[0])
    assert imported_roots.isdisjoint(
        {"sqlalchemy", "requests", "httpx", "urllib3", "aiohttp", "json"}
    )
    lowered = source.lower()
    assert "http://" not in lowered
    assert "https://" not in lowered
    assert "connect(" not in inspect.getsource(
        SqliteLifecyclePersistence.register_order_acknowledgement
    )
    assert "connect(" not in inspect.getsource(SqliteLifecyclePersistence.apply_fill)
