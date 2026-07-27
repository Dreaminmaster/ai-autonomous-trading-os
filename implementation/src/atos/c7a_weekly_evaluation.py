"""Synthetic-only weekly evaluation for the preregistered C7A candidate."""
from __future__ import annotations

import math
from datetime import UTC, datetime
from typing import Any, Mapping, Sequence

from atos.c7a_contract import (
    C7AError,
    assert_synthetic_only,
    finite,
    scored_decision_times,
)

COST_LABELS = ("1.0x", "1.5x", "2.0x")
ACTIVE_ORIENTATIONS = ("LONG_BTC_SHORT_ETH", "LONG_ETH_SHORT_BTC")


def _iso(value: Any) -> str:
    try:
        stamp = value if isinstance(value, datetime) else datetime.fromisoformat(
            str(value).replace("Z", "+00:00")
        )
    except (TypeError, ValueError) as exc:
        raise C7AError(f"invalid C7A decision timestamp: {value!r}") from exc
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=UTC)
    return stamp.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _close(left: float, right: float, label: str) -> None:
    if not math.isclose(left, right, rel_tol=1e-12, abs_tol=1e-9):
        raise C7AError(f"C7A reconciliation mismatch: {label}")


def _positive_share(values: Sequence[float], top: int) -> float | None:
    positive = sorted((float(v) for v in values if float(v) > 0), reverse=True)
    total = sum(positive)
    return None if total <= 0 else sum(positive[:top]) / total


def _drawdown(curve: Sequence[float]) -> float:
    peak = float(curve[0])
    result = 0.0
    for value in curve:
        peak = max(peak, float(value))
        result = max(result, 1.0 - float(value) / peak)
    return result


def _statistics(values: Sequence[float]) -> dict[str, float]:
    if len(values) != 26:
        raise C7AError("C7A statistics require exactly 26 weekly returns")
    data = tuple(finite(v, "weekly return") for v in values)
    mean = sum(data) / 26
    centered = tuple(v - mean for v in data)
    m2 = sum(v * v for v in centered)
    if m2 == 0:
        if mean != 0:
            raise C7AError("nonzero C7A weekly mean with zero variance")
        return {"weekly_sharpe_annualized": 0.0, "weekly_psr": 0.0}
    sample_std = math.sqrt(m2 / 25)
    raw = mean / sample_std
    variance = m2 / 26
    skewness = (sum(v**3 for v in centered) / 26) / variance**1.5
    kurtosis = (sum(v**4 for v in centered) / 26) / variance**2
    radicand = 1.0 - skewness * raw + ((kurtosis - 1.0) / 4.0) * raw * raw
    if not math.isfinite(radicand) or radicand <= 0:
        raise C7AError("invalid C7A PSR radicand")
    z_score = raw * math.sqrt(25) / math.sqrt(radicand)
    return {
        "weekly_sharpe_annualized": raw * math.sqrt(52),
        "weekly_psr": 0.5 * (1.0 + math.erf(z_score / math.sqrt(2.0))),
    }


def _beta(strategy: Sequence[float], btc: Sequence[float]) -> float | None:
    mean_x = sum(btc) / 26
    mean_y = sum(strategy) / 26
    sxx = sum((v - mean_x) ** 2 for v in btc)
    if sxx <= 0:
        return None
    return sum(
        (x - mean_x) * (y - mean_y)
        for x, y in zip(btc, strategy, strict=True)
    ) / sxx


