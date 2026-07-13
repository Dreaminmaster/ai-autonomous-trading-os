"""Fail-closed durable-authority tests for the B5D2 paper coordinator."""
from __future__ import annotations

import hashlib
import pathlib
import tempfile
from dataclasses import replace
from datetime import datetime, timezone
from decimal import Decimal

import pytest

from atos.execution_idempotency_repository import (
    SqliteExecutionIdempotencyRepository,
)
from atos.execution_idempotency_types import (
    DispatchCommitCommand,
    ExecutionIdempotencyCommand,
    ExecutionIdempotencyConflictError,
    ExecutionIdempotencyPreconditionError,
    derive_attempt_id,
    derive_client_order_id,
)
from atos.lifecycle_types import ExecutionStatus, OrderSide, utc_text
from atos.paper_execution_adapter import (
    PaperExecutionEnvelope,
    PaperExecutionOutcome,
    SqlitePaperExecutionCoordinator,
)
from atos.position_accounting import NettingPositionAccountingV1
from atos.runtime_db import RuntimeDatabase
from atos.runtime_migrations import MIGRATION_PLAN, MigrationManager

T0 = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)
T1 = datetime(2026, 1, 1, 0, 1, tzinfo=timezone.utc)
T2 = datetime(2026, 1, 1, 0, 2, tzinfo=timezone.utc)


def _make_db() -> RuntimeDatabase:
    path = pathlib.Path(tempfile.mkdtemp()) / "runtime.db"
    db = RuntimeDatabase(path)
    db.connect()
    MigrationManager(db, MIGRATION_PLAN).migrate()
    return db


def _seed_dispatch(db: RuntimeDatabase) -> PaperExecutionEnvelope:
    normalized = hashlib.sha256(b"b5d2-authority").hexdigest()
    connection = db.connection
    connection.execute(
        "INSERT INTO runtime_sessions VALUES (?,?,?,?,NULL,NULL)",
        ("session-authority", utc_text(T0), "paper", "RUNNING"),
    )
    connection.execute(
        "INSERT INTO runtime_cycles "
        "(cycle_id,session_id,symbol,started_at,status) VALUES (?,?,?,?,?)",
        (
            "cycle-authority",
            "session-authority",
            "BTC/USDT",
            utc_text(T0),
            "CREATED",
        ),
    )
    connection.execute(
        "INSERT INTO trade_intents VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            "trade-authority",
            "BTC/USDT",
            "BUY",
            "0.9",
            "authority thesis",
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
            "risk-authority",
            "trade-authority",
            "APPROVED",
            "[]",
            "0.1",
            "{}",
            utc_text(T0),
        ),
    )
    connection.execute(
        "INSERT INTO execution_intents VALUES (?,?,?,?,?,?,?,?,?)",
        (
            "execution-authority",
            "trade-authority",
            "risk-authority",
            "cycle-authority",
            "BTC/USDT",
            "BUY",
            "250",
            normalized,
            utc_text(T0),
        ),
    )
    connection.commit()

    repository = SqliteExecutionIdempotencyRepository(db)
    claimed = repository.claim_execution(
        ExecutionIdempotencyCommand(
            execution_intent_id="execution-authority",
            venue="okx_paper",
            account_scope="spot-main",
            symbol="BTC/USDT",
            action=OrderSide.BUY,
            normalized_intent_hash=normalized,
            created_at=T0,
        )
    )
    committed = repository.commit_dispatch(
        DispatchCommitCommand("execution-authority", T1)
    )
    return PaperExecutionEnvelope(
        execution_intent_id="execution-authority",
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


def _coordinator(db: RuntimeDatabase) -> SqlitePaperExecutionCoordinator:
    return SqlitePaperExecutionCoordinator(db, NettingPositionAccountingV1())


def _lifecycle_counts(db: RuntimeDatabase) -> tuple[int, int, int, int]:
    connection = db.connection
    return tuple(
        connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        for table in (
            "order_states",
            "fill_states",
            "position_states",
            "position_accounting_details",
        )
    )


@pytest.mark.parametrize(
    "mutation",
    [
        {"symbol": "ETH/USDT"},
        {"side": OrderSide.SELL},
        {"venue": "alternate_paper"},
        {"account_scope": "spot-alt"},
    ],
)
def test_envelope_semantic_substitution_fails_before_any_side_effect(
    mutation: dict[str, object],
) -> None:
    db = _make_db()
    envelope = _seed_dispatch(db)
    before_changes = db.connection.total_changes
    before_counts = _lifecycle_counts(db)

    with pytest.raises(
        ExecutionIdempotencyConflictError,
        match="durable execution authority",
    ):
        _coordinator(db).execute(replace(envelope, **mutation))

    state = db.connection.execute(
        "SELECT status FROM execution_states WHERE execution_intent_id=?",
        (envelope.execution_intent_id,),
    ).fetchone()
    assert state["status"] == ExecutionStatus.DISPATCH_COMMITTED.value
    assert db.connection.total_changes == before_changes
    assert _lifecycle_counts(db) == before_counts == (0, 0, 0, 0)


def test_missing_durable_claim_fails_before_any_side_effect() -> None:
    db = _make_db()
    key = "0" * 64
    envelope = PaperExecutionEnvelope(
        execution_intent_id="missing-execution",
        idempotency_key=key,
        attempt_id=derive_attempt_id(key, 1),
        client_order_id=derive_client_order_id(key),
        venue="okx_paper",
        account_scope="spot-main",
        symbol="BTC/USDT",
        side=OrderSide.BUY,
        quantity=Decimal("1"),
        mark_price=Decimal("100"),
        fee_currency="USDT",
        observed_at=T2,
    )
    before_changes = db.connection.total_changes

    with pytest.raises(
        ExecutionIdempotencyPreconditionError,
        match="durable idempotency claim",
    ):
        _coordinator(db).execute(envelope)

    assert db.connection.total_changes == before_changes
    assert _lifecycle_counts(db) == (0, 0, 0, 0)


def test_matching_durable_authority_still_reaches_one_fill() -> None:
    db = _make_db()
    envelope = _seed_dispatch(db)

    result = _coordinator(db).execute(envelope)

    assert result.outcome is PaperExecutionOutcome.FILLED
    assert result.execution_status is ExecutionStatus.FILLED
    assert _lifecycle_counts(db) == (1, 1, 1, 1)
