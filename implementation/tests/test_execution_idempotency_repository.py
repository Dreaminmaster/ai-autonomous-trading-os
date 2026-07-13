"""B5C atomic execution claim and dispatch repository contract tests."""
from __future__ import annotations

import ast
import hashlib
import inspect
import pathlib
import sqlite3
import tempfile
import threading
from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

import atos.execution_idempotency_repository as repository_module
from atos.execution_idempotency_repository import (
    SqliteExecutionIdempotencyRepository,
)
from atos.execution_idempotency_types import (
    DispatchCommitCommand,
    ExecutionClaimResult,
    ExecutionIdempotencyCommand,
    ExecutionIdempotencyConflictError,
    ExecutionIdempotencyInvariantError,
    ExecutionIdempotencyOutcome,
    ExecutionIdempotencyPreconditionError,
    derive_attempt_id,
    derive_client_order_id,
)
from atos.lifecycle_types import (
    DispatchAttemptStatus,
    ExecutionStatus,
    OrderSide,
)
from atos.runtime_db import RuntimeDatabase
from atos.runtime_migrations import MIGRATION_PLAN, MigrationManager

T0 = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)
T1 = datetime(2026, 1, 1, 0, 1, tzinfo=timezone.utc)


class InjectedCrash(RuntimeError):
    pass


class CrashRepository(SqliteExecutionIdempotencyRepository):
    def __init__(self, db: RuntimeDatabase, boundary: str) -> None:
        super().__init__(db)
        self.boundary = boundary

    def _after_mutation(self, boundary: str, connection: sqlite3.Connection) -> None:
        del connection
        if boundary == self.boundary:
            raise InjectedCrash(boundary)