def aggregate_candidate_weekly(
    rows: Sequence[Mapping[str, Any]],
    *,
    cost_label: str,
    metadata: Mapping[str, Any],
) -> dict[str, Any]:
    assert_synthetic_only(metadata)
    if cost_label not in COST_LABELS or len(rows) != 26:
        raise C7AError("C7A candidate requires one frozen cost label and 26 rows")
    times = tuple(t.isoformat().replace("+00:00", "Z") for t in scored_decision_times())
    curve: list[float] = []
    returns: list[float] = []
    weekly_pnl: list[float] = []
    btc_returns: list[float] = []
    active: list[bool] = []
    orientations: list[str] = []
    funding_total = receipts_total = costs_total = turnover_total = 0.0
    carry_equity = previous = None

    for index, (row, expected_time) in enumerate(zip(rows, times, strict=True)):
        if _iso(row.get("decision_time")) != expected_time:
            raise C7AError("C7A weekly decision-grid mismatch")
        if row.get("cost_label") != cost_label:
            raise C7AError("C7A weekly cost-label mismatch")
        start = finite(row.get("starting_equity"), "starting equity")
        end = finite(row.get("ending_equity"), "ending equity")
        funding = finite(row.get("funding_pnl"), "funding PnL")
        receipts = finite(row.get("gross_funding_receipts"), "funding receipts")
        payments = finite(row.get("gross_funding_payments"), "funding payments")
        relative = finite(row.get("relative_price_pnl"), "relative-price PnL")
        cost = finite(row.get("trading_cost"), "trading cost")
        turnover = finite(row.get("turnover"), "turnover")
        btc_return = finite(row.get("btc_mark_return"), "BTC weekly return")
        if min(start, end) <= 0 or min(receipts, payments, cost, turnover) < 0:
            raise C7AError("invalid C7A weekly accounting value")
        if previous is not None:
            _close(start, previous, f"equity chain week {index}")
        _close(funding, receipts - payments, f"funding week {index}")
        _close(end, start + funding + relative - cost, f"weekly accounting week {index}")
        is_active = row.get("active")
        orientation = row.get("orientation")
        if not isinstance(is_active, bool):
            raise C7AError("C7A active state must be boolean")
        if is_active != (orientation in ACTIVE_ORIENTATIONS):
            raise C7AError("C7A active/orientation mismatch")
        if row.get("missing_decision") is not False:
            raise C7AError("C7A missing-decision evidence must be false")
        if row.get("unaccounted_funding_settlements") != 0:
            raise C7AError("C7A unaccounted funding settlements must be zero")
        if not curve:
            curve.append(start)
            carry_equity = start
        weekly_return = end / start - 1.0
        returns.append(weekly_return)
        weekly_pnl.append(end - start)
        btc_returns.append(btc_return)
        curve.append(end)
        funding_total += funding
        receipts_total += receipts
        costs_total += cost
        turnover_total += turnover
        active.append(is_active)
        orientations.append(str(orientation))
        carry_equity *= 1.0 + (funding + min(relative, 0.0) - cost) / start
        if carry_equity <= 0 or not math.isfinite(carry_equity):
            raise C7AError("invalid C7A carry-only stress equity")
        previous = end

    active_count = sum(active)
    active_orientations = [v for v in orientations if v in ACTIVE_ORIENTATIONS]
    orientation_share = (
        max(active_orientations.count(v) for v in ACTIVE_ORIENTATIONS) / active_count
        if active_count
        else None
    )
    result = {
        "stage": "C7A",
        "status": "PASS",
        "cost_label": cost_label,
        "decision_times": list(times),
        "first_half_net_return": curve[13] / curve[0] - 1.0,
        "second_half_net_return": curve[-1] / curve[13] - 1.0,
        "aggregate_net_return": curve[-1] / curve[0] - 1.0,
        "maximum_drawdown": _drawdown(curve),
        "strategy_beta_to_btc": _beta(returns, btc_returns),
        "aggregate_funding_pnl": funding_total,
        "gross_funding_receipts_to_costs": (
            receipts_total / costs_total if costs_total > 0 else None
        ),
        "carry_only_stress_return": carry_equity / curve[0] - 1.0,
        "active_weeks": active_count,
        "first_half_active_weeks": sum(active[:13]),
        "second_half_active_weeks": sum(active[13:]),
        "maximum_orientation_share": orientation_share,
        "annualized_one_way_turnover": turnover_total * 2.0,
        "maximum_positive_week_pnl_share": _positive_share(weekly_pnl, 1),
        "maximum_top_three_positive_week_pnl_share": _positive_share(weekly_pnl, 3),
        "missing_decision_count": 0,
        "unaccounted_funding_settlement_count": 0,
        "non_positive_equity_count": 0,
        "real_data_authorized": False,
        "network_execution_authorized": False,
        "economic_run_authorized": False,
        "paper_state": "PAPER_CLOSED",
        "shadow_state": "SHADOW_CLOSED",
        "live_state": "LIVE_FORBIDDEN",
    }
    result.update(_statistics(returns))
    return result


