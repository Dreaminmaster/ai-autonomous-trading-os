"""B5D1 pure execution recovery policy tests."""
from __future__ import annotations

import ast
import inspect

import pytest

import atos.execution_recovery as recovery_module
from atos.execution_idempotency_types import (
    ExecutionIdempotencyInvariantError,
    ExecutionRecoveryDecision,
)
from atos.execution_recovery import (
    ExecutionRecoverySnapshot,
    decide_execution_recovery,
)
from atos.lifecycle_types import DispatchAttemptStatus, ExecutionStatus


def snapshot(
    status: ExecutionStatus,
    *,
    attempt_count: int,
    attempt_status: DispatchAttemptStatus | None,
    reconciliation_available: bool = True,
    order_present: bool = False,
    fill_present: bool = False,
) -> ExecutionRecoverySnapshot:
    return ExecutionRecoverySnapshot(
        execution_status=status,
        attempt_count=attempt_count,
        attempt_status=attempt_status,
        reconciliation_available=reconciliation_available,
        order_present=order_present,
        fill_present=fill_present,
    )


def test_prepared_without_attempt_is_safe_commit_dispatch() -> None:
    value = snapshot(
        ExecutionStatus.PREPARED,
        attempt_count=0,
        attempt_status=None,
        reconciliation_available=False,
    )
    assert (
        decide_execution_recovery(value)
        is ExecutionRecoveryDecision.SAFE_COMMIT_DISPATCH
    )


@pytest.mark.parametrize(
    ("attempt_count", "attempt_status", "order_present", "fill_present"),
    [
        (1, DispatchAttemptStatus.PRE_DISPATCH_PROVEN, False, False),
        (0, None, True, False),
        (0, None, True, True),
    ],
)
def test_prepared_with_any_side_effect_authority_pauses(
    attempt_count: int,
    attempt_status: DispatchAttemptStatus | None,
    order_present: bool,
    fill_present: bool,
) -> None:
    value = snapshot(
        ExecutionStatus.PREPARED,
        attempt_count=attempt_count,
        attempt_status=attempt_status,
        order_present=order_present,
        fill_present=fill_present,
    )
    assert (
        decide_execution_recovery(value)
        is ExecutionRecoveryDecision.PAUSE_RECOVERY
    )


@pytest.mark.parametrize(
    ("status", "attempt_status", "order_present"),
    [
        (
            ExecutionStatus.DISPATCH_COMMITTED,
            DispatchAttemptStatus.PRE_DISPATCH_PROVEN,
            False,
        ),
        (
            ExecutionStatus.DISPATCHED,
            DispatchAttemptStatus.SUBMITTED,
            False,
        ),
        (
            ExecutionStatus.DISPATCHED,
            DispatchAttemptStatus.DISPATCH_INITIATED,
            False,
        ),
        (
            ExecutionStatus.ACKNOWLEDGED,
            DispatchAttemptStatus.ACCEPTED,
            True,
        ),
        (
            ExecutionStatus.AMBIGUOUS,
            DispatchAttemptStatus.TIMEOUT,
            False,
        ),
        (
            ExecutionStatus.AMBIGUOUS,
            DispatchAttemptStatus.AMBIGUOUS,
            False,
        ),
    ],
)
def test_valid_post_dispatch_states_require_reconciliation(
    status: ExecutionStatus,
    attempt_status: DispatchAttemptStatus,
    order_present: bool,
) -> None:
    value = snapshot(
        status,
        attempt_count=1,
        attempt_status=attempt_status,
        reconciliation_available=True,
        order_present=order_present,
    )
    assert (
        decide_execution_recovery(value)
        is ExecutionRecoveryDecision.RECONCILE_REQUIRED
    )


