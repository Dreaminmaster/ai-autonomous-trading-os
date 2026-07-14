"""B5D2 deterministic paper adapter and replay-safe orchestration tests."""
from __future__ import annotations

import ast
import hashlib
import inspect
import pathlib
import sqlite3
import tempfile
import threading
from dataclasses import replace
from datetime import datetime, timezone
from decimal import Decimal

import pytest

import atos.paper_execution_adapter as adapter_module
from atos.execution_idempotency_repository import (
    SqliteExecutionIdempotencyRepository,
)
from atos.execution_idempotency_types import (
    DispatchCommitCommand,
    ExecutionIdempotencyCommand,
    ExecutionIdempotencyValidationError,
    derive_attempt_id,
    derive_client_order_id,
)
from atos.execution_outcome_repository import (
    DispatchAmbiguousCommand,
    DispatchRejectedCommand,
    DispatchSubmittedCommand,
    SqliteExecutionOutcomeRepository,
)
from atos.lifecycle_types import (
    DispatchAttemptStatus,
    ExecutionStatus,
    LifecycleConflictError,
    OrderSide,
    PersistenceOutcome,
    decimal_text,
    utc_text,
)
from atos.paper_execution_adapter import (
    LIVE,
    DeterministicPaperExecutionAdapter,
    PaperExecutionConfig,
    PaperExecutionEnvelope,
    PaperExecutionOutcome,
    SqlitePaperExecutionCoordinator,
    derive_paper_fill_id,
    derive_paper_order_id,
)
from atos.position_accounting import NettingPositionAccountingV1
from atos.runtime_db import RuntimeDatabase
from atos.runtime_migrations import MIGRATION_PLAN, MigrationManager

T0 = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)
T1 = datetime(2026, 1, 1, 0, 1, tzinfo=timezone.utc)
T2 = datetime(2026, 1, 1, 0, 2, tzinfo=timezone.utc)
T3 = datetime(2026, 1, 1, 0, 3, tzinfo=timezone.utc)


class InjectedCrash(RuntimeError):
    pass


class CrashCoordinator(SqlitePaperExecutionCoordinator):
    def __init__(
        self,
        db: RuntimeDatabase,
        *,
        before: str | None = None,
        after: str | None = None,
    ) -> None:
        super().__init__(db, NettingPositionAccountingV1())
        self.before = before
        self.after = after

    def _before_step(self, step, plan) -> None:
        del plan
        if step == self.before:
            raise InjectedCrash(f"before:{step}")

    def _after_step(self, step, plan) -> None:
        del plan
        if step == self.after:
            raise InjectedCrash(f"after:{step}")


def make_db(path: pathlib.Path | None = None) -> RuntimeDatabase:
    target = path or pathlib.Path(tempfile.mkdtemp()) / "runtime.db"
    db = RuntimeDatabase(target)
    db.connect()
    MigrationManager(db, MIGRATION_PLAN).migrate()
    return db


def seed_execution(
    db: RuntimeDatabase,
    suffix: str = "1",
    *,
    symbol: str = "BTC/USDT",
    action: str = "BUY",
    decision: str = "APPROVED",
    normalized_intent_hash: str | None = None,
) -> dict[str, str]:
    normalized = normalized_intent_hash or hashlib.sha256(
        f"paper-intent-{suffix}".encode()
    ).hexdigest()
    graph = {
        "session_id": f"session-{suffix}",
        "cycle_id": f"cycle-{suffix}",
        "trade_intent_id": f"trade-{suffix}",
        "risk_decision_id": f"risk-{suffix}",
        "execution_intent_id": f"execution-{suffix}",
        "symbol": symbol,
        "action": action,
        "normalized_intent_hash": normalized,
    }
    connection = db.connection
    connection.execute(
        "INSERT INTO runtime_sessions VALUES (?,?,?,?,NULL,NULL)",
        (graph["session_id"], utc_text(T0), "paper", "RUNNING"),
    )
    connection.execute(
        "INSERT INTO runtime_cycles "
        "(cycle_id,session_id,symbol,started_at,status) VALUES (?,?,?,?,?)",
        (
            graph["cycle_id"],
            graph["session_id"],
            symbol,
            utc_text(T0),
            "CREATED",
        ),
    )
    connection.execute(
        "INSERT INTO trade_intents VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            graph["trade_intent_id"],
            symbol,
            action,
            "0.9",
            "paper thesis",
            "{}",
            "0.1",
            "0.02",
            "0.04",
            "[]",
            "[]",
            utc_text(T0),
        ),
    )
    connection.execute(
        "INSERT INTO risk_decisions VALUES (?,?,?,?,?,?,?)",
        (
            graph["risk_decision_id"],
            graph["trade_intent_id"],
            decision,
            "[]",
            "0.1",
            "{}",
            utc_text(T0),
        ),
    )
    connection.execute(
        "INSERT INTO execution_intents VALUES (?,?,?,?,?,?,?,?,?)",
        (
            graph["execution_intent_id"],
            graph["trade_intent_id"],
            graph["risk_decision_id"],
            graph["cycle_id"],
            symbol,
            action,
            "250",
            normalized,
            utc_text(T0),
        ),
    )
    connection.commit()
    return graph


