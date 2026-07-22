"""C6A independent-window hourly simulation and accounting.

This module consumes validated public primitives only.  It does not download
market data and has no authenticated, account, order, paper, shadow, or live
path.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, Mapping, Sequence

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
from atos.c6a_ledger import PnLComponents, SleeveState
from atos.c6a_metrics import annualized_one_way_turnover, maximum_drawdown
from atos.c6a_policy import (
    AssetTarget,
    WeeklyPolicyDecision,
    construct_always_on_decision,
    construct_candidate_decision,
)
from atos.c6a_rounding import RoundedPair, SpotRules, SwapRules, joint_round_pair

COST_LABELS = ("1.0x", "1.5x", "2.0x")
POLICY_IDS = ("C6AMarketNeutralFundingCarry", "AlwaysOnDeltaNeutralComparator")
ZERO = Decimal("0")


@dataclass(frozen=True)
class SolvedTarget:
    target: AssetTarget
    pair: RoundedPair | None
    collateral: Decimal


@dataclass(frozen=True)
class TargetSolution:
    scale: Decimal
    residual_cash: Decimal
    solved: Mapping[str, SolvedTarget]
    estimated_fees: Decimal


def _aggregate_components(states: Mapping[str, SleeveState]) -> PnLComponents:
    result = PnLComponents()
    for state in states.values():
        result = result.add(
            spot_price_pnl=state.components.spot_price_pnl,
            perpetual_price_pnl=state.components.perpetual_price_pnl,
            funding_pnl=state.components.funding_pnl,
            spot_cost=state.components.spot_cost,
            swap_cost=state.components.swap_cost,
        )
    return result


def _equity(starting_equity: Decimal, states: Mapping[str, SleeveState]) -> Decimal:
    result = starting_equity + _aggregate_components(states).net_pnl
    if result <= 0:
        raise C6AError("C6A equity became non-positive")
    return result


def _current_paired_notional(
    state: SleeveState, *, spot_price: Decimal, swap_price: Decimal
) -> Decimal:
    if not state.active:
        return ZERO
    return min(state.spot_quantity * spot_price, state.perpetual_base_quantity * swap_price)


def _rules(
    records: Sequence[MetadataRecord],
    *,
    spot: str,
    timestamp: datetime,
) -> tuple[SpotRules, SwapRules]:
    swap = SPOT_TO_SWAP[spot]
    spot_meta = metadata_at(records, spot, timestamp)
    swap_meta = metadata_at(records, swap, timestamp)
    if swap_meta.contract_value is None:
        raise C6AError("swap contract value missing after metadata validation")
    return (
        SpotRules(spot, spot_meta.lot_size, spot_meta.minimum_size),
        SwapRules(
            swap,
            swap_meta.contract_value,
            swap_meta.lot_size,
            swap_meta.minimum_size,
        ),
    )


def _solve_targets(
    *,
    decision: WeeklyPolicyDecision,
    states: Mapping[str, SleeveState],
    metadata_records: Sequence[MetadataRecord],
    timestamp: datetime,
    spot_prices: Mapping[str, Decimal],
    swap_prices: Mapping[str, Decimal],
    total_equity: Decimal,
    fee_rate: Decimal,
    config: Mapping[str, Any],
    blocked_assets: set[str],
) -> TargetSolution:
    target_by_spot = {row.spot_instrument: row for row in decision.targets}
    if set(target_by_spot) != set(SPOT_INSTRUMENTS):
        raise C6AError("policy target set mismatch")

    def at_scale(scale: Decimal) -> tuple[dict[str, SolvedTarget], Decimal, Decimal]:
        solved: dict[str, SolvedTarget] = {}
        allocated = ZERO
        fees = ZERO
        for spot in SPOT_INSTRUMENTS:
            target = target_by_spot[spot]
            state = states[spot]
            action = target.action
            if spot in blocked_assets:
                action = "CLOSE" if state.active else "HOLD_CASH"
            pair: RoundedPair | None = None
            collateral = ZERO
            if action == "HOLD":
                allocated += state.spot_quantity * spot_prices[spot] + state.dedicated_collateral
            elif action in {"OPEN", "RESIZE"} and scale > 0:
                scaled_spot_target = target.spot_target_notional * scale
                collateral = target.collateral_target * scale
                if scaled_spot_target > 0:
                    spot_rules, swap_rules = _rules(
                        metadata_records, spot=spot, timestamp=timestamp
                    )
                    pair = joint_round_pair(
                        desired_base_quantity=scaled_spot_target / spot_prices[spot],
                        post_cost_spot_target=scaled_spot_target,
                        spot_price=spot_prices[spot],
                        swap_price=swap_prices[spot],
                        spot_rules=spot_rules,
                        swap_rules=swap_rules,
                        maximum_hedge_error=config["maximum_hedge_error"],
                    )
                if pair is not None:
                    allocated += pair.spot_notional + collateral
                else:
                    collateral = ZERO
            new_spot = (
                state.spot_quantity
                if action == "HOLD"
                else (ZERO if pair is None else pair.spot_quantity)
            )
            new_swap = (
                state.perpetual_base_quantity
                if action == "HOLD"
                else (ZERO if pair is None else pair.perpetual_base_quantity)
            )
            fees += abs(new_spot - state.spot_quantity) * spot_prices[spot] * fee_rate
            fees += abs(new_swap - state.perpetual_base_quantity) * swap_prices[spot] * fee_rate
            solved[spot] = SolvedTarget(target=target, pair=pair, collateral=collateral)
        return solved, allocated, fees

    solved, allocated, fees = at_scale(Decimal("1"))
    if allocated + fees <= total_equity:
        return TargetSolution(
            scale=Decimal("1"),
            residual_cash=total_equity - allocated - fees,
            solved=solved,
            estimated_fees=fees,
        )
    low, high = ZERO, Decimal("1")
    feasible: tuple[dict[str, SolvedTarget], Decimal, Decimal] | None = None
    for _ in range(120):
        mid = (low + high) / Decimal(2)
        candidate = at_scale(mid)
        if candidate[1] + candidate[2] <= total_equity:
            low = mid
            feasible = candidate
        else:
            high = mid
    if feasible is None:
        feasible = at_scale(ZERO)
        if feasible[1] + feasible[2] > total_equity:
            raise C6AError("no feasible post-cost target scale")
    solved, allocated, fees = feasible
    residual = total_equity - allocated - fees
    if residual < 0:
        raise C6AError("target solver produced negative residual cash")
    return TargetSolution(
        scale=low,
        residual_cash=residual,
        solved=solved,
        estimated_fees=fees,
    )


def _trade_turnover(
    *,
    before: SleeveState,
    after: SleeveState,
    spot_price: Decimal,
    swap_price: Decimal,
    pre_trade_equity: Decimal,
) -> Decimal:
    paired = Decimal("0.5") * (
        abs(after.spot_quantity - before.spot_quantity) * spot_price
        + abs(after.perpetual_base_quantity - before.perpetual_base_quantity)
        * swap_price
    )
    return paired / pre_trade_equity


def _finalize_week(
    *,
    window_id: str,
    week_index: int,
    start_time: datetime,
    end_time: datetime,
    start_equity: Decimal,
    end_equity: Decimal,
    start_components: PnLComponents,
    states: Mapping[str, SleeveState],
    active: bool,
    risk_exit: bool,
) -> dict[str, Any]:
    components = _aggregate_components(states).minus(start_components)
    pnl = end_equity - start_equity
    residual = pnl - components.net_pnl
    if abs(residual) > Decimal("1e-8"):
        raise C6AError(f"weekly reconciliation residual: {residual}")
    return {
        "window_id": window_id,
        "week_index": week_index,
        "start_time": start_time.isoformat(),
        "end_time": end_time.isoformat(),
        "start_reference_equity": str(start_equity),
        "end_reference_equity": str(end_equity),
        "weekly_pnl": str(pnl),
        "weekly_return": str(pnl / start_equity),
        "components": {key: str(value) for key, value in asdict(components).items()},
        "reconciliation_residual": str(residual),
        "active": active,
        "risk_exit": risk_exit,
    }


def simulate_policy_window(
    market: C6AMarket,
    funding_records: Sequence[FundingRecord],
    metadata_records: Sequence[MetadataRecord],
    *,
    policy_id: str,
    window: Mapping[str, Any],
    cost_label: str,
    config: Mapping[str, Any],
) -> dict[str, Any]:
    validate_config(config)
    market.validate_alignment()
    if policy_id not in POLICY_IDS:
        raise C6AError(f"unknown C6A policy: {policy_id}")
    if cost_label not in COST_LABELS:
        raise C6AError(f"unknown C6A cost label: {cost_label}")
    if window not in config["windows"]:
        raise C6AError("window is not part of frozen C6A configuration")
    start = parse_timestamp(window["start"])
    end = parse_timestamp(window["end"])
    terminal = terminal_time(window)
    expected_times = tuple(start + timedelta(hours=index) for index in range(int((end - start).total_seconds() // 3600)))
    reference = market.spot[SPOT_INSTRUMENTS[0]]
    index_by_time = {row.timestamp: index for index, row in enumerate(reference)}
    missing = [stamp for stamp in expected_times if stamp not in index_by_time]
    if missing:
        raise C6AError(f"window hourly coverage missing: {missing[0].isoformat()}")
    fee_rate = decimal_value(config["cost_rates"][cost_label], "cost rate")
    starting_equity = decimal_value(config["starting_equity"], "starting equity")
    states = {spot: SleeveState(asset=spot.split("-")[0]) for spot in SPOT_INSTRUMENTS}
    funding_by_key = {(row.instrument, row.funding_time): row for row in funding_records}
    if len(funding_by_key) != len(funding_records):
        raise C6AError("duplicate funding records reached simulator")

    weekly: list[dict[str, Any]] = []
    decisions: list[dict[str, Any]] = []
    events: list[dict[str, Any]] = []
    hourly_equity: list[Decimal] = [starting_equity]
    turnover: list[Decimal] = []
    active_funding_settlements = 0
    week_start_time: datetime | None = None
    week_start_equity: Decimal | None = None
    week_start_components: PnLComponents | None = None
    week_active = False
    week_risk_exit = False

    for timestamp in expected_times:
        index = index_by_time[timestamp]
        spot_open = {spot: market.spot[spot][index].open for spot in SPOT_INSTRUMENTS}
        spot_close = {spot: market.spot[spot][index].close for spot in SPOT_INSTRUMENTS}
        swap_open = {
            spot: market.swap[SPOT_TO_SWAP[spot]][index].open for spot in SPOT_INSTRUMENTS
        }
        mark_close = {
            spot: market.mark[SPOT_TO_SWAP[spot]][index].close for spot in SPOT_INSTRUMENTS
        }

        # Mark carried positions from the preceding completed marks to the
        # current transaction opens before funding or trades.
        for spot in SPOT_INSTRUMENTS:
            states[spot] = states[spot].mark(
                spot_price=spot_open[spot], perpetual_mark=swap_open[spot]
            )
        pre_event_equity = _equity(starting_equity, states)

        if timestamp.weekday() == 0 and timestamp.hour == 0:
            if week_start_time is not None:
                if week_start_equity is None or week_start_components is None:
                    raise C6AError("incomplete weekly start state")
                weekly.append(
                    _finalize_week(
                        window_id=str(window["id"]),
                        week_index=len(weekly),
                        start_time=week_start_time,
                        end_time=timestamp,
                        start_equity=week_start_equity,
                        end_equity=pre_event_equity,
                        start_components=week_start_components,
                        states=states,
                        active=week_active,
                        risk_exit=week_risk_exit,
                    )
                )
            week_start_time = timestamp
            week_start_equity = pre_event_equity
            week_start_components = _aggregate_components(states)
            week_active = any(state.active for state in states.values())
            week_risk_exit = False

        # Funding belongs to the carried pre-trade position.
        if index == 0:
            preceding_mark = None
        else:
            preceding_mark = {
                spot: market.mark[SPOT_TO_SWAP[spot]][index - 1].close
                for spot in SPOT_INSTRUMENTS
            }
        for spot in SPOT_INSTRUMENTS:
            record = funding_by_key.get((SPOT_TO_SWAP[spot], timestamp))
            if record is None:
                continue
            if preceding_mark is None:
                raise C6AError("funding settlement lacks preceding completed mark")
            was_active = states[spot].perpetual_base_quantity > 0
            states[spot] = states[spot].apply_funding(
                realized_rate=record.realized_rate,
                preceding_mark=preceding_mark[spot],
            )
            active_funding_settlements += int(was_active)
            events.append(
                {
                    "kind": "FUNDING",
                    "time": timestamp.isoformat(),
                    "instrument": record.instrument,
                    "realized_rate": str(record.realized_rate),
                    "active_before": was_active,
                }
            )

        blocked_assets: set[str] = set()
        for spot in SPOT_INSTRUMENTS:
            if not states[spot].risk_exit_pending:
                continue
            before = states[spot]
            pre_trade = _equity(starting_equity, states)
            states[spot] = states[spot].terminal_close(
                spot_trade_price=spot_open[spot],
                swap_trade_price=swap_open[spot],
                cost_rate=fee_rate,
            )
            turnover.append(
                _trade_turnover(
                    before=before,
                    after=states[spot],
                    spot_price=spot_open[spot],
                    swap_price=swap_open[spot],
                    pre_trade_equity=pre_trade,
                )
            )
            blocked_assets.add(spot)
            week_risk_exit = True
            events.append(
                {
                    "kind": "RISK_EXIT",
                    "time": timestamp.isoformat(),
                    "spot_instrument": spot,
                    "equity_before": str(pre_trade),
                    "equity_after": str(_equity(starting_equity, states)),
                }
            )

        if timestamp == terminal:
            for spot in SPOT_INSTRUMENTS:
                if not states[spot].active:
                    continue
                before = states[spot]
                pre_trade = _equity(starting_equity, states)
                states[spot] = states[spot].terminal_close(
                    spot_trade_price=spot_open[spot],
                    swap_trade_price=swap_open[spot],
                    cost_rate=fee_rate,
                )
                turnover.append(
                    _trade_turnover(
                        before=before,
                        after=states[spot],
                        spot_price=spot_open[spot],
                        swap_price=swap_open[spot],
                        pre_trade_equity=pre_trade,
                    )
                )
                events.append(
                    {
                        "kind": "TERMINAL_LIQUIDATION",
                        "time": timestamp.isoformat(),
                        "spot_instrument": spot,
                        "equity_before": str(pre_trade),
                        "equity_after": str(_equity(starting_equity, states)),
                    }
                )
            final_equity = _equity(starting_equity, states)
            if week_start_time is None or week_start_equity is None or week_start_components is None:
                raise C6AError("terminal liquidation lacks weekly state")
            weekly.append(
                _finalize_week(
                    window_id=str(window["id"]),
                    week_index=len(weekly),
                    start_time=week_start_time,
                    end_time=end,
                    start_equity=week_start_equity,
                    end_equity=final_equity,
                    start_components=week_start_components,
                    states=states,
                    active=week_active,
                    risk_exit=week_risk_exit,
                )
            )
            hourly_equity.append(final_equity)
            break

        if timestamp.weekday() == 0 and timestamp.hour == 0:
            if index < 2:
                raise C6AError("decision lacks completed Sunday 22:00 candle")
            signal_index = index - 2
            completed_basis = {
                spot: market.mark[SPOT_TO_SWAP[spot]][signal_index].close
                / market.spot[spot][signal_index].close
                - Decimal("1")
                for spot in SPOT_INSTRUMENTS
            }
            total_equity = _equity(starting_equity, states)
            current = {
                spot: _current_paired_notional(
                    states[spot],
                    spot_price=spot_open[spot],
                    swap_price=swap_open[spot],
                )
                for spot in SPOT_INSTRUMENTS
            }
            if policy_id == "C6AMarketNeutralFundingCarry":
                decision = construct_candidate_decision(
                    decision_time=timestamp,
                    total_equity=total_equity,
                    funding_records=funding_records,
                    completed_basis=completed_basis,
                    current_paired_notional=current,
                    config=config,
                )
            else:
                decision = construct_always_on_decision(
                    decision_time=timestamp,
                    total_equity=total_equity,
                    current_paired_notional=current,
                    config=config,
                )
            solution = _solve_targets(
                decision=decision,
                states=states,
                metadata_records=metadata_records,
                timestamp=timestamp,
                spot_prices=spot_open,
                swap_prices=swap_open,
                total_equity=total_equity,
                fee_rate=fee_rate,
                config=config,
                blocked_assets=blocked_assets,
            )
            decision_row = {
                "time": timestamp.isoformat(),
                "policy_id": policy_id,
                "window_id": str(window["id"]),
                "cost_label": cost_label,
                "eligible_assets": list(decision.eligible_assets),
                "cash_only": decision.cash_only,
                "target_scale": str(solution.scale),
                "solver_residual_cash": str(solution.residual_cash),
                "blocked_assets": sorted(blocked_assets),
                "asset_inputs": {
                    key: {
                        "basis": str(value.basis),
                        "eligible": value.eligible,
                        "signal": {field: str(raw) for field, raw in value.signal.items()},
                    }
                    for key, value in decision.asset_inputs.items()
                },
                "targets": [],
            }
            for spot in SPOT_INSTRUMENTS:
                target = solution.solved[spot]
                original = states[spot]
                effective_action = target.target.action
                if spot in blocked_assets:
                    effective_action = "BLOCKED_AFTER_RISK_EXIT"
                if effective_action != "HOLD":
                    pair = target.pair
                    new_spot = ZERO if pair is None else pair.spot_quantity
                    new_swap = ZERO if pair is None else pair.perpetual_base_quantity
                    collateral = ZERO if pair is None else target.collateral
                    pre_trade = _equity(starting_equity, states)
                    states[spot] = states[spot].trade(
                        new_spot_quantity=new_spot,
                        new_perpetual_base_quantity=new_swap,
                        spot_trade_price=spot_open[spot],
                        swap_trade_price=swap_open[spot],
                        cost_rate=fee_rate,
                        dedicated_collateral=collateral,
                    )
                    event_turnover = _trade_turnover(
                        before=original,
                        after=states[spot],
                        spot_price=spot_open[spot],
                        swap_price=swap_open[spot],
                        pre_trade_equity=pre_trade,
                    )
                    turnover.append(event_turnover)
                    events.append(
                        {
                            "kind": "SCHEDULED_TRADE",
                            "time": timestamp.isoformat(),
                            "spot_instrument": spot,
                            "action": effective_action,
                            "spot_quantity_before": str(original.spot_quantity),
                            "spot_quantity_after": str(states[spot].spot_quantity),
                            "perpetual_base_before": str(original.perpetual_base_quantity),
                            "perpetual_base_after": str(states[spot].perpetual_base_quantity),
                            "normalized_one_way_turnover": str(event_turnover),
                        }
                    )
                decision_row["targets"].append(
                    {
                        "spot_instrument": spot,
                        "action": effective_action,
                        "spot_quantity": str(states[spot].spot_quantity),
                        "perpetual_base_quantity": str(states[spot].perpetual_base_quantity),
                        "dedicated_collateral": str(states[spot].dedicated_collateral),
                        "hedge_error": str(states[spot].hedge_error),
                    }
                )
            decisions.append(decision_row)

        week_active = week_active or any(state.active for state in states.values())
        # Complete the hour after all same-timestamp funding and trades.
        for spot in SPOT_INSTRUMENTS:
            states[spot] = states[spot].mark(
                spot_price=spot_close[spot], perpetual_mark=mark_close[spot]
            )
            basis = mark_close[spot] / spot_close[spot] - Decimal("1")
            states[spot] = states[spot].observe_risk(
                current_mark=mark_close[spot],
                current_basis=basis,
                minimum_buffer=config["minimum_collateral_buffer_ratio"],
                maximum_abs_basis=config["maximum_risk_abs_basis"],
                maximum_hedge_error=config["maximum_hedge_error"],
            )
        hourly_equity.append(_equity(starting_equity, states))

    if len(weekly) != 26 or len(decisions) != 26:
        raise C6AError(
            f"C6A window evidence count mismatch: weeks={len(weekly)} decisions={len(decisions)}"
        )
    if any(state.active for state in states.values()):
        raise C6AError("C6A window ended with an open position")
    final_equity = _equity(starting_equity, states)
    components = _aggregate_components(states)
    weekly_pnl = sum((Decimal(row["weekly_pnl"]) for row in weekly), ZERO)
    if abs(weekly_pnl - components.net_pnl) > Decimal("1e-8"):
        raise C6AError("C6A window weekly/component reconciliation failure")
    asset_contributions = {
        state.asset: state.components.net_pnl for state in states.values()
    }
    return {
        "schema_version": 1,
        "stage": "C6A",
        "status": "PASS",
        "policy_id": policy_id,
        "window_id": str(window["id"]),
        "cost_label": cost_label,
        "fee_rate": str(fee_rate),
        "starting_equity": str(starting_equity),
        "final_equity": str(final_equity),
        "net_return": str(final_equity / starting_equity - Decimal("1")),
        "maximum_drawdown": str(maximum_drawdown(hourly_equity)),
        "annualized_one_way_turnover": str(
            annualized_one_way_turnover(turnover, scored_weeks=26)
        ),
        "active_week_count": sum(bool(row["active"]) for row in weekly),
        "active_funding_settlements": active_funding_settlements,
        "collateral_buffer_breaches": sum(
            state.collateral_buffer_breaches for state in states.values()
        ),
        "hedge_breaches": sum(state.hedge_breaches for state in states.values()),
        "asset_contributions": {
            key: str(value) for key, value in asset_contributions.items()
        },
        "components": {key: str(value) for key, value in asdict(components).items()},
        "weekly_buckets": weekly,
        "weekly_returns": [row["weekly_return"] for row in weekly],
        "decisions": decisions,
        "events": events,
        "confirmation_opened": False,
        "c5b_state": "C5B_CLOSED_AND_UNTOUCHED",
        "holdout_state": "HOLDOUT_CLOSED",
        "paper_state": "PAPER_CLOSED",
        "shadow_state": "SHADOW_CLOSED",
        "live": "FORBIDDEN",
    }
