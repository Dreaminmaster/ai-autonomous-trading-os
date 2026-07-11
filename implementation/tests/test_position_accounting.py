from __future__ import annotations

import inspect
from dataclasses import FrozenInstanceError
from datetime import datetime, timedelta, timezone
from decimal import Decimal, getcontext

import pytest

from atos.lifecycle_types import (
    AccountingEventType,
    FillApplicationCommand,
    LifecycleInvariantError,
    LifecyclePersistenceError,
    LifecycleValidationError,
    OperationStats,
    OrderAcknowledgementCommand,
    OrderSide,
    OrderStatus,
    OrderType,
    PositionMutationKind,
    PositionSide,
    PositionSnapshot,
    PositionStatus,
    decimal_text,
    deterministic_id,
    length_delimited_bytes,
    require_identity,
    require_utc_datetime,
    utc_text,
)
from atos.position_accounting import NettingPositionAccountingV1


UTC = timezone.utc
T0 = datetime(2026, 7, 11, 10, 0, tzinfo=UTC)
T1 = datetime(2026, 7, 11, 10, 0, 1, tzinfo=UTC)


def fill(
    *,
    side_status: OrderStatus = OrderStatus.PARTIALLY_FILLED,
    fill_id: str = "fill-1",
    quantity: str = "2",
    price: str = "120",
    fee: str = "3",
) -> FillApplicationCommand:
    return FillApplicationCommand(
        venue="okx_paper",
        account_scope="spot-main",
        fill_id=fill_id,
        order_id="order-1",
        symbol="BTC/USDT",
        quantity=Decimal(quantity),
        price=Decimal(price),
        fee=Decimal(fee),
        fee_currency="USDT",
        occurred_at=T0,
        recorded_at=T1,
        order_status_after=side_status,
    )


def position(
    side: PositionSide,
    *,
    position_id: str | None = None,
    quantity: str = "5",
    avg: str = "100",
    realized: str = "7",
    unrealized: str = "9",
    venue: str = "okx_paper",
    account_scope: str = "spot-main",
    symbol: str = "BTC/USDT",
    status: PositionStatus = PositionStatus.OPEN,
) -> PositionSnapshot:
    closed_at = None if status is PositionStatus.OPEN else T0
    qty = Decimal(quantity) if status is PositionStatus.OPEN else Decimal("0")
    return PositionSnapshot(
        position_id=position_id or f"pos-{side.value.lower()}",
        venue=venue,
        account_scope=account_scope,
        symbol=symbol,
        side=side,
        quantity=qty,
        avg_entry_price=Decimal(avg),
        realized_pnl=Decimal(realized),
        unrealized_pnl=Decimal(unrealized),
        status=status,
        opened_at=T0 - timedelta(days=1),
        closed_at=closed_at,
        updated_at=T0 - timedelta(minutes=1),
    )


def plan(
    order_side: OrderSide,
    command: FillApplicationCommand,
    *positions: PositionSnapshot,
):
    return NettingPositionAccountingV1().plan(
        command=command,
        order_side=order_side,
        open_positions=positions,
    )


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (Decimal("1.2300"), "1.23"),
        (Decimal("0E-8"), "0"),
        (Decimal("-0.000"), "0"),
        (Decimal("100"), "100"),
        (Decimal("-12.3400"), "-12.34"),
        (Decimal("1E+3"), "1000"),
    ],
)
def test_decimal_text_is_canonical(value, expected):
    assert decimal_text(value) == expected


@pytest.mark.parametrize(
    "value",
    [1.2, "1", Decimal("NaN"), Decimal("Infinity")],
)
def test_decimal_validation_rejects_non_decimal_or_non_finite(value):
    with pytest.raises(LifecycleValidationError):
        decimal_text(value)