@pytest.mark.parametrize(
    ("status", "attempt_status", "order_present"),
    [
        (
            ExecutionStatus.DISPATCH_COMMITTED,
            DispatchAttemptStatus.PRE_DISPATCH_PROVEN,
            False,
        ),
        (
            ExecutionStatus.DISPATCHED,
            DispatchAttemptStatus.SUBMITTED,
            False,
        ),
        (
            ExecutionStatus.ACKNOWLEDGED,
            DispatchAttemptStatus.ACCEPTED,
            True,
        ),
        (
            ExecutionStatus.AMBIGUOUS,
            DispatchAttemptStatus.TIMEOUT,
            False,
        ),
    ],
)
def test_unavailable_reconciliation_pauses(
    status: ExecutionStatus,
    attempt_status: DispatchAttemptStatus,
    order_present: bool,
) -> None:
    value = snapshot(
        status,
        attempt_count=1,
        attempt_status=attempt_status,
        reconciliation_available=False,
        order_present=order_present,
    )
    assert (
        decide_execution_recovery(value)
        is ExecutionRecoveryDecision.PAUSE_RECOVERY
    )


def test_filled_complete_lifecycle_is_terminal_noop() -> None:
    value = snapshot(
        ExecutionStatus.FILLED,
        attempt_count=1,
        attempt_status=DispatchAttemptStatus.ACCEPTED,
        order_present=True,
        fill_present=True,
    )
    assert (
        decide_execution_recovery(value)
        is ExecutionRecoveryDecision.TERMINAL_NOOP
    )


def test_terminal_rejection_is_terminal_noop() -> None:
    value = snapshot(
        ExecutionStatus.TERMINAL,
        attempt_count=1,
        attempt_status=DispatchAttemptStatus.REJECTED,
    )
    assert (
        decide_execution_recovery(value)
        is ExecutionRecoveryDecision.TERMINAL_NOOP
    )


@pytest.mark.parametrize(
    "value",
    [
        snapshot(
            ExecutionStatus.FILLED,
            attempt_count=1,
            attempt_status=DispatchAttemptStatus.ACCEPTED,
            order_present=True,
            fill_present=False,
        ),
        snapshot(
            ExecutionStatus.TERMINAL,
            attempt_count=1,
            attempt_status=DispatchAttemptStatus.ACCEPTED,
        ),
        snapshot(
            ExecutionStatus.ACKNOWLEDGED,
            attempt_count=1,
            attempt_status=DispatchAttemptStatus.ACCEPTED,
            order_present=False,
        ),
        snapshot(
            ExecutionStatus.DISPATCHED,
            attempt_count=1,
            attempt_status=DispatchAttemptStatus.SUBMITTED,
            fill_present=False,
            order_present=True,
        ),
        snapshot(
            ExecutionStatus.DISPATCHED,
            attempt_count=2,
            attempt_status=DispatchAttemptStatus.SUBMITTED,
        ),
    ],
)
def test_impossible_or_incomplete_graph_pauses(
    value: ExecutionRecoverySnapshot,
) -> None:
    assert (
        decide_execution_recovery(value)
        is ExecutionRecoveryDecision.PAUSE_RECOVERY
    )


def test_snapshot_rejects_status_without_attempt_count() -> None:
    with pytest.raises(ExecutionIdempotencyInvariantError):
        snapshot(
            ExecutionStatus.DISPATCHED,
            attempt_count=0,
            attempt_status=DispatchAttemptStatus.SUBMITTED,
        )


def test_snapshot_rejects_attempt_without_status() -> None:
    with pytest.raises(ExecutionIdempotencyInvariantError):
        snapshot(
            ExecutionStatus.DISPATCHED,
            attempt_count=1,
            attempt_status=None,
        )


def test_snapshot_rejects_fill_without_order() -> None:
    with pytest.raises(ExecutionIdempotencyInvariantError):
        snapshot(
            ExecutionStatus.FILLED,
            attempt_count=1,
            attempt_status=DispatchAttemptStatus.ACCEPTED,
            fill_present=True,
            order_present=False,
        )


def test_recovery_module_is_pure_and_live_forbidden() -> None:
    source = inspect.getsource(recovery_module)
    tree = ast.parse(source)
    imported = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in node.names
    }
    forbidden = {
        "sqlite3",
        "requests",
        "httpx",
        "aiohttp",
        "ccxt",
        "pathlib",
        "os",
        "time",
        "datetime",
        "paper_executor",
    }
    assert not any(
        name == blocked or name.startswith(blocked + ".")
        for name in imported
        for blocked in forbidden
    )
    assert recovery_module.LIVE == "FORBIDDEN"
