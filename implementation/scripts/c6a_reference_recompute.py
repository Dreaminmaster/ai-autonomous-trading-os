"""Independent C6A primitive-input recomputation.

This module intentionally does not import the production policy, rounding,
ledger, simulation, aggregation, metrics, comparator, evidence, or gate code.
It independently reconstructs the two delta-neutral policies from validated
primitive public inputs and the frozen semantic configuration.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal, ROUND_FLOOR
from typing import Any, Mapping, Sequence

import numpy as np
from scipy.stats import kurtosis, norm, skew

from atos.c6a_contract import (
    C6AError,
    FundingRecord,
    MetadataRecord,
    SPOT_INSTRUMENTS,
    SPOT_TO_SWAP,
    decimal_value,
    metadata_at,
    parse_timestamp,
    terminal_time,
    validate_config,
)
from atos.c6a_data import C6AMarket

ZERO = Decimal("0")
ONE = Decimal("1")
POLICIES = ("C6AMarketNeutralFundingCarry", "AlwaysOnDeltaNeutralComparator")
COST_LABELS = ("1.0x", "1.5x", "2.0x")


@dataclass
class RefComponents:
    spot_price_pnl: Decimal = ZERO
    perpetual_price_pnl: Decimal = ZERO
    funding_pnl: Decimal = ZERO
    spot_cost: Decimal = ZERO
    swap_cost: Decimal = ZERO

    @property
    def net(self) -> Decimal:
        return (
            self.spot_price_pnl
            + self.perpetual_price_pnl
            + self.funding_pnl
            - self.spot_cost
            - self.swap_cost
        )

    def snapshot(self) -> tuple[Decimal, Decimal, Decimal, Decimal, Decimal]:
        return (
            self.spot_price_pnl,
            self.perpetual_price_pnl,
            self.funding_pnl,
            self.spot_cost,
            self.swap_cost,
        )


@dataclass
class RefState:
    asset: str
    spot_quantity: Decimal = ZERO
    swap_quantity: Decimal = ZERO
    last_spot: Decimal | None = None
    last_swap: Decimal | None = None
    collateral: Decimal = ZERO
    components: RefComponents = field(default_factory=RefComponents)
    collateral_checkpoint: tuple[Decimal, Decimal, Decimal, Decimal, Decimal] = (
        ZERO,
        ZERO,
        ZERO,
        ZERO,
        ZERO,
    )
    collateral_breaches: int = 0
    hedge_breaches: int = 0
    risk_pending: bool = False

    @property
    def active(self) -> bool:
        return self.spot_quantity > 0 or self.swap_quantity > 0

    @property
    def hedge_error(self) -> Decimal:
        denominator = max(self.spot_quantity, self.swap_quantity)
        return ZERO if denominator == 0 else abs(self.spot_quantity - self.swap_quantity) / denominator

    @property
    def collateral_equity(self) -> Decimal:
        cp = self.collateral_checkpoint
        return (
            self.collateral
            + (self.components.perpetual_price_pnl - cp[1])
            + (self.components.funding_pnl - cp[2])
            - (self.components.swap_cost - cp[4])
        )


def _component_totals(states: Mapping[str, RefState]) -> RefComponents:
    result = RefComponents()
    for state in states.values():
        result.spot_price_pnl += state.components.spot_price_pnl
        result.perpetual_price_pnl += state.components.perpetual_price_pnl
        result.funding_pnl += state.components.funding_pnl
        result.spot_cost += state.components.spot_cost
        result.swap_cost += state.components.swap_cost
    return result


def _component_delta(
    states: Mapping[str, RefState],
    earlier: tuple[Decimal, Decimal, Decimal, Decimal, Decimal],
) -> RefComponents:
    current = _component_totals(states)
    return RefComponents(
        current.spot_price_pnl - earlier[0],
        current.perpetual_price_pnl - earlier[1],
        current.funding_pnl - earlier[2],
        current.spot_cost - earlier[3],
        current.swap_cost - earlier[4],
    )


def _equity(starting: Decimal, states: Mapping[str, RefState]) -> Decimal:
    equity = starting + _component_totals(states).net
    if equity <= 0:
        raise C6AError("reference C6A equity became non-positive")
    return equity


def _mark(state: RefState, spot: Decimal, swap: Decimal) -> None:
    if spot <= 0 or swap <= 0:
        raise C6AError("reference mark must be positive")
    if state.last_spot is None or state.last_swap is None:
        if state.active:
            raise C6AError("reference active state lacks prior mark")
    else:
        state.components.spot_price_pnl += state.spot_quantity * (spot - state.last_spot)
        state.components.perpetual_price_pnl += state.swap_quantity * (state.last_swap - swap)
    state.last_spot = spot
    state.last_swap = swap


def _fund(state: RefState, rate: Decimal, mark: Decimal) -> Decimal:
    pnl = state.swap_quantity * mark * rate
    state.components.funding_pnl += pnl
    return pnl


def _trade(
    state: RefState,
    *,
    new_spot: Decimal,
    new_swap: Decimal,
    spot_price: Decimal,
    swap_price: Decimal,
    fee_rate: Decimal,
    collateral: Decimal,
) -> tuple[Decimal, Decimal]:
    if min(new_spot, new_swap, collateral) < 0:
        raise C6AError("reference trade cannot use negative quantity/collateral")
    if new_swap > 0 and collateral <= 0:
        raise C6AError("reference active swap lacks collateral")
    spot_fee = abs(new_spot - state.spot_quantity) * spot_price * fee_rate
    swap_fee = abs(new_swap - state.swap_quantity) * swap_price * fee_rate
    checkpoint = state.components.snapshot()
    state.components.spot_cost += spot_fee
    state.components.swap_cost += swap_fee
    state.spot_quantity = new_spot
    state.swap_quantity = new_swap
    state.last_spot = spot_price
    state.last_swap = swap_price
    state.collateral = ZERO if new_spot == 0 and new_swap == 0 else collateral
    state.collateral_checkpoint = checkpoint
    if not state.active:
        state.risk_pending = False
    return spot_fee, swap_fee


def _observe_risk(
    state: RefState, *, mark: Decimal, basis: Decimal, config: Mapping[str, Any]
) -> None:
    if not state.active:
        return
    short_notional = state.swap_quantity * mark
    if short_notional <= 0:
        raise C6AError("reference active state has invalid short notional")
    buffer_breach = (
        state.collateral_equity / short_notional
        < decimal_value(config["minimum_collateral_buffer_ratio"], "buffer")
    )
    hedge_breach = state.hedge_error > decimal_value(
        config["maximum_hedge_error"], "hedge limit"
    )
    basis_breach = abs(basis) > decimal_value(config["maximum_risk_abs_basis"], "risk basis")
    state.collateral_breaches += int(buffer_breach)
    state.hedge_breaches += int(hedge_breach)
    state.risk_pending = state.risk_pending or buffer_breach or basis_breach


def _funding_signal(
    records: Sequence[FundingRecord], *, instrument: str, decision: datetime
) -> dict[str, Any]:
    start = decision - timedelta(days=28)
    selected = [
        row
        for row in records
        if row.instrument == instrument and start <= row.funding_time < decision
    ]
    if not selected:
        raise C6AError(f"reference funding lookback empty: {instrument}")
    total = sum((row.realized_rate for row in selected), ZERO)
    positive = sum(row.realized_rate > 0 for row in selected)
    share = Decimal(positive) / Decimal(len(selected))
    return {
        "settlement_count": len(selected),
        "positive_settlement_count": positive,
        "funding_sum_28d": total,
        "positive_funding_share_28d": share,
    }


def _eligible(signal: Mapping[str, Any], basis: Decimal, config: Mapping[str, Any]) -> bool:
    return (
        signal["funding_sum_28d"]
        > decimal_value(config["minimum_funding_sum_28d_exclusive"], "funding threshold")
        and signal["positive_funding_share_28d"]
        >= decimal_value(config["minimum_positive_funding_share"], "positive share")
        and abs(basis)
        <= decimal_value(config["maximum_entry_abs_basis"], "entry basis")
    )


def _floor(value: Decimal, step: Decimal) -> Decimal:
    return (value / step).to_integral_value(rounding=ROUND_FLOOR) * step


def _round_pair(
    *,
    desired: Decimal,
    target_notional: Decimal,
    spot_price: Decimal,
    swap_price: Decimal,
    spot_meta: MetadataRecord,
    swap_meta: MetadataRecord,
    hedge_limit: Decimal,
) -> tuple[Decimal, Decimal, Decimal] | None:
    if swap_meta.contract_value is None:
        raise C6AError("reference swap contract value missing")
    contract_value = swap_meta.contract_value
    maximum_count = (desired + contract_value * swap_meta.lot_size) / contract_value
    first_units = int(
        (swap_meta.minimum_size / swap_meta.lot_size).to_integral_value(
            rounding=ROUND_FLOOR
        )
    )
    if Decimal(first_units) * swap_meta.lot_size < swap_meta.minimum_size:
        first_units += 1
    final_units = int(
        (maximum_count / swap_meta.lot_size).to_integral_value(rounding=ROUND_FLOOR)
    )
    candidates: list[tuple[Decimal, Decimal, Decimal, Decimal]] = []
    for units in range(first_units, final_units + 1):
        contracts = Decimal(units) * swap_meta.lot_size
        swap_quantity = contracts * contract_value
        spot_cap = min(desired, swap_quantity, target_notional / spot_price)
        spot_quantity = _floor(spot_cap, spot_meta.lot_size)
        if spot_quantity < spot_meta.minimum_size:
            continue
        denominator = max(spot_quantity, swap_quantity)
        error = abs(spot_quantity - swap_quantity) / denominator
        if error > hedge_limit:
            continue
        paired = min(spot_quantity * spot_price, swap_quantity * swap_price)
        candidates.append((error, -paired, contracts, spot_quantity))
    if not candidates:
        return None
    error, _, contracts, spot_quantity = min(candidates)
    return spot_quantity, contracts * contract_value, error


def _decision_targets(
    *,
    policy_id: str,
    timestamp: datetime,
    states: Mapping[str, RefState],
    total_equity: Decimal,
    spot_prices: Mapping[str, Decimal],
    swap_prices: Mapping[str, Decimal],
    basis: Mapping[str, Decimal],
    funding: Sequence[FundingRecord],
    config: Mapping[str, Any],
) -> tuple[dict[str, dict[str, Any]], tuple[str, ...]]:
    inputs: dict[str, dict[str, Any]] = {}
    eligible_assets: list[str] = []
    for spot in SPOT_INSTRUMENTS:
        if policy_id == "AlwaysOnDeltaNeutralComparator":
            signal = {
                "settlement_count": 0,
                "positive_settlement_count": 0,
                "funding_sum_28d": ZERO,
                "positive_funding_share_28d": ZERO,
            }
            eligible = True
        else:
            signal = _funding_signal(
                funding, instrument=SPOT_TO_SWAP[spot], decision=timestamp
            )
            eligible = _eligible(signal, basis[spot], config)
        inputs[spot] = {
            "basis": basis[spot],
            "signal": signal,
            "eligible": eligible,
        }
        if eligible:
            eligible_assets.append(spot)
    sleeve = ZERO if not eligible_assets else total_equity / Decimal(len(eligible_assets))
    resize_band = decimal_value(config["resizing_band"], "resize band")
    for spot in SPOT_INSTRUMENTS:
        current = min(
            states[spot].spot_quantity * spot_prices[spot],
            states[spot].swap_quantity * swap_prices[spot],
        )
        if spot not in eligible_assets:
            action = "CLOSE" if current > 0 else "HOLD_CASH"
            target_spot = ZERO
            target_collateral = ZERO
        else:
            target_spot = sleeve / Decimal(3)
            target_collateral = sleeve * Decimal(2) / Decimal(3)
            if current == 0:
                action = "OPEN"
            elif abs(target_spot - current) / current >= resize_band:
                action = "RESIZE"
            else:
                action = "HOLD"
        inputs[spot].update(
            {
                "action": action,
                "spot_target_notional": target_spot,
                "collateral_target": target_collateral,
            }
        )
    return inputs, tuple(eligible_assets)


def _solve(
    *,
    timestamp: datetime,
    states: Mapping[str, RefState],
    targets: Mapping[str, Mapping[str, Any]],
    metadata: Sequence[MetadataRecord],
    spot_prices: Mapping[str, Decimal],
    swap_prices: Mapping[str, Decimal],
    total_equity: Decimal,
    fee_rate: Decimal,
    config: Mapping[str, Any],
    blocked: set[str],
) -> tuple[Decimal, dict[str, tuple[Decimal, Decimal, Decimal, Decimal]], Decimal]:
    hedge_limit = decimal_value(config["maximum_hedge_error"], "hedge limit")

    def at(scale: Decimal):
        solved: dict[str, tuple[Decimal, Decimal, Decimal, Decimal]] = {}
        allocated = ZERO
        fees = ZERO
        for spot in SPOT_INSTRUMENTS:
            target = targets[spot]
            action = str(target["action"])
            if spot in blocked:
                action = "CLOSE" if states[spot].active else "HOLD_CASH"
            new_spot = ZERO
            new_swap = ZERO
            collateral = ZERO
            error = ZERO
            if action == "HOLD":
                new_spot = states[spot].spot_quantity
                new_swap = states[spot].swap_quantity
                collateral = states[spot].collateral
                allocated += new_spot * spot_prices[spot] + collateral
            elif action in {"OPEN", "RESIZE"} and scale > 0:
                spot_target = target["spot_target_notional"] * scale
                collateral = target["collateral_target"] * scale
                spot_meta = metadata_at(metadata, spot, timestamp)
                swap_meta = metadata_at(metadata, SPOT_TO_SWAP[spot], timestamp)
                pair = _round_pair(
                    desired=spot_target / spot_prices[spot],
                    target_notional=spot_target,
                    spot_price=spot_prices[spot],
                    swap_price=swap_prices[spot],
                    spot_meta=spot_meta,
                    swap_meta=swap_meta,
                    hedge_limit=hedge_limit,
                )
                if pair is not None:
                    new_spot, new_swap, error = pair
                    allocated += new_spot * spot_prices[spot] + collateral
                else:
                    collateral = ZERO
            fees += abs(new_spot - states[spot].spot_quantity) * spot_prices[spot] * fee_rate
            fees += abs(new_swap - states[spot].swap_quantity) * swap_prices[spot] * fee_rate
            solved[spot] = (new_spot, new_swap, collateral, error)
        return solved, allocated, fees

    solved, allocated, fees = at(ONE)
    if allocated + fees <= total_equity:
        return ONE, solved, total_equity - allocated - fees
    low, high = ZERO, ONE
    feasible = at(ZERO)
    for _ in range(120):
        mid = (low + high) / Decimal(2)
        candidate = at(mid)
        if candidate[1] + candidate[2] <= total_equity:
            low = mid
            feasible = candidate
        else:
            high = mid
    solved, allocated, fees = feasible
    residual = total_equity - allocated - fees
    if residual < 0:
        raise C6AError("reference target solve negative residual")
    return low, solved, residual


def recompute_window(
    market: C6AMarket,
    funding: Sequence[FundingRecord],
    metadata: Sequence[MetadataRecord],
    *,
    policy_id: str,
    window: Mapping[str, Any],
    cost_label: str,
    config: Mapping[str, Any],
) -> dict[str, Any]:
    validate_config(config)
    market.validate_alignment()
    if policy_id not in POLICIES or cost_label not in COST_LABELS:
        raise C6AError("invalid reference policy or cost label")
    start = parse_timestamp(window["start"])
    end = parse_timestamp(window["end"])
    terminal = terminal_time(window)
    times = tuple(start + timedelta(hours=index) for index in range(int((end-start).total_seconds()/3600)))
    reference = market.spot[SPOT_INSTRUMENTS[0]]
    index_by_time = {row.timestamp: index for index, row in enumerate(reference)}
    if any(timestamp not in index_by_time for timestamp in times):
        raise C6AError("reference window coverage missing")
    fee_rate = decimal_value(config["cost_rates"][cost_label], "cost")
    starting = decimal_value(config["starting_equity"], "starting equity")
    states = {spot: RefState(asset=spot.split("-")[0]) for spot in SPOT_INSTRUMENTS}
    funding_by_key = {(row.instrument, row.funding_time): row for row in funding}
    weekly: list[dict[str, Any]] = []
    decisions: list[dict[str, Any]] = []
    events: list[dict[str, Any]] = []
    hourly_equity = [starting]
    turnover: list[Decimal] = []
    active_funding = 0
    week_start_time: datetime | None = None
    week_start_equity: Decimal | None = None
    week_start_components: tuple[Decimal, Decimal, Decimal, Decimal, Decimal] | None = None
    week_active = False
    week_risk = False

    for timestamp in times:
        index = index_by_time[timestamp]
        spot_open = {spot: market.spot[spot][index].open for spot in SPOT_INSTRUMENTS}
        spot_close = {spot: market.spot[spot][index].close for spot in SPOT_INSTRUMENTS}
        swap_open = {spot: market.swap[SPOT_TO_SWAP[spot]][index].open for spot in SPOT_INSTRUMENTS}
        mark_close = {spot: market.mark[SPOT_TO_SWAP[spot]][index].close for spot in SPOT_INSTRUMENTS}
        for spot in SPOT_INSTRUMENTS:
            _mark(states[spot], spot_open[spot], swap_open[spot])
        boundary_equity = _equity(starting, states)
        if timestamp.weekday() == 0 and timestamp.hour == 0:
            if week_start_time is not None:
                assert week_start_equity is not None and week_start_components is not None
                components = _component_delta(states, week_start_components)
                pnl = boundary_equity - week_start_equity
                residual = pnl - components.net
                if abs(residual) > Decimal("1e-8"):
                    raise C6AError(f"reference weekly reconciliation: {residual}")
                weekly.append(
                    {
                        "start_time": week_start_time.isoformat(),
                        "end_time": timestamp.isoformat(),
                        "start_equity": week_start_equity,
                        "end_equity": boundary_equity,
                        "pnl": pnl,
                        "return": pnl / week_start_equity,
                        "components": components,
                        "active": week_active,
                        "risk_exit": week_risk,
                    }
                )
            week_start_time = timestamp
            week_start_equity = boundary_equity
            week_start_components = _component_totals(states).snapshot()
            week_active = any(state.active for state in states.values())
            week_risk = False

        preceding_marks = None if index == 0 else {
            spot: market.mark[SPOT_TO_SWAP[spot]][index-1].close for spot in SPOT_INSTRUMENTS
        }
        for spot in SPOT_INSTRUMENTS:
            record = funding_by_key.get((SPOT_TO_SWAP[spot], timestamp))
            if record is None:
                continue
            if preceding_marks is None:
                raise C6AError("reference funding lacks predecessor mark")
            was_active = states[spot].swap_quantity > 0
            pnl = _fund(states[spot], record.realized_rate, preceding_marks[spot])
            active_funding += int(was_active)
            events.append(
                {
                    "kind": "FUNDING",
                    "time": timestamp.isoformat(),
                    "instrument": record.instrument,
                    "rate": record.realized_rate,
                    "quantity": states[spot].swap_quantity,
                    "mark": preceding_marks[spot],
                    "pnl": pnl,
                    "active": was_active,
                }
            )

        blocked: set[str] = set()
        for spot in SPOT_INSTRUMENTS:
            if states[spot].risk_pending:
                before_spot = states[spot].spot_quantity
                before_swap = states[spot].swap_quantity
                equity_before = _equity(starting, states)
                _trade(
                    states[spot],
                    new_spot=ZERO,
                    new_swap=ZERO,
                    spot_price=spot_open[spot],
                    swap_price=swap_open[spot],
                    fee_rate=fee_rate,
                    collateral=ZERO,
                )
                paired = Decimal("0.5") * (
                    before_spot * spot_open[spot] + before_swap * swap_open[spot]
                )
                turnover.append(paired / equity_before)
                blocked.add(spot)
                week_risk = True
                events.append({"kind": "RISK_EXIT", "time": timestamp.isoformat(), "spot": spot})

        if timestamp == terminal:
            for spot in SPOT_INSTRUMENTS:
                if not states[spot].active:
                    continue
                before_spot = states[spot].spot_quantity
                before_swap = states[spot].swap_quantity
                equity_before = _equity(starting, states)
                _trade(
                    states[spot],
                    new_spot=ZERO,
                    new_swap=ZERO,
                    spot_price=spot_open[spot],
                    swap_price=swap_open[spot],
                    fee_rate=fee_rate,
                    collateral=ZERO,
                )
                turnover.append(
                    Decimal("0.5")
                    * (before_spot * spot_open[spot] + before_swap * swap_open[spot])
                    / equity_before
                )
                events.append({"kind": "TERMINAL", "time": timestamp.isoformat(), "spot": spot})
            final_equity = _equity(starting, states)
            assert week_start_time is not None and week_start_equity is not None and week_start_components is not None
            components = _component_delta(states, week_start_components)
            pnl = final_equity - week_start_equity
            residual = pnl - components.net
            if abs(residual) > Decimal("1e-8"):
                raise C6AError(f"reference terminal weekly reconciliation: {residual}")
            weekly.append(
                {
                    "start_time": week_start_time.isoformat(),
                    "end_time": end.isoformat(),
                    "start_equity": week_start_equity,
                    "end_equity": final_equity,
                    "pnl": pnl,
                    "return": pnl / week_start_equity,
                    "components": components,
                    "active": week_active,
                    "risk_exit": week_risk,
                }
            )
            hourly_equity.append(final_equity)
            break

        if timestamp.weekday() == 0 and timestamp.hour == 0:
            signal_index = index - 2
            if signal_index < 0:
                raise C6AError("reference decision lacks Sunday 22 close")
            basis = {
                spot: market.mark[SPOT_TO_SWAP[spot]][signal_index].close
                / market.spot[spot][signal_index].close
                - ONE
                for spot in SPOT_INSTRUMENTS
            }
            total_equity = _equity(starting, states)
            targets, eligible_assets = _decision_targets(
                policy_id=policy_id,
                timestamp=timestamp,
                states=states,
                total_equity=total_equity,
                spot_prices=spot_open,
                swap_prices=swap_open,
                basis=basis,
                funding=funding,
                config=config,
            )
            scale, solved, residual_cash = _solve(
                timestamp=timestamp,
                states=states,
                targets=targets,
                metadata=metadata,
                spot_prices=spot_open,
                swap_prices=swap_open,
                total_equity=total_equity,
                fee_rate=fee_rate,
                config=config,
                blocked=blocked,
            )
            decision_row = {
                "time": timestamp,
                "eligible_assets": eligible_assets,
                "scale": scale,
                "residual_cash": residual_cash,
                "inputs": targets,
                "targets": {},
            }
            for spot in SPOT_INSTRUMENTS:
                action = str(targets[spot]["action"])
                if spot in blocked:
                    action = "BLOCKED_AFTER_RISK_EXIT"
                if action != "HOLD":
                    before_spot = states[spot].spot_quantity
                    before_swap = states[spot].swap_quantity
                    equity_before = _equity(starting, states)
                    new_spot, new_swap, collateral, error = solved[spot]
                    _trade(
                        states[spot],
                        new_spot=new_spot,
                        new_swap=new_swap,
                        spot_price=spot_open[spot],
                        swap_price=swap_open[spot],
                        fee_rate=fee_rate,
                        collateral=collateral,
                    )
                    turnover.append(
                        Decimal("0.5")
                        * (
                            abs(new_spot - before_spot) * spot_open[spot]
                            + abs(new_swap - before_swap) * swap_open[spot]
                        )
                        / equity_before
                    )
                decision_row["targets"][spot] = {
                    "action": action,
                    "spot_quantity": states[spot].spot_quantity,
                    "swap_quantity": states[spot].swap_quantity,
                    "collateral": states[spot].collateral,
                    "hedge_error": states[spot].hedge_error,
                }
            decisions.append(decision_row)

        week_active = week_active or any(state.active for state in states.values())
        for spot in SPOT_INSTRUMENTS:
            _mark(states[spot], spot_close[spot], mark_close[spot])
            _observe_risk(
                states[spot],
                mark=mark_close[spot],
                basis=mark_close[spot] / spot_close[spot] - ONE,
                config=config,
            )
        hourly_equity.append(_equity(starting, states))

    if len(weekly) != 26 or len(decisions) != 26:
        raise C6AError("reference window evidence count mismatch")
    if any(state.active for state in states.values()):
        raise C6AError("reference window ended active")
    final_equity = _equity(starting, states)
    components = _component_totals(states)
    weekly_pnl = sum((row["pnl"] for row in weekly), ZERO)
    if abs(weekly_pnl - components.net) > Decimal("1e-8"):
        raise C6AError("reference window reconciliation failure")
    peak = hourly_equity[0]
    drawdown = ZERO
    for equity in hourly_equity:
        peak = max(peak, equity)
        drawdown = max(drawdown, ONE - equity / peak)
    annualized_turnover = sum(turnover, ZERO) / (Decimal(26) / Decimal(52))
    return {
        "policy_id": policy_id,
        "window_id": str(window["id"]),
        "cost_label": cost_label,
        "starting_equity": starting,
        "final_equity": final_equity,
        "net_return": final_equity / starting - ONE,
        "maximum_drawdown": drawdown,
        "annualized_one_way_turnover": annualized_turnover,
        "active_week_count": sum(bool(row["active"]) for row in weekly),
        "active_funding_settlements": active_funding,
        "collateral_buffer_breaches": sum(state.collateral_breaches for state in states.values()),
        "hedge_breaches": sum(state.hedge_breaches for state in states.values()),
        "asset_contributions": {state.asset: state.components.net for state in states.values()},
        "components": components,
        "weekly": weekly,
        "decisions": decisions,
        "events": events,
    }


def reference_statistics(weekly_returns: Sequence[Decimal]) -> dict[str, Any]:
    values = np.asarray([float(value) for value in weekly_returns], dtype=float)
    if len(values) != 130 or not np.isfinite(values).all():
        raise C6AError("reference statistics require 130 finite weeks")
    standard = float(np.std(values, ddof=1))
    if standard <= 0 or not math.isfinite(standard):
        raise C6AError("reference weekly variance is invalid")
    mean = float(np.mean(values))
    weekly_sharpe = mean / standard
    sample_skew = float(skew(values, bias=False))
    ordinary_kurtosis = float(kurtosis(values, fisher=False, bias=False))
    denominator = math.sqrt(
        1
        - sample_skew * weekly_sharpe
        + ((ordinary_kurtosis - 1) / 4) * weekly_sharpe**2
    )
    z = weekly_sharpe * math.sqrt(129) / denominator
    return {
        "n": 130,
        "mean": mean,
        "sample_std": standard,
        "weekly_sharpe": weekly_sharpe,
        "annualized_weekly_sharpe": weekly_sharpe * math.sqrt(52),
        "unbiased_skewness": sample_skew,
        "unbiased_ordinary_kurtosis": ordinary_kurtosis,
        "psr_numerator": weekly_sharpe * math.sqrt(129),
        "psr_denominator": denominator,
        "psr_z_score": z,
        "psr_probability": float(norm.cdf(z)),
        "weekly_statistic": "PSR_NOT_DSR",
        "program_level_sequential_history_corrected": False,
    }


def aggregate_reference(windows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    by_id = {str(row["window_id"]): row for row in windows}
    if set(by_id) != {"W1", "W2", "W3", "W4", "W5"}:
        raise C6AError("reference aggregate window set mismatch")
    ordered = [by_id[f"W{i}"] for i in range(1, 6)]
    weekly = [row["return"] for window in ordered for row in window["weekly"]]
    statistics = reference_statistics(weekly)
    final = sum((row["final_equity"] for row in ordered), ZERO)
    window_pnl = {row["window_id"]: row["final_equity"] - Decimal("1000") for row in ordered}
    week_pnl = {
        f"{row['window_id']}-week-{index:02d}": bucket["pnl"]
        for row in ordered
        for index, bucket in enumerate(row["weekly"])
    }
    asset_pnl = {"BTC": ZERO, "ETH": ZERO}
    for row in ordered:
        for asset in asset_pnl:
            asset_pnl[asset] += row["asset_contributions"][asset]
    costs = sum(
        (
            row["components"].spot_cost + row["components"].swap_cost
            for row in ordered
        ),
        ZERO,
    )
    receipts = sum(
        (
            max(event["pnl"], ZERO)
            for row in ordered
            for event in row["events"]
            if event["kind"] == "FUNDING"
        ),
        ZERO,
    )
    return {
        "policy_id": ordered[0]["policy_id"],
        "cost_label": ordered[0]["cost_label"],
        "aggregate_return": final / Decimal("5000") - ONE,
        "window_returns": {row["window_id"]: row["net_return"] for row in ordered},
        "window_pnl": window_pnl,
        "weekly_returns": weekly,
        "weekly_pnl": week_pnl,
        "statistics": statistics,
        "maximum_drawdown": max(row["maximum_drawdown"] for row in ordered),
        "annualized_one_way_turnover": sum(
            (row["annualized_one_way_turnover"] for row in ordered), ZERO
        ) / Decimal("5"),
        "funding_cost_coverage": None if costs == 0 else receipts / costs,
        "active_weeks_total": sum(int(row["active_week_count"]) for row in ordered),
        "active_weeks_by_window": {
            row["window_id"]: int(row["active_week_count"]) for row in ordered
        },
        "active_funding_settlements": sum(
            int(row["active_funding_settlements"]) for row in ordered
        ),
        "collateral_buffer_breaches": sum(
            int(row["collateral_buffer_breaches"]) for row in ordered
        ),
        "hedge_breaches": sum(int(row["hedge_breaches"]) for row in ordered),
        "asset_pnl": asset_pnl,
    }
