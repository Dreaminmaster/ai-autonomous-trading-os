"""Deterministic C6A joint spot/perpetual rounding and post-cost sizing."""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_FLOOR
from typing import Iterable, Mapping

from atos.c6a_contract import C6AError, decimal_value


@dataclass(frozen=True)
class SpotRules:
    instrument: str
    lot_size: Decimal
    minimum_size: Decimal

    def validate(self) -> None:
        if self.lot_size <= 0 or self.minimum_size <= 0:
            raise C6AError("spot lot and minimum size must be positive")


@dataclass(frozen=True)
class SwapRules:
    instrument: str
    contract_value: Decimal
    lot_size: Decimal
    minimum_size: Decimal

    @property
    def base_quantum(self) -> Decimal:
        return self.contract_value * self.lot_size

    def validate(self) -> None:
        if self.contract_value <= 0 or self.lot_size <= 0 or self.minimum_size <= 0:
            raise C6AError("swap contract value, lot size and minimum size must be positive")


@dataclass(frozen=True)
class RoundedPair:
    spot_instrument: str
    swap_instrument: str
    spot_quantity: Decimal
    contract_count: Decimal
    perpetual_base_quantity: Decimal
    hedge_error: Decimal
    spot_notional: Decimal
    swap_notional: Decimal
    paired_notional: Decimal


def floor_step(value: Decimal, step: Decimal) -> Decimal:
    if value < 0 or step <= 0:
        raise C6AError("floor_step requires non-negative value and positive step")
    units = (value / step).to_integral_value(rounding=ROUND_FLOOR)
    return units * step


def _step_values(start: Decimal, stop: Decimal, step: Decimal) -> Iterable[Decimal]:
    if step <= 0 or stop < start:
        return ()
    start_units = (start / step).to_integral_value(rounding=ROUND_FLOOR)
    if start_units * step < start:
        start_units += 1
    stop_units = (stop / step).to_integral_value(rounding=ROUND_FLOOR)
    return (Decimal(index) * step for index in range(int(start_units), int(stop_units) + 1))


def joint_round_pair(
    *,
    desired_base_quantity: Decimal | str,
    post_cost_spot_target: Decimal | str,
    spot_price: Decimal | str,
    swap_price: Decimal | str,
    spot_rules: SpotRules,
    swap_rules: SwapRules,
    maximum_hedge_error: Decimal | str,
) -> RoundedPair | None:
    """Select the frozen deterministic rounded pair.

    Contract counts up to one base quantum above the desired quantity are
    enumerated.  Each is paired with the closest non-exceeding feasible spot
    quantity.  Ordering is hedge error, larger paired notional, lower contract
    count, then lexical swap instrument.
    """

    desired = decimal_value(desired_base_quantity, "desired base quantity")
    target = decimal_value(post_cost_spot_target, "post-cost spot target")
    spot_px = decimal_value(spot_price, "spot price")
    swap_px = decimal_value(swap_price, "swap price")
    tolerance = decimal_value(maximum_hedge_error, "maximum hedge error")
    spot_rules.validate()
    swap_rules.validate()
    if desired <= 0 or target <= 0 or spot_px <= 0 or swap_px <= 0 or tolerance < 0:
        raise C6AError("rounding inputs must be positive and tolerance non-negative")

    maximum_contract_count = (desired + swap_rules.base_quantum) / swap_rules.contract_value
    candidates: list[RoundedPair] = []
    for contract_count in _step_values(
        swap_rules.minimum_size,
        maximum_contract_count,
        swap_rules.lot_size,
    ):
        perpetual_base = contract_count * swap_rules.contract_value
        spot_cap = min(desired, perpetual_base, target / spot_px)
        spot_quantity = floor_step(spot_cap, spot_rules.lot_size)
        if spot_quantity < spot_rules.minimum_size:
            continue
        denominator = max(spot_quantity, perpetual_base)
        if denominator <= 0:
            continue
        hedge_error = abs(spot_quantity - perpetual_base) / denominator
        if hedge_error > tolerance:
            continue
        spot_notional = spot_quantity * spot_px
        swap_notional = perpetual_base * swap_px
        paired_notional = min(spot_notional, swap_notional)
        if spot_notional > target:
            continue
        candidates.append(
            RoundedPair(
                spot_instrument=spot_rules.instrument,
                swap_instrument=swap_rules.instrument,
                spot_quantity=spot_quantity,
                contract_count=contract_count,
                perpetual_base_quantity=perpetual_base,
                hedge_error=hedge_error,
                spot_notional=spot_notional,
                swap_notional=swap_notional,
                paired_notional=paired_notional,
            )
        )
    if not candidates:
        return None
    return min(
        candidates,
        key=lambda row: (
            row.hedge_error,
            -row.paired_notional,
            row.contract_count,
            row.swap_instrument,
        ),
    )


