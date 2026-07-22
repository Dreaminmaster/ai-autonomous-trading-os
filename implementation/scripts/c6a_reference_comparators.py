"""Independent C6A cash and spot comparator recomputation.

This module imports no production comparator, policy, simulation, aggregate, or
gate implementation.
"""
from __future__ import annotations

from datetime import timedelta
from decimal import Decimal, ROUND_FLOOR
from typing import Any, Mapping, Sequence

from atos.c6a_contract import (
    C6AError,
    MetadataRecord,
    SPOT_INSTRUMENTS,
    decimal_value,
    metadata_at,
    parse_timestamp,
    terminal_time,
    validate_config,
)
from atos.c6a_data import C6AMarket

ZERO = Decimal("0")
ONE = Decimal("1")


def reference_cash_window(
    *, window: Mapping[str, Any], cost_label: str, config: Mapping[str, Any]
) -> dict[str, Any]:
    validate_config(config)
    starting = decimal_value(config["starting_equity"], "starting equity")
    start = parse_timestamp(window["start"])
    weekly = [
        {
            "start_time": (start + timedelta(weeks=index)).isoformat(),
            "end_time": (start + timedelta(weeks=index + 1)).isoformat(),
            "start_equity": starting,
            "end_equity": starting,
            "pnl": ZERO,
            "return": ZERO,
            "active": False,
            "risk_exit": False,
        }
        for index in range(26)
    ]
    return {
        "policy_id": "CashComparator",
        "window_id": str(window["id"]),
        "cost_label": cost_label,
        "starting_equity": starting,
        "final_equity": starting,
        "net_return": ZERO,
        "maximum_drawdown": ZERO,
        "annualized_one_way_turnover": ZERO,
        "active_week_count": 0,
        "active_funding_settlements": 0,
        "collateral_buffer_breaches": 0,
        "hedge_breaches": 0,
        "asset_contributions": {"BTC": ZERO, "ETH": ZERO},
        "components": {
            "spot_price_pnl": ZERO,
            "perpetual_price_pnl": ZERO,
            "funding_pnl": ZERO,
            "spot_cost": ZERO,
            "swap_cost": ZERO,
        },
        "weekly": weekly,
    }


def _floor(value: Decimal, step: Decimal) -> Decimal:
    if value < 0 or step <= 0:
        raise C6AError("reference floor inputs invalid")
    return (value / step).to_integral_value(rounding=ROUND_FLOOR) * step