def claim_execution(
    db: RuntimeDatabase,
    graph: dict[str, str],
):
    repository = SqliteExecutionIdempotencyRepository(db)
    return repository.claim_execution(
        ExecutionIdempotencyCommand(
            execution_intent_id=graph["execution_intent_id"],
            venue="okx_paper",
            account_scope="spot-main",
            symbol=graph["symbol"],
            action=OrderSide(graph["action"]),
            normalized_intent_hash=graph["normalized_intent_hash"],
            created_at=T0,
        )
    )


def prepare_dispatch(
    db: RuntimeDatabase,
    graph: dict[str, str] | None = None,
) -> tuple[dict[str, str], PaperExecutionEnvelope]:
    graph = graph or seed_execution(db)
    claimed = claim_execution(db, graph)
    committed = SqliteExecutionIdempotencyRepository(db).commit_dispatch(
        DispatchCommitCommand(graph["execution_intent_id"], T1)
    )
    envelope = PaperExecutionEnvelope(
        execution_intent_id=graph["execution_intent_id"],
        idempotency_key=claimed.claim.idempotency_key,
        attempt_id=committed.attempt_id,
        client_order_id=claimed.claim.client_order_id,
        venue=claimed.claim.venue,
        account_scope=claimed.claim.account_scope,
        symbol=claimed.claim.symbol,
        side=claimed.claim.action,
        quantity=Decimal("2.5"),
        mark_price=Decimal("100"),
        fee_currency="USDT",
        observed_at=T2,
    )
    return graph, envelope


def coordinator(
    db: RuntimeDatabase,
    config: PaperExecutionConfig | None = None,
) -> SqlitePaperExecutionCoordinator:
    return SqlitePaperExecutionCoordinator(
        db,
        NettingPositionAccountingV1(),
        config,
    )


def count(db: RuntimeDatabase, table: str) -> int:
    return db.connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


def authoritative_state(db: RuntimeDatabase, execution_intent_id: str):
    state = db.connection.execute(
        "SELECT status,last_attempt_id,retry_count FROM execution_states "
        "WHERE execution_intent_id=?",
        (execution_intent_id,),
    ).fetchone()
    attempt = db.connection.execute(
        "SELECT status,attempt_no FROM dispatch_attempts "
        "WHERE execution_intent_id=?",
        (execution_intent_id,),
    ).fetchone()
    return state, attempt


def test_frozen_deterministic_vector_and_commands() -> None:
    key = "0123456789abcdef" * 4
    client = "a50123456789abcdef0123456789ab"
    attempt = (
        "att_afe790ab80ee4ddfe393eeeeb803839ed995a2e4977a4682675a5f594e70657c"
    )
    envelope = PaperExecutionEnvelope(
        execution_intent_id="execution-vector",
        idempotency_key=key,
        attempt_id=attempt,
        client_order_id=client,
        venue="okx_paper",
        account_scope="spot-main",
        symbol="BTC/USDT",
        side=OrderSide.BUY,
        quantity=Decimal("2.5"),
        mark_price=Decimal("100"),
        fee_currency="USDT",
        observed_at=T2,
    )

    plan = DeterministicPaperExecutionAdapter().build(envelope)

    assert derive_client_order_id(key) == client
    assert derive_attempt_id(key, 1) == attempt
    assert plan.order_id == (
        "pord_b7931eac37dcb9638e3297a0d38ac2638007929b2efa644e488bbe6498949943"
    )
    assert plan.fill_id == (
        "pfill_2ead92c30d123e5c01cef53ced87339885b3590bf4a05f4bfe06ff0c12af1fe0"
    )
    assert plan.execution_price == Decimal("100.05")
    assert plan.fee == Decimal("0.250125")
    assert plan.order_command.order_id == plan.order_id
    assert plan.order_command.client_order_id == client
    assert plan.fill_command.fill_id == plan.fill_id
    assert plan.fill_command.order_status_after.value == "FILLED"
    assert plan.order_command.order_type.value == "MARKET"
    assert plan.order_command.acknowledged_at == T2
    assert plan.fill_command.occurred_at == T2
    assert plan.fill_command.recorded_at == T2
    assert plan == DeterministicPaperExecutionAdapter().build(envelope)


