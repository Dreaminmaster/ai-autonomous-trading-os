"""Deterministic B5D paper execution planning and replay-safe orchestration.

This module is independent of the legacy random paper executor. It performs no
network, exchange, private API, wall-clock, random, or filesystem I/O. The
coordinator uses only the frozen B5D outcome repository and B4.3 lifecycle
persistence against one injected RuntimeDatabase authority.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, ROUND_HALF_EVEN, localcontext
from enum import StrEnum

from atos.execution_idempotency_types import (
    ExecutionIdempotencyConflictError,
    ExecutionIdempotencyInvariantError,
    ExecutionIdempotencyPreconditionError,
    ExecutionIdempotencyValidationError,
    ExecutionRecoveryDecision,
    derive_attempt_id,
    derive_client_order_id,
    derive_idempotency_key,
)
from atos.execution_outcome_repository import (
    DispatchSubmittedCommand,
    ExecutionFilledCommand,
    ExecutionOutcomeResult,
    SqliteExecutionOutcomeRepository,
)
from atos.execution_recovery import (
    ExecutionRecoverySnapshot,
    decide_execution_recovery,
)
from atos.lifecycle_persistence import SqliteLifecyclePersistence
from atos.lifecycle_types import (
    DispatchAttemptStatus,
    ExecutionStatus,
    FillApplicationCommand,
    OrderAcknowledgementCommand,
    OrderSide,
    OrderStatus,
    OrderType,
    PersistenceOutcome,
    PositionAccountingPolicy,
    deterministic_id,
    require_decimal,
    require_identity,
    require_utc_datetime,
)
from atos.runtime_db import RuntimeDatabase

LIVE = "FORBIDDEN"
PAPER_ORDER_ID_VERSION = "B5D:PAPER_ORDER:V1"
PAPER_FILL_ID_VERSION = "B5D:PAPER_FILL:V1"
_DECIMAL_PRECISION = 34
_BPS_DENOMINATOR = Decimal("10000")
_ZERO = Decimal("0")
_ONE = Decimal("1")


class PaperExecutionOutcome(StrEnum):
    FILLED = "FILLED"
    SAFE_COMMIT_DISPATCH = "SAFE_COMMIT_DISPATCH"
    RECONCILE_REQUIRED = "RECONCILE_REQUIRED"
    TERMINAL_NOOP = "TERMINAL_NOOP"
    PAUSE_RECOVERY = "PAUSE_RECOVERY"


def _identity(value: str, field_name: str) -> str:
    try:
        return require_identity(value, field_name)
    except Exception as exc:
        raise ExecutionIdempotencyValidationError(str(exc)) from exc


def _decimal(
    value: Decimal,
    field_name: str,
    *,
    positive: bool = False,
    non_negative: bool = False,
) -> Decimal:
    try:
        return require_decimal(
            value,
            field_name,
            positive=positive,
            non_negative=non_negative,
        )
    except Exception as exc:
        raise ExecutionIdempotencyValidationError(str(exc)) from exc


def _utc(value, field_name: str):
    try:
        return require_utc_datetime(value, field_name)
    except Exception as exc:
        raise ExecutionIdempotencyValidationError(str(exc)) from exc


def _lower_hex_64(value: str, field_name: str) -> str:
    _identity(value, field_name)
    if (
        len(value) != 64
        or value != value.lower()
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ExecutionIdempotencyValidationError(
            f"{field_name} must be exactly 64 lowercase hexadecimal characters"
        )
    return value


def _canonical_decimal(value: Decimal) -> Decimal:
    if value == 0:
        return _ZERO
    return value.normalize()


def derive_paper_order_id(
    *, venue: str, account_scope: str, client_order_id: str
) -> str:
    return deterministic_id(
        "pord_",
        (
            PAPER_ORDER_ID_VERSION,
            _identity(venue, "venue"),
            _identity(account_scope, "account_scope"),
            _identity(client_order_id, "client_order_id"),
        ),
    )


def derive_paper_fill_id(
    *, venue: str, account_scope: str, client_order_id: str
) -> str:
    return deterministic_id(
        "pfill_",
        (
            PAPER_FILL_ID_VERSION,
            _identity(venue, "venue"),
            _identity(account_scope, "account_scope"),
            _identity(client_order_id, "client_order_id"),
        ),
    )


@dataclass(frozen=True, slots=True)
class PaperExecutionConfig:
    fee_bps: Decimal = Decimal("10")
    slippage_bps: Decimal = Decimal("5")

    def __post_init__(self) -> None:
        _decimal(self.fee_bps, "fee_bps", non_negative=True)
        _decimal(self.slippage_bps, "slippage_bps", non_negative=True)
        if self.fee_bps > _BPS_DENOMINATOR:
            raise ExecutionIdempotencyValidationError(
                "fee_bps must be <= 10000"
            )
        if self.slippage_bps >= _BPS_DENOMINATOR:
            raise ExecutionIdempotencyValidationError(
                "slippage_bps must be < 10000"
            )


@dataclass(frozen=True, slots=True)
class PaperExecutionEnvelope:
    execution_intent_id: str
    idempotency_key: str
    attempt_id: str
    client_order_id: str
    venue: str
    account_scope: str
    symbol: str
    side: OrderSide
    quantity: Decimal
    mark_price: Decimal
    fee_currency: str
    observed_at: datetime

    def __post_init__(self) -> None:
        for name in (
            "execution_intent_id",
            "attempt_id",
            "client_order_id",
            "venue",
            "account_scope",
            "symbol",
            "fee_currency",
        ):
            _identity(getattr(self, name), name)
        key = _lower_hex_64(self.idempotency_key, "idempotency_key")
        if type(self.side) is not OrderSide:
            raise ExecutionIdempotencyValidationError("side must be OrderSide")
        _decimal(self.quantity, "quantity", positive=True)
        _decimal(self.mark_price, "mark_price", positive=True)
        _utc(self.observed_at, "observed_at")
        venue_kind = self.venue.lower()
        if "paper" not in venue_kind and "shadow" not in venue_kind:
            raise ExecutionIdempotencyValidationError(
                "B5D adapter accepts only paper or shadow venues"
            )
        expected_attempt = derive_attempt_id(key, 1)
        expected_client = derive_client_order_id(key)
        if self.attempt_id != expected_attempt:
            raise ExecutionIdempotencyValidationError(
                "attempt_id does not match the frozen B5 V1 identity"
            )
        if self.client_order_id != expected_client:
            raise ExecutionIdempotencyValidationError(
                "client_order_id does not match the frozen B5 V1 projection"
            )


@dataclass(frozen=True, slots=True)
class PaperExecutionPlan:
    envelope: PaperExecutionEnvelope
    config: PaperExecutionConfig
    order_id: str
    fill_id: str
    execution_price: Decimal
    fee: Decimal
    dispatch_command: DispatchSubmittedCommand
    order_command: OrderAcknowledgementCommand
    fill_command: FillApplicationCommand
    filled_command: ExecutionFilledCommand

    def __post_init__(self) -> None:
        if type(self.envelope) is not PaperExecutionEnvelope:
            raise ExecutionIdempotencyValidationError(
                "envelope must be PaperExecutionEnvelope"
            )
        if type(self.config) is not PaperExecutionConfig:
            raise ExecutionIdempotencyValidationError(
                "config must be PaperExecutionConfig"
            )
        _identity(self.order_id, "order_id")
        _identity(self.fill_id, "fill_id")
        _decimal(self.execution_price, "execution_price", positive=True)
        _decimal(self.fee, "fee", non_negative=True)
        if self.order_command.order_id != self.order_id:
            raise ExecutionIdempotencyInvariantError(
                "order command identity drift"
            )
        if (
            self.fill_command.fill_id != self.fill_id
            or self.fill_command.order_id != self.order_id
        ):
            raise ExecutionIdempotencyInvariantError(
                "fill command identity drift"
            )
        if (
            self.filled_command.order_id != self.order_id
            or self.filled_command.fill_id != self.fill_id
        ):
            raise ExecutionIdempotencyInvariantError(
                "filled command identity drift"
            )


@dataclass(frozen=True, slots=True)
class PaperExecutionResult:
    outcome: PaperExecutionOutcome
    execution_status: ExecutionStatus
    attempt_status: DispatchAttemptStatus | None
    order_id: str
    fill_id: str
    dispatch_outcome: PersistenceOutcome | None = None
    order_outcome: PersistenceOutcome | None = None
    fill_outcome: PersistenceOutcome | None = None
    final_outcome: PersistenceOutcome | None = None

    def __post_init__(self) -> None:
        if type(self.outcome) is not PaperExecutionOutcome:
            raise ExecutionIdempotencyValidationError(
                "outcome must be PaperExecutionOutcome"
            )
        if type(self.execution_status) is not ExecutionStatus:
            raise ExecutionIdempotencyValidationError(
                "execution_status must be ExecutionStatus"
            )
        if self.attempt_status is not None and type(
            self.attempt_status
        ) is not DispatchAttemptStatus:
            raise ExecutionIdempotencyValidationError(
                "attempt_status must be DispatchAttemptStatus or None"
            )
        for name in ("order_id", "fill_id"):
            _identity(getattr(self, name), name)
        for name in (
            "dispatch_outcome",
            "order_outcome",
            "fill_outcome",
            "final_outcome",
        ):
            value = getattr(self, name)
            if value is not None and type(value) is not PersistenceOutcome:
                raise ExecutionIdempotencyValidationError(
                    f"{name} must be PersistenceOutcome or None"
                )
        allowed_statuses = {
            PaperExecutionOutcome.FILLED: {ExecutionStatus.FILLED},
            PaperExecutionOutcome.SAFE_COMMIT_DISPATCH: {ExecutionStatus.PREPARED},
            PaperExecutionOutcome.RECONCILE_REQUIRED: {ExecutionStatus.AMBIGUOUS},
            PaperExecutionOutcome.TERMINAL_NOOP: {
                ExecutionStatus.FILLED,
                ExecutionStatus.TERMINAL,
            },
            PaperExecutionOutcome.PAUSE_RECOVERY: set(ExecutionStatus),
        }
        if self.execution_status not in allowed_statuses[self.outcome]:
            raise ExecutionIdempotencyInvariantError(
                "paper result outcome does not match execution status"
            )


class DeterministicPaperExecutionAdapter:
    """Pure builder for byte-stable paper lifecycle commands."""

    def __init__(self, config: PaperExecutionConfig | None = None) -> None:
        self._config = config or PaperExecutionConfig()
        if type(self._config) is not PaperExecutionConfig:
            raise ExecutionIdempotencyValidationError(
                "config must be PaperExecutionConfig"
            )

    def build(self, envelope: PaperExecutionEnvelope) -> PaperExecutionPlan:
        if type(envelope) is not PaperExecutionEnvelope:
            raise ExecutionIdempotencyValidationError(
                "envelope must be PaperExecutionEnvelope"
            )
        order_id = derive_paper_order_id(
            venue=envelope.venue,
            account_scope=envelope.account_scope,
            client_order_id=envelope.client_order_id,
        )
        fill_id = derive_paper_fill_id(
            venue=envelope.venue,
            account_scope=envelope.account_scope,
            client_order_id=envelope.client_order_id,
        )
        with localcontext() as context:
            context.prec = _DECIMAL_PRECISION
            context.rounding = ROUND_HALF_EVEN
            slippage_fraction = self._config.slippage_bps / _BPS_DENOMINATOR
            if envelope.side is OrderSide.BUY:
                execution_price = envelope.mark_price * (_ONE + slippage_fraction)
            else:
                execution_price = envelope.mark_price * (_ONE - slippage_fraction)
            fee = (
                envelope.quantity
                * execution_price
                * self._config.fee_bps
                / _BPS_DENOMINATOR
            )
            execution_price = _canonical_decimal(+execution_price)
            fee = _canonical_decimal(+fee)
        if execution_price <= 0:
            raise ExecutionIdempotencyInvariantError(
                "paper execution price must remain positive"
            )

        dispatch_command = DispatchSubmittedCommand(
            envelope.execution_intent_id,
            envelope.attempt_id,
            envelope.observed_at,
        )
        order_command = OrderAcknowledgementCommand(
            venue=envelope.venue,
            account_scope=envelope.account_scope,
            order_id=order_id,
            execution_intent_id=envelope.execution_intent_id,
            attempt_id=envelope.attempt_id,
            client_order_id=envelope.client_order_id,
            symbol=envelope.symbol,
            side=envelope.side,
            quantity=envelope.quantity,
            price=execution_price,
            order_type=OrderType.MARKET,
            acknowledged_at=envelope.observed_at,
        )
        fill_command = FillApplicationCommand(
            venue=envelope.venue,
            account_scope=envelope.account_scope,
            fill_id=fill_id,
            order_id=order_id,
            symbol=envelope.symbol,
            quantity=envelope.quantity,
            price=execution_price,
            fee=fee,
            fee_currency=envelope.fee_currency,
            occurred_at=envelope.observed_at,
            recorded_at=envelope.observed_at,
            order_status_after=OrderStatus.FILLED,
        )
        filled_command = ExecutionFilledCommand(
            execution_intent_id=envelope.execution_intent_id,
            attempt_id=envelope.attempt_id,
            order_id=order_id,
            fill_id=fill_id,
            observed_at=envelope.observed_at,
        )
        return PaperExecutionPlan(
            envelope=envelope,
            config=self._config,
            order_id=order_id,
            fill_id=fill_id,
            execution_price=execution_price,
            fee=fee,
            dispatch_command=dispatch_command,
            order_command=order_command,
            fill_command=fill_command,
            filled_command=filled_command,
        )


class SqlitePaperExecutionCoordinator:
    """Replay-safe paper orchestration over one canonical SQLite authority."""

    def __init__(
        self,
        db: RuntimeDatabase,
        accounting_policy: PositionAccountingPolicy,
        config: PaperExecutionConfig | None = None,
    ) -> None:
        if not isinstance(db, RuntimeDatabase):
            raise ExecutionIdempotencyValidationError("db must be RuntimeDatabase")
        if db.conn is None:
            raise ExecutionIdempotencyValidationError(
                "db must be connected before coordinator construction"
            )
        if not isinstance(accounting_policy, PositionAccountingPolicy):
            raise ExecutionIdempotencyValidationError(
                "accounting_policy must implement PositionAccountingPolicy"
            )
        self._db = db
        self._connection = db.conn
        self._adapter = DeterministicPaperExecutionAdapter(config)
        self._outcomes = SqliteExecutionOutcomeRepository(db)
        self._lifecycle = SqliteLifecyclePersistence(db, accounting_policy)

    def _before_step(self, step: str, plan: PaperExecutionPlan) -> None:
        """Injected-crash seam; production implementation is a no-op."""
        del step, plan

    def _after_step(self, step: str, plan: PaperExecutionPlan) -> None:
        """Injected-crash seam; production implementation is a no-op."""
        del step, plan

    def _require_connection(self) -> None:
        if self._db.conn is not self._connection:
            raise ExecutionIdempotencyInvariantError(
                "RuntimeDatabase connection changed inside paper coordinator"
            )
        if self._connection.in_transaction:
            raise ExecutionIdempotencyPreconditionError(
                "nested paper orchestration transaction is forbidden"
            )

    def _require_durable_authority(
        self,
        envelope: PaperExecutionEnvelope,
    ) -> None:
        row = self._connection.execute(
            "SELECT c.idempotency_key,c.execution_intent_id,c.venue,"
            "c.account_scope,c.symbol AS claim_symbol,c.action AS claim_action,"
            "c.normalized_intent_hash,c.client_order_id,"
            "e.symbol AS intent_symbol,e.action AS intent_action,"
            "e.normalized_intent_hash AS intent_hash "
            "FROM execution_idempotency_claims AS c "
            "JOIN execution_intents AS e "
            "ON e.execution_intent_id=c.execution_intent_id "
            "WHERE c.execution_intent_id=?",
            (envelope.execution_intent_id,),
        ).fetchone()
        if row is None:
            raise ExecutionIdempotencyPreconditionError(
                "paper execution requires one durable idempotency claim"
            )
        try:
            claim_action = OrderSide(row["claim_action"])
            intent_action = OrderSide(row["intent_action"])
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise ExecutionIdempotencyInvariantError(
                "persisted execution action is invalid"
            ) from exc

        if (
            row["claim_symbol"] != row["intent_symbol"]
            or claim_action is not intent_action
            or row["normalized_intent_hash"] != row["intent_hash"]
        ):
            raise ExecutionIdempotencyInvariantError(
                "idempotency claim and execution intent authority disagree"
            )

        expected_key = derive_idempotency_key(
            venue=row["venue"],
            account_scope=row["account_scope"],
            symbol=row["claim_symbol"],
            action=claim_action,
            normalized_intent_hash=row["normalized_intent_hash"],
        )
        expected_client = derive_client_order_id(expected_key)
        expected_attempt = derive_attempt_id(expected_key, 1)
        if (
            row["idempotency_key"] != expected_key
            or row["client_order_id"] != expected_client
        ):
            raise ExecutionIdempotencyInvariantError(
                "persisted paper execution identity is not self-consistent"
            )

        envelope_authority = (
            envelope.idempotency_key,
            envelope.attempt_id,
            envelope.client_order_id,
            envelope.venue,
            envelope.account_scope,
            envelope.symbol,
            envelope.side,
        )
        durable_authority = (
            expected_key,
            expected_attempt,
            expected_client,
            row["venue"],
            row["account_scope"],
            row["claim_symbol"],
            claim_action,
        )
        if envelope_authority != durable_authority:
            raise ExecutionIdempotencyConflictError(
                "paper envelope does not match durable execution authority"
            )

    @staticmethod
    def _passive_result(
        *,
        outcome: PaperExecutionOutcome,
        status: ExecutionStatus,
        attempt_status: DispatchAttemptStatus | None,
        plan: PaperExecutionPlan,
    ) -> PaperExecutionResult:
        return PaperExecutionResult(
            outcome=outcome,
            execution_status=status,
            attempt_status=attempt_status,
            order_id=plan.order_id,
            fill_id=plan.fill_id,
        )

    @classmethod
    def _passive_for_decision(
        cls,
        *,
        decision: ExecutionRecoveryDecision,
        snapshot: ExecutionRecoverySnapshot,
        plan: PaperExecutionPlan,
    ) -> PaperExecutionResult | None:
        if decision is ExecutionRecoveryDecision.SAFE_COMMIT_DISPATCH:
            return cls._passive_result(
                outcome=PaperExecutionOutcome.SAFE_COMMIT_DISPATCH,
                status=snapshot.execution_status,
                attempt_status=snapshot.attempt_status,
                plan=plan,
            )
        if decision is ExecutionRecoveryDecision.PAUSE_RECOVERY:
            return cls._passive_result(
                outcome=PaperExecutionOutcome.PAUSE_RECOVERY,
                status=snapshot.execution_status,
                attempt_status=snapshot.attempt_status,
                plan=plan,
            )
        if (
            decision is ExecutionRecoveryDecision.RECONCILE_REQUIRED
            and snapshot.execution_status is ExecutionStatus.AMBIGUOUS
        ):
            return cls._passive_result(
                outcome=PaperExecutionOutcome.RECONCILE_REQUIRED,
                status=snapshot.execution_status,
                attempt_status=snapshot.attempt_status,
                plan=plan,
            )
        if (
            decision is ExecutionRecoveryDecision.TERMINAL_NOOP
            and snapshot.execution_status is ExecutionStatus.TERMINAL
        ):
            return cls._passive_result(
                outcome=PaperExecutionOutcome.TERMINAL_NOOP,
                status=snapshot.execution_status,
                attempt_status=snapshot.attempt_status,
                plan=plan,
            )
        return None

    def execute(
        self,
        envelope: PaperExecutionEnvelope,
        *,
        reconciliation_available: bool = True,
    ) -> PaperExecutionResult:
        self._require_connection()
        if type(reconciliation_available) is not bool:
            raise ExecutionIdempotencyValidationError(
                "reconciliation_available must be bool"
            )
        self._require_durable_authority(envelope)
        plan = self._adapter.build(envelope)
        snapshot = self._outcomes.read_recovery_snapshot(
            envelope.execution_intent_id,
            reconciliation_available=reconciliation_available,
        )
        decision = decide_execution_recovery(snapshot)
        passive = self._passive_for_decision(
            decision=decision,
            snapshot=snapshot,
            plan=plan,
        )
        if passive is not None:
            return passive

        dispatch_outcome = None
        if snapshot.execution_status is ExecutionStatus.DISPATCH_COMMITTED:
            self._before_step("mark_dispatched", plan)
            try:
                dispatch_result = self._outcomes.mark_dispatched(
                    plan.dispatch_command
                )
                dispatch_outcome = dispatch_result.outcome
                self._after_step("mark_dispatched", plan)
            except (
                ExecutionIdempotencyPreconditionError,
                ExecutionIdempotencyConflictError,
            ):
                refreshed = self._outcomes.read_recovery_snapshot(
                    envelope.execution_intent_id,
                    reconciliation_available=reconciliation_available,
                )
                refreshed_decision = decide_execution_recovery(refreshed)
                passive = self._passive_for_decision(
                    decision=refreshed_decision,
                    snapshot=refreshed,
                    plan=plan,
                )
                if passive is not None:
                    return passive
                if refreshed.execution_status not in {
                    ExecutionStatus.DISPATCHED,
                    ExecutionStatus.ACKNOWLEDGED,
                    ExecutionStatus.FILLED,
                }:
                    raise
                snapshot = refreshed
        elif snapshot.execution_status not in {
            ExecutionStatus.DISPATCHED,
            ExecutionStatus.ACKNOWLEDGED,
            ExecutionStatus.FILLED,
        }:
            return self._passive_result(
                outcome=PaperExecutionOutcome.PAUSE_RECOVERY,
                status=snapshot.execution_status,
                attempt_status=snapshot.attempt_status,
                plan=plan,
            )

        self._before_step("order_acknowledgement", plan)
        order_result = self._lifecycle.register_order_acknowledgement(
            plan.order_command
        )
        self._after_step("order_acknowledgement", plan)

        self._before_step("fill_application", plan)
        fill_result = self._lifecycle.apply_fill(plan.fill_command)
        self._after_step("fill_application", plan)

        self._before_step("mark_filled", plan)
        final_result: ExecutionOutcomeResult = self._outcomes.mark_filled(
            plan.filled_command
        )
        self._after_step("mark_filled", plan)

        final_snapshot = self._outcomes.read_recovery_snapshot(
            envelope.execution_intent_id,
            reconciliation_available=True,
        )
        final_decision = decide_execution_recovery(final_snapshot)
        if (
            final_snapshot.execution_status is not ExecutionStatus.FILLED
            or final_snapshot.attempt_status is not DispatchAttemptStatus.ACCEPTED
            or final_decision is not ExecutionRecoveryDecision.TERMINAL_NOOP
        ):
            raise ExecutionIdempotencyInvariantError(
                "paper execution did not reach verified FILLED authority"
            )
        return PaperExecutionResult(
            outcome=(
                PaperExecutionOutcome.TERMINAL_NOOP
                if snapshot.execution_status is ExecutionStatus.FILLED
                else PaperExecutionOutcome.FILLED
            ),
            execution_status=ExecutionStatus.FILLED,
            attempt_status=DispatchAttemptStatus.ACCEPTED,
            order_id=plan.order_id,
            fill_id=plan.fill_id,
            dispatch_outcome=dispatch_outcome,
            order_outcome=order_result.outcome,
            fill_outcome=fill_result.outcome,
            final_outcome=final_result.outcome,
        )
