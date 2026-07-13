"""B5D1 atomic execution outcome repository tests."""
from __future__ import annotations

import ast
import hashlib
import inspect
import pathlib
import sqlite3
import tempfile
import threading
from datetime import datetime, timedelta, timezone

import pytest

import atos.execution_outcome_repository as outcome_module
from atos.execution_idempotency_repository import (
    SqliteExecutionIdempotencyRepository,
)
from atos.execution_idempotency_types import (
    DispatchCommitCommand,
    ExecutionIdempotencyCommand,
    ExecutionIdempotencyConflictError,
    ExecutionIdempotencyPreconditionError,
)
from atos.execution_outcome_repository import (
    DispatchAmbiguousCommand,
    DispatchRejectedCommand,
    DispatchSubmittedCommand,
    ExecutionFilledCommand,
    SqliteExecutionOutcomeRepository,
)
from atos.lifecycle_types import (
    DispatchAttemptStatus,
    ExecutionStatus,
    OrderSide,
    PersistenceOutcome,
)
from atos.runtime_db import RuntimeDatabase
from atos.runtime_migrations import MIGRATION_PLAN, MigrationManager

T0 = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)
T1 = datetime(2026, 1, 1, 0, 1, tzinfo=timezone.utc)
T2 = datetime(2026, 1, 1, 0, 2, tzinfo=timezone.utc)


class InjectedCrash(RuntimeError):
    pass


class CrashOutcomeRepository(SqliteExecutionOutcomeRepository):
    def __init__(self, db: RuntimeDatabase, boundary: str) -> None:
        super().__init__(db)
        self.boundary = boundary

    def _after_mutation(
        self,
        boundary: str,
        connection: sqlite3.Connection,
    ) -> None:
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
) -> dict[str, str]:
    normalized = hashlib.sha256(f"intent-{suffix}".encode()).hexdigest()
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
            "APPROVED",
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


def claim_command(graph: dict[str, str]) -> ExecutionIdempotencyCommand:
    return ExecutionIdempotencyCommand(
        execution_intent_id=graph["execution_intent_id"],
        venue="okx_paper",
        account_scope="spot-main",
        symbol=graph["symbol"],
        action=OrderSide(graph["action"]),
        normalized_intent_hash=graph["normalized_intent_hash"],
        created_at=T0,
    )


def claimed(
    db: RuntimeDatabase,
    suffix: str = "1",
) -> tuple[dict[str, str], object]:
    graph = seed_execution(db, suffix)
    claim = SqliteExecutionIdempotencyRepository(db).claim_execution(
        claim_command(graph)
    )
    return graph, claim


def committed(
    db: RuntimeDatabase,
    suffix: str = "1",
) -> tuple[dict[str, str], object, object]:
    graph, claim = claimed(db, suffix)
    dispatch = SqliteExecutionIdempotencyRepository(db).commit_dispatch(
        DispatchCommitCommand(graph["execution_intent_id"], T1)
    )
    return graph, claim, dispatch


def state_row(db: RuntimeDatabase) -> sqlite3.Row:
    row = db.connection.execute("SELECT * FROM execution_states").fetchone()
    assert row is not None
    return row


def attempt_row(db: RuntimeDatabase) -> sqlite3.Row:
    row = db.connection.execute("SELECT * FROM dispatch_attempts").fetchone()
    assert row is not None
    return row


def mark_dispatched(
    db: RuntimeDatabase,
    graph: dict[str, str],
    dispatch,
    *,
    timestamp: datetime = T1,
):
    return SqliteExecutionOutcomeRepository(db).mark_dispatched(
        DispatchSubmittedCommand(
            graph["execution_intent_id"],
            dispatch.attempt_id,
            timestamp,
        )
    )


