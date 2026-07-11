"""Atomic SQLite lifecycle persistence for B4.3B2.

Modular-monolith hot path: one injected RuntimeDatabase connection, one
BEGIN IMMEDIATE transaction per public mutation, typed commands/results,
and no network, ORM, internal JSON transport, or per-call reconnect.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Sequence

from atos.lifecycle_types import (
    AccountingEvent,
    AccountingEventType,
    AccountingPlan,
    DispatchAttemptStatus,
    ExecutionStatus,
    FillApplicationCommand,
    FillApplicationResult,
    FillSequenceWriter,
    LifecycleConflictError,
    LifecycleInvariantError,
    LifecyclePersistenceError,
    LifecyclePreconditionError,
    LifecycleValidationError,
    OperationStats,
    OrderAcknowledgementCommand,
    OrderAcknowledgementResult,
    OrderAcknowledgementWriter,
    OrderSide,
    OrderStatus,
    PersistenceOutcome,
    PositionAccountingPolicy,
    PositionMutation,
    PositionMutationKind,
    PositionSide,
    PositionSnapshot,
    PositionStatus,
    decimal_text,
    deterministic_id,
    require_utc_datetime,
    utc_text,
)
from atos.runtime_db import RuntimeDatabase

_ZERO = Decimal("0")


@dataclass(slots=True)
class _MutableStats:
    connection_identity: int
    reads: int = 0
    attempted: int = 0
    transactions: int = 0

    def snapshot(self, *, committed: bool) -> OperationStats:
        return OperationStats(
            read_statements=self.reads,
            attempted_mutations=self.attempted,
            committed_mutations=self.attempted if committed else 0,
            transaction_count=self.transactions,
            db_connection_identity=self.connection_identity,
        )


def _parse_utc_text(value: str, field_name: str) -> datetime:
    if not isinstance(value, str):
        raise LifecycleInvariantError(f"{field_name} must be persisted as TEXT")
    try:
        parsed = datetime.fromisoformat(
            value[:-1] + "+00:00" if value.endswith("Z") else value
        )
    except ValueError as exc:
        raise LifecycleInvariantError(
            f"{field_name} is not valid ISO-8601 UTC text"
        ) from exc
    try:
        return require_utc_datetime(parsed, field_name)
    except LifecycleValidationError as exc:
        raise LifecycleInvariantError(str(exc)) from exc


def _decimal_from_text(value: str, field_name: str) -> Decimal:
    if not isinstance(value, str):
        raise LifecycleInvariantError(f"{field_name} must be persisted as TEXT")
    try:
        parsed = Decimal(value)
    except (InvalidOperation, ValueError) as exc:
        raise LifecycleInvariantError(
            f"{field_name} is not valid Decimal text"
        ) from exc
    if not parsed.is_finite():
        raise LifecycleInvariantError(f"{field_name} must be finite")
    return parsed


def _event_id(command: FillApplicationCommand, event_no: int) -> str:
    return deterministic_id(
        "pae_",
        (
            "B4.3B:PAE:V1",
            command.venue,
            command.account_scope,
            command.fill_id,
            str(event_no),
        ),
    )


def _position_id(
    command: FillApplicationCommand,
    side: PositionSide,
    event_no: int,
) -> str:
    return deterministic_id(
        "pos_",
        (
            "B4.3B:POSITION:NETTING_V1",
            command.venue,
            command.account_scope,
            command.symbol,
            side.value,
            command.fill_id,
            str(event_no),
        ),
    )


class SqliteLifecyclePersistence(OrderAcknowledgementWriter, FillSequenceWriter):
    """Concrete atomic lifecycle writer using one injected SQLite authority."""

    def __init__(
        self,
        db: RuntimeDatabase,
        accounting_policy: PositionAccountingPolicy,
    ) -> None:
        if not isinstance(db, RuntimeDatabase):
            raise LifecycleValidationError("db must be RuntimeDatabase")
        if not isinstance(accounting_policy, PositionAccountingPolicy):
            raise LifecycleValidationError(
                "accounting_policy must implement PositionAccountingPolicy"
            )
        self._db = db
        self._accounting_policy = accounting_policy

    def _after_mutation(
        self,
        boundary: str,
        connection: sqlite3.Connection,
    ) -> None:
        """Test seam for injected crashes; production implementation is a no-op."""
        del boundary, connection

    @staticmethod
    def _read(
        connection: sqlite3.Connection,
        stats: _MutableStats,
        sql: str,
        parameters: Sequence[Any],
    ) -> sqlite3.Cursor:
        stats.reads += 1
        return connection.execute(sql, tuple(parameters))

    def _mutate(
        self,
        connection: sqlite3.Connection,
        stats: _MutableStats,
        boundary: str,
        sql: str,
        parameters: Sequence[Any],
    ) -> sqlite3.Cursor:
        stats.attempted += 1
        cursor = connection.execute(sql, tuple(parameters))
        self._after_mutation(boundary, connection)
        return cursor

    @staticmethod
    def _ensure_connection_stable(
        db: RuntimeDatabase,
        connection: sqlite3.Connection,
    ) -> None:
        if db.connection is not connection:
            raise LifecycleInvariantError(
                "RuntimeDatabase connection changed inside lifecycle operation"
            )

    @staticmethod
    def _order_payload(command: OrderAcknowledgementCommand) -> tuple[str, ...]:
        return (
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
            utc_text(command.acknowledged_at),
        )

    @staticmethod
    def _fill_payload(command: FillApplicationCommand) -> tuple[str, ...]:
        return (
            command.venue,
            command.account_scope,
            command.fill_id,
            command.order_id,
            command.symbol,
            decimal_text(command.quantity),
            decimal_text(command.price),
            decimal_text(command.fee),
            command.fee_currency,
            utc_text(command.occurred_at),
        )

    @staticmethod
    def _raise_with_stats(
        error_type: type[LifecyclePersistenceError],
        message: str,
        stats: _MutableStats,
        cause: BaseException | None = None,
    ) -> None:
        error = error_type(message, stats.snapshot(committed=False))
        if cause is None:
            raise error
        raise error from cause

    @staticmethod
    def _validate_plan(
        command: FillApplicationCommand,
        order_side: OrderSide,
        open_positions: Sequence[PositionSnapshot],
        plan: AccountingPlan,
    ) -> None:
        """Reject a corrupt injected policy before the first authoritative write."""
        if not isinstance(plan, AccountingPlan):
            raise LifecycleInvariantError("accounting policy must return AccountingPlan")

        snapshots = {position.position_id: position for position in open_positions}
        expected_sign = Decimal("1") if order_side is OrderSide.BUY else Decimal("-1")
        target_side = PositionSide.LONG if order_side is OrderSide.BUY else PositionSide.SHORT
        opposite_side = (
            PositionSide.SHORT if order_side is OrderSide.BUY else PositionSide.LONG
        )
        total_abs_delta = _ZERO
        total_fee = _ZERO
        position_ids: list[str] = []

        for event, mutation in zip(plan.events, plan.positions, strict=True):
            if event.event_id != _event_id(command, event.event_no):
                raise LifecycleInvariantError("policy produced a non-deterministic event_id")
            if event.timestamp != command.occurred_at:
                raise LifecycleInvariantError("policy event timestamp must equal occurred_at")
            if event.price != command.price:
                raise LifecycleInvariantError("policy event price must equal fill price")
            if event.delta_qty * expected_sign <= 0:
                raise LifecycleInvariantError("policy event delta direction contradicts order side")
            total_abs_delta += abs(event.delta_qty)
            total_fee += event.fee

            expected_fee = command.fee if event.event_no == 1 else _ZERO
            if event.fee != expected_fee:
                raise LifecycleInvariantError("policy fee attribution is not deterministic")
            if event.event_type in (
                AccountingEventType.OPEN,
                AccountingEventType.INCREASE,
            ) and event.realized_pnl != 0:
                raise LifecycleInvariantError(
                    "OPEN/INCREASE event realized_pnl must be zero"
                )

            if (
                mutation.venue != command.venue
                or mutation.account_scope != command.account_scope
                or mutation.symbol != command.symbol
            ):
                raise LifecycleInvariantError(
                    "policy position mutation scope does not match fill scope"
                )
            if mutation.updated_at != command.recorded_at:
                raise LifecycleInvariantError(
                    "policy position updated_at must equal recorded_at"
                )
            if mutation.unrealized_pnl != 0:
                raise LifecycleInvariantError(
                    "policy position unrealized_pnl must be zero without a mark"
                )

            if event.event_type is AccountingEventType.OPEN:
                if (
                    mutation.kind is not PositionMutationKind.INSERT
                    or mutation.status is not PositionStatus.OPEN
                    or mutation.side is not target_side
                    or mutation.opened_at != command.occurred_at
                    or mutation.closed_at is not None
                    or mutation.position_id
                    != _position_id(command, mutation.side, event.event_no)
                    or mutation.quantity != abs(event.delta_qty)
                    or mutation.avg_entry_price != command.price
                    or mutation.realized_pnl != 0
                ):
                    raise LifecycleInvariantError("invalid OPEN position mutation")
            else:
                if mutation.kind is not PositionMutationKind.UPDATE:
                    raise LifecycleInvariantError(
                        "non-OPEN accounting event must update an existing position"
                    )
                previous = snapshots.get(mutation.position_id)
                if previous is None:
                    raise LifecycleInvariantError(
                        "policy update does not target an authoritative open snapshot"
                    )
                if (
                    mutation.venue != previous.venue
                    or mutation.account_scope != previous.account_scope
                    or mutation.symbol != previous.symbol
                    or mutation.side is not previous.side
                    or mutation.opened_at != previous.opened_at
                ):
                    raise LifecycleInvariantError(
                        "policy update changed immutable position identity"
                    )

                if event.event_type is AccountingEventType.INCREASE:
                    if (
                        mutation.side is not target_side
                        or mutation.status is not PositionStatus.OPEN
                        or mutation.closed_at is not None
                        or mutation.quantity - previous.quantity
                        != abs(event.delta_qty)
                        or mutation.realized_pnl != previous.realized_pnl
                    ):
                        raise LifecycleInvariantError("invalid INCREASE position mutation")
                elif event.event_type is AccountingEventType.REDUCE:
                    if (
                        mutation.side is not opposite_side
                        or mutation.status is not PositionStatus.OPEN
                        or mutation.closed_at is not None
                        or previous.quantity - mutation.quantity
                        != abs(event.delta_qty)
                        or mutation.avg_entry_price != previous.avg_entry_price
                        or mutation.realized_pnl
                        != previous.realized_pnl + event.realized_pnl
                    ):
                        raise LifecycleInvariantError("invalid REDUCE position mutation")
                elif event.event_type is AccountingEventType.CLOSE:
                    if (
                        mutation.side is not opposite_side
                        or mutation.status is not PositionStatus.CLOSED
                        or mutation.quantity != 0
                        or mutation.closed_at != command.occurred_at
                        or previous.quantity != abs(event.delta_qty)
                        or mutation.avg_entry_price != previous.avg_entry_price
                        or mutation.realized_pnl
                        != previous.realized_pnl + event.realized_pnl
                    ):
                        raise LifecycleInvariantError("invalid CLOSE position mutation")
                else:
                    raise LifecycleInvariantError("unknown accounting event type")

            position_ids.append(mutation.position_id)

        if total_abs_delta != command.quantity:
            raise LifecycleInvariantError("policy event deltas do not consume fill quantity")
        if total_fee != command.fee:
            raise LifecycleInvariantError("policy event fees do not equal fill fee")
        if len(plan.events) == 2:
            if plan.events[0].event_type is not AccountingEventType.CLOSE:
                raise LifecycleInvariantError(
                    "two-event zero crossing must close the opposite position first"
                )
            if plan.events[1].event_type not in (
                AccountingEventType.OPEN,
                AccountingEventType.INCREASE,
            ):
                raise LifecycleInvariantError(
                    "zero-crossing second event must OPEN or INCREASE"
                )
            if len(set(position_ids)) != 2:
                raise LifecycleInvariantError(
                    "zero-crossing events must affect two distinct positions"
                )

    @staticmethod
    def _validate_replay_events(
        command: FillApplicationCommand,
        rows: Sequence[sqlite3.Row],
    ) -> tuple[tuple[str, ...], tuple[str, ...]]:
        if len(rows) not in (1, 2):
            raise LifecycleInvariantError(
                "replayed fill has an incomplete or excessive accounting sequence"
            )

        expected_numbers = tuple(range(1, len(rows) + 1))
        actual_numbers = tuple(row["source_fill_event_no"] for row in rows)
        if actual_numbers != expected_numbers:
            raise LifecycleInvariantError(
                "replayed fill accounting sequence is not contiguous"
            )

        total_abs_delta = _ZERO
        total_fee = _ZERO
        delta_sign: int | None = None
        position_ids: list[str] = []
        for row in rows:
            event_no = row["source_fill_event_no"]
            if row["event_id"] != _event_id(command, event_no):
                raise LifecycleInvariantError(
                    "replayed fill accounting event_id is not deterministic"
                )
            if row["source_fill_symbol"] != command.symbol:
                raise LifecycleInvariantError(
                    "replayed fill accounting symbol does not match fill"
                )
            if _decimal_from_text(row["price"], "event price") != command.price:
                raise LifecycleInvariantError(
                    "replayed fill accounting price does not match fill"
                )
            if _parse_utc_text(row["timestamp"], "event timestamp") != command.occurred_at:
                raise LifecycleInvariantError(
                    "replayed fill accounting timestamp does not match fill"
                )

            fee = _decimal_from_text(row["fee"], "event fee")
            expected_fee = command.fee if event_no == 1 else _ZERO
            if fee != expected_fee:
                raise LifecycleInvariantError(
                    "replayed fill accounting fee attribution is invalid"
                )
            total_fee += fee

            delta = _decimal_from_text(row["delta_qty"], "event delta_qty")
            if delta == 0:
                raise LifecycleInvariantError("replayed accounting delta cannot be zero")
            current_sign = 1 if delta > 0 else -1
            if delta_sign is None:
                delta_sign = current_sign
            elif delta_sign != current_sign:
                raise LifecycleInvariantError(
                    "replayed accounting deltas have inconsistent directions"
                )
            total_abs_delta += abs(delta)
            position_ids.append(row["position_id"])

        if total_fee != command.fee:
            raise LifecycleInvariantError("replayed event fees do not equal fill fee")
        if total_abs_delta != command.quantity:
            raise LifecycleInvariantError(
                "replayed event deltas do not consume fill quantity"
            )
        if len(rows) == 2:
            if rows[0]["event_type"] != AccountingEventType.CLOSE.value:
                raise LifecycleInvariantError(
                    "replayed zero crossing does not close first"
                )
            if rows[1]["event_type"] not in (
                AccountingEventType.OPEN.value,
                AccountingEventType.INCREASE.value,
            ):
                raise LifecycleInvariantError(
                    "replayed zero crossing has invalid second event"
                )
            if len(set(position_ids)) != 2:
                raise LifecycleInvariantError(
                    "replayed zero crossing does not affect distinct positions"
                )

        return (
            tuple(row["event_id"] for row in rows),
            tuple(position_ids),
        )

    def register_order_acknowledgement(
        self,
        command: OrderAcknowledgementCommand,
    ) -> OrderAcknowledgementResult:
        if not isinstance(command, OrderAcknowledgementCommand):
            raise LifecycleValidationError(
                "command must be OrderAcknowledgementCommand",
                OperationStats(),
            )

        connection = self._db.connection
        stats = _MutableStats(connection_identity=id(connection))
        if connection.in_transaction:
            raise LifecyclePreconditionError(
                "nested lifecycle transaction is forbidden",
                stats.snapshot(committed=False),
            )

        replay = False
        try:
            stats.transactions = 1
            with self._db.transaction(immediate=True) as tx:
                row = self._read(
                    tx,
                    stats,
                    """
                    SELECT venue, account_scope, order_id, execution_intent_id,
                           attempt_id, client_order_id, symbol, side, quantity,
                           price, order_type, created_at
                    FROM order_states
                    WHERE venue = ? AND account_scope = ? AND order_id = ?
                    """,
                    (command.venue, command.account_scope, command.order_id),
                ).fetchone()

                if row is not None:
                    if tuple(row) != self._order_payload(command):
                        self._raise_with_stats(
                            LifecycleConflictError,
                            "authoritative order identity exists with conflicting payload",
                            stats,
                        )
                    replay = True
                else:
                    cursor = self._mutate(
                        tx,
                        stats,
                        "order_ack.dispatch_accept",
                        """
                        UPDATE dispatch_attempts
                        SET status = ?, response_received_at = ?
                        WHERE execution_intent_id = ?
                          AND attempt_id = ?
                          AND venue = ?
                          AND account_scope = ?
                          AND client_order_id = ?
                          AND status = ?
                        """,
                        (
                            DispatchAttemptStatus.ACCEPTED.value,
                            utc_text(command.acknowledged_at),
                            command.execution_intent_id,
                            command.attempt_id,
                            command.venue,
                            command.account_scope,
                            command.client_order_id,
                            DispatchAttemptStatus.SUBMITTED.value,
                        ),
                    )
                    if cursor.rowcount != 1:
                        self._raise_with_stats(
                            LifecyclePreconditionError,
                            "dispatch attempt is not the exact SUBMITTED owner",
                            stats,
                        )

                    self._mutate(
                        tx,
                        stats,
                        "order_ack.order_insert",
                        """
                        INSERT INTO order_states (
                            venue, account_scope, order_id, execution_intent_id,
                            attempt_id, client_order_id, symbol, side, quantity,
                            price, order_type, status, created_at, updated_at
                        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                        """,
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
                            OrderStatus.OPEN.value,
                            utc_text(command.acknowledged_at),
                            utc_text(command.acknowledged_at),
                        ),
                    )

                    cursor = self._mutate(
                        tx,
                        stats,
                        "order_ack.execution_acknowledge",
                        """
                        UPDATE execution_states
                        SET status = ?, state_started_at = ?, updated_at = ?
                        WHERE execution_intent_id = ?
                          AND last_attempt_id = ?
                          AND status = ?
                        """,
                        (
                            ExecutionStatus.ACKNOWLEDGED.value,
                            utc_text(command.acknowledged_at),
                            utc_text(command.acknowledged_at),
                            command.execution_intent_id,
                            command.attempt_id,
                            ExecutionStatus.DISPATCHED.value,
                        ),
                    )
                    if cursor.rowcount != 1:
                        self._raise_with_stats(
                            LifecyclePreconditionError,
                            "execution state is not DISPATCHED for the exact attempt",
                            stats,
                        )

                self._ensure_connection_stable(self._db, connection)
        except LifecyclePersistenceError as exc:
            self._raise_with_stats(type(exc), str(exc), stats, exc)
        except sqlite3.IntegrityError as exc:
            self._raise_with_stats(
                LifecycleInvariantError,
                "order acknowledgement violated an authoritative database constraint",
                stats,
                exc,
            )
        except sqlite3.Error as exc:
            self._raise_with_stats(
                LifecycleInvariantError,
                "order acknowledgement SQLite operation failed",
                stats,
                exc,
            )
        except Exception as exc:
            self._raise_with_stats(
                LifecycleInvariantError,
                "order acknowledgement aborted by injected or unexpected failure",
                stats,
                exc,
            )

        return OrderAcknowledgementResult(
            outcome=(
                PersistenceOutcome.REPLAY_NOOP
                if replay
                else PersistenceOutcome.APPLIED
            ),
            order_id=command.order_id,
            stats=stats.snapshot(committed=True),
        )

    def apply_fill(
        self,
        command: FillApplicationCommand,
    ) -> FillApplicationResult:
        if not isinstance(command, FillApplicationCommand):
            raise LifecycleValidationError(
                "command must be FillApplicationCommand",
                OperationStats(),
            )

        connection = self._db.connection
        stats = _MutableStats(connection_identity=id(connection))
        if connection.in_transaction:
            raise LifecyclePreconditionError(
                "nested lifecycle transaction is forbidden",
                stats.snapshot(committed=False),
            )

        replay_event_ids: tuple[str, ...] = ()
        replay_position_ids: tuple[str, ...] = ()
        applied_plan: AccountingPlan | None = None

        try:
            stats.transactions = 1
            with self._db.transaction(immediate=True) as tx:
                existing = self._read(
                    tx,
                    stats,
                    """
                    SELECT venue, account_scope, fill_id, order_id, symbol,
                           quantity, price, fee, fee_currency, timestamp
                    FROM fill_states
                    WHERE venue = ? AND account_scope = ? AND fill_id = ?
                    """,
                    (command.venue, command.account_scope, command.fill_id),
                ).fetchone()

                if existing is not None:
                    if tuple(existing) != self._fill_payload(command):
                        self._raise_with_stats(
                            LifecycleConflictError,
                            "authoritative fill identity exists with conflicting payload",
                            stats,
                        )
                    event_rows = self._read(
                        tx,
                        stats,
                        """
                        SELECT event_id, position_id, source_fill_event_no,
                               source_fill_symbol, event_type, delta_qty,
                               price, fee, realized_pnl, timestamp
                        FROM position_accounting_details
                        WHERE source_fill_venue = ?
                          AND source_fill_account_scope = ?
                          AND source_fill_id = ?
                        ORDER BY source_fill_event_no
                        """,
                        (command.venue, command.account_scope, command.fill_id),
                    ).fetchall()
                    replay_event_ids, replay_position_ids = self._validate_replay_events(
                        command,
                        event_rows,
                    )
                else:
                    order = self._read(
                        tx,
                        stats,
                        """
                        SELECT symbol, side, status
                        FROM order_states
                        WHERE venue = ? AND account_scope = ? AND order_id = ?
                        """,
                        (command.venue, command.account_scope, command.order_id),
                    ).fetchone()
                    if order is None:
                        self._raise_with_stats(
                            LifecyclePreconditionError,
                            "authoritative order does not exist in fill scope",
                            stats,
                        )
                    if order["symbol"] != command.symbol:
                        self._raise_with_stats(
                            LifecyclePreconditionError,
                            "fill symbol does not match authoritative order",
                            stats,
                        )
                    try:
                        order_side = OrderSide(order["side"])
                        current_status = OrderStatus(order["status"])
                    except ValueError as exc:
                        self._raise_with_stats(
                            LifecycleInvariantError,
                            "authoritative order contains an unknown enum value",
                            stats,
                            exc,
                        )

                    allowed_targets = {
                        OrderStatus.OPEN: {
                            OrderStatus.PARTIALLY_FILLED,
                            OrderStatus.FILLED,
                        },
                        OrderStatus.PARTIALLY_FILLED: {
                            OrderStatus.PARTIALLY_FILLED,
                            OrderStatus.FILLED,
                        },
                    }
                    if command.order_status_after not in allowed_targets.get(
                        current_status,
                        set(),
                    ):
                        self._raise_with_stats(
                            LifecyclePreconditionError,
                            "fill has an invalid order status transition",
                            stats,
                        )

                    position_rows = self._read(
                        tx,
                        stats,
                        """
                        SELECT position_id, venue, account_scope, symbol, side,
                               quantity, avg_entry_price, realized_pnl,
                               unrealized_pnl, status, opened_at, closed_at,
                               updated_at
                        FROM position_states
                        WHERE venue = ? AND account_scope = ? AND symbol = ?
                          AND status = ?
                        ORDER BY side, position_id
                        """,
                        (
                            command.venue,
                            command.account_scope,
                            command.symbol,
                            PositionStatus.OPEN.value,
                        ),
                    ).fetchall()
                    open_positions = tuple(
                        self._position_snapshot_from_row(row)
                        for row in position_rows
                    )
                    applied_plan = self._accounting_policy.plan(
                        command=command,
                        order_side=order_side,
                        open_positions=open_positions,
                    )
                    self._validate_plan(
                        command,
                        order_side,
                        open_positions,
                        applied_plan,
                    )

                    tx.execute("PRAGMA defer_foreign_keys = ON")
                    self._mutate(
                        tx,
                        stats,
                        "fill.fill_insert",
                        """
                        INSERT INTO fill_states (
                            venue, account_scope, fill_id, order_id, symbol,
                            quantity, price, fee, fee_currency, timestamp
                        ) VALUES (?,?,?,?,?,?,?,?,?,?)
                        """,
                        (
                            command.venue,
                            command.account_scope,
                            command.fill_id,
                            command.order_id,
                            command.symbol,
                            decimal_text(command.quantity),
                            decimal_text(command.price),
                            decimal_text(command.fee),
                            command.fee_currency,
                            utc_text(command.occurred_at),
                        ),
                    )

                    cursor = self._mutate(
                        tx,
                        stats,
                        "fill.order_update",
                        """
                        UPDATE order_states
                        SET status = ?, updated_at = ?
                        WHERE venue = ? AND account_scope = ? AND order_id = ?
                          AND symbol = ? AND status = ?
                        """,
                        (
                            command.order_status_after.value,
                            utc_text(command.recorded_at),
                            command.venue,
                            command.account_scope,
                            command.order_id,
                            command.symbol,
                            current_status.value,
                        ),
                    )
                    if cursor.rowcount != 1:
                        self._raise_with_stats(
                            LifecyclePreconditionError,
                            "authoritative order changed before fill application",
                            stats,
                        )

                    for event, mutation in zip(
                        applied_plan.events,
                        applied_plan.positions,
                        strict=True,
                    ):
                        self._insert_accounting_event(tx, stats, command, event)
                        self._apply_position_mutation(
                            tx,
                            stats,
                            event.event_no,
                            mutation,
                        )

                self._ensure_connection_stable(self._db, connection)
        except LifecyclePersistenceError as exc:
            self._raise_with_stats(type(exc), str(exc), stats, exc)
        except sqlite3.IntegrityError as exc:
            self._raise_with_stats(
                LifecycleInvariantError,
                "fill application violated an authoritative database constraint",
                stats,
                exc,
            )
        except sqlite3.Error as exc:
            self._raise_with_stats(
                LifecycleInvariantError,
                "fill application SQLite operation failed",
                stats,
                exc,
            )
        except Exception as exc:
            self._raise_with_stats(
                LifecycleInvariantError,
                "fill application aborted by injected or unexpected failure",
                stats,
                exc,
            )

        if applied_plan is None:
            return FillApplicationResult(
                outcome=PersistenceOutcome.REPLAY_NOOP,
                fill_id=command.fill_id,
                event_ids=replay_event_ids,
                position_ids=replay_position_ids,
                stats=stats.snapshot(committed=True),
            )
        return FillApplicationResult(
            outcome=PersistenceOutcome.APPLIED,
            fill_id=command.fill_id,
            event_ids=tuple(event.event_id for event in applied_plan.events),
            position_ids=tuple(
                mutation.position_id for mutation in applied_plan.positions
            ),
            stats=stats.snapshot(committed=True),
        )

    @staticmethod
    def _position_snapshot_from_row(row: sqlite3.Row) -> PositionSnapshot:
        try:
            side = PositionSide(row["side"])
            status = PositionStatus(row["status"])
        except ValueError as exc:
            raise LifecycleInvariantError(
                "position row contains an unknown enum value"
            ) from exc
        closed_at = (
            None
            if row["closed_at"] is None
            else _parse_utc_text(row["closed_at"], "closed_at")
        )
        return PositionSnapshot(
            position_id=row["position_id"],
            venue=row["venue"],
            account_scope=row["account_scope"],
            symbol=row["symbol"],
            side=side,
            quantity=_decimal_from_text(row["quantity"], "quantity"),
            avg_entry_price=_decimal_from_text(
                row["avg_entry_price"],
                "avg_entry_price",
            ),
            realized_pnl=_decimal_from_text(
                row["realized_pnl"],
                "realized_pnl",
            ),
            unrealized_pnl=_decimal_from_text(
                row["unrealized_pnl"],
                "unrealized_pnl",
            ),
            status=status,
            opened_at=_parse_utc_text(row["opened_at"], "opened_at"),
            closed_at=closed_at,
            updated_at=_parse_utc_text(row["updated_at"], "updated_at"),
        )

    def _insert_accounting_event(
        self,
        connection: sqlite3.Connection,
        stats: _MutableStats,
        command: FillApplicationCommand,
        event: AccountingEvent,
    ) -> None:
        self._mutate(
            connection,
            stats,
            f"fill.accounting_event_{event.event_no}",
            """
            INSERT INTO position_accounting_details (
                event_id, position_id, source_fill_venue,
                source_fill_account_scope, source_fill_id,
                source_fill_symbol, source_fill_event_no, event_type,
                delta_qty, price, fee, realized_pnl, timestamp
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                event.event_id,
                event.position_id,
                command.venue,
                command.account_scope,
                command.fill_id,
                command.symbol,
                event.event_no,
                event.event_type.value,
                decimal_text(event.delta_qty),
                decimal_text(event.price),
                decimal_text(event.fee),
                decimal_text(event.realized_pnl),
                utc_text(event.timestamp),
            ),
        )

    def _apply_position_mutation(
        self,
        connection: sqlite3.Connection,
        stats: _MutableStats,
        event_no: int,
        mutation: PositionMutation,
    ) -> None:
        if mutation.kind is PositionMutationKind.INSERT:
            self._mutate(
                connection,
                stats,
                f"fill.position_{event_no}_insert",
                """
                INSERT INTO position_states (
                    position_id, venue, account_scope, symbol, side, quantity,
                    avg_entry_price, realized_pnl, unrealized_pnl, status,
                    opened_at, closed_at, updated_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    mutation.position_id,
                    mutation.venue,
                    mutation.account_scope,
                    mutation.symbol,
                    mutation.side.value,
                    decimal_text(mutation.quantity),
                    decimal_text(mutation.avg_entry_price),
                    decimal_text(mutation.realized_pnl),
                    decimal_text(mutation.unrealized_pnl),
                    mutation.status.value,
                    utc_text(mutation.opened_at),
                    (
                        None
                        if mutation.closed_at is None
                        else utc_text(mutation.closed_at)
                    ),
                    utc_text(mutation.updated_at),
                ),
            )
            return

        if mutation.kind is not PositionMutationKind.UPDATE:
            raise LifecycleInvariantError("unknown position mutation kind")

        cursor = self._mutate(
            connection,
            stats,
            f"fill.position_{event_no}_update",
            """
            UPDATE position_states
            SET quantity = ?, avg_entry_price = ?, realized_pnl = ?,
                unrealized_pnl = ?, status = ?, closed_at = ?, updated_at = ?
            WHERE position_id = ? AND venue = ? AND account_scope = ?
              AND symbol = ? AND side = ? AND status = ?
            """,
            (
                decimal_text(mutation.quantity),
                decimal_text(mutation.avg_entry_price),
                decimal_text(mutation.realized_pnl),
                decimal_text(mutation.unrealized_pnl),
                mutation.status.value,
                (
                    None
                    if mutation.closed_at is None
                    else utc_text(mutation.closed_at)
                ),
                utc_text(mutation.updated_at),
                mutation.position_id,
                mutation.venue,
                mutation.account_scope,
                mutation.symbol,
                mutation.side.value,
                PositionStatus.OPEN.value,
            ),
        )
        if cursor.rowcount != 1:
            self._raise_with_stats(
                LifecyclePreconditionError,
                "planned position update did not match one open authoritative row",
                stats,
            )