def make_db(path: pathlib.Path | None = None) -> RuntimeDatabase:
    db = RuntimeDatabase(path or pathlib.Path(tempfile.mkdtemp()) / "runtime.db")
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
        "normalized_intent_hash": normalized,
    }
    connection = db.connection
    connection.execute(
        "INSERT INTO runtime_sessions VALUES (?,?,?,?,NULL,NULL)",
        (graph["session_id"], "2026-01-01T00:00:00Z", "paper", "RUNNING"),
    )
    connection.execute(
        "INSERT INTO runtime_cycles "
        "(cycle_id,session_id,symbol,started_at,status) VALUES (?,?,?,?,?)",
        (
            graph["cycle_id"],
            graph["session_id"],
            symbol,
            "2026-01-01T00:00:00Z",
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
    connection.execute(
        "INSERT INTO risk_decisions VALUES (?,?,?,?,?,?,?)",
        (
            graph["risk_decision_id"],
            graph["trade_intent_id"],
            decision,
            "[]",
            "0.1",
            "{}",
            "2026-01-01T00:00:00Z",
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
            "100",
            normalized,
            "2026-01-01T00:00:00Z",
        ),
    )
    connection.commit()
    return graph


def claim_command(
    graph: dict[str, str],
    *,
    venue: str = "okx_paper",
    account_scope: str = "spot-main",
    created_at: datetime = T0,
) -> ExecutionIdempotencyCommand:
    return ExecutionIdempotencyCommand(
        execution_intent_id=graph["execution_intent_id"],
        venue=venue,
        account_scope=account_scope,
        symbol=graph["symbol"],
        action=OrderSide(graph["action"]),
        normalized_intent_hash=graph["normalized_intent_hash"],
        created_at=created_at,
    )


def row_count(db: RuntimeDatabase, table: str) -> int:
    return db.connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


def insert_claim_only(
    db: RuntimeDatabase,
    command: ExecutionIdempotencyCommand,
    *,
    idempotency_key: str | None = None,
    client_order_id: str | None = None,
    created_at: str = "2026-01-01T00:00:00Z",
) -> None:
    key = idempotency_key or command.idempotency_key
    client = client_order_id or derive_client_order_id(key)
    db.connection.execute(
        "INSERT INTO execution_idempotency_claims VALUES (?,?,?,?,?,?,?,?,?)",
        (
            key,
            command.execution_intent_id,
            command.venue,
            command.account_scope,
            command.symbol,
            command.action.value,
            command.normalized_intent_hash,
            client,
            created_at,
        ),
    )
    db.connection.commit()


def test_repository_requires_connected_runtime_database() -> None:
    path = pathlib.Path(tempfile.mkdtemp()) / "runtime.db"
    with pytest.raises(Exception):
        SqliteExecutionIdempotencyRepository(RuntimeDatabase(path))


def test_first_claim_atomically_creates_claim_and_prepared_state() -> None:
    db = make_db()
    graph = seed_execution(db)
    repository = SqliteExecutionIdempotencyRepository(db)
    before = db.connection.total_changes

    result = repository.claim_execution(claim_command(graph))

    assert type(result) is ExecutionClaimResult
    assert result.outcome is ExecutionIdempotencyOutcome.CLAIMED
    assert result.execution_status is ExecutionStatus.PREPARED
    assert result.claim.execution_intent_id == graph["execution_intent_id"]
    assert result.claim.client_order_id == derive_client_order_id(
        result.claim.idempotency_key
    )
    assert db.connection.total_changes - before == 2
    assert row_count(db, "execution_idempotency_claims") == 1
    assert row_count(db, "execution_states") == 1
    assert row_count(db, "dispatch_attempts") == 0
    state = db.connection.execute("SELECT * FROM execution_states").fetchone()
    assert state["status"] == "PREPARED"
    assert state["last_attempt_id"] is None
    assert state["retry_count"] == 0


def test_prepared_replay_is_zero_mutation_and_ignores_new_timestamp() -> None:
    db = make_db()
    graph = seed_execution(db)
    repository = SqliteExecutionIdempotencyRepository(db)
    first = repository.claim_execution(claim_command(graph, created_at=T0))
    before = db.connection.total_changes

    replay = repository.claim_execution(claim_command(graph, created_at=T1))

    assert replay.outcome is ExecutionIdempotencyOutcome.REPLAY_PREPARED
    assert replay.execution_status is ExecutionStatus.PREPARED
    assert replay.claim == first.claim
    assert replay.claim.created_at == T0
    assert db.connection.total_changes == before


@pytest.mark.parametrize(
    ("state_status", "attempt_status", "expected"),
    [
        ("DISPATCH_COMMITTED", "PRE_DISPATCH_PROVEN", "RECONCILE_REQUIRED"),
        ("DISPATCHED", "SUBMITTED", "RECONCILE_REQUIRED"),
        ("ACKNOWLEDGED", "ACCEPTED", "RECONCILE_REQUIRED"),
        ("AMBIGUOUS", "TIMEOUT", "RECONCILE_REQUIRED"),
        ("FILLED", "ACCEPTED", "TERMINAL_NOOP"),
        ("TERMINAL", "REJECTED", "TERMINAL_NOOP"),
    ],
)
def test_post_dispatch_replay_mapping(
    state_status: str,
    attempt_status: str,
    expected: str,
) -> None:
    db = make_db()
    graph = seed_execution(db)
    repository = SqliteExecutionIdempotencyRepository(db)
    repository.claim_execution(claim_command(graph))
    repository.commit_dispatch(
        DispatchCommitCommand(graph["execution_intent_id"], T1)
    )
    db.connection.execute(
        "UPDATE dispatch_attempts SET status=?",
        (attempt_status,),
    )
    db.connection.execute(
        "UPDATE execution_states SET status=?,updated_at=?",
        (state_status, "2026-01-01T00:02:00Z"),
    )
    db.connection.commit()

    replay = repository.claim_execution(claim_command(graph))

    assert replay.outcome.value == expected
    assert replay.execution_status.value == state_status
    assert row_count(db, "dispatch_attempts") == 1


@pytest.mark.parametrize("decision", ["REJECTED", "KILL_SWITCH_ACTIVE", "PAUSED"])
def test_non_approved_risk_writes_nothing(decision: str) -> None:
    db = make_db()
    graph = seed_execution(db, decision=decision)
    repository = SqliteExecutionIdempotencyRepository(db)

    with pytest.raises(ExecutionIdempotencyPreconditionError):
        repository.claim_execution(claim_command(graph))

    assert row_count(db, "execution_idempotency_claims") == 0
    assert row_count(db, "execution_states") == 0


def test_missing_parent_writes_nothing() -> None:
    db = make_db()
    command = ExecutionIdempotencyCommand(
        "missing",
        "okx_paper",
        "spot-main",
        "BTC/USDT",
        OrderSide.BUY,
        "a" * 64,
        T0,
    )
    with pytest.raises(ExecutionIdempotencyPreconditionError):
        SqliteExecutionIdempotencyRepository(db).claim_execution(command)
    assert row_count(db, "execution_idempotency_claims") == 0


@pytest.mark.parametrize(
    "mutation",
    [
        {"symbol": "ETH/USDT"},
        {"action": OrderSide.SELL},
        {"normalized_intent_hash": "b" * 64},
    ],
)
def test_parent_semantic_mismatch_writes_nothing(mutation: dict) -> None:
    db = make_db()
    graph = seed_execution(db)
    command = claim_command(graph)
    command = replace(command, **mutation)
    with pytest.raises(ExecutionIdempotencyConflictError):
        SqliteExecutionIdempotencyRepository(db).claim_execution(command)
    assert row_count(db, "execution_idempotency_claims") == 0
    assert row_count(db, "execution_states") == 0


def test_same_semantic_key_different_execution_intent_conflicts() -> None:
    db = make_db()
    shared_hash = "c" * 64
    first_graph = seed_execution(db, "1", normalized_intent_hash=shared_hash)
    second_graph = seed_execution(db, "2", normalized_intent_hash=shared_hash)
    repository = SqliteExecutionIdempotencyRepository(db)
    repository.claim_execution(claim_command(first_graph))

    with pytest.raises(ExecutionIdempotencyConflictError):
        repository.claim_execution(claim_command(second_graph))

    assert row_count(db, "execution_idempotency_claims") == 1
    assert row_count(db, "execution_states") == 1


def test_same_execution_intent_different_key_conflicts() -> None:
    db = make_db()
    graph = seed_execution(db)
    repository = SqliteExecutionIdempotencyRepository(db)
    repository.claim_execution(claim_command(graph, account_scope="spot-main"))

    with pytest.raises(ExecutionIdempotencyConflictError):
        repository.claim_execution(claim_command(graph, account_scope="spot-alt"))

    assert row_count(db, "execution_idempotency_claims") == 1


def test_state_without_claim_is_invariant_failure() -> None:
    db = make_db()
    graph = seed_execution(db)
    db.connection.execute(
        "INSERT INTO execution_states VALUES (?,?,?,?,?,?)",
        (
            graph["execution_intent_id"],
            "PREPARED",
            None,
            0,
            "2026-01-01T00:00:00Z",
            "2026-01-01T00:00:00Z",
        ),
    )
    db.connection.commit()

    with pytest.raises(ExecutionIdempotencyInvariantError):
        SqliteExecutionIdempotencyRepository(db).claim_execution(claim_command(graph))


def test_claim_without_state_is_invariant_failure() -> None:
    db = make_db()
    graph = seed_execution(db)
    command = claim_command(graph)
    insert_claim_only(db, command)

    with pytest.raises(ExecutionIdempotencyInvariantError):
        SqliteExecutionIdempotencyRepository(db).claim_execution(command)


def test_corrupt_stored_derived_key_fails_closed() -> None:
    db = make_db()
    graph = seed_execution(db)
    command = claim_command(graph)
    corrupt_client_order_id = "a5" + "0" * 28
    insert_claim_only(
        db,
        command,
        client_order_id=corrupt_client_order_id,
    )

    with pytest.raises(ExecutionIdempotencyInvariantError):
        SqliteExecutionIdempotencyRepository(db).claim_execution(command)


def test_invalid_persisted_claim_timestamp_fails_closed() -> None:
    db = make_db()
    graph = seed_execution(db)
    command = claim_command(graph)
    insert_claim_only(db, command, created_at="not-a-time")

    with pytest.raises(ExecutionIdempotencyInvariantError):
        SqliteExecutionIdempotencyRepository(db).claim_execution(command)


@pytest.mark.parametrize("boundary", ["claim_inserted", "prepared_state_inserted"])
def test_injected_claim_crash_rolls_back_all_rows(boundary: str) -> None:
    db = make_db()
    graph = seed_execution(db)

    with pytest.raises(InjectedCrash):
        CrashRepository(db, boundary).claim_execution(claim_command(graph))

    assert row_count(db, "execution_idempotency_claims") == 0
    assert row_count(db, "execution_states") == 0
    assert row_count(db, "dispatch_attempts") == 0


def test_commit_dispatch_atomically_persists_attempt_and_state() -> None:
    db = make_db()
    graph = seed_execution(db)
    repository = SqliteExecutionIdempotencyRepository(db)
    claim = repository.claim_execution(claim_command(graph))
    before = db.connection.total_changes

    result = repository.commit_dispatch(
        DispatchCommitCommand(graph["execution_intent_id"], T1)
    )

    assert result.attempt_id == derive_attempt_id(claim.claim.idempotency_key, 1)
    assert result.client_order_id == claim.claim.client_order_id
    assert result.attempt_no == 1
    assert result.attempt_status is DispatchAttemptStatus.PRE_DISPATCH_PROVEN
    assert result.execution_status is ExecutionStatus.DISPATCH_COMMITTED
    assert db.connection.total_changes - before == 2
    attempt = db.connection.execute("SELECT * FROM dispatch_attempts").fetchone()
    assert attempt["status"] == "PRE_DISPATCH_PROVEN"
    assert attempt["dispatch_started_at"] is None
    assert attempt["response_received_at"] is None
    assert attempt["error_class"] is None
    state = db.connection.execute("SELECT * FROM execution_states").fetchone()
    assert state["status"] == "DISPATCH_COMMITTED"
    assert state["last_attempt_id"] == result.attempt_id
    assert state["retry_count"] == 0


def test_commit_without_claim_fails_closed() -> None:
    db = make_db()
    graph = seed_execution(db)
    with pytest.raises(ExecutionIdempotencyPreconditionError):
        SqliteExecutionIdempotencyRepository(db).commit_dispatch(
            DispatchCommitCommand(graph["execution_intent_id"], T1)
        )
    assert row_count(db, "dispatch_attempts") == 0


def test_second_commit_requires_reconciliation_and_creates_no_second_attempt() -> None:
    db = make_db()
    graph = seed_execution(db)
    repository = SqliteExecutionIdempotencyRepository(db)
    repository.claim_execution(claim_command(graph))
    repository.commit_dispatch(
        DispatchCommitCommand(graph["execution_intent_id"], T1)
    )

    with pytest.raises(ExecutionIdempotencyPreconditionError):
        repository.commit_dispatch(
            DispatchCommitCommand(graph["execution_intent_id"], T1 + timedelta(minutes=1))
        )

    assert row_count(db, "dispatch_attempts") == 1


def test_prepared_state_with_attempt_is_invariant_failure() -> None:
    db = make_db()
    graph = seed_execution(db)
    repository = SqliteExecutionIdempotencyRepository(db)
    claim = repository.claim_execution(claim_command(graph)).claim
    attempt_id = derive_attempt_id(claim.idempotency_key, 1)
    db.connection.execute(
        "INSERT INTO dispatch_attempts VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (
            attempt_id,
            graph["execution_intent_id"],
            claim.client_order_id,
            claim.venue,
            claim.account_scope,
            "PRE_DISPATCH_PROVEN",
            1,
            "2026-01-01T00:01:00Z",
            None,
            None,
            None,
        ),
    )
    db.connection.commit()

    with pytest.raises(ExecutionIdempotencyInvariantError):
        repository.commit_dispatch(
            DispatchCommitCommand(graph["execution_intent_id"], T1)
        )


@pytest.mark.parametrize(
    "boundary", ["dispatch_attempt_inserted", "dispatch_state_committed"]
)
def test_injected_dispatch_crash_rolls_back_attempt_and_state(boundary: str) -> None:
    db = make_db()
    graph = seed_execution(db)
    setup_repository = SqliteExecutionIdempotencyRepository(db)
    setup_repository.claim_execution(claim_command(graph))

    with pytest.raises(InjectedCrash):
        CrashRepository(db, boundary).commit_dispatch(
            DispatchCommitCommand(graph["execution_intent_id"], T1)
        )

    assert row_count(db, "dispatch_attempts") == 0
    state = db.connection.execute("SELECT * FROM execution_states").fetchone()
    assert state["status"] == "PREPARED"
    assert state["last_attempt_id"] is None


def test_post_dispatch_state_without_attempt_is_invariant_failure() -> None:
    db = make_db()
    graph = seed_execution(db)
    repository = SqliteExecutionIdempotencyRepository(db)
    repository.claim_execution(claim_command(graph))
    db.connection.execute(
        "UPDATE execution_states SET status='DISPATCH_COMMITTED',updated_at=?",
        ("2026-01-01T00:01:00Z",),
    )
    db.connection.commit()

    with pytest.raises(ExecutionIdempotencyInvariantError):
        repository.claim_execution(claim_command(graph))


def test_nonzero_retry_count_is_invariant_failure() -> None:
    db = make_db()
    graph = seed_execution(db)
    repository = SqliteExecutionIdempotencyRepository(db)
    repository.claim_execution(claim_command(graph))
    db.connection.execute("UPDATE execution_states SET retry_count=1")
    db.connection.commit()

    with pytest.raises(ExecutionIdempotencyInvariantError):
        repository.claim_execution(claim_command(graph))


def test_replaced_connection_fails_before_mutation() -> None:
    db = make_db()
    graph = seed_execution(db)
    repository = SqliteExecutionIdempotencyRepository(db)
    db.close()
    db.connect()

    with pytest.raises(ExecutionIdempotencyPreconditionError):
        repository.claim_execution(claim_command(graph))


def test_database_busy_maps_to_fail_closed_precondition() -> None:
    path = pathlib.Path(tempfile.mkdtemp()) / "runtime.db"
    seed_db = make_db(path)
    graph = seed_execution(seed_db)
    seed_db.close()

    holder = RuntimeDatabase(path)
    holder.connect()
    blocked = RuntimeDatabase(path)
    blocked.connect()
    blocked.connection.execute("PRAGMA busy_timeout=1")
    holder.connection.execute("BEGIN IMMEDIATE")
    try:
        with pytest.raises(ExecutionIdempotencyPreconditionError):
            SqliteExecutionIdempotencyRepository(blocked).claim_execution(
                claim_command(graph)
            )
    finally:
        holder.connection.rollback()
        holder.close()
        blocked.close()


def test_two_connection_claim_race_yields_claim_and_replay() -> None:
    path = pathlib.Path(tempfile.mkdtemp()) / "runtime.db"
    setup = make_db(path)
    graph = seed_execution(setup)
    setup.close()
    barrier = threading.Barrier(2)
    outcomes: list[ExecutionIdempotencyOutcome] = []
    errors: list[BaseException] = []

    def worker() -> None:
        db = RuntimeDatabase(path)
        try:
            db.connect()
            repository = SqliteExecutionIdempotencyRepository(db)
            barrier.wait(timeout=5)
            result = repository.claim_execution(claim_command(graph))
            outcomes.append(result.outcome)
        except BaseException as exc:  # captured for main-thread assertion
            errors.append(exc)
        finally:
            db.close()

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)

    assert not errors
    assert sorted(outcome.value for outcome in outcomes) == [
        "CLAIMED",
        "REPLAY_PREPARED",
    ]
    check = RuntimeDatabase(path)
    check.connect()
    assert row_count(check, "execution_idempotency_claims") == 1
    assert row_count(check, "execution_states") == 1
    assert row_count(check, "dispatch_attempts") == 0
    check.close()


