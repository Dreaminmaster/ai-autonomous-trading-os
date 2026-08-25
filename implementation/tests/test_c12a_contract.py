from __future__ import annotations

from decimal import Decimal

import pytest

from atos.c12a_contract import (
    ENTRY_THRESHOLD,
    EXECUTION_MAX_DELAY,
    WINDOWS,
    C12AError,
    base_quantity,
    contract_decisions,
    load_frozen_config,
    normalized_basis,
    safety_boundary,
    should_enter,
)


def test_frozen_decision_inventory_has_two_assets_and_two_expiries_per_window() -> None:
    config = load_frozen_config(verify_authority=False)
    decisions = contract_decisions(config)
    assert len(decisions) == 20
    assert len({item.futures_instrument for item in decisions}) == 20
    for window in WINDOWS:
        selected = [item for item in decisions if item.window_id == window.window_id]
        assert len(selected) == 4
        assert {item.asset for item in selected} == {"BTC", "ETH"}
        assert all(window.start <= item.entry_timestamp < item.exit_timestamp < window.end for item in selected)


def test_signal_entry_and_exit_clocks_are_exact() -> None:
    config = load_frozen_config(verify_authority=False)
    decisions = contract_decisions(config)
    assert EXECUTION_MAX_DELAY.total_seconds() == 300
    assert config["execution_trade_max_delay_seconds"] == 300
    for item in decisions:
        assert (item.entry_timestamp - item.signal_cutoff).total_seconds() == 3600
        assert (item.expiry - item.entry_timestamp).days == 28
        assert (item.expiry - item.exit_timestamp).total_seconds() == 3600


def test_normalized_basis_threshold_is_strict() -> None:
    spot = Decimal(247)
    boundary_future = Decimal(253)
    assert normalized_basis(futures_price=boundary_future, spot_price=spot) == ENTRY_THRESHOLD
    assert should_enter(futures_price=boundary_future, spot_price=spot) is False
    assert should_enter(futures_price=boundary_future + Decimal("0.000001"), spot_price=spot)
    assert not should_enter(futures_price=spot, spot_price=spot)


def test_base_quantity_uses_combined_notional_and_cost_reserve() -> None:
    quantity = base_quantity(
        sleeve_equity="500",
        spot_entry="100",
        futures_entry="102",
        cost_rate="0.003",
    )
    assert quantity == Decimal(500) / (Decimal(202) * Decimal("1.003"))
    assert quantity * Decimal(202) < Decimal(500)


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        (
            {
                "sleeve_equity": "0",
                "spot_entry": "100",
                "futures_entry": "102",
                "cost_rate": "0.003",
            },
            "sleeve equity",
        ),
        (
            {
                "sleeve_equity": "500",
                "spot_entry": "100",
                "futures_entry": "102",
                "cost_rate": "-0.001",
            },
            "non-negative",
        ),
    ],
)
def test_base_quantity_rejects_invalid_state(kwargs: dict[str, str], message: str) -> None:
    with pytest.raises(C12AError, match=message):
        base_quantity(**kwargs)


def test_safety_boundary_is_closed() -> None:
    assert safety_boundary() == {
        "authenticated": False,
        "contains_account_data": False,
        "contains_order_data": False,
        "paper_side_effect": False,
        "shadow_side_effect": False,
        "paper_state": "PAPER_CLOSED",
        "shadow_state": "SHADOW_CLOSED",
        "live_state": "LIVE_FORBIDDEN",
    }