def insert_complete_order_fill(
    db: RuntimeDatabase,
    graph: dict[str, str],
    dispatch,
    *,
    order_id: str = "paper_order_1",
    fill_id: str = "paper_fill_1",
) -> tuple[str, str]:
    db.connection.execute(
        "UPDATE dispatch_attempts SET status='ACCEPTED',"
        "response_received_at='2026-01-01T00:02:00Z' "
        "WHERE attempt_id=?",
        (dispatch.attempt_id,),
    )
    db.connection.execute(
        "UPDATE execution_states SET status='ACKNOWLEDGED',"
        "state_started_at='2026-01-01T00:02:00Z',"
        "updated_at='2026-01-01T00:02:00Z' "
        "WHERE execution_intent_id=?",
        (graph["execution_intent_id"],),
    )
    db.connection.execute(
        "INSERT INTO order_states "
        "(venue,account_scope,order_id,execution_intent_id,attempt_id,"
        "client_order_id,symbol,side,quantity,price,order_type,status,"
        "created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            "okx_paper",
            "spot-main",
            order_id,
            graph["execution_intent_id"],
            dispatch.attempt_id,
            dispatch.client_order_id,
            graph["symbol"],
            graph["action"],
            "1",
            "100",
            "MARKET",
            "FILLED",
            "2026-01-01T00:02:00Z",
            "2026-01-01T00:03:00Z",
        ),
    )
    db.connection.execute(
        "INSERT INTO fill_states VALUES (?,?,?,?,?,?,?,?,?,?)",
        (
            "okx_paper",
            "spot-main",
            fill_id,
            order_id,
            graph["symbol"],
            "1",
            "100",
            "0.1",
            "USDT",
            "2026-01-01T00:03:00Z",
        ),
    )
    db.connection.commit()
    return order_id, fill_id


def test_repository_requires_connected_runtime_database() -> None:
    path = pathlib.Path(tempfile.mkdtemp()) / "runtime.db"
    with pytest.raises(Exception):
        SqliteExecutionOutcomeRepository(RuntimeDatabase(path))


def test_mark_dispatched_atomically_transitions_attempt_and_state() -> None:
    db = make_db()
    graph, _, dispatch = committed(db)
    result = mark_dispatched(db, graph, dispatch)

    assert result.outcome is PersistenceOutcome.APPLIED
    assert result.execution_status is ExecutionStatus.DISPATCHED
    assert result.attempt_status is DispatchAttemptStatus.SUBMITTED
    assert state_row(db)["status"] == "DISPATCHED"
    attempt = attempt_row(db)
    assert attempt["status"] == "SUBMITTED"
    assert attempt["dispatch_started_at"] == "2026-01-01T00:01:00Z"


def test_mark_dispatched_replay_is_noop_and_preserves_first_timestamp() -> None:
    db = make_db()
    graph, _, dispatch = committed(db)
    repository = SqliteExecutionOutcomeRepository(db)
    first = repository.mark_dispatched(
        DispatchSubmittedCommand(graph["execution_intent_id"], dispatch.attempt_id, T1)
    )
    before = db.connection.total_changes
    replay = repository.mark_dispatched(
        DispatchSubmittedCommand(graph["execution_intent_id"], dispatch.attempt_id, T2)
    )

    assert first.outcome is PersistenceOutcome.APPLIED
    assert replay.outcome is PersistenceOutcome.REPLAY_NOOP
    assert db.connection.total_changes == before
    assert attempt_row(db)["dispatch_started_at"] == "2026-01-01T00:01:00Z"


@pytest.mark.parametrize(
    "boundary",
    ["dispatch.attempt_submitted", "dispatch.execution_dispatched"],
)
def test_mark_dispatched_injected_crash_rolls_back_both_rows(
    boundary: str,
) -> None:
    db = make_db()
    graph, _, dispatch = committed(db)
    repository = CrashOutcomeRepository(db, boundary)

    with pytest.raises(InjectedCrash):
        repository.mark_dispatched(
            DispatchSubmittedCommand(
                graph["execution_intent_id"],
                dispatch.attempt_id,
                T1,
            )
        )

    assert state_row(db)["status"] == "DISPATCH_COMMITTED"
    attempt = attempt_row(db)
    assert attempt["status"] == "PRE_DISPATCH_PROVEN"
    assert attempt["dispatch_started_at"] is None


def test_mark_dispatched_rejects_wrong_attempt_identity() -> None:
    db = make_db()
    graph, _, _ = committed(db)
    with pytest.raises(Exception):
        SqliteExecutionOutcomeRepository(db).mark_dispatched(
            DispatchSubmittedCommand(graph["execution_intent_id"], "wrong", T1)
        )


