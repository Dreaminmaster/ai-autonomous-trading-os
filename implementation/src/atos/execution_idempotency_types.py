"""Pure B5 execution-idempotency identities and immutable typed values.

No database, filesystem, clock, executor, or network I/O is permitted here.
All remote/local identities are derived by deterministic V1 policy and are
never accepted from an LLM or other caller as authoritative inputs.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from hashlib import sha256

from atos.lifecycle_types import (
    DispatchAttemptStatus,
    ExecutionStatus,
    OrderSide,
    length_delimited_bytes,
    require_identity,
    require_utc_datetime,
)

LIVE = "FORBIDDEN"
CLIENT_ORDER_ID_VERSION = "a5"
CLIENT_ORDER_ID_HEX_LENGTH = 28
CLIENT_ORDER_ID_LENGTH = len(CLIENT_ORDER_ID_VERSION) + CLIENT_ORDER_ID_HEX_LENGTH
ATTEMPT_ID_VERSION = "b5.v1"
ATTEMPT_ID_PREFIX = "att_"

__all__ = (
    "ATTEMPT_ID_PREFIX",
    "ATTEMPT_ID_VERSION",
    "CLIENT_ORDER_ID_HEX_LENGTH",
    "CLIENT_ORDER_ID_LENGTH",
    "CLIENT_ORDER_ID_VERSION",
    "ConcurrentExecutionTransitionError",
    "DispatchCommitCommand",
    "DispatchCommitResult",
    "DispatchOutcomeCommand",
    "ExecutionClaimResult",
    "ExecutionIdempotencyClaim",
    "ExecutionIdempotencyCommand",
    "ExecutionIdempotencyConflictError",
    "ExecutionIdempotencyError",
    "ExecutionIdempotencyInvariantError",
    "ExecutionIdempotencyOutcome",
    "ExecutionIdempotencyPreconditionError",
    "ExecutionIdempotencyValidationError",
    "ExecutionRecoveryDecision",
    "LIVE",
    "derive_attempt_id",
    "derive_client_order_id",
    "derive_idempotency_key",
)


class ExecutionIdempotencyError(Exception):
    """Base B5 idempotency error."""


class ExecutionIdempotencyValidationError(ExecutionIdempotencyError, ValueError):
    """A typed command or persisted value is malformed."""


class ExecutionIdempotencyPreconditionError(ExecutionIdempotencyError):
    """A required parent or approved risk decision is absent."""


class ExecutionIdempotencyConflictError(ExecutionIdempotencyError):
    """One semantic identity has conflicting durable ownership."""


class ExecutionIdempotencyInvariantError(ExecutionIdempotencyError):
    """Persisted rows violate the frozen B5 contract."""


class ConcurrentExecutionTransitionError(ExecutionIdempotencyError):
    """A compare-and-swap execution transition lost a race."""


class ExecutionIdempotencyOutcome(StrEnum):
    CLAIMED = "CLAIMED"
    REPLAY_PREPARED = "REPLAY_PREPARED"
    RECONCILE_REQUIRED = "RECONCILE_REQUIRED"
    TERMINAL_NOOP = "TERMINAL_NOOP"


class ExecutionRecoveryDecision(StrEnum):
    SAFE_COMMIT_DISPATCH = "SAFE_COMMIT_DISPATCH"
    RECONCILE_REQUIRED = "RECONCILE_REQUIRED"
    TERMINAL_NOOP = "TERMINAL_NOOP"
    PAUSE_RECOVERY = "PAUSE_RECOVERY"


def _identity(value: str, field_name: str) -> str:
    try:
        return require_identity(value, field_name)
    except Exception as exc:
        raise ExecutionIdempotencyValidationError(str(exc)) from exc


def _utc(value: datetime, field_name: str) -> datetime:
    try:
        return require_utc_datetime(value, field_name)
    except Exception as exc:
        raise ExecutionIdempotencyValidationError(str(exc)) from exc


def _lower_hex_64(value: str, field_name: str) -> str:
    _identity(value, field_name)
    if len(value) != 64 or value != value.lower():
        raise ExecutionIdempotencyValidationError(
            f"{field_name} must be exactly 64 lowercase hexadecimal characters"
        )
    if any(character not in "0123456789abcdef" for character in value):
        raise ExecutionIdempotencyValidationError(
            f"{field_name} must be exactly 64 lowercase hexadecimal characters"
        )
    return value


def _order_side(value: OrderSide, field_name: str = "action") -> OrderSide:
    if type(value) is not OrderSide:
        raise ExecutionIdempotencyValidationError(
            f"{field_name} must be OrderSide, got {type(value).__name__}"
        )
    return value


def derive_idempotency_key(
    *,
    venue: str,
    account_scope: str,
    symbol: str,
    action: OrderSide,
    normalized_intent_hash: str,
) -> str:
    """Return the frozen B5 V1 semantic execution key."""
    components = (
        _identity(venue, "venue"),
        _identity(account_scope, "account_scope"),
        _identity(symbol, "symbol"),
        _order_side(action).value,
        _lower_hex_64(normalized_intent_hash, "normalized_intent_hash"),
    )
    return sha256(length_delimited_bytes(components)).hexdigest()


def derive_client_order_id(idempotency_key: str) -> str:
    """Project a full local key to the exact 30-character B5 V1 remote ID."""
    key = _lower_hex_64(idempotency_key, "idempotency_key")
    projected = CLIENT_ORDER_ID_VERSION + key[:CLIENT_ORDER_ID_HEX_LENGTH]
    if len(projected) != CLIENT_ORDER_ID_LENGTH:
        raise ExecutionIdempotencyInvariantError("client order ID length drift")
    return projected


def derive_attempt_id(idempotency_key: str, attempt_no: int = 1) -> str:
    """Return the frozen deterministic B5 V1 dispatch-attempt identity."""
    key = _lower_hex_64(idempotency_key, "idempotency_key")
    if type(attempt_no) is not int or attempt_no < 1:
        raise ExecutionIdempotencyValidationError("attempt_no must be int >= 1")
    canonical_attempt = str(attempt_no)
    digest = sha256(
        length_delimited_bytes((ATTEMPT_ID_VERSION, key, canonical_attempt))
    ).hexdigest()
    return ATTEMPT_ID_PREFIX + digest


@dataclass(frozen=True, slots=True)
class ExecutionIdempotencyCommand:
    """Authoritative source components plus provenance; derived IDs are properties."""

    execution_intent_id: str
    venue: str
    account_scope: str
    symbol: str
    action: OrderSide
    normalized_intent_hash: str
    created_at: datetime

    def __post_init__(self) -> None:
        _identity(self.execution_intent_id, "execution_intent_id")
        _identity(self.venue, "venue")
        _identity(self.account_scope, "account_scope")
        _identity(self.symbol, "symbol")
        _order_side(self.action)
        _lower_hex_64(self.normalized_intent_hash, "normalized_intent_hash")
        _utc(self.created_at, "created_at")

    @property
    def idempotency_key(self) -> str:
        return derive_idempotency_key(
            venue=self.venue,
            account_scope=self.account_scope,
            symbol=self.symbol,
            action=self.action,
            normalized_intent_hash=self.normalized_intent_hash,
        )

    @property
    def client_order_id(self) -> str:
        return derive_client_order_id(self.idempotency_key)


@dataclass(frozen=True, slots=True)
class ExecutionIdempotencyClaim:
    """Immutable persisted claim reconstructed with fail-closed identity checks."""

    idempotency_key: str
    execution_intent_id: str
    venue: str
    account_scope: str
    symbol: str
    action: OrderSide
    normalized_intent_hash: str
    client_order_id: str
    created_at: datetime

    def __post_init__(self) -> None:
        _lower_hex_64(self.idempotency_key, "idempotency_key")
        _identity(self.execution_intent_id, "execution_intent_id")
        _identity(self.venue, "venue")
        _identity(self.account_scope, "account_scope")
        _identity(self.symbol, "symbol")
        _order_side(self.action)
        _lower_hex_64(self.normalized_intent_hash, "normalized_intent_hash")
        _identity(self.client_order_id, "client_order_id")
        _utc(self.created_at, "created_at")

        expected_key = derive_idempotency_key(
            venue=self.venue,
            account_scope=self.account_scope,
            symbol=self.symbol,
            action=self.action,
            normalized_intent_hash=self.normalized_intent_hash,
        )
        if self.idempotency_key != expected_key:
            raise ExecutionIdempotencyInvariantError(
                "stored idempotency_key does not match semantic components"
            )
        expected_client_order_id = derive_client_order_id(expected_key)
        if self.client_order_id != expected_client_order_id:
            raise ExecutionIdempotencyInvariantError(
                "stored client_order_id does not match idempotency_key"
            )


@dataclass(frozen=True, slots=True)
class ExecutionClaimResult:
    """Typed result for first claim and all deterministic replay outcomes."""

    outcome: ExecutionIdempotencyOutcome
    claim: ExecutionIdempotencyClaim
    execution_status: ExecutionStatus

    def __post_init__(self) -> None:
        if type(self.outcome) is not ExecutionIdempotencyOutcome:
            raise ExecutionIdempotencyValidationError(
                "outcome must be ExecutionIdempotencyOutcome"
            )
        if type(self.claim) is not ExecutionIdempotencyClaim:
            raise ExecutionIdempotencyValidationError(
                "claim must be ExecutionIdempotencyClaim"
            )
        if type(self.execution_status) is not ExecutionStatus:
            raise ExecutionIdempotencyValidationError(
                "execution_status must be ExecutionStatus"
            )
        allowed = {
            ExecutionIdempotencyOutcome.CLAIMED: {ExecutionStatus.PREPARED},
            ExecutionIdempotencyOutcome.REPLAY_PREPARED: {ExecutionStatus.PREPARED},
            ExecutionIdempotencyOutcome.RECONCILE_REQUIRED: {
                ExecutionStatus.DISPATCH_COMMITTED,
                ExecutionStatus.DISPATCHED,
                ExecutionStatus.ACKNOWLEDGED,
                ExecutionStatus.AMBIGUOUS,
            },
            ExecutionIdempotencyOutcome.TERMINAL_NOOP: {
                ExecutionStatus.FILLED,
                ExecutionStatus.TERMINAL,
            },
        }
        if self.execution_status not in allowed[self.outcome]:
            raise ExecutionIdempotencyInvariantError(
                "claim outcome does not match execution status"
            )


@dataclass(frozen=True, slots=True)
class DispatchCommitCommand:
    execution_intent_id: str
    committed_at: datetime

    def __post_init__(self) -> None:
        _identity(self.execution_intent_id, "execution_intent_id")
        _utc(self.committed_at, "committed_at")


@dataclass(frozen=True, slots=True)
class DispatchCommitResult:
    execution_intent_id: str
    idempotency_key: str
    attempt_id: str
    client_order_id: str
    attempt_no: int
    attempt_status: DispatchAttemptStatus
    execution_status: ExecutionStatus

    def __post_init__(self) -> None:
        _identity(self.execution_intent_id, "execution_intent_id")
        key = _lower_hex_64(self.idempotency_key, "idempotency_key")
        _identity(self.attempt_id, "attempt_id")
        _identity(self.client_order_id, "client_order_id")
        if type(self.attempt_no) is not int or self.attempt_no != 1:
            raise ExecutionIdempotencyValidationError(
                "B5 V1 dispatch attempt_no must be exactly 1"
            )
        if type(self.attempt_status) is not DispatchAttemptStatus:
            raise ExecutionIdempotencyValidationError(
                "attempt_status must be DispatchAttemptStatus"
            )
        if self.attempt_status is not DispatchAttemptStatus.PRE_DISPATCH_PROVEN:
            raise ExecutionIdempotencyValidationError(
                "dispatch commit result must be PRE_DISPATCH_PROVEN"
            )
        if type(self.execution_status) is not ExecutionStatus:
            raise ExecutionIdempotencyValidationError(
                "execution_status must be ExecutionStatus"
            )
        if self.execution_status is not ExecutionStatus.DISPATCH_COMMITTED:
            raise ExecutionIdempotencyValidationError(
                "dispatch commit result must be DISPATCH_COMMITTED"
            )
        if self.attempt_id != derive_attempt_id(key, self.attempt_no):
            raise ExecutionIdempotencyInvariantError(
                "attempt_id does not match frozen B5 V1 derivation"
            )
        if self.client_order_id != derive_client_order_id(key):
            raise ExecutionIdempotencyInvariantError(
                "client_order_id does not match frozen B5 V1 derivation"
            )


@dataclass(frozen=True, slots=True)
class DispatchOutcomeCommand:
    execution_intent_id: str
    attempt_id: str
    attempt_status: DispatchAttemptStatus
    execution_status: ExecutionStatus
    observed_at: datetime
    error_class: str | None = None

    def __post_init__(self) -> None:
        _identity(self.execution_intent_id, "execution_intent_id")
        _identity(self.attempt_id, "attempt_id")
        if type(self.attempt_status) is not DispatchAttemptStatus:
            raise ExecutionIdempotencyValidationError(
                "attempt_status must be DispatchAttemptStatus"
            )
        if type(self.execution_status) is not ExecutionStatus:
            raise ExecutionIdempotencyValidationError(
                "execution_status must be ExecutionStatus"
            )
        _utc(self.observed_at, "observed_at")
        if self.error_class is not None:
            _identity(self.error_class, "error_class")
