"""Non-selectable C6A cash and spot buy-and-hold comparators."""
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
from atos.c6a_metrics import annualized_one_way_turnover, maximum_drawdown

ZERO = Decimal("0")
COST_LABELS = ("1.0x", "1.5x", "2.0x")


def simulate_cash_window(
    *, window: Mapping[str, Any], cost_label: str, config: Mapping[str, Any]
) -> dict[str, Any]:
    validate_config(config)
    if window not in config["windows"] or cost_label not in COST_LABELS:
        raise C6AError("invalid cash-comparator window or cost label")
    start = parse_timestamp(window["start"])
    equity = decimal_value(config["starting_equity"], "starting equity")
    weekly = []
    for index in range(26):
        week_start = start + timedelta(weeks=index)
        weekly.append(
            {
                "window_id": str(window["id"]),
                "week_index": index,
                "start_time": week_start.isoformat(),
                "end_time": (week_start + timedelta(weeks=1)).isoformat(),
                "start_reference_equity": str(equity),
                "end_reference_equity": str(equity),
                "weekly_pnl": "0",
                "weekly_return": "0",
                "active": False,
                "risk_exit": False,
                "reconciliation_residual": "0",
            }
        )
    return {
        "schema_version": 1,
        "stage": "C6A",
        "status": "PASS",
        "policy_id": "CashComparator",
        "window_id": str(window["id"]),
        "cost_label": cost_label,
        "starting_equity": str(equity),
        "final_equity": str(equity),
        "net_return": "0",
        "maximum_drawdown": "0",
        "annualized_one_way_turnover": "0",
        "active_week_count": 0,
        "active_funding_settlements": 0,
        "collateral_buffer_breaches": 0,
        "hedge_breaches": 0,
        "asset_contributions": {"BTC": "0", "ETH": "0"},
        "components": {
            "spot_price_pnl": "0",
            "perpetual_price_pnl": "0",
            "funding_pnl": "0",
            "spot_cost": "0",
            "swap_cost": "0",
        },
        "weekly_buckets": weekly,
        "weekly_returns": ["0"] * 26,
        "decisions": [],
        "events": [],
        "confirmation_opened": False,
        "c5b_state": "C5B_CLOSED_AND_UNTOUCHED",
        "holdout_state": "HOLDOUT_CLOSED",
        "paper_state": "PAPER_CLOSED",
        "shadow_state": "SHADOW_CLOSED",
        "live": "FORBIDDEN",
    }


def _floor(value: Decimal, step: Decimal) -> Decimal:
    return (value / step).to_integral_value(rounding=ROUND_FLOOR) * step


