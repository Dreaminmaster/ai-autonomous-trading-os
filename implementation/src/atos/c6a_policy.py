"""Frozen weekly policy construction for the single C6A candidate."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any, Mapping, Sequence

from atos.c6a_contract import (
    C6AError,
    FundingRecord,
    SPOT_INSTRUMENTS,
    SPOT_TO_SWAP,
    candidate_eligible,
    funding_signal,
    parse_timestamp,
)
from atos.c6a_rounding import SleeveTarget, equal_sleeve_targets, should_resize


@dataclass(frozen=True)
class AssetDecisionInput:
    spot_instrument: str
    decision_time: datetime
    basis: Decimal
    signal: Mapping[str, Decimal | int]
    eligible: bool


@dataclass(frozen=True)
class AssetTarget:
    spot_instrument: str
    swap_instrument: str
    sleeve_capital: Decimal
    spot_target_notional: Decimal
    collateral_target: Decimal
    action: str


@dataclass(frozen=True)
class WeeklyPolicyDecision:
    decision_time: datetime
    asset_inputs: Mapping[str, AssetDecisionInput]
    eligible_assets: tuple[str, ...]
    targets: tuple[AssetTarget, ...]
    cash_only: bool


def construct_candidate_decision(
    *,
    decision_time: datetime,
    total_equity: Any,
    funding_records: Sequence[FundingRecord],
    completed_basis: Mapping[str, Any],
    current_paired_notional: Mapping[str, Any],
    config: Mapping[str, Any],
) -> WeeklyPolicyDecision:
    decision = parse_timestamp(decision_time)
    if decision.weekday() != 0 or decision.hour != 0 or decision.minute != 0:
        raise C6AError("C6A policy decision must occur Monday 00:00 UTC")
    if set(completed_basis) != set(SPOT_INSTRUMENTS):
        raise C6AError("completed basis set mismatch")
    if set(current_paired_notional) != set(SPOT_INSTRUMENTS):
        raise C6AError("current paired-notional set mismatch")

    inputs: dict[str, AssetDecisionInput] = {}
    eligible: list[str] = []
    for spot in SPOT_INSTRUMENTS:
        signal = funding_signal(
            funding_records,
            instrument=SPOT_TO_SWAP[spot],
            decision_time=decision,
        )
        basis = Decimal(str(completed_basis[spot]))
        is_eligible = candidate_eligible(signal, basis=basis, config=config)
        inputs[spot] = AssetDecisionInput(
            spot_instrument=spot,
            decision_time=decision,
            basis=basis,
            signal=signal,
            eligible=is_eligible,
        )
        if is_eligible:
            eligible.append(spot)

    raw_targets: tuple[SleeveTarget, ...] = equal_sleeve_targets(
        total_equity=total_equity,
        eligible_assets=eligible,
    )
    target_by_asset = {row.asset: row for row in raw_targets}
    output: list[AssetTarget] = []
    for spot in SPOT_INSTRUMENTS:
        current = Decimal(str(current_paired_notional[spot]))
        row = target_by_asset.get(spot)
        if row is None:
            action = "CLOSE" if current > 0 else "HOLD_CASH"
            output.append(
                AssetTarget(
                    spot_instrument=spot,
                    swap_instrument=SPOT_TO_SWAP[spot],
                    sleeve_capital=Decimal("0"),
                    spot_target_notional=Decimal("0"),
                    collateral_target=Decimal("0"),
                    action=action,
                )
            )
            continue
        action = (
            "RESIZE"
            if should_resize(
                current_paired_notional=current,
                target_paired_notional=row.spot_target_notional,
                band=config["resizing_band"],
            )
            else "HOLD"
        )
        if current == 0:
            action = "OPEN"
        output.append(
            AssetTarget(
                spot_instrument=spot,
                swap_instrument=SPOT_TO_SWAP[spot],
                sleeve_capital=row.sleeve_capital,
                spot_target_notional=row.spot_target_notional,
                collateral_target=row.collateral_target,
                action=action,
            )
        )
    return WeeklyPolicyDecision(
        decision_time=decision,
        asset_inputs=inputs,
        eligible_assets=tuple(eligible),
        targets=tuple(output),
        cash_only=not eligible,
    )


def construct_always_on_decision(
    *, decision_time: datetime, total_equity: Any,
    current_paired_notional: Mapping[str, Any], config: Mapping[str, Any]
) -> WeeklyPolicyDecision:
    decision = parse_timestamp(decision_time)
    if decision.weekday() != 0 or decision.hour != 0 or decision.minute != 0:
        raise C6AError("always-on decision must occur Monday 00:00 UTC")
    if set(current_paired_notional) != set(SPOT_INSTRUMENTS):
        raise C6AError("current paired-notional set mismatch")
    raw_targets = equal_sleeve_targets(
        total_equity=total_equity,
        eligible_assets=SPOT_INSTRUMENTS,
    )
    targets: list[AssetTarget] = []
    inputs: dict[str, AssetDecisionInput] = {}
    for row in raw_targets:
        current = Decimal(str(current_paired_notional[row.asset]))
        action = (
            "OPEN"
            if current == 0
            else (
                "RESIZE"
                if should_resize(
                    current_paired_notional=current,
                    target_paired_notional=row.spot_target_notional,
                    band=config["resizing_band"],
                )
                else "HOLD"
            )
        )
        targets.append(
            AssetTarget(
                spot_instrument=row.asset,
                swap_instrument=SPOT_TO_SWAP[row.asset],
                sleeve_capital=row.sleeve_capital,
                spot_target_notional=row.spot_target_notional,
                collateral_target=row.collateral_target,
                action=action,
            )
        )
        inputs[row.asset] = AssetDecisionInput(
            spot_instrument=row.asset,
            decision_time=decision,
            basis=Decimal("0"),
            signal={
                "settlement_count": 0,
                "positive_settlement_count": 0,
                "funding_sum_28d": Decimal("0"),
                "positive_funding_share_28d": Decimal("0"),
            },
            eligible=True,
        )
    return WeeklyPolicyDecision(
        decision_time=decision,
        asset_inputs=inputs,
        eligible_assets=SPOT_INSTRUMENTS,
        targets=tuple(targets),
        cash_only=False,
    )