def test_sell_slippage_and_fee_are_decimal_deterministic() -> None:
    key = "f" * 64
    envelope = PaperExecutionEnvelope(
        "execution-sell",
        key,
        derive_attempt_id(key, 1),
        derive_client_order_id(key),
        "okx_paper",
        "spot-main",
        "ETH/USDT",
        OrderSide.SELL,
        Decimal("2.5"),
        Decimal("100"),
        "USDT",
        T2,
    )
    plan = DeterministicPaperExecutionAdapter().build(envelope)
    assert plan.execution_price == Decimal("99.95")
    assert plan.fee == Decimal("0.249875")


@pytest.mark.parametrize(
    "mutation",
    [
        {"attempt_id": "att_wrong"},
        {"client_order_id": "a5" + "0" * 28},
        {"idempotency_key": "A" * 64},
        {"venue": "okx_live"},
        {"quantity": Decimal("0")},
        {"mark_price": Decimal("0")},
    ],
)
def test_invalid_or_live_envelope_is_rejected(mutation: dict) -> None:
    key = "b" * 64
    envelope = PaperExecutionEnvelope(
        "execution-invalid",
        key,
        derive_attempt_id(key, 1),
        derive_client_order_id(key),
        "okx_paper",
        "spot-main",
        "BTC/USDT",
        OrderSide.BUY,
        Decimal("1"),
        Decimal("100"),
        "USDT",
        T2,
    )
    with pytest.raises(ExecutionIdempotencyValidationError):
        replace(envelope, **mutation)


@pytest.mark.parametrize(
    "config",
    [
        PaperExecutionConfig(fee_bps=Decimal("0"), slippage_bps=Decimal("0")),
        PaperExecutionConfig(fee_bps=Decimal("10000"), slippage_bps=Decimal("9999")),
    ],
)
def test_valid_config_boundaries(config: PaperExecutionConfig) -> None:
    assert DeterministicPaperExecutionAdapter(config)


@pytest.mark.parametrize(
    ("fee", "slippage"),
    [
        (Decimal("-1"), Decimal("0")),
        (Decimal("0"), Decimal("-1")),
        (Decimal("10001"), Decimal("0")),
        (Decimal("0"), Decimal("10000")),
        (Decimal("NaN"), Decimal("0")),
    ],
)
def test_invalid_config_is_rejected(fee: Decimal, slippage: Decimal) -> None:
    with pytest.raises(ExecutionIdempotencyValidationError):
        PaperExecutionConfig(fee_bps=fee, slippage_bps=slippage)


def test_full_paper_execution_reaches_one_filled_lifecycle() -> None:
    db = make_db()
    graph, envelope = prepare_dispatch(db)

    result = coordinator(db).execute(envelope)

    assert result.outcome is PaperExecutionOutcome.FILLED
    assert result.execution_status is ExecutionStatus.FILLED
    assert result.attempt_status is DispatchAttemptStatus.ACCEPTED
    assert result.dispatch_outcome is PersistenceOutcome.APPLIED
    assert result.order_outcome is PersistenceOutcome.APPLIED
    assert result.fill_outcome is PersistenceOutcome.APPLIED
    assert result.final_outcome is PersistenceOutcome.APPLIED
    assert count(db, "execution_idempotency_claims") == 1
    assert count(db, "dispatch_attempts") == 1
    assert count(db, "order_states") == 1
    assert count(db, "fill_states") == 1
    assert count(db, "position_states") == 1
    assert count(db, "position_accounting_details") == 1
    state, attempt = authoritative_state(db, graph["execution_intent_id"])
    assert state["status"] == "FILLED"
    assert state["retry_count"] == 0
    assert attempt["status"] == "ACCEPTED"
    assert attempt["attempt_no"] == 1