def simulate_spot_buy_hold_window(
    market: C6AMarket,
    metadata_records: Sequence[MetadataRecord],
    *,
    window: Mapping[str, Any],
    cost_label: str,
    config: Mapping[str, Any],
) -> dict[str, Any]:
    validate_config(config)
    market.validate_alignment()
    if window not in config["windows"] or cost_label not in COST_LABELS:
        raise C6AError("invalid spot comparator window or cost label")
    start = parse_timestamp(window["start"])
    end = parse_timestamp(window["end"])
    terminal = terminal_time(window)
    index_by_time = {
        row.timestamp: index
        for index, row in enumerate(market.spot[SPOT_INSTRUMENTS[0]])
    }
    if start not in index_by_time or terminal not in index_by_time:
        raise C6AError("spot comparator window coverage missing")
    start_index = index_by_time[start]
    terminal_index = index_by_time[terminal]
    starting_equity = decimal_value(config["starting_equity"], "starting equity")
    fee_rate = decimal_value(config["cost_rates"][cost_label], "cost rate")
    quantities: dict[str, Decimal] = {}
    opening_costs: dict[str, Decimal] = {}
    cash = starting_equity
    per_asset_budget = starting_equity / Decimal(2)
    for spot in SPOT_INSTRUMENTS:
        price = market.spot[spot][start_index].open
        meta = metadata_at(metadata_records, spot, start)
        spend_before_fee = per_asset_budget / (Decimal("1") + fee_rate)
        quantity = _floor(spend_before_fee / price, meta.lot_size)
        if quantity < meta.minimum_size:
            raise C6AError(f"spot comparator quantity below minimum: {spot}")
        notional = quantity * price
        fee = notional * fee_rate
        quantities[spot] = quantity
        opening_costs[spot] = fee
        cash -= notional + fee
    if cash < 0:
        raise C6AError("spot comparator opening cash became negative")

    initial_prices = {
        spot: market.spot[spot][start_index].open for spot in SPOT_INSTRUMENTS
    }
    hourly_equity = [starting_equity - sum(opening_costs.values(), ZERO)]

    def marked_equity(index: int, *, use_open: bool) -> Decimal:
        values = ZERO
        for spot in SPOT_INSTRUMENTS:
            candle = market.spot[spot][index]
            price = candle.open if use_open else candle.close
            values += quantities[spot] * price
        return cash + values

    weekly = []
    week_start_equity = starting_equity
    for hour_index in range(start_index, terminal_index):
        timestamp = market.spot[SPOT_INSTRUMENTS[0]][hour_index].timestamp
        if timestamp > start and timestamp.weekday() == 0 and timestamp.hour == 0:
            current = marked_equity(hour_index, use_open=True)
            week_number = len(weekly)
            weekly.append(
                {
                    "window_id": str(window["id"]),
                    "week_index": week_number,
                    "start_time": (start + timedelta(weeks=week_number)).isoformat(),
                    "end_time": timestamp.isoformat(),
                    "start_reference_equity": str(week_start_equity),
                    "end_reference_equity": str(current),
                    "weekly_pnl": str(current - week_start_equity),
                    "weekly_return": str(current / week_start_equity - Decimal("1")),
                    "active": True,
                    "risk_exit": False,
                    "reconciliation_residual": "0",
                }
            )
            week_start_equity = current
        hourly_equity.append(marked_equity(hour_index, use_open=False))

    terminal_pre_cost = marked_equity(terminal_index, use_open=True)
    closing_costs = {
        spot: quantities[spot] * market.spot[spot][terminal_index].open * fee_rate
        for spot in SPOT_INSTRUMENTS
    }
    final_equity = terminal_pre_cost - sum(closing_costs.values(), ZERO)
    hourly_equity.append(final_equity)
    weekly.append(
        {
            "window_id": str(window["id"]),
            "week_index": len(weekly),
            "start_time": (start + timedelta(weeks=len(weekly))).isoformat(),
            "end_time": end.isoformat(),
            "start_reference_equity": str(week_start_equity),
            "end_reference_equity": str(final_equity),
            "weekly_pnl": str(final_equity - week_start_equity),
            "weekly_return": str(final_equity / week_start_equity - Decimal("1")),
            "active": True,
            "risk_exit": False,
            "reconciliation_residual": "0",
        }
    )
    if len(weekly) != 26:
        raise C6AError(f"spot comparator weekly count mismatch: {len(weekly)}")
    contributions = {}
    for spot in SPOT_INSTRUMENTS:
        terminal_price = market.spot[spot][terminal_index].open
        price_pnl = quantities[spot] * (terminal_price - initial_prices[spot])
        contributions[spot.split("-")[0]] = (
            price_pnl - opening_costs[spot] - closing_costs[spot]
        )
    if abs(sum(contributions.values(), ZERO) - (final_equity - starting_equity)) > Decimal("1e-8"):
        raise C6AError("spot comparator contribution reconciliation failure")
    opening_turnover = sum(
        quantities[spot] * initial_prices[spot] for spot in SPOT_INSTRUMENTS
    ) / starting_equity
    closing_turnover = sum(
        quantities[spot] * market.spot[spot][terminal_index].open
        for spot in SPOT_INSTRUMENTS
    ) / terminal_pre_cost
    costs = sum(opening_costs.values(), ZERO) + sum(closing_costs.values(), ZERO)
    return {
        "schema_version": 1,
        "stage": "C6A",
        "status": "PASS",
        "policy_id": "SpotBuyAndHoldComparator",
        "window_id": str(window["id"]),
        "cost_label": cost_label,
        "starting_equity": str(starting_equity),
        "final_equity": str(final_equity),
        "net_return": str(final_equity / starting_equity - Decimal("1")),
        "maximum_drawdown": str(maximum_drawdown(hourly_equity)),
        "annualized_one_way_turnover": str(
            annualized_one_way_turnover(
                (opening_turnover, closing_turnover), scored_weeks=26
            )
        ),
        "active_week_count": 26,
        "active_funding_settlements": 0,
        "collateral_buffer_breaches": 0,
        "hedge_breaches": 0,
        "asset_contributions": {key: str(value) for key, value in contributions.items()},
        "components": {
            "spot_price_pnl": str(
                sum(contributions.values(), ZERO) + costs
            ),
            "perpetual_price_pnl": "0",
            "funding_pnl": "0",
            "spot_cost": str(costs),
            "swap_cost": "0",
        },
        "weekly_buckets": weekly,
        "weekly_returns": [row["weekly_return"] for row in weekly],
        "decisions": [],
        "events": [
            {"kind": "SPOT_BUY_HOLD_OPEN", "time": start.isoformat()},
            {"kind": "SPOT_BUY_HOLD_TERMINAL", "time": terminal.isoformat()},
        ],
        "confirmation_opened": False,
        "c5b_state": "C5B_CLOSED_AND_UNTOUCHED",
        "holdout_state": "HOLDOUT_CLOSED",
        "paper_state": "PAPER_CLOSED",
        "shadow_state": "SHADOW_CLOSED",
        "live": "FORBIDDEN",
    }