def test_utc_validation_and_serialization():
    assert utc_text(T0) == "2026-07-11T10:00:00Z"
    with pytest.raises(LifecycleValidationError):
        require_utc_datetime(datetime(2026, 7, 11, 10, 0), "t")
    with pytest.raises(LifecycleValidationError):
        require_utc_datetime(
            datetime(
                2026,
                7,
                11,
                18,
                0,
                tzinfo=timezone(timedelta(hours=8)),
            ),
            "t",
        )


def test_identity_rejects_empty_and_whitespace_but_preserves_bytes():
    with pytest.raises(LifecycleValidationError):
        require_identity("", "x")
    with pytest.raises(LifecycleValidationError):
        require_identity("  \t", "x")
    assert require_identity(" BTC/USDT ", "x") == " BTC/USDT "


def test_command_runtime_types_are_enforced():
    with pytest.raises(LifecycleValidationError):
        fill(side_status="FILLED")
    with pytest.raises(LifecycleValidationError):
        OrderAcknowledgementCommand(
            venue="okx_paper",
            account_scope="spot-main",
            order_id="o",
            execution_intent_id="ei",
            attempt_id="a",
            client_order_id="c",
            symbol="BTC/USDT",
            side="BUY",
            quantity=Decimal("1"),
            price=Decimal("0"),
            order_type=OrderType.MARKET,
            acknowledged_at=T0,
        )


def test_length_delimited_encoding_prevents_ambiguous_sequences():
    assert length_delimited_bytes(("ab", "c")) != length_delimited_bytes(
        ("a", "bc")
    )
    assert length_delimited_bytes(("é",)) == b"2:\xc3\xa9"


def test_deterministic_ids_match_fixed_vectors():
    assert deterministic_id(
        "pae_",
        (
            "B4.3B:PAE:V1",
            "okx_paper",
            "spot-main",
            "fill-1",
            "1",
        ),
    ) == (
        "pae_2f8ad840cfc2689fcd2b45c1ccc3453b83dc0982338f8f8911be754176c296f8"
    )
    assert deterministic_id(
        "pos_",
        (
            "B4.3B:POSITION:NETTING_V1",
            "okx_paper",
            "spot-main",
            "BTC/USDT",
            "LONG",
            "fill-1",
            "1",
        ),
    ) == (
        "pos_0c1fca3b65cbb8880095b13f99133f0103c54e78e02c374eb7c91e03029c75d4"
    )


def test_buy_opens_long_with_fee_separate_from_realized_pnl():
    result = plan(
        OrderSide.BUY,
        fill(quantity="2", price="120", fee="3"),
    )
    event = result.events[0]
    mutation = result.positions[0]
    assert event.event_type is AccountingEventType.OPEN
    assert event.delta_qty == Decimal("2")
    assert event.fee == Decimal("3")
    assert event.realized_pnl == 0
    assert event.timestamp == T0
    assert mutation.kind is PositionMutationKind.INSERT
    assert mutation.side is PositionSide.LONG
    assert mutation.quantity == 2
    assert mutation.avg_entry_price == 120
    assert mutation.realized_pnl == 0
    assert mutation.opened_at == T0
    assert mutation.updated_at == T1


def test_sell_opens_short():
    result = plan(OrderSide.SELL, fill(quantity="2", price="120"))
    assert result.events[0].event_type is AccountingEventType.OPEN
    assert result.events[0].delta_qty == Decimal("-2")
    assert result.positions[0].side is PositionSide.SHORT


def test_buy_increases_long_and_uses_explicit_decimal_context():
    old_precision = getcontext().prec
    try:
        getcontext().prec = 3
        result = plan(
            OrderSide.BUY,
            fill(quantity="2", price="130", fee="1"),
            position(PositionSide.LONG, quantity="3", avg="100"),
        )
    finally:
        getcontext().prec = old_precision

    event = result.events[0]
    mutation = result.positions[0]
    assert event.event_type is AccountingEventType.INCREASE
    assert event.realized_pnl == 0
    assert event.fee == 1
    assert mutation.quantity == 5
    assert mutation.avg_entry_price == Decimal("112")
    assert mutation.realized_pnl == 7
    assert mutation.unrealized_pnl == 0