@pytest.mark.parametrize(
    ("from_dispatched", "target"),
    [
        (False, DispatchAttemptStatus.TIMEOUT),
        (False, DispatchAttemptStatus.AMBIGUOUS),
        (True, DispatchAttemptStatus.TIMEOUT),
        (True, DispatchAttemptStatus.AMBIGUOUS),
    ],
)
def test_mark_ambiguous_from_allowed_preconditions(
    from_dispatched: bool,
    target: DispatchAttemptStatus,
) -> None:
    db = make_db()
    graph, _, dispatch = committed(db)
    if from_dispatched:
        mark_dispatched(db, graph, dispatch)
    result = SqliteExecutionOutcomeRepository(db).mark_ambiguous(
        DispatchAmbiguousCommand(
            graph["execution_intent_id"],
            dispatch.attempt_id,
            target,
            T2,
            "transport_uncertain",
        )
    )

    assert result.outcome is PersistenceOutcome.APPLIED
    assert result.execution_status is ExecutionStatus.AMBIGUOUS
    assert result.attempt_status is target
    assert state_row(db)["status"] == "AMBIGUOUS"
    attempt = attempt_row(db)
    assert attempt["status"] == target.value
    assert attempt["error_class"] == "transport_uncertain"
    assert attempt["response_received_at"] == "2026-01-01T00:02:00Z"


def test_mark_ambiguous_replay_is_noop() -> None:
    db = make_db()
    graph, _, dispatch = committed(db)
    repository = SqliteExecutionOutcomeRepository(db)
    command = DispatchAmbiguousCommand(
        graph["execution_intent_id"],
        dispatch.attempt_id,
        DispatchAttemptStatus.TIMEOUT,
        T2,
        "timeout",
    )
    repository.mark_ambiguous(command)
    before = db.connection.total_changes
    replay = repository.mark_ambiguous(command)

    assert replay.outcome is PersistenceOutcome.REPLAY_NOOP
    assert db.connection.total_changes == before


@pytest.mark.parametrize(
    "boundary",
    ["ambiguous.attempt_update", "ambiguous.execution_update"],
)
def test_mark_ambiguous_injected_crash_rolls_back(
    boundary: str,
) -> None:
    db = make_db()
    graph, _, dispatch = committed(db)
    repository = CrashOutcomeRepository(db, boundary)
    with pytest.raises(InjectedCrash):
        repository.mark_ambiguous(
            DispatchAmbiguousCommand(
                graph["execution_intent_id"],
                dispatch.attempt_id,
                DispatchAttemptStatus.TIMEOUT,
                T2,
                "timeout",
            )
        )
    assert state_row(db)["status"] == "DISPATCH_COMMITTED"
    assert attempt_row(db)["status"] == "PRE_DISPATCH_PROVEN"


def test_timeout_never_returns_to_prepared() -> None:
    db = make_db()
    graph, _, dispatch = committed(db)
    SqliteExecutionOutcomeRepository(db).mark_ambiguous(
        DispatchAmbiguousCommand(
            graph["execution_intent_id"],
            dispatch.attempt_id,
            DispatchAttemptStatus.TIMEOUT,
            T2,
            "timeout",
        )
    )
    assert state_row(db)["status"] == "AMBIGUOUS"
    with pytest.raises(ExecutionIdempotencyPreconditionError):
        SqliteExecutionIdempotencyRepository(db).commit_dispatch(
            DispatchCommitCommand(graph["execution_intent_id"], T2)
        )


def test_terminal_rejection_requires_submitted_dispatch_and_no_order() -> None:
    db = make_db()
    graph, _, dispatch = committed(db)
    mark_dispatched(db, graph, dispatch)
    repository = SqliteExecutionOutcomeRepository(db)
    result = repository.mark_terminal_rejection(
        DispatchRejectedCommand(
            graph["execution_intent_id"],
            dispatch.attempt_id,
            T2,
            "deterministic_rejection",
        )
    )

    assert result.outcome is PersistenceOutcome.APPLIED
    assert state_row(db)["status"] == "TERMINAL"
    attempt = attempt_row(db)
    assert attempt["status"] == "REJECTED"
    assert attempt["error_class"] == "deterministic_rejection"

    before = db.connection.total_changes
    replay = repository.mark_terminal_rejection(
        DispatchRejectedCommand(
            graph["execution_intent_id"],
            dispatch.attempt_id,
            T2 + timedelta(seconds=1),
            "deterministic_rejection",
        )
    )
    assert replay.outcome is PersistenceOutcome.REPLAY_NOOP
    assert db.connection.total_changes == before


