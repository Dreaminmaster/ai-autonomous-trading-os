"""Explicit Decimal cash, spot, margin, funding, and cost ledger for C9A."""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal, localcontext
from typing import Any

from atos.c9a_contract import (
    MAXIMUM_RISK_ABS_BASIS,
    MINIMUM_COLLATERAL_BUFFER,
    RECONCILIATION_TOLERANCE,
    SPOT_INSTRUMENTS,
    C9AError,
    decimal_value,
    iso,
)

ZERO = Decimal(0)
COMPONENT_NAMES = (
    "spot_price_pnl",
    "perpetual_price_pnl",
    "funding_pnl",
    "spot_cost",
    "swap_cost",
)


@dataclass
class Sleeve:
    spot_instrument: str
    spot_quantity: Decimal = ZERO
    short_quantity: Decimal = ZERO
    margin_cash: Decimal = ZERO
    last_spot_price: Decimal | None = None
    last_perpetual_price: Decimal | None = None
    components: dict[str, Decimal] = field(
        default_factory=lambda: {name: ZERO for name in COMPONENT_NAMES}
    )
    risk_exit_pending: bool = False
    blocked_until: datetime | None = None
    collateral_buffer_breaches: int = 0
    hedge_mismatches: int = 0

    @property
    def active(self) -> bool:
        return self.spot_quantity > 0 or self.short_quantity > 0

    def net_component_pnl(self) -> Decimal:
        return (
            self.components["spot_price_pnl"]
            + self.components["perpetual_price_pnl"]
            + self.components["funding_pnl"]
            - self.components["spot_cost"]
            - self.components["swap_cost"]
        )