def test_two_connection_dispatch_race_creates_exactly_one_attempt() -> None:
    path = pathlib.Path(tempfile.mkdtemp()) / "runtime.db"
    setup = make_db(path)
    graph = seed_execution(setup)
    SqliteExecutionIdempotencyRepository(setup).claim_execution(claim_command(graph))
    setup.close()
    barrier = threading.Barrier(2)
    successes: list[str] = []
    errors: list[BaseException] = []

    def worker() -> None:
        db = RuntimeDatabase(path)
        try:
            db.connect()
            repository = SqliteExecutionIdempotencyRepository(db)
            barrier.wait(timeout=5)
            result = repository.commit_dispatch(
                DispatchCommitCommand(graph["execution_intent_id"], T1)
            )
            successes.append(result.attempt_id)
        except BaseException as exc:  # expected for the losing worker
            errors.append(exc)
        finally:
            db.close()

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)

    assert len(successes) == 1
    assert len(errors) == 1
    assert isinstance(errors[0], ExecutionIdempotencyPreconditionError)
    check = RuntimeDatabase(path)
    check.connect()
    assert row_count(check, "dispatch_attempts") == 1
    state = check.connection.execute("SELECT * FROM execution_states").fetchone()
    assert state["status"] == "DISPATCH_COMMITTED"
    assert state["last_attempt_id"] == successes[0]
    check.close()