def test_complete_replay_is_zero_mutation_and_verifies_payload() -> None:
    db = make_db()
    _, envelope = prepare_dispatch(db)
    first = coordinator(db).execute(envelope)
    before = db.connection.total_changes

    replay = coordinator(db).execute(envelope)

    assert first.outcome is PaperExecutionOutcome.FILLED
    assert replay.outcome is PaperExecutionOutcome.TERMINAL_NOOP
    assert replay.order_outcome is PersistenceOutcome.REPLAY_NOOP
    assert replay.fill_outcome is PersistenceOutcome.REPLAY_NOOP
    assert replay.final_outcome is PersistenceOutcome.REPLAY_NOOP
    assert db.connection.total_changes == before
    assert count(db, "dispatch_attempts") == 1
    assert count(db, "order_states") == 1
    assert count(db, "fill_states") == 1
    assert count(db, "position_accounting_details") == 1


@pytest.mark.parametrize(
    ("before", "after"),
    [
        ("mark_dispatched", None),
        (None, "mark_dispatched"),
        (None, "order_acknowledgement"),
        (None, "fill_application"),
        (None, "mark_filled"),
    ],
)
def test_restart_after_every_inter_step_crash_completes_once(
    before: str | None,
    after: str | None,
) -> None:
    db = make_db()
    graph, envelope = prepare_dispatch(db)

    with pytest.raises(InjectedCrash):
        CrashCoordinator(db, before=before, after=after).execute(envelope)

    result = coordinator(db).execute(envelope)

    assert result.execution_status is ExecutionStatus.FILLED
    assert count(db, "dispatch_attempts") == 1
    assert count(db, "order_states") == 1
    assert count(db, "fill_states") == 1
    assert count(db, "position_accounting_details") == 1
    state, attempt = authoritative_state(db, graph["execution_intent_id"])
    assert state["status"] == "FILLED"
    assert attempt["status"] == "ACCEPTED"


def test_prepared_execution_returns_safe_commit_without_side_effect() -> None:
    db = make_db()
    graph = seed_execution(db)
    claimed = claim_execution(db, graph)
    key = claimed.claim.idempotency_key
    envelope = PaperExecutionEnvelope(
        graph["execution_intent_id"],
        key,
        derive_attempt_id(key, 1),
        claimed.claim.client_order_id,
        claimed.claim.venue,
        claimed.claim.account_scope,
        graph["symbol"],
        OrderSide.BUY,
        Decimal("1"),
        Decimal("100"),
        "USDT",
        T2,
    )

    result = coordinator(db).execute(envelope)

    assert result.outcome is PaperExecutionOutcome.SAFE_COMMIT_DISPATCH
    assert result.execution_status is ExecutionStatus.PREPARED
    assert result.attempt_status is None
    assert count(db, "dispatch_attempts") == 0
    assert count(db, "order_states") == 0


def test_unavailable_reconciliation_pauses_without_mutation() -> None:
    db = make_db()
    _, envelope = prepare_dispatch(db)
    before = db.connection.total_changes

    result = coordinator(db).execute(
        envelope,
        reconciliation_available=False,
    )

    assert result.outcome is PaperExecutionOutcome.PAUSE_RECOVERY
    assert result.execution_status is ExecutionStatus.DISPATCH_COMMITTED
    assert db.connection.total_changes == before
    assert count(db, "order_states") == 0


def test_ambiguous_execution_requires_reconciliation_and_does_not_fill() -> None:
    db = make_db()
    graph, envelope = prepare_dispatch(db)
    SqliteExecutionOutcomeRepository(db).mark_ambiguous(
        DispatchAmbiguousCommand(
            graph["execution_intent_id"],
            envelope.attempt_id,
            DispatchAttemptStatus.TIMEOUT,
            T3,
            "PaperTransportTimeout",
        )
    )
    before = db.connection.total_changes

    result = coordinator(db).execute(envelope)

    assert result.outcome is PaperExecutionOutcome.RECONCILE_REQUIRED
    assert result.execution_status is ExecutionStatus.AMBIGUOUS
    assert result.attempt_status is DispatchAttemptStatus.TIMEOUT
    assert db.connection.total_changes == before
    assert count(db, "order_states") == 0
    assert count(db, "fill_states") == 0


def test_terminal_rejection_is_terminal_noop_without_fabricated_lifecycle() -> None:
    db = make_db()
    graph, envelope = prepare_dispatch(db)
    outcomes = SqliteExecutionOutcomeRepository(db)
    outcomes.mark_dispatched(
        DispatchSubmittedCommand(graph["execution_intent_id"], envelope.attempt_id, T2)
    )
    outcomes.mark_terminal_rejection(
        DispatchRejectedCommand(
            graph["execution_intent_id"],
            envelope.attempt_id,
            T3,
            "PaperDeterministicRejection",
        )
    )

    result = coordinator(db).execute(envelope)

    assert result.outcome is PaperExecutionOutcome.TERMINAL_NOOP
    assert result.execution_status is ExecutionStatus.TERMINAL
    assert result.attempt_status is DispatchAttemptStatus.REJECTED
    assert count(db, "order_states") == 0
    assert count(db, "fill_states") == 0