def reference_spot_buy_hold_window(
    market: C6AMarket,
    metadata: Sequence[MetadataRecord],
    *,
    window: Mapping[str, Any],
    cost_label: str,
    config: Mapping[str, Any],
) -> dict[str, Any]:
    validate_config(config)
    market.validate_alignment()
    start = parse_timestamp(window["start"])
    end = parse_timestamp(window["end"])
    terminal = terminal_time(window)
    times = tuple(row.timestamp for row in market.spot[SPOT_INSTRUMENTS[0]])
    index_by_time = {timestamp: index for index, timestamp in enumerate(times)}
    if start not in index_by_time or terminal not in index_by_time:
        raise C6AError("reference spot comparator coverage missing")
    start_index = index_by_time[start]
    terminal_index = index_by_time[terminal]
    starting = decimal_value(config["starting_equity"], "starting equity")
    fee_rate = decimal_value(config["cost_rates"][cost_label], "cost rate")
    budget = starting / Decimal(2)
    quantities: dict[str, Decimal] = {}
    initial_prices: dict[str, Decimal] = {}
    opening_fees: dict[str, Decimal] = {}
    cash = starting
    for spot in SPOT_INSTRUMENTS:
        price = market.spot[spot][start_index].open
        rule = metadata_at(metadata, spot, start)
        quantity = _floor(budget / (ONE + fee_rate) / price, rule.lot_size)
        if quantity < rule.minimum_size:
            raise C6AError("reference spot quantity below minimum")
        fee = quantity * price * fee_rate
        quantities[spot] = quantity
        initial_prices[spot] = price
        opening_fees[spot] = fee
        cash -= quantity * price + fee
    if cash < 0:
        raise C6AError("reference spot comparator negative opening cash")

    def equity(index: int, *, use_open: bool) -> Decimal:
        total = cash
        for spot in SPOT_INSTRUMENTS:
            candle = market.spot[spot][index]
            price = candle.open if use_open else candle.close
            total += quantities[spot] * price
        return total

    hourly = [starting - sum(opening_fees.values(), ZERO)]
    weekly: list[dict[str, Any]] = []
    week_start = starting
    week_start_time = start
    for index in range(start_index, terminal_index):
        timestamp = times[index]
        if timestamp > start and timestamp.weekday() == 0 and timestamp.hour == 0:
            current = equity(index, use_open=True)
            weekly.append(
                {
                    "start_time": week_start_time.isoformat(),
                    "end_time": timestamp.isoformat(),
                    "start_equity": week_start,
                    "end_equity": current,
                    "pnl": current - week_start,
                    "return": current / week_start - ONE,
                    "active": True,
                    "risk_exit": False,
                }
            )
            week_start = current
            week_start_time = timestamp
        hourly.append(equity(index, use_open=False))
    terminal_pre_cost = equity(terminal_index, use_open=True)
    closing_fees = {
        spot: quantities[spot] * market.spot[spot][terminal_index].open * fee_rate
        for spot in SPOT_INSTRUMENTS
    }
    final = terminal_pre_cost - sum(closing_fees.values(), ZERO)
    weekly.append(
        {
            "start_time": week_start_time.isoformat(),
            "end_time": end.isoformat(),
            "start_equity": week_start,
            "end_equity": final,
            "pnl": final - week_start,
            "return": final / week_start - ONE,
            "active": True,
            "risk_exit": False,
        }
    )
    if len(weekly) != 26:
        raise C6AError("reference spot comparator weekly count mismatch")
    hourly.append(final)
    peak = hourly[0]
    drawdown = ZERO
    for value in hourly:
        peak = max(peak, value)
        drawdown = max(drawdown, ONE - value / peak)
    contributions: dict[str, Decimal] = {}
    for spot in SPOT_INSTRUMENTS:
        final_price = market.spot[spot][terminal_index].open
        contributions[spot.split("-")[0]] = (
            quantities[spot] * (final_price - initial_prices[spot])
            - opening_fees[spot]
            - closing_fees[spot]
        )
    if sum(contributions.values(), ZERO) != final - starting:
        raise C6AError("reference spot contribution reconciliation failure")
    opening_turnover = sum(
        quantities[spot] * initial_prices[spot] for spot in SPOT_INSTRUMENTS
    ) / starting
    closing_turnover = sum(
        quantities[spot] * market.spot[spot][terminal_index].open
        for spot in SPOT_INSTRUMENTS
    ) / terminal_pre_cost
    turnover = (opening_turnover + closing_turnover) / (Decimal(26) / Decimal(52))
    total_fees = sum(opening_fees.values(), ZERO) + sum(closing_fees.values(), ZERO)
    return {
        "policy_id": "SpotBuyAndHoldComparator",
        "window_id": str(window["id"]),
        "cost_label": cost_label,
        "starting_equity": starting,
        "final_equity": final,
        "net_return": final / starting - ONE,
        "maximum_drawdown": drawdown,
        "annualized_one_way_turnover": turnover,
        "active_week_count": 26,
        "active_funding_settlements": 0,
        "collateral_buffer_breaches": 0,
        "hedge_breaches": 0,
        "asset_contributions": contributions,
        "components": {
            "spot_price_pnl": sum(contributions.values(), ZERO) + total_fees,
            "perpetual_price_pnl": ZERO,
            "funding_pnl": ZERO,
            "spot_cost": total_fees,
            "swap_cost": ZERO,
        },
        "weekly": weekly,
    }