def test_each_public_mutation_uses_one_explicit_transaction() -> None:
    db = make_db()
    graph = seed_execution(db)
    repository = SqliteExecutionIdempotencyRepository(db)
    traced: list[str] = []
    db.connection.set_trace_callback(traced.append)
    repository.claim_execution(claim_command(graph))
    claim_trace = list(traced)
    traced.clear()
    repository.commit_dispatch(
        DispatchCommitCommand(graph["execution_intent_id"], T1)
    )
    dispatch_trace = list(traced)
    db.connection.set_trace_callback(None)

    for trace in (claim_trace, dispatch_trace):
        normalized = [statement.strip().upper() for statement in trace]
        assert sum(statement == "BEGIN IMMEDIATE" for statement in normalized) == 1
        assert sum(statement == "COMMIT" for statement in normalized) == 1
        assert sum(statement == "ROLLBACK" for statement in normalized) == 0


def test_repository_source_has_no_executor_network_or_helper_commit() -> None:
    source = inspect.getsource(repository_module)
    tree = ast.parse(source)
    imports = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in node.names
    }
    forbidden = {
        "requests",
        "httpx",
        "aiohttp",
        "ccxt",
        "paper_executor",
        "execution_adapter",
    }
    assert not any(
        imported == forbidden_name or imported.startswith(forbidden_name + ".")
        for imported in imports
        for forbidden_name in forbidden
    )
    assert ".commit(" not in source
    assert repository_module.LIVE == "FORBIDDEN"