def test_contradictory_dispatched_order_authority_pauses() -> None:
    db = make_db()
    graph, envelope = prepare_dispatch(db)
    outcomes = SqliteExecutionOutcomeRepository(db)
    outcomes.mark_dispatched(
        DispatchSubmittedCommand(graph["execution_intent_id"], envelope.attempt_id, T2)
    )
    plan = DeterministicPaperExecutionAdapter().build(envelope)
    command = plan.order_command
    db.connection.execute(
        "INSERT INTO order_states "
        "(venue,account_scope,order_id,execution_intent_id,attempt_id,"
        "client_order_id,symbol,side,quantity,price,order_type,status,"
        "created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            command.venue,
            command.account_scope,
            command.order_id,
            command.execution_intent_id,
            command.attempt_id,
            command.client_order_id,
            command.symbol,
            command.side.value,
            decimal_text(command.quantity),
            decimal_text(command.price),
            command.order_type.value,
            "OPEN",
            utc_text(command.acknowledged_at),
            utc_text(command.acknowledged_at),
        ),
    )
    db.connection.commit()
    before = db.connection.total_changes

    result = coordinator(db).execute(envelope)

    assert result.outcome is PaperExecutionOutcome.PAUSE_RECOVERY
    assert result.execution_status is ExecutionStatus.DISPATCHED
    assert db.connection.total_changes == before
    assert count(db, "fill_states") == 0


def test_changed_fee_config_on_terminal_replay_fails_closed() -> None:
    db = make_db()
    _, envelope = prepare_dispatch(db)
    coordinator(db).execute(envelope)

    with pytest.raises(LifecycleConflictError):
        coordinator(
            db,
            PaperExecutionConfig(
                fee_bps=Decimal("20"),
                slippage_bps=Decimal("5"),
            ),
        ).execute(envelope)

    assert count(db, "fill_states") == 1
    assert count(db, "position_accounting_details") == 1


def test_two_connections_racing_produce_one_lifecycle() -> None:
    directory = pathlib.Path(tempfile.mkdtemp())
    path = directory / "runtime.db"
    setup = make_db(path)
    graph, envelope = prepare_dispatch(setup)
    setup.close()
    barrier = threading.Barrier(2)
    results = []
    errors = []
    lock = threading.Lock()

    def worker() -> None:
        local = RuntimeDatabase(path)
        try:
            local.connect()
            instance = coordinator(local)
            barrier.wait(timeout=10)
            result = instance.execute(envelope)
            with lock:
                results.append(result)
        except BaseException as exc:
            with lock:
                errors.append(exc)
        finally:
            local.close()

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=20)

    assert not errors
    assert len(results) == 2
    verify = make_db(path)
    assert count(verify, "dispatch_attempts") == 1
    assert count(verify, "order_states") == 1
    assert count(verify, "fill_states") == 1
    assert count(verify, "position_accounting_details") == 1
    state, attempt = authoritative_state(verify, graph["execution_intent_id"])
    assert state["status"] == "FILLED"
    assert attempt["status"] == "ACCEPTED"


def test_derived_id_helpers_are_scope_separated() -> None:
    client = "a5" + "1" * 28
    order = derive_paper_order_id(
        venue="okx_paper",
        account_scope="spot-main",
        client_order_id=client,
    )
    fill = derive_paper_fill_id(
        venue="okx_paper",
        account_scope="spot-main",
        client_order_id=client,
    )
    assert order.startswith("pord_")
    assert fill.startswith("pfill_")
    assert order != fill
    assert order != derive_paper_order_id(
        venue="okx_paper",
        account_scope="spot-alt",
        client_order_id=client,
    )


def test_source_has_no_legacy_executor_or_forbidden_io_imports() -> None:
    source = inspect.getsource(adapter_module)
    tree = ast.parse(source)
    imported_roots = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_roots.add(node.module.split(".")[0])
    assert not imported_roots.intersection(
        {
            "ccxt",
            "httpx",
            "os",
            "random",
            "requests",
            "secrets",
            "socket",
            "subprocess",
            "time",
            "urllib",
            "uuid",
        }
    )
    assert "paper_executor" not in source
    assert "new_id(" not in source
    assert "utc_now(" not in source
    assert LIVE == "FORBIDDEN"