def aggregate_comparator_weekly(
    rows: Sequence[Mapping[str, Any]],
    *,
    comparator_id: str,
    metadata: Mapping[str, Any],
) -> dict[str, Any]:
    assert_synthetic_only(metadata)
    if len(rows) != 26:
        raise C7AError("C7A comparator requires exactly 26 rows")
    times = tuple(t.isoformat().replace("+00:00", "Z") for t in scored_decision_times())
    curve: list[float] = []
    returns: list[float] = []
    previous = None
    for row, expected_time in zip(rows, times, strict=True):
        if _iso(row.get("decision_time")) != expected_time:
            raise C7AError("C7A comparator decision-grid mismatch")
        start = finite(row.get("starting_equity"), "comparator starting equity")
        end = finite(row.get("ending_equity"), "comparator ending equity")
        if min(start, end) <= 0:
            raise C7AError("C7A comparator equity must remain positive")
        if previous is not None:
            _close(start, previous, "comparator equity chain")
        if not curve:
            curve.append(start)
        curve.append(end)
        returns.append(end / start - 1.0)
        previous = end
    result = {
        "stage": "C7A",
        "status": "PASS",
        "comparator_id": comparator_id,
        "decision_times": list(times),
        "aggregate_net_return": curve[-1] / curve[0] - 1.0,
        "maximum_drawdown": _drawdown(curve),
        "real_data_authorized": False,
        "network_execution_authorized": False,
        "economic_run_authorized": False,
        "paper_state": "PAPER_CLOSED",
        "shadow_state": "SHADOW_CLOSED",
        "live_state": "LIVE_FORBIDDEN",
    }
    result.update(_statistics(returns))
    return result


def decide_c7a(
    *,
    expected: Mapping[str, Any],
    stress_1_5x: Mapping[str, Any],
    stress_2_0x: Mapping[str, Any],
    always_on: Mapping[str, Any],
) -> dict[str, Any]:
    if (
        expected.get("cost_label"),
        stress_1_5x.get("cost_label"),
        stress_2_0x.get("cost_label"),
    ) != COST_LABELS:
        raise C7AError("C7A aggregate cost-label mismatch")
    if len(
        {
            tuple(v.get("decision_times", ()))
            for v in (expected, stress_1_5x, stress_2_0x, always_on)
        }
    ) != 1:
        raise C7AError("C7A aggregate decision-grid mismatch")
    checks = {
        "first_half_return": expected["first_half_net_return"] > 0,
        "second_half_return": expected["second_half_net_return"] > 0,
        "aggregate_expected_return": expected["aggregate_net_return"] > 0,
        "aggregate_1_5x_return": stress_1_5x["aggregate_net_return"] > 0,
        "aggregate_2_0x_return": stress_2_0x["aggregate_net_return"] >= 0,
        "weekly_sharpe": expected["weekly_sharpe_annualized"] >= 1.0,
        "weekly_psr": expected["weekly_psr"] >= 0.95,
        "maximum_drawdown": expected["maximum_drawdown"] <= 0.10,
        "strategy_beta_to_btc": expected["strategy_beta_to_btc"] is not None
        and abs(expected["strategy_beta_to_btc"]) <= 0.15,
        "aggregate_funding_pnl": expected["aggregate_funding_pnl"] > 0,
        "funding_receipts_to_costs": expected["gross_funding_receipts_to_costs"]
        is not None
        and expected["gross_funding_receipts_to_costs"] >= 2.0,
        "carry_only_stress": expected["carry_only_stress_return"] > 0,
        "always_on_return_increment": expected["aggregate_net_return"]
        > always_on["aggregate_net_return"],
        "always_on_sharpe_increment": expected["weekly_sharpe_annualized"]
        >= always_on["weekly_sharpe_annualized"] + 0.10,
        "active_weeks": expected["active_weeks"] >= 13,
        "first_half_active_weeks": expected["first_half_active_weeks"] >= 5,
        "second_half_active_weeks": expected["second_half_active_weeks"] >= 5,
        "orientation_concentration": expected["maximum_orientation_share"] is not None
        and expected["maximum_orientation_share"] <= 0.85,
        "annualized_turnover": expected["annualized_one_way_turnover"] <= 8.0,
        "maximum_positive_week_share": expected["maximum_positive_week_pnl_share"]
        is not None
        and expected["maximum_positive_week_pnl_share"] <= 0.25,
        "top_three_positive_week_share": expected[
            "maximum_top_three_positive_week_pnl_share"
        ]
        is not None
        and expected["maximum_top_three_positive_week_pnl_share"] <= 0.50,
        "complete_evidence": expected["missing_decision_count"] == 0
        and expected["unaccounted_funding_settlement_count"] == 0
        and expected["non_positive_equity_count"] == 0,
    }
    failed = [name for name, passed in checks.items() if not passed]
    return {
        "stage": "C7A",
        "status": "PASS",
        "decision": "SELECTED" if not failed else "REJECTED",
        "failed_gates": failed,
        "selected_policy": "C7ABetaNeutralFundingDispersion" if not failed else None,
        "c7b_state": "CLOSED",
        "real_data_authorized": False,
        "network_execution_authorized": False,
        "economic_run_authorized": False,
        "paper_state": "PAPER_CLOSED",
        "shadow_state": "SHADOW_CLOSED",
        "live_state": "LIVE_FORBIDDEN",
    }