@pytest.mark.parametrize(
    "boundary",
    ["rejection.attempt_update", "rejection.execution_update"],
)
def test_terminal_rejection_injected_crash_rolls_back(
    boundary: str,
) -> None:
    db = make_db()
    graph, _, dispatch = committed(db)
    mark_dispatched(db, graph, dispatch)
    with pytest.raises(InjectedCrash):
        CrashOutcomeRepository(db, boundary).mark_terminal_rejection(
            DispatchRejectedCommand(
                graph["execution_intent_id"],
                dispatch.attempt_id,
                T2,
                "reject",
            )
        )
    assert state_row(db)["status"] == "DISPATCHED"
    assert attempt_row(db)["status"] == "SUBMITTED"


def test_terminal_rejection_fails_after_authoritative_order_exists() -> None:
    db = make_db()
    graph, _, dispatch = committed(db)
    mark_dispatched(db, graph, dispatch)
    insert_complete_order_fill(db, graph, dispatch)
    with pytest.raises(ExecutionIdempotencyPreconditionError):
        SqliteExecutionOutcomeRepository(db).mark_terminal_rejection(
            DispatchRejectedCommand(
                graph["execution_intent_id"],
                dispatch.attempt_id,
                T2,
                "reject",
            )
        )


def test_mark_filled_requires_exact_authoritative_order_and_fill() -> None:
    db = make_db()
    graph, _, dispatch = committed(db)
    mark_dispatched(db, graph, dispatch)
    order_id, fill_id = insert_complete_order_fill(db, graph, dispatch)
    repository = SqliteExecutionOutcomeRepository(db)
    result = repository.mark_filled(
        ExecutionFilledCommand(
            graph["execution_intent_id"],
            dispatch.attempt_id,
            order_id,
            fill_id,
            T2,
        )
    )

    assert result.outcome is PersistenceOutcome.APPLIED
    assert result.execution_status is ExecutionStatus.FILLED
    assert state_row(db)["status"] == "FILLED"

    before = db.connection.total_changes
    replay = repository.mark_filled(
        ExecutionFilledCommand(
            graph["execution_intent_id"],
            dispatch.attempt_id,
            order_id,
            fill_id,
            T2 + timedelta(seconds=1),
        )
    )
    assert replay.outcome is PersistenceOutcome.REPLAY_NOOP
    assert db.connection.total_changes == before


def test_mark_filled_missing_or_wrong_authority_fails_closed() -> None:
    db = make_db()
    graph, _, dispatch = committed(db)
    mark_dispatched(db, graph, dispatch)
    with pytest.raises(ExecutionIdempotencyPreconditionError):
        SqliteExecutionOutcomeRepository(db).mark_filled(
            ExecutionFilledCommand(
                graph["execution_intent_id"],
                dispatch.attempt_id,
                "missing-order",
                "missing-fill",
                T2,
            )
        )


def test_mark_filled_injected_crash_rolls_back() -> None:
    db = make_db()
    graph, _, dispatch = committed(db)
    mark_dispatched(db, graph, dispatch)
    order_id, fill_id = insert_complete_order_fill(db, graph, dispatch)
    with pytest.raises(InjectedCrash):
        CrashOutcomeRepository(db, "filled.execution_update").mark_filled(
            ExecutionFilledCommand(
                graph["execution_intent_id"],
                dispatch.attempt_id,
                order_id,
                fill_id,
                T2,
            )
        )
    assert state_row(db)["status"] == "ACKNOWLEDGED"


def test_read_recovery_snapshot_prepared() -> None:
    db = make_db()
    graph, _ = claimed(db)
    value = SqliteExecutionOutcomeRepository(db).read_recovery_snapshot(
        graph["execution_intent_id"],
        reconciliation_available=False,
    )
    assert value.execution_status is ExecutionStatus.PREPARED
    assert value.attempt_count == 0
    assert value.attempt_status is None
    assert not value.order_present
    assert not value.fill_present


def test_read_recovery_snapshot_dispatch_committed() -> None:
    db = make_db()
    graph, _, _ = committed(db)
    value = SqliteExecutionOutcomeRepository(db).read_recovery_snapshot(
        graph["execution_intent_id"],
        reconciliation_available=True,
    )
    assert value.execution_status is ExecutionStatus.DISPATCH_COMMITTED
    assert value.attempt_count == 1
    assert value.attempt_status is DispatchAttemptStatus.PRE_DISPATCH_PROVEN