def test_sell_reduces_long_and_records_gross_pnl_not_net_of_fee():
    result = plan(
        OrderSide.SELL,
        fill(quantity="2", price="120", fee="3"),
        position(
            PositionSide.LONG,
            quantity="5",
            avg="100",
            realized="7",
        ),
    )
    event = result.events[0]
    mutation = result.positions[0]
    assert event.event_type is AccountingEventType.REDUCE
    assert event.delta_qty == -2
    assert event.realized_pnl == 40
    assert event.fee == 3
    assert mutation.quantity == 3
    assert mutation.realized_pnl == 47
    assert mutation.avg_entry_price == 100
    assert mutation.status is PositionStatus.OPEN
    assert mutation.closed_at is None


def test_sell_closes_long():
    result = plan(
        OrderSide.SELL,
        fill(quantity="5", price="80", fee="2"),
        position(
            PositionSide.LONG,
            quantity="5",
            avg="100",
            realized="7",
        ),
    )
    event = result.events[0]
    mutation = result.positions[0]
    assert event.event_type is AccountingEventType.CLOSE
    assert event.realized_pnl == -100
    assert mutation.quantity == 0
    assert mutation.realized_pnl == -93
    assert mutation.status is PositionStatus.CLOSED
    assert mutation.closed_at == T0


def test_buy_reduces_short():
    result = plan(
        OrderSide.BUY,
        fill(quantity="2", price="80", fee="4"),
        position(
            PositionSide.SHORT,
            quantity="5",
            avg="100",
            realized="7",
        ),
    )
    assert result.events[0].event_type is AccountingEventType.REDUCE
    assert result.events[0].delta_qty == 2
    assert result.events[0].realized_pnl == 40
    assert result.positions[0].quantity == 3
    assert result.positions[0].realized_pnl == 47


def test_buy_closes_short():
    result = plan(
        OrderSide.BUY,
        fill(quantity="5", price="120", fee="4"),
        position(
            PositionSide.SHORT,
            quantity="5",
            avg="100",
            realized="7",
        ),
    )
    assert result.events[0].event_type is AccountingEventType.CLOSE
    assert result.events[0].realized_pnl == -100
    assert result.positions[0].status is PositionStatus.CLOSED


def test_sell_crosses_long_to_new_short_with_two_events_and_fee_once():
    command = fill(quantity="8", price="120", fee="3")
    result = plan(
        OrderSide.SELL,
        command,
        position(
            PositionSide.LONG,
            quantity="5",
            avg="100",
            realized="7",
        ),
    )
    first, second = result.events
    closed, opened = result.positions
    assert [event.event_type for event in result.events] == [
        AccountingEventType.CLOSE,
        AccountingEventType.OPEN,
    ]
    assert [event.event_no for event in result.events] == [1, 2]
    assert [event.delta_qty for event in result.events] == [
        Decimal("-5"),
        Decimal("-3"),
    ]
    assert [event.fee for event in result.events] == [
        Decimal("3"),
        Decimal("0"),
    ]
    assert sum(event.fee for event in result.events) == command.fee
    assert first.realized_pnl == 100
    assert second.realized_pnl == 0
    assert closed.status is PositionStatus.CLOSED
    assert opened.side is PositionSide.SHORT
    assert opened.quantity == 3
    assert opened.avg_entry_price == 120
    assert opened.realized_pnl == 0
    assert opened.position_id.startswith("pos_")
    assert len(opened.position_id) == 68


def test_buy_crosses_short_to_new_long():
    result = plan(
        OrderSide.BUY,
        fill(quantity="8", price="80", fee="3"),
        position(PositionSide.SHORT, quantity="5", avg="100"),
    )
    assert [event.event_type for event in result.events] == [
        AccountingEventType.CLOSE,
        AccountingEventType.OPEN,
    ]
    assert [event.delta_qty for event in result.events] == [
        Decimal("5"),
        Decimal("3"),
    ]
    assert result.positions[1].side is PositionSide.LONG


