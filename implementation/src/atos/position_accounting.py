"""Pure deterministic B4.3B linear netting accounting policy."""
from __future__ import annotations

from decimal import Decimal, ROUND_HALF_EVEN, localcontext
from typing import Sequence

from atos.lifecycle_types import (
    AccountingEvent,
    AccountingEventType,
    AccountingPlan,
    FillApplicationCommand,
    LifecycleInvariantError,
    OrderSide,
    PositionAccountingPolicy,
    PositionMutation,
    PositionMutationKind,
    PositionSide,
    PositionSnapshot,
    PositionStatus,
    deterministic_id,
)


_DECIMAL_PRECISION = 34
_ZERO = Decimal("0")


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


def _gross_close_pnl(
    position: PositionSnapshot,
    close_quantity: Decimal,
    fill_price: Decimal,
) -> Decimal:
    with localcontext() as ctx:
        ctx.prec = _DECIMAL_PRECISION
        ctx.rounding = ROUND_HALF_EVEN
        if position.side is PositionSide.LONG:
            return close_quantity * (
                fill_price - position.avg_entry_price
            )
        return close_quantity * (
            position.avg_entry_price - fill_price
        )


def _weighted_average(
    position: PositionSnapshot,
    added_quantity: Decimal,
    fill_price: Decimal,
) -> Decimal:
    with localcontext() as ctx:
        ctx.prec = _DECIMAL_PRECISION
        ctx.rounding = ROUND_HALF_EVEN
        total = position.quantity + added_quantity
        return (
            position.quantity * position.avg_entry_price
            + added_quantity * fill_price
        ) / total


