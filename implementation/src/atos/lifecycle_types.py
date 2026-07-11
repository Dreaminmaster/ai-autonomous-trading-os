"""Typed lifecycle values for B4.3B — immutable, in-process, no database I/O."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from enum import StrEnum
from hashlib import sha256
from typing import Protocol, Sequence, runtime_checkable


class OrderSide(StrEnum):
    BUY = "BUY"
    SELL = "SELL"


class OrderType(StrEnum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"


class OrderStatus(StrEnum):
    NEW = "NEW"
    PENDING_SUBMIT = "PENDING_SUBMIT"
    OPEN = "OPEN"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    CANCEL_REQUESTED = "CANCEL_REQUESTED"
    CANCEL_PENDING = "CANCEL_PENDING"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"
    UNKNOWN = "UNKNOWN"


class DispatchAttemptStatus(StrEnum):
    PRE_DISPATCH_PROVEN = "PRE_DISPATCH_PROVEN"
    DISPATCH_INITIATED = "DISPATCH_INITIATED"
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    TIMEOUT = "TIMEOUT"
    AMBIGUOUS = "AMBIGUOUS"


class ExecutionStatus(StrEnum):
    PREPARED = "PREPARED"
    DISPATCH_COMMITTED = "DISPATCH_COMMITTED"
    DISPATCHED = "DISPATCHED"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    AMBIGUOUS = "AMBIGUOUS"
    FILLED = "FILLED"
    TERMINAL = "TERMINAL"


class PositionSide(StrEnum):
    LONG = "LONG"
    SHORT = "SHORT"


class PositionStatus(StrEnum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class AccountingEventType(StrEnum):
    OPEN = "OPEN"
    INCREASE = "INCREASE"
    REDUCE = "REDUCE"
    CLOSE = "CLOSE"


class PositionMutationKind(StrEnum):
    INSERT = "INSERT"
    UPDATE = "UPDATE"


class PersistenceOutcome(StrEnum):
    APPLIED = "APPLIED"
    REPLAY_NOOP = "REPLAY_NOOP"


@dataclass(frozen=True, slots=True)
class OperationStats:
    read_statements: int = 0
    attempted_mutations: int = 0
    committed_mutations: int = 0
    transaction_count: int = 0
    db_connection_identity: int = 0

    def __post_init__(self) -> None:
        for name in (
            "read_statements",
            "attempted_mutations",
            "committed_mutations",
            "transaction_count",
            "db_connection_identity",
        ):
            value = getattr(self, name)
            if type(value) is not int or value < 0:
                raise ValueError(f"{name} must be a non-negative int")
        if self.committed_mutations > self.attempted_mutations:
            raise ValueError(
                "committed_mutations cannot exceed attempted_mutations"
            )


class LifecyclePersistenceError(Exception):
    """Base lifecycle error carrying immutable operation statistics."""

    def __init__(self, message: str, stats: OperationStats | None = None):
        super().__init__(message)
        self.stats = stats or OperationStats()


class LifecycleValidationError(LifecyclePersistenceError):
    pass


class LifecyclePreconditionError(LifecyclePersistenceError):
    pass


class LifecycleConflictError(LifecyclePersistenceError):
    pass


class LifecycleInvariantError(LifecyclePersistenceError):
    pass


def require_identity(value: str, field_name: str) -> str:
    if not isinstance(value, str):
        raise LifecycleValidationError(f"{field_name} must be str")
    if value == "" or value.isspace():
        raise LifecycleValidationError(f"{field_name} must not be empty or whitespace")
    return value


def require_decimal(
    value: Decimal,
    field_name: str,
    *,
    positive: bool = False,
    non_negative: bool = False,
) -> Decimal:
    if not isinstance(value, Decimal):
        raise LifecycleValidationError(f"{field_name} must be Decimal")
    if not value.is_finite():
        raise LifecycleValidationError(f"{field_name} must be finite")
    if positive and value <= 0:
        raise LifecycleValidationError(f"{field_name} must be > 0")
    if non_negative and value < 0:
        raise LifecycleValidationError(f"{field_name} must be >= 0")
    return value


def require_utc_datetime(value: datetime, field_name: str) -> datetime:
    if not isinstance(value, datetime):
        raise LifecycleValidationError(f"{field_name} must be datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise LifecycleValidationError(f"{field_name} must be timezone-aware UTC")
    if value.utcoffset() != timedelta(0):
        raise LifecycleValidationError(f"{field_name} must use UTC offset +00:00")
    return value


def decimal_text(value: Decimal) -> str:
    require_decimal(value, "value")
    if value == 0:
        return "0"
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text


def utc_text(value: datetime) -> str:
    require_utc_datetime(value, "value")
    return value.isoformat().replace("+00:00", "Z")


def length_delimited_bytes(components: Sequence[str]) -> bytes:
    encoded = bytearray()
    for component in components:
        require_identity(component, "hash component")
        raw = component.encode("utf-8")
        encoded.extend(str(len(raw)).encode("ascii"))
        encoded.extend(b":")
        encoded.extend(raw)
    return bytes(encoded)


def deterministic_id(prefix: str, components: Sequence[str]) -> str:
    require_identity(prefix, "prefix")
    return prefix + sha256(length_delimited_bytes(components)).hexdigest()


@dataclass(frozen=True, slots=True)
class OrderAcknowledgementCommand:
    venue: str
    account_scope: str
    order_id: str
    execution_intent_id: str
    attempt_id: str
    client_order_id: str
    symbol: str
    side: OrderSide
    quantity: Decimal
    price: Decimal
    order_type: OrderType
    acknowledged_at: datetime

    def __post_init__(self) -> None:
        for name in (
            "venue",
            "account_scope",
            "order_id",
            "execution_intent_id",
            "attempt_id",
            "client_order_id",
            "symbol",
        ):
            require_identity(getattr(self, name), name)
        if not isinstance(self.side, OrderSide):
            raise LifecycleValidationError("side must be OrderSide")
        if not isinstance(self.order_type, OrderType):
            raise LifecycleValidationError("order_type must be OrderType")
        require_decimal(self.quantity, "quantity", positive=True)
        require_decimal(self.price, "price", non_negative=True)
        require_utc_datetime(self.acknowledged_at, "acknowledged_at")


@dataclass(frozen=True, slots=True)
class FillApplicationCommand:
    venue: str
    account_scope: str
    fill_id: str
    order_id: str
    symbol: str
    quantity: Decimal
    price: Decimal
    fee: Decimal
    fee_currency: str
    occurred_at: datetime
    recorded_at: datetime
    order_status_after: OrderStatus

    def __post_init__(self) -> None:
        for name in (
            "venue",
            "account_scope",
            "fill_id",
            "order_id",
            "symbol",
            "fee_currency",
        ):
            require_identity(getattr(self, name), name)
        require_decimal(self.quantity, "quantity", positive=True)
        require_decimal(self.price, "price", non_negative=True)
        require_decimal(self.fee, "fee", non_negative=True)
        require_utc_datetime(self.occurred_at, "occurred_at")
        require_utc_datetime(self.recorded_at, "recorded_at")
        if not isinstance(self.order_status_after, OrderStatus) or self.order_status_after not in (
            OrderStatus.PARTIALLY_FILLED,
            OrderStatus.FILLED,
        ):
            raise LifecycleValidationError(
                "order_status_after must be PARTIALLY_FILLED or FILLED"
            )


@dataclass(frozen=True, slots=True)
class PositionSnapshot:
    position_id: str
    venue: str
    account_scope: str
    symbol: str
    side: PositionSide
    quantity: Decimal
    avg_entry_price: Decimal
    realized_pnl: Decimal
    unrealized_pnl: Decimal
    status: PositionStatus
    opened_at: datetime
    closed_at: datetime | None
    updated_at: datetime

    def __post_init__(self) -> None:
        for name in ("position_id", "venue", "account_scope", "symbol"):
            require_identity(getattr(self, name), name)
        if not isinstance(self.side, PositionSide):
            raise LifecycleValidationError("side must be PositionSide")
        if not isinstance(self.status, PositionStatus):
            raise LifecycleValidationError("status must be PositionStatus")
        require_decimal(self.quantity, "quantity", non_negative=True)
        require_decimal(self.avg_entry_price, "avg_entry_price", non_negative=True)
        require_decimal(self.realized_pnl, "realized_pnl")
        require_decimal(self.unrealized_pnl, "unrealized_pnl")
        require_utc_datetime(self.opened_at, "opened_at")
        require_utc_datetime(self.updated_at, "updated_at")
        if self.closed_at is not None:
            require_utc_datetime(self.closed_at, "closed_at")
        if self.status is PositionStatus.OPEN:
            if self.quantity <= 0 or self.closed_at is not None:
                raise LifecycleValidationError(
                    "OPEN position requires quantity > 0 and closed_at=None"
                )
        elif self.quantity != 0 or self.closed_at is None:
            raise LifecycleValidationError(
                "CLOSED position requires quantity=0 and closed_at"
            )


@dataclass(frozen=True, slots=True)
class AccountingEvent:
    event_id: str
    position_id: str
    event_no: int
    event_type: AccountingEventType
    delta_qty: Decimal
    price: Decimal
    fee: Decimal
    realized_pnl: Decimal
    timestamp: datetime

    def __post_init__(self) -> None:
        require_identity(self.event_id, "event_id")
        require_identity(self.position_id, "position_id")
        if type(self.event_no) is not int or self.event_no < 1:
            raise LifecycleValidationError("event_no must be int >= 1")
        if not isinstance(self.event_type, AccountingEventType):
            raise LifecycleValidationError("event_type must be AccountingEventType")
        require_decimal(self.delta_qty, "delta_qty")
        if self.delta_qty == 0:
            raise LifecycleValidationError("delta_qty must be non-zero")
        require_decimal(self.price, "price", non_negative=True)
        require_decimal(self.fee, "fee", non_negative=True)
        require_decimal(self.realized_pnl, "realized_pnl")
        require_utc_datetime(self.timestamp, "timestamp")


@dataclass(frozen=True, slots=True)
class PositionMutation:
    kind: PositionMutationKind
    position_id: str
    venue: str
    account_scope: str
    symbol: str
    side: PositionSide
    quantity: Decimal
    avg_entry_price: Decimal
    realized_pnl: Decimal
    unrealized_pnl: Decimal
    status: PositionStatus
    opened_at: datetime
    closed_at: datetime | None
    updated_at: datetime

    def __post_init__(self) -> None:
        if not isinstance(self.kind, PositionMutationKind):
            raise LifecycleValidationError("kind must be PositionMutationKind")
        PositionSnapshot(
            position_id=self.position_id,
            venue=self.venue,
            account_scope=self.account_scope,
            symbol=self.symbol,
            side=self.side,
            quantity=self.quantity,
            avg_entry_price=self.avg_entry_price,
            realized_pnl=self.realized_pnl,
            unrealized_pnl=self.unrealized_pnl,
            status=self.status,
            opened_at=self.opened_at,
            closed_at=self.closed_at,
            updated_at=self.updated_at,
        )
        if self.kind is PositionMutationKind.INSERT and self.status is not PositionStatus.OPEN:
            raise LifecycleValidationError(
                "INSERT position mutation must create an OPEN position"
            )


@dataclass(frozen=True, slots=True)
class AccountingPlan:
    events: tuple[AccountingEvent, ...]
    positions: tuple[PositionMutation, ...]

    def __post_init__(self) -> None:
        if len(self.events) not in (1, 2):
            raise LifecycleValidationError("accounting plan must contain 1 or 2 events")
        if len(self.positions) != len(self.events):
            raise LifecycleValidationError(
                "each accounting event must have one position mutation"
            )
        if tuple(event.event_no for event in self.events) != tuple(
            range(1, len(self.events) + 1)
        ):
            raise LifecycleValidationError("event numbers must be contiguous from 1")
        for event, mutation in zip(self.events, self.positions, strict=True):
            if event.position_id != mutation.position_id:
                raise LifecycleValidationError(
                    "event position_id must match its position mutation"
                )


@runtime_checkable
class PositionAccountingPolicy(Protocol):
    def plan(
        self,
        *,
        command: FillApplicationCommand,
        order_side: OrderSide,
        open_positions: Sequence[PositionSnapshot],
    ) -> AccountingPlan: ...


@runtime_checkable
class OrderAcknowledgementWriter(Protocol):
    def register_order_acknowledgement(
        self, command: OrderAcknowledgementCommand
    ) -> "OrderAcknowledgementResult": ...


@runtime_checkable
class FillSequenceWriter(Protocol):
    def apply_fill(
        self, command: FillApplicationCommand
    ) -> "FillApplicationResult": ...


@dataclass(frozen=True, slots=True)
class OrderAcknowledgementResult:
    outcome: PersistenceOutcome
    order_id: str
    stats: OperationStats = field(default_factory=OperationStats)


@dataclass(frozen=True, slots=True)
class FillApplicationResult:
    outcome: PersistenceOutcome
    fill_id: str
    event_ids: tuple[str, ...]
    position_ids: tuple[str, ...]
    stats: OperationStats = field(default_factory=OperationStats)