@dataclass(frozen=True)
class SleeveTarget:
    asset: str
    sleeve_capital: Decimal
    spot_target_notional: Decimal
    collateral_target: Decimal


def equal_sleeve_targets(
    *, total_equity: Decimal | str, eligible_assets: Iterable[str]
) -> tuple[SleeveTarget, ...]:
    equity = decimal_value(total_equity, "total equity")
    assets = tuple(sorted(set(eligible_assets)))
    if equity < 0:
        raise C6AError("equity cannot be negative")
    if not assets:
        return ()
    sleeve = equity / Decimal(len(assets))
    return tuple(
        SleeveTarget(
            asset=asset,
            sleeve_capital=sleeve,
            spot_target_notional=sleeve / Decimal(3),
            collateral_target=sleeve * Decimal(2) / Decimal(3),
        )
        for asset in assets
    )


def should_resize(
    *, current_paired_notional: Decimal | str, target_paired_notional: Decimal | str,
    band: Decimal | str
) -> bool:
    current = decimal_value(current_paired_notional, "current paired notional")
    target = decimal_value(target_paired_notional, "target paired notional")
    threshold = decimal_value(band, "resizing band")
    if current < 0 or target < 0 or threshold < 0:
        raise C6AError("resize inputs cannot be negative")
    if current == 0:
        return target > 0
    return abs(target - current) / current >= threshold


def solve_global_scale(
    *,
    total_equity: Decimal | str,
    unscaled_targets: Mapping[str, Decimal | str],
    cost_rate: Decimal | str,
    fixed_collateral: Mapping[str, Decimal | str],
    tolerance: Decimal | str = "0.01",
) -> tuple[Decimal, Decimal]:
    """Solve one global scale for all new spot targets.

    The cash model is intentionally conservative: scaled spot purchases,
    scaled matching swap opening fees, spot opening fees, and dedicated
    collateral must all fit inside current equity.  Bisection is deterministic
    and returns `(scale, residual_cash)`.
    """

    equity = decimal_value(total_equity, "total equity")
    rate = decimal_value(cost_rate, "cost rate")
    cash_tolerance = decimal_value(tolerance, "cash tolerance")
    targets = {key: decimal_value(value, f"target {key}") for key, value in unscaled_targets.items()}
    collateral = {
        key: decimal_value(value, f"collateral {key}") for key, value in fixed_collateral.items()
    }
    if set(targets) != set(collateral):
        raise C6AError("target and collateral asset sets differ")
    if equity < 0 or rate < 0 or cash_tolerance < 0:
        raise C6AError("scale inputs cannot be negative")
    if any(value < 0 for value in (*targets.values(), *collateral.values())):
        raise C6AError("target and collateral values cannot be negative")

    def required(scale: Decimal) -> Decimal:
        spot = sum((value * scale for value in targets.values()), Decimal("0"))
        margin = sum((value * scale for value in collateral.values()), Decimal("0"))
        fees = spot * rate * Decimal(2)
        return spot + margin + fees

    if required(Decimal("1")) <= equity:
        return Decimal("1"), equity - required(Decimal("1"))
    low, high = Decimal("0"), Decimal("1")
    for _ in range(120):
        mid = (low + high) / Decimal(2)
        if required(mid) <= equity:
            low = mid
        else:
            high = mid
    residual = equity - required(low)
    if residual < 0:
        raise C6AError("post-cost scale produced negative cash")
    if residual > cash_tolerance:
        # The later quantum solver may explain a larger exact-quantum residual;
        # this continuous solver itself must be within the frozen tolerance.
        raise C6AError("post-cost scale residual exceeds tolerance")
    return low, residual
