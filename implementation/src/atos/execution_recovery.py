"""Pure B5D execution recovery decisions.

No database, filesystem, clock, executor, or network I/O is permitted here.
"""
from __future__ import annotations

from dataclasses import dataclass

from atos.execution_idempotency_types import (
    ExecutionIdempotencyInvariantError,
    ExecutionIdempotencyValidationError,
    ExecutionRecoveryDecision,
)
from atos.lifecycle_types import DispatchAttemptStatus, ExecutionStatus

LIVE = "FORBIDDEN"


@dataclass(frozen=True, slots=True)
class ExecutionRecoverySnapshot:
    """Immutable authority snapshot for one semantic execution."""

    execution_status: ExecutionStatus
    attempt_count: int
    attempt_status: DispatchAttemptStatus | None
    reconciliation_available: bool
    order_present: bool = False
    fill_present: bool = False

    def __post_init__(self) -> None:
        if type(self.execution_status) is not ExecutionStatus:
            raise ExecutionIdempotencyValidationError(
                "execution_status must be ExecutionStatus"
            )
        if type(self.attempt_count) is not int or self.attempt_count < 0:
            raise ExecutionIdempotencyValidationError(
                "attempt_count must be a non-negative int"
            )
        if self.attempt_status is not None and type(
            self.attempt_status
        ) is not DispatchAttemptStatus:
            raise ExecutionIdempotencyValidationError(
                "attempt_status must be DispatchAttemptStatus or None"
            )
        for name in (
            "reconciliation_available",
            "order_present",
            "fill_present",
        ):
            if type(getattr(self, name)) is not bool:
                raise ExecutionIdempotencyValidationError(f"{name} must be bool")
        if self.attempt_count == 0 and self.attempt_status is not None:
            raise ExecutionIdempotencyInvariantError(
                "attempt_status cannot exist when attempt_count is zero"
            )
        if self.attempt_count > 0 and self.attempt_status is None:
            raise ExecutionIdempotencyInvariantError(
                "attempt_status is required when an attempt exists"
            )
        if self.fill_present and not self.order_present:
            raise ExecutionIdempotencyInvariantError(
                "a fill cannot exist without its authoritative order"
            )


def decide_execution_recovery(
    snapshot: ExecutionRecoverySnapshot,
) -> ExecutionRecoveryDecision:
    """Return the frozen B5 recovery decision for an authority snapshot."""
    if type(snapshot) is not ExecutionRecoverySnapshot:
        raise ExecutionIdempotencyValidationError(
            "snapshot must be ExecutionRecoverySnapshot"
        )

    status = snapshot.execution_status

    if status is ExecutionStatus.PREPARED:
        if (
            snapshot.attempt_count == 0
            and not snapshot.order_present
            and not snapshot.fill_present
        ):
            return ExecutionRecoveryDecision.SAFE_COMMIT_DISPATCH
        return ExecutionRecoveryDecision.PAUSE_RECOVERY

    if status is ExecutionStatus.FILLED:
        if (
            snapshot.attempt_count == 1
            and snapshot.attempt_status is DispatchAttemptStatus.ACCEPTED
            and snapshot.order_present
            and snapshot.fill_present
        ):
            return ExecutionRecoveryDecision.TERMINAL_NOOP
        return ExecutionRecoveryDecision.PAUSE_RECOVERY

    if status is ExecutionStatus.TERMINAL:
        if (
            snapshot.attempt_count == 1
            and snapshot.attempt_status is DispatchAttemptStatus.REJECTED
            and not snapshot.order_present
            and not snapshot.fill_present
        ):
            return ExecutionRecoveryDecision.TERMINAL_NOOP
        return ExecutionRecoveryDecision.PAUSE_RECOVERY

    if snapshot.attempt_count != 1:
        return ExecutionRecoveryDecision.PAUSE_RECOVERY

    allowed_attempts = {
        ExecutionStatus.DISPATCH_COMMITTED: {
            DispatchAttemptStatus.PRE_DISPATCH_PROVEN,
        },
        ExecutionStatus.DISPATCHED: {
            DispatchAttemptStatus.DISPATCH_INITIATED,
            DispatchAttemptStatus.SUBMITTED,
        },
        ExecutionStatus.ACKNOWLEDGED: {
            DispatchAttemptStatus.ACCEPTED,
        },
        ExecutionStatus.AMBIGUOUS: {
            DispatchAttemptStatus.TIMEOUT,
            DispatchAttemptStatus.AMBIGUOUS,
        },
    }
    allowed = allowed_attempts.get(status)
    if allowed is None or snapshot.attempt_status not in allowed:
        return ExecutionRecoveryDecision.PAUSE_RECOVERY

    if status is ExecutionStatus.ACKNOWLEDGED and not snapshot.order_present:
        return ExecutionRecoveryDecision.PAUSE_RECOVERY
    if status in {
        ExecutionStatus.DISPATCH_COMMITTED,
        ExecutionStatus.DISPATCHED,
    } and (snapshot.order_present or snapshot.fill_present):
        return ExecutionRecoveryDecision.PAUSE_RECOVERY

    if not snapshot.reconciliation_available:
        return ExecutionRecoveryDecision.PAUSE_RECOVERY

    return ExecutionRecoveryDecision.RECONCILE_REQUIRED
