"""Exact C6A sleeve ledger primitives.

The ledger models research accounting only.  It has no exchange connectivity or
execution capability.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from decimal import Decimal
from typing import Any

from atos.c6a_contract import C6AError, decimal_value

ZERO = Decimal("0")


@dataclass(frozen=True)
class PnLComponents:
    spot_price_pnl: Decimal = ZERO
    perpetual_price_pnl: Decimal = ZERO
    funding_pnl: Decimal = ZERO
    spot_cost: Decimal = ZERO
    swap_cost: Decimal = ZERO

    @property
    def net_pnl(self) -> Decimal:
        return (
            self.spot_price_pnl
            + self.perpetual_price_pnl
            + self.funding_pnl
            - self.spot_cost
            - self.swap_cost
        )

    def add(self, **changes: Decimal) -> "PnLComponents":
        values = {
            "spot_price_pnl": self.spot_price_pnl,
            "perpetual_price_pnl": self.perpetual_price_pnl,
            "funding_pnl": self.funding_pnl,
            "spot_cost": self.spot_cost,
            "swap_cost": self.swap_cost,
        }
        for key, value in changes.items():
            if key not in values:
                raise C6AError(f"unknown PnL component: {key}")
            values[key] += value
        return PnLComponents(**values)

    def minus(self, earlier: "PnLComponents") -> "PnLComponents":
        return PnLComponents(
            spot_price_pnl=self.spot_price_pnl - earlier.spot_price_pnl,
            perpetual_price_pnl=self.perpetual_price_pnl - earlier.perpetual_price_pnl,
            funding_pnl=self.funding_pnl - earlier.funding_pnl,
            spot_cost=self.spot_cost - earlier.spot_cost,
            swap_cost=self.swap_cost - earlier.swap_cost,
        )


@dataclass(frozen=True)
class SleeveState:
    asset: str
    spot_quantity: Decimal = ZERO
    perpetual_base_quantity: Decimal = ZERO
    last_spot_mark: Decimal | None = None
    last_perpetual_mark: Decimal | None = None
    dedicated_collateral: Decimal = ZERO
    components: PnLComponents = PnLComponents()
    collateral_checkpoint: PnLComponents = PnLComponents()
    collateral_buffer_breaches: int = 0
    hedge_breaches: int = 0
    risk_exit_pending: bool = False

    @property
    def active(self) -> bool:
        return self.spot_quantity > 0 or self.perpetual_base_quantity > 0

    @property
    def collateral_equity(self) -> Decimal:
        since_rebalance = self.components.minus(self.collateral_checkpoint)
        return (
            self.dedicated_collateral
            + since_rebalance.perpetual_price_pnl
            + since_rebalance.funding_pnl
            - since_rebalance.swap_cost
        )

    @property
    def hedge_error(self) -> Decimal:
        denominator = max(self.spot_quantity, self.perpetual_base_quantity)
        if denominator == 0:
            return ZERO
        return abs(self.spot_quantity - self.perpetual_base_quantity) / denominator

    def mark(self, *, spot_price: Any, perpetual_mark: Any) -> "SleeveState":
        spot = decimal_value(spot_price, "spot mark")
        swap = decimal_value(perpetual_mark, "perpetual mark")
        if spot <= 0 or swap <= 0:
            raise C6AError("marks must be positive")
        if self.last_spot_mark is None or self.last_perpetual_mark is None:
            if self.active:
                raise C6AError("active sleeve is missing prior marks")
            return replace(self, last_spot_mark=spot, last_perpetual_mark=swap)
        spot_pnl = self.spot_quantity * (spot - self.last_spot_mark)
        perpetual_pnl = self.perpetual_base_quantity * (
            self.last_perpetual_mark - swap
        )
        return replace(
            self,
            last_spot_mark=spot,
            last_perpetual_mark=swap,
            components=self.components.add(
                spot_price_pnl=spot_pnl,
                perpetual_price_pnl=perpetual_pnl,
            ),
        )

    def apply_funding(self, *, realized_rate: Any, preceding_mark: Any) -> "SleeveState":
        rate = decimal_value(realized_rate, "realized funding rate")
        mark = decimal_value(preceding_mark, "preceding funding mark")
        if mark <= 0:
            raise C6AError("funding mark must be positive")
        funding = self.perpetual_base_quantity * mark * rate
        return replace(
            self,
            components=self.components.add(funding_pnl=funding),
        )

    def trade(
        self,
        *,
        new_spot_quantity: Any,
        new_perpetual_base_quantity: Any,
        spot_trade_price: Any,
        swap_trade_price: Any,
        cost_rate: Any,
        dedicated_collateral: Any | None = None,
    ) -> "SleeveState":
        new_spot = decimal_value(new_spot_quantity, "new spot quantity")
        new_swap = decimal_value(new_perpetual_base_quantity, "new perpetual quantity")
        spot_price = decimal_value(spot_trade_price, "spot trade price")
        swap_price = decimal_value(swap_trade_price, "swap trade price")
        rate = decimal_value(cost_rate, "cost rate")
        if new_spot < 0 or new_swap < 0 or spot_price <= 0 or swap_price <= 0 or rate < 0:
            raise C6AError("invalid trade inputs")
        spot_cost = abs(new_spot - self.spot_quantity) * spot_price * rate
        swap_cost = abs(new_swap - self.perpetual_base_quantity) * swap_price * rate
        collateral = (
            self.dedicated_collateral
            if dedicated_collateral is None
            else decimal_value(dedicated_collateral, "dedicated collateral")
        )
        if collateral < 0:
            raise C6AError("dedicated collateral cannot be negative")
        if new_swap > 0 and collateral == 0:
            raise C6AError("active short requires dedicated collateral")
        resetting_collateral = dedicated_collateral is not None
        if new_swap == 0 and new_spot == 0:
            collateral = ZERO
            resetting_collateral = True
        updated_components = self.components.add(spot_cost=spot_cost, swap_cost=swap_cost)
        return replace(
            self,
            spot_quantity=new_spot,
            perpetual_base_quantity=new_swap,
            last_spot_mark=spot_price,
            last_perpetual_mark=swap_price,
            dedicated_collateral=collateral,
            components=updated_components,
            # The new trade's swap fee is deliberately after the checkpoint and
            # therefore immediately reduces the refreshed collateral equity.
            collateral_checkpoint=(self.components if resetting_collateral else self.collateral_checkpoint),
        )

    def observe_risk(
        self,
        *,
        current_mark: Any,
        current_basis: Any,
        minimum_buffer: Any,
        maximum_abs_basis: Any,
        maximum_hedge_error: Any,
    ) -> "SleeveState":
        mark = decimal_value(current_mark, "current mark")
        basis = decimal_value(current_basis, "current basis")
        buffer_limit = decimal_value(minimum_buffer, "minimum buffer")
        basis_limit = decimal_value(maximum_abs_basis, "maximum basis")
        hedge_limit = decimal_value(maximum_hedge_error, "maximum hedge error")
        if not self.active:
            return self
        short_notional = self.perpetual_base_quantity * mark
        if short_notional <= 0:
            raise C6AError("active sleeve has non-positive short notional")
        buffer = self.collateral_equity / short_notional
        collateral_breach = buffer < buffer_limit
        hedge_breach = self.hedge_error > hedge_limit
        basis_breach = abs(basis) > basis_limit
        return replace(
            self,
            collateral_buffer_breaches=self.collateral_buffer_breaches
            + int(collateral_breach),
            hedge_breaches=self.hedge_breaches + int(hedge_breach),
            risk_exit_pending=self.risk_exit_pending
            or collateral_breach
            or basis_breach,
        )

    def terminal_close(
        self, *, spot_trade_price: Any, swap_trade_price: Any, cost_rate: Any
    ) -> "SleeveState":
        if not self.active:
            return self
        closed = self.trade(
            new_spot_quantity=ZERO,
            new_perpetual_base_quantity=ZERO,
            spot_trade_price=spot_trade_price,
            swap_trade_price=swap_trade_price,
            cost_rate=cost_rate,
            dedicated_collateral=ZERO,
        )
        if closed.active or closed.dedicated_collateral != 0:
            raise C6AError("terminal close failed to produce zero position")
        return replace(closed, risk_exit_pending=False)


@dataclass(frozen=True)
class WeeklyBucket:
    start_reference_equity: Decimal
    end_reference_equity: Decimal
    components: PnLComponents
    active: bool
    risk_exit: bool

    @property
    def weekly_pnl(self) -> Decimal:
        return self.end_reference_equity - self.start_reference_equity

    @property
    def weekly_return(self) -> Decimal:
        if self.start_reference_equity <= 0:
            raise C6AError("weekly start equity must be positive")
        return self.weekly_pnl / self.start_reference_equity

    def validate_reconciliation(self, tolerance: Decimal = Decimal("1e-8")) -> None:
        residual = self.weekly_pnl - self.components.net_pnl
        if abs(residual) > tolerance:
            raise C6AError(f"weekly reconciliation residual: {residual}")