class NettingPositionAccountingV1(PositionAccountingPolicy):
    """Opposite-first linear quantity-times-price accounting policy."""

    def plan(
        self,
        *,
        command: FillApplicationCommand,
        order_side: OrderSide,
        open_positions: Sequence[PositionSnapshot],
    ) -> AccountingPlan:
        with localcontext() as ctx:
            ctx.prec = _DECIMAL_PRECISION
            ctx.rounding = ROUND_HALF_EVEN
            return self._plan(
                command=command,
                order_side=order_side,
                open_positions=open_positions,
            )

    def _plan(
        self,
        *,
        command: FillApplicationCommand,
        order_side: OrderSide,
        open_positions: Sequence[PositionSnapshot],
    ) -> AccountingPlan:
        if not isinstance(order_side, OrderSide):
            raise LifecycleInvariantError(
                "order_side must be OrderSide"
            )

        by_side: dict[PositionSide, PositionSnapshot] = {}
        position_ids: set[str] = set()
        for position in open_positions:
            if position.status is not PositionStatus.OPEN:
                raise LifecycleInvariantError(
                    "policy received non-open position"
                )
            if (
                position.venue != command.venue
                or position.account_scope != command.account_scope
                or position.symbol != command.symbol
            ):
                raise LifecycleInvariantError(
                    "position scope does not match fill scope"
                )
            if position.position_id in position_ids:
                raise LifecycleInvariantError(
                    "duplicate open position_id"
                )
            position_ids.add(position.position_id)
            if position.side in by_side:
                raise LifecycleInvariantError(
                    f"duplicate open {position.side.value} position"
                )
            by_side[position.side] = position

        if order_side is OrderSide.BUY:
            opposite_side = PositionSide.SHORT
            target_side = PositionSide.LONG
            signed_unit = Decimal("1")
        else:
            opposite_side = PositionSide.LONG
            target_side = PositionSide.SHORT
            signed_unit = Decimal("-1")

        opposite = by_side.get(opposite_side)
        same_side = by_side.get(target_side)
        remaining = command.quantity
        events: list[AccountingEvent] = []
        mutations: list[PositionMutation] = []

        def append_event(
            *,
            event_type: AccountingEventType,
            position_id: str,
            delta_qty: Decimal,
            realized_pnl: Decimal,
            mutation: PositionMutation,
        ) -> None:
            event_no = len(events) + 1
            fee = command.fee if event_no == 1 else _ZERO
            events.append(
                AccountingEvent(
                    event_id=_event_id(command, event_no),
                    position_id=position_id,
                    event_no=event_no,
                    event_type=event_type,
                    delta_qty=delta_qty,
                    price=command.price,
                    fee=fee,
                    realized_pnl=realized_pnl,
                    timestamp=command.occurred_at,
                )
            )
            mutations.append(mutation)

        if opposite is not None:
            close_quantity = min(
                remaining, opposite.quantity
            )
            realized = _gross_close_pnl(
                opposite, close_quantity, command.price
            )
            remaining -= close_quantity
            new_quantity = opposite.quantity - close_quantity

            if new_quantity == 0:
                event_type = AccountingEventType.CLOSE
                status = PositionStatus.CLOSED
                closed_at = command.occurred_at
            else:
                event_type = AccountingEventType.REDUCE
                status = PositionStatus.OPEN
                closed_at = None

            mutation = PositionMutation(
                kind=PositionMutationKind.UPDATE,
                position_id=opposite.position_id,
                venue=opposite.venue,
                account_scope=opposite.account_scope,
                symbol=opposite.symbol,
                side=opposite.side,
                quantity=new_quantity,
                avg_entry_price=opposite.avg_entry_price,
                realized_pnl=opposite.realized_pnl + realized,
                unrealized_pnl=_ZERO,
                status=status,
                opened_at=opposite.opened_at,
                closed_at=closed_at,
                updated_at=command.recorded_at,
            )
            append_event(
                event_type=event_type,
                position_id=opposite.position_id,
                delta_qty=signed_unit * close_quantity,
                realized_pnl=realized,
                mutation=mutation,
            )

        if remaining > 0:
            if same_side is None:
                event_no = len(events) + 1
                position_id = _position_id(
                    command, target_side, event_no
                )
                event_type = AccountingEventType.OPEN
                mutation = PositionMutation(
                    kind=PositionMutationKind.INSERT,
                    position_id=position_id,
                    venue=command.venue,
                    account_scope=command.account_scope,
                    symbol=command.symbol,
                    side=target_side,
                    quantity=remaining,
                    avg_entry_price=command.price,
                    realized_pnl=_ZERO,
                    unrealized_pnl=_ZERO,
                    status=PositionStatus.OPEN,
                    opened_at=command.occurred_at,
                    closed_at=None,
                    updated_at=command.recorded_at,
                )
            else:
                position_id = same_side.position_id
                event_type = AccountingEventType.INCREASE
                mutation = PositionMutation(
                    kind=PositionMutationKind.UPDATE,
                    position_id=same_side.position_id,
                    venue=same_side.venue,
                    account_scope=same_side.account_scope,
                    symbol=same_side.symbol,
                    side=same_side.side,
                    quantity=same_side.quantity + remaining,
                    avg_entry_price=_weighted_average(
                        same_side, remaining, command.price
                    ),
                    realized_pnl=same_side.realized_pnl,
                    unrealized_pnl=_ZERO,
                    status=PositionStatus.OPEN,
                    opened_at=same_side.opened_at,
                    closed_at=None,
                    updated_at=command.recorded_at,
                )

            append_event(
                event_type=event_type,
                position_id=position_id,
                delta_qty=signed_unit * remaining,
                realized_pnl=_ZERO,
                mutation=mutation,
            )
            remaining = _ZERO

        if remaining != 0:
            raise LifecycleInvariantError(
                "fill quantity was not fully consumed"
            )
        if len(events) not in (1, 2):
            raise LifecycleInvariantError(
                "fill must produce one or two events"
            )
        if (
            len(events) == 2
            and events[0].event_type
            is not AccountingEventType.CLOSE
        ):
            raise LifecycleInvariantError(
                "two-event crossing requires event 1 to close "
                "opposite position"
            )
        if sum(
            (event.fee for event in events), _ZERO
        ) != command.fee:
            raise LifecycleInvariantError(
                "event fee sum does not equal fill fee"
            )
        if tuple(event.event_no for event in events) != tuple(
            range(1, len(events) + 1)
        ):
            raise LifecycleInvariantError(
                "event sequence is not contiguous"
            )

        return AccountingPlan(tuple(events), tuple(mutations))