@dataclass
class Portfolio:
    free_cash: Decimal
    sleeves: dict[str, Sleeve]
    starting_equity: Decimal

    @classmethod
    def create(cls, starting_equity: Any) -> Portfolio:
        equity = decimal_value(starting_equity, "starting equity", positive=True)
        return cls(
            free_cash=equity,
            sleeves={spot: Sleeve(spot) for spot in SPOT_INSTRUMENTS},
            starting_equity=equity,
        )

    def clone(self) -> Portfolio:
        return deepcopy(self)

    def components(self) -> dict[str, Decimal]:
        return {
            name: sum(
                (sleeve.components[name] for sleeve in self.sleeves.values()), ZERO
            )
            for name in COMPONENT_NAMES
        }

    def net_component_pnl(self) -> Decimal:
        values = self.components()
        return (
            values["spot_price_pnl"]
            + values["perpetual_price_pnl"]
            + values["funding_pnl"]
            - values["spot_cost"]
            - values["swap_cost"]
        )

    def equity(self) -> Decimal:
        result = self.free_cash
        for sleeve in self.sleeves.values():
            if sleeve.last_spot_price is None:
                if sleeve.active:
                    raise C9AError("active sleeve lacks a spot mark")
            else:
                result += sleeve.spot_quantity * sleeve.last_spot_price
            result += sleeve.margin_cash
        if not result.is_finite() or result <= 0:
            raise C9AError("C9A portfolio equity became non-positive or non-finite")
        return result

    def assert_reconciled(self) -> Decimal:
        residual = self.equity() - (self.starting_equity + self.net_component_pnl())
        if abs(residual) > RECONCILIATION_TOLERANCE:
            raise C9AError(f"C9A ledger reconciliation residual: {residual}")
        if self.free_cash < -RECONCILIATION_TOLERANCE:
            raise C9AError("C9A free cash became negative")
        for sleeve in self.sleeves.values():
            if sleeve.active:
                if sleeve.margin_cash <= 0:
                    raise C9AError("active C9A short has non-positive margin cash")
                if sleeve.spot_quantity != sleeve.short_quantity:
                    raise C9AError("C9A exact base-unit hedge was violated")
            elif (
                sleeve.spot_quantity != 0
                or sleeve.short_quantity != 0
                or sleeve.margin_cash != 0
            ):
                raise C9AError("flat C9A sleeve retains position or margin")
        return residual

    def accrue_to(
        self,
        *,
        spot_prices: Mapping[str, Any],
        perpetual_prices: Mapping[str, Any],
    ) -> list[dict[str, str]]:
        if set(spot_prices) != set(SPOT_INSTRUMENTS) or set(perpetual_prices) != set(
            SPOT_INSTRUMENTS
        ):
            raise C9AError("C9A mark set is incomplete")
        events = []
        with localcontext() as context:
            context.prec = 60
            for spot, sleeve in self.sleeves.items():
                new_spot = decimal_value(spot_prices[spot], "spot mark", positive=True)
                new_perp = decimal_value(
                    perpetual_prices[spot], "perpetual mark", positive=True
                )
                old_spot = sleeve.last_spot_price
                old_perp = sleeve.last_perpetual_price
                spot_pnl = ZERO
                perp_pnl = ZERO
                if old_spot is not None and old_perp is not None:
                    spot_pnl = sleeve.spot_quantity * (new_spot - old_spot)
                    perp_pnl = sleeve.short_quantity * (old_perp - new_perp)
                    sleeve.margin_cash += perp_pnl
                    sleeve.components["spot_price_pnl"] += spot_pnl
                    sleeve.components["perpetual_price_pnl"] += perp_pnl
                elif sleeve.active:
                    raise C9AError("active C9A sleeve lacks preceding prices")
                sleeve.last_spot_price = new_spot
                sleeve.last_perpetual_price = new_perp
                events.append(
                    {
                        "spot_instrument": spot,
                        "old_spot_price": "" if old_spot is None else str(old_spot),
                        "new_spot_price": str(new_spot),
                        "old_perpetual_price": ""
                        if old_perp is None
                        else str(old_perp),
                        "new_perpetual_price": str(new_perp),
                        "spot_price_pnl": str(spot_pnl),
                        "perpetual_price_pnl": str(perp_pnl),
                    }
                )
        self.assert_reconciled()
        return events

    def apply_funding(
        self,
        *,
        spot: str,
        realized_rate: Any,
        preceding_mark: Any,
    ) -> Decimal:
        sleeve = self.sleeves[spot]
        rate = decimal_value(realized_rate, "realized funding rate")
        mark = decimal_value(preceding_mark, "preceding completed mark", positive=True)
        pnl = sleeve.short_quantity * mark * rate
        sleeve.margin_cash += pnl
        sleeve.components["funding_pnl"] += pnl
        self.assert_reconciled()
        return pnl

    def observe_risk(
        self, *, spot: str, mark_price: Any, spot_price: Any
    ) -> dict[str, Any]:
        sleeve = self.sleeves[spot]
        if not sleeve.active:
            return {
                "active": False,
                "buffer": None,
                "basis": None,
                "new_breach": False,
            }
        mark = decimal_value(mark_price, "risk mark", positive=True)
        cash_price = decimal_value(spot_price, "risk spot", positive=True)
        notional = sleeve.short_quantity * mark
        if notional <= 0 or sleeve.margin_cash <= 0:
            raise C9AError("active C9A margin state is non-positive")
        buffer = sleeve.margin_cash / notional
        basis = mark / cash_price - Decimal(1)
        hedge_mismatch = sleeve.spot_quantity != sleeve.short_quantity
        if hedge_mismatch:
            sleeve.hedge_mismatches += 1
        breach = (
            buffer < MINIMUM_COLLATERAL_BUFFER or abs(basis) > MAXIMUM_RISK_ABS_BASIS
        )
        new_breach = breach and not sleeve.risk_exit_pending
        if new_breach:
            sleeve.collateral_buffer_breaches += int(buffer < MINIMUM_COLLATERAL_BUFFER)
        sleeve.risk_exit_pending = sleeve.risk_exit_pending or breach or hedge_mismatch
        return {
            "active": True,
            "buffer": str(buffer),
            "basis": str(basis),
            "buffer_breach": buffer < MINIMUM_COLLATERAL_BUFFER,
            "basis_breach": abs(basis) > MAXIMUM_RISK_ABS_BASIS,
            "hedge_mismatch": hedge_mismatch,
            "new_breach": new_breach,
        }

    def trade_target(
        self,
        *,
        spot: str,
        new_quantity: Any,
        target_margin_before_fee: Any,
        spot_trade_price: Any,
        swap_trade_price: Any,
        cost_rate: Any,
    ) -> dict[str, str]:
        sleeve = self.sleeves[spot]
        quantity = decimal_value(new_quantity, "target base quantity")
        collateral = decimal_value(target_margin_before_fee, "target margin")
        spot_price = decimal_value(spot_trade_price, "spot trade price", positive=True)
        swap_price = decimal_value(swap_trade_price, "swap trade price", positive=True)
        rate = decimal_value(cost_rate, "cost rate")
        if quantity < 0 or collateral < 0 or rate < 0:
            raise C9AError("C9A trade target cannot be negative")
        if (quantity == 0) != (collateral == 0):
            raise C9AError("flat quantity and target margin must agree")
        before_quantity = sleeve.spot_quantity
        before_short = sleeve.short_quantity
        before_margin = sleeve.margin_cash
        before_cash = self.free_cash
        delta_spot = quantity - before_quantity
        delta_short = quantity - before_short
        spot_cost = abs(delta_spot) * spot_price * rate
        swap_cost = abs(delta_short) * swap_price * rate
        self.free_cash -= delta_spot * spot_price + spot_cost
        if quantity == 0:
            remaining = before_margin - swap_cost
            if remaining < 0:
                raise C9AError("closing swap fee exceeds dedicated margin")
            self.free_cash += remaining
            sleeve.margin_cash = ZERO
            sleeve.risk_exit_pending = False
        else:
            transfer = collateral - before_margin
            self.free_cash -= transfer
            sleeve.margin_cash = collateral - swap_cost
            if sleeve.margin_cash <= 0:
                raise C9AError("post-fee active margin must be positive")
        sleeve.spot_quantity = quantity
        sleeve.short_quantity = quantity
        sleeve.last_spot_price = spot_price
        sleeve.last_perpetual_price = swap_price
        sleeve.components["spot_cost"] += spot_cost
        sleeve.components["swap_cost"] += swap_cost
        residual = self.assert_reconciled()
        return {
            "spot_instrument": spot,
            "quantity_before": str(before_quantity),
            "quantity_after": str(quantity),
            "short_before": str(before_short),
            "short_after": str(quantity),
            "spot_delta": str(delta_spot),
            "short_delta": str(delta_short),
            "spot_trade_price": str(spot_price),
            "swap_trade_price": str(swap_price),
            "spot_cost": str(spot_cost),
            "swap_cost": str(swap_cost),
            "margin_before": str(before_margin),
            "margin_after": str(sleeve.margin_cash),
            "free_cash_before": str(before_cash),
            "free_cash_after": str(self.free_cash),
            "reconciliation_residual": str(residual),
        }

    def close_for_risk(
        self,
        *,
        spot: str,
        timestamp: datetime,
        spot_trade_price: Any,
        swap_trade_price: Any,
        cost_rate: Any,
    ) -> dict[str, str]:
        event = self.trade_target(
            spot=spot,
            new_quantity=ZERO,
            target_margin_before_fee=ZERO,
            spot_trade_price=spot_trade_price,
            swap_trade_price=swap_trade_price,
            cost_rate=cost_rate,
        )
        next_monday = timestamp + timedelta(days=(7 - timestamp.weekday()) % 7)
        next_monday = next_monday.replace(hour=0, minute=0, second=0, microsecond=0)
        if next_monday <= timestamp:
            next_monday += timedelta(days=7)
        self.sleeves[spot].blocked_until = next_monday
        event["blocked_until"] = iso(next_monday)
        return event


def component_delta(
    later: Mapping[str, Decimal], earlier: Mapping[str, Decimal]
) -> dict[str, Decimal]:
    if set(later) != set(COMPONENT_NAMES) or set(earlier) != set(COMPONENT_NAMES):
        raise C9AError("component key drift")
    return {name: later[name] - earlier[name] for name in COMPONENT_NAMES}


def component_net(values: Mapping[str, Decimal]) -> Decimal:
    return (
        values["spot_price_pnl"]
        + values["perpetual_price_pnl"]
        + values["funding_pnl"]
        - values["spot_cost"]
        - values["swap_cost"]
    )
