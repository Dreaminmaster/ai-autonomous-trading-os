from decimal import Decimal

import pytest

from atos.c6a_contract import C6AError
from atos.c6a_ledger import PnLComponents, SleeveState, WeeklyBucket


def opened_sleeve() -> SleeveState:
    return SleeveState(asset="BTC").trade(
        new_spot_quantity="1",
        new_perpetual_base_quantity="1",
        spot_trade_price="100",
        swap_trade_price="100",
        cost_rate="0.0015",
        dedicated_collateral="200",
    )


def test_long_spot_short_perpetual_mark_signs_and_funding_sign() -> None:
    state = opened_sleeve().mark(spot_price="110", perpetual_mark="109")
    assert state.components.spot_price_pnl == Decimal("10")
    assert state.components.perpetual_price_pnl == Decimal("-9")

    state = state.apply_funding(realized_rate="0.001", preceding_mark="108")
    assert state.components.funding_pnl == Decimal("0.108")
    assert state.collateral_equity == Decimal("190.9580")

    paid = state.apply_funding(realized_rate="-0.002", preceding_mark="109")
    assert paid.components.funding_pnl == Decimal("-0.110")


def test_open_and_terminal_close_charge_both_legs_and_zero_state() -> None:
    state = opened_sleeve().mark(spot_price="110", perpetual_mark="109")
    state = state.apply_funding(realized_rate="0.001", preceding_mark="108")
    closed = state.terminal_close(
        spot_trade_price="110", swap_trade_price="109", cost_rate="0.0015"
    )
    assert not closed.active
    assert closed.spot_quantity == 0
    assert closed.perpetual_base_quantity == 0
    assert closed.dedicated_collateral == 0
    assert closed.components.spot_cost == Decimal("0.3150")
    assert closed.components.swap_cost == Decimal("0.3135")
    assert closed.components.net_pnl == Decimal("0.4795")


def test_funding_on_zero_short_is_exactly_zero() -> None:
    state = SleeveState(asset="ETH").apply_funding(
        realized_rate="0.01", preceding_mark="3000"
    )
    assert state.components.funding_pnl == 0


def test_collateral_basis_and_hedge_breaches_are_retained() -> None:
    state = opened_sleeve().mark(spot_price="100", perpetual_mark="300")
    observed = state.observe_risk(
        current_mark="300",
        current_basis="0.06",
        minimum_buffer="1.25",
        maximum_abs_basis="0.05",
        maximum_hedge_error="0.001",
    )
    assert observed.collateral_buffer_breaches == 1
    assert observed.risk_exit_pending is True

    unhedged = SleeveState(asset="BTC").trade(
        new_spot_quantity="1",
        new_perpetual_base_quantity="0.9",
        spot_trade_price="100",
        swap_trade_price="100",
        cost_rate="0",
        dedicated_collateral="200",
    )
    unhedged = unhedged.observe_risk(
        current_mark="100",
        current_basis="0",
        minimum_buffer="1.25",
        maximum_abs_basis="0.05",
        maximum_hedge_error="0.001",
    )
    assert unhedged.hedge_breaches == 1


def test_active_sleeve_without_prior_marks_fails_closed() -> None:
    bad = SleeveState(
        asset="BTC",
        spot_quantity=Decimal("1"),
        perpetual_base_quantity=Decimal("1"),
        dedicated_collateral=Decimal("200"),
    )
    with pytest.raises(C6AError, match="missing prior marks"):
        bad.mark(spot_price="100", perpetual_mark="100")


def test_weekly_bucket_reconciles_exact_components() -> None:
    components = PnLComponents(
        spot_price_pnl=Decimal("4"),
        perpetual_price_pnl=Decimal("-3"),
        funding_pnl=Decimal("2"),
        spot_cost=Decimal("0.5"),
        swap_cost=Decimal("0.5"),
    )
    bucket = WeeklyBucket(
        start_reference_equity=Decimal("100"),
        end_reference_equity=Decimal("102"),
        components=components,
        active=True,
        risk_exit=False,
    )
    assert bucket.weekly_return == Decimal("0.02")
    bucket.validate_reconciliation()

    invalid = WeeklyBucket(
        start_reference_equity=Decimal("100"),
        end_reference_equity=Decimal("102.1"),
        components=components,
        active=True,
        risk_exit=False,
    )
    with pytest.raises(C6AError, match="reconciliation"):
        invalid.validate_reconciliation()
