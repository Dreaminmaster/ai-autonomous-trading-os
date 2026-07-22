from decimal import Decimal

import pytest

from atos.c6a_contract import C6AError
from atos.c6a_rounding import (
    SpotRules,
    SwapRules,
    equal_sleeve_targets,
    floor_step,
    joint_round_pair,
    should_resize,
    solve_global_scale,
)


def test_floor_step_is_decimal_and_non_overshooting() -> None:
    assert floor_step(Decimal("1.2349"), Decimal("0.001")) == Decimal("1.234")
    with pytest.raises(C6AError):
        floor_step(Decimal("1"), Decimal("0"))


def test_joint_rounding_selects_best_hedged_largest_pair() -> None:
    result = joint_round_pair(
        desired_base_quantity="0.1014",
        post_cost_spot_target="10000",
        spot_price="50000",
        swap_price="50010",
        spot_rules=SpotRules("BTC-USDT", Decimal("0.0001"), Decimal("0.0001")),
        swap_rules=SwapRules(
            "BTC-USDT-SWAP",
            contract_value=Decimal("0.01"),
            lot_size=Decimal("1"),
            minimum_size=Decimal("1"),
        ),
        maximum_hedge_error="0.001",
    )
    assert result is not None
    assert result.spot_quantity == Decimal("0.10")
    assert result.perpetual_base_quantity == Decimal("0.10")
    assert result.contract_count == Decimal("10")
    assert result.hedge_error == 0


def test_joint_rounding_fails_closed_when_quantum_cannot_hedge() -> None:
    result = joint_round_pair(
        desired_base_quantity="0.005",
        post_cost_spot_target="500",
        spot_price="50000",
        swap_price="50000",
        spot_rules=SpotRules("BTC-USDT", Decimal("0.0001"), Decimal("0.0001")),
        swap_rules=SwapRules(
            "BTC-USDT-SWAP",
            contract_value=Decimal("0.01"),
            lot_size=Decimal("1"),
            minimum_size=Decimal("1"),
        ),
        maximum_hedge_error="0.001",
    )
    assert result is None


def test_equal_sleeves_use_one_third_spot_two_thirds_collateral() -> None:
    targets = equal_sleeve_targets(total_equity="900", eligible_assets=["ETH", "BTC", "ETH"])
    assert [row.asset for row in targets] == ["BTC", "ETH"]
    assert all(row.sleeve_capital == Decimal("450") for row in targets)
    assert all(row.spot_target_notional == Decimal("150") for row in targets)
    assert all(row.collateral_target == Decimal("300") for row in targets)
    assert equal_sleeve_targets(total_equity="900", eligible_assets=[]) == ()


def test_resize_band_boundary_is_inclusive() -> None:
    assert not should_resize(current_paired_notional="100", target_paired_notional="109.999", band="0.10")
    assert should_resize(current_paired_notional="100", target_paired_notional="110", band="0.10")
    assert should_resize(current_paired_notional="0", target_paired_notional="1", band="0.10")


def test_global_post_cost_scale_preserves_single_scale_and_cash() -> None:
    scale, residual = solve_global_scale(
        total_equity="1000",
        unscaled_targets={"BTC": "200", "ETH": "200"},
        fixed_collateral={"BTC": "400", "ETH": "400"},
        cost_rate="0.0015",
        tolerance="0.01",
    )
    assert Decimal("0") < scale < Decimal("1")
    required = scale * (Decimal("400") + Decimal("800") + Decimal("400") * Decimal("0.003"))
    assert required <= Decimal("1000")
    assert Decimal("0") <= residual <= Decimal("0.01")


def test_global_scale_rejects_asset_set_mismatch() -> None:
    with pytest.raises(C6AError, match="asset sets differ"):
        solve_global_scale(
            total_equity="1000",
            unscaled_targets={"BTC": "100"},
            fixed_collateral={"ETH": "200"},
            cost_rate="0.0015",
        )