def test_read_recovery_snapshot_complete_fill() -> None:
    db = make_db()
    graph, _, dispatch = committed(db)
    mark_dispatched(db, graph, dispatch)
    order_id, fill_id = insert_complete_order_fill(db, graph, dispatch)
    SqliteExecutionOutcomeRepository(db).mark_filled(
        ExecutionFilledCommand(
            graph["execution_intent_id"],
            dispatch.attempt_id,
            order_id,
            fill_id,
            T2,
        )
    )
    value = SqliteExecutionOutcomeRepository(db).read_recovery_snapshot(
        graph["execution_intent_id"],
        reconciliation_available=False,
    )
    assert value.execution_status is ExecutionStatus.FILLED
    assert value.attempt_status is DispatchAttemptStatus.ACCEPTED
    assert value.order_present
    assert value.fill_present


def test_two_connections_racing_mark_dispatched_yield_apply_and_replay() -> None:
    path = pathlib.Path(tempfile.mkdtemp()) / "race.db"
    setup = make_db(path)
    graph, _, dispatch = committed(setup)
    setup.close()

    barrier = threading.Barrier(2)
    results: list[PersistenceOutcome] = []
    errors: list[BaseException] = []
    lock = threading.Lock()

    def worker() -> None:
        db = RuntimeDatabase(path)
        db.connect()
        repository = SqliteExecutionOutcomeRepository(db)
        try:
            barrier.wait(timeout=5)
            result = repository.mark_dispatched(
                DispatchSubmittedCommand(
                    graph["execution_intent_id"],
                    dispatch.attempt_id,
                    T1,
                )
            )
            with lock:
                results.append(result.outcome)
        except BaseException as exc:
            with lock:
                errors.append(exc)
        finally:
            db.close()

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)

    assert not errors
    assert sorted(result.value for result in results) == [
        "APPLIED",
        "REPLAY_NOOP",
    ]
    verify = RuntimeDatabase(path)
    verify.connect()
    assert verify.connection.execute(
        "SELECT COUNT(*) FROM dispatch_attempts"
    ).fetchone()[0] == 1
    assert verify.connection.execute(
        "SELECT status FROM execution_states"
    ).fetchone()[0] == "DISPATCHED"
    verify.close()


def test_database_busy_fails_closed_without_mutation() -> None:
    path = pathlib.Path(tempfile.mkdtemp()) / "busy.db"
    first = make_db(path)
    graph, _, dispatch = committed(first)
    second = RuntimeDatabase(path)
    second.connect()
    second.connection.execute("PRAGMA busy_timeout=1")
    first.connection.execute("BEGIN IMMEDIATE")
    try:
        with pytest.raises(ExecutionIdempotencyPreconditionError):
            SqliteExecutionOutcomeRepository(second).mark_dispatched(
                DispatchSubmittedCommand(
                    graph["execution_intent_id"],
                    dispatch.attempt_id,
                    T1,
                )
            )
    finally:
        first.connection.rollback()
        first.close()
        second.close()

    verify = RuntimeDatabase(path)
    verify.connect()
    assert verify.connection.execute(
        "SELECT status FROM execution_states"
    ).fetchone()[0] == "DISPATCH_COMMITTED"
    assert verify.connection.execute(
        "SELECT status FROM dispatch_attempts"
    ).fetchone()[0] == "PRE_DISPATCH_PROVEN"
    verify.close()


def test_replaced_connection_is_rejected() -> None:
    db = make_db()
    graph, _, dispatch = committed(db)
    repository = SqliteExecutionOutcomeRepository(db)
    db.close()
    db.connect()
    with pytest.raises(ExecutionIdempotencyPreconditionError):
        repository.mark_dispatched(
            DispatchSubmittedCommand(
                graph["execution_intent_id"],
                dispatch.attempt_id,
                T1,
            )
        )


def test_nested_transaction_is_rejected() -> None:
    db = make_db()
    graph, _, dispatch = committed(db)
    db.connection.execute("BEGIN")
    try:
        with pytest.raises(ExecutionIdempotencyPreconditionError):
            SqliteExecutionOutcomeRepository(db).mark_dispatched(
                DispatchSubmittedCommand(
                    graph["execution_intent_id"],
                    dispatch.attempt_id,
                    T1,
                )
            )
    finally:
        db.connection.rollback()


def test_source_has_no_executor_network_filesystem_or_helper_commit() -> None:
    source = inspect.getsource(outcome_module)
    tree = ast.parse(source)
    imported = {
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
        "pathlib",
        "os",
        "paper_executor",
        "execution_adapter",
    }
    assert not any(
        name == blocked or name.startswith(blocked + ".")
        for name in imported
        for blocked in forbidden
    )
    assert ".commit(" not in source
    assert outcome_module.LIVE == "FORBIDDEN"