def test_crossing_increases_existing_same_side():
    long_position = position(
        PositionSide.LONG,
        position_id="long-existing",
        quantity="4",
        avg="90",
        realized="2",
    )
    short_position = position(
        PositionSide.SHORT,
        position_id="short-existing",
        quantity="5",
        avg="100",
        realized="3",
    )
    result = plan(
        OrderSide.BUY,
        fill(quantity="8", price="110"),
        long_position,
        short_position,
    )
    assert [event.event_type for event in result.events] == [
        AccountingEventType.CLOSE,
        AccountingEventType.INCREASE,
    ]
    assert result.positions[1].position_id == "long-existing"
    assert result.positions[1].quantity == 7
    assert result.positions[1].avg_entry_price == Decimal(
        "98.57142857142857142857142857142857"
    )


def test_policy_rejects_duplicate_side_wrong_scope_and_closed_input():
    command = fill()
    with pytest.raises(LifecycleInvariantError):
        plan(
            OrderSide.BUY,
            command,
            position(PositionSide.LONG, position_id="a"),
            position(PositionSide.LONG, position_id="b"),
        )
    with pytest.raises(LifecycleInvariantError):
        plan(
            OrderSide.BUY,
            command,
            position(PositionSide.LONG, account_scope="other"),
        )
    with pytest.raises(LifecycleInvariantError):
        plan(
            OrderSide.BUY,
            command,
            position(
                PositionSide.LONG,
                status=PositionStatus.CLOSED,
            ),
        )


def test_policy_does_not_mutate_inputs():
    snapshot = position(PositionSide.LONG, quantity="5", avg="100")
    before = repr(snapshot)
    plan(
        OrderSide.SELL,
        fill(quantity="2", price="120"),
        snapshot,
    )
    assert repr(snapshot) == before
    with pytest.raises(FrozenInstanceError):
        snapshot.quantity = Decimal("99")


def test_policy_module_has_no_database_network_or_json_dependency():
    import atos.position_accounting as module

    source = inspect.getsource(module)
    assert "sqlite3" not in source
    assert "RuntimeDatabase" not in source
    assert "requests" not in source
    assert "urllib" not in source
    assert "json" not in source


def test_errors_carry_immutable_default_stats():
    error = LifecyclePersistenceError("x")
    assert error.stats == OperationStats()
    assert error.stats.committed_mutations == 0


def test_plan_is_deterministic_and_pairs_events_to_positions():
    command = fill(quantity="8", price="120", fee="3")
    first = plan(
        OrderSide.SELL,
        command,
        position(PositionSide.LONG, quantity="5", avg="100"),
    )
    second = plan(
        OrderSide.SELL,
        command,
        position(PositionSide.LONG, quantity="5", avg="100"),
    )
    assert first == second
    assert tuple(event.position_id for event in first.events) == tuple(
        mutation.position_id for mutation in first.positions
    )
    assert all(
        event.event_id.startswith("pae_")
        and len(event.event_id) == 68
        for event in first.events
    )


def test_operation_stats_reject_invalid_counts():
    with pytest.raises(ValueError):
        OperationStats(read_statements=-1)
    with pytest.raises(ValueError):
        OperationStats(
            attempted_mutations=1,
            committed_mutations=2,
        )
    with pytest.raises(ValueError):
        OperationStats(transaction_count=True)


def test_fill_command_rejects_invalid_status_and_negative_values():
    with pytest.raises(LifecycleValidationError):
        fill(side_status=OrderStatus.OPEN)
    with pytest.raises(LifecycleValidationError):
        fill(quantity="0")
    with pytest.raises(LifecycleValidationError):
        fill(fee="-1")


def test_policy_rejects_duplicate_position_id_across_sides():
    command = fill()
    with pytest.raises(LifecycleInvariantError):
        plan(
            OrderSide.BUY,
            command,
            position(PositionSide.LONG, position_id="same"),
            position(PositionSide.SHORT, position_id="same"),
        )
