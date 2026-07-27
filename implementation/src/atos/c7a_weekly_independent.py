"""Independent reviewer for retained synthetic C7A weekly evidence.

Imports neither the producer nor the C7A contract module.
"""
from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta
from typing import Any, Mapping, Sequence

COST_LABELS = ("1.0x", "1.5x", "2.0x")
COST_RATES = {"1.0x": 0.0015, "1.5x": 0.00225, "2.0x": 0.003}
COMPARATORS = ("cash", "always_on_funding_rank", "equal_notional_funding_rank")
ORIENTATIONS = ("LONG_BTC_SHORT_ETH", "LONG_ETH_SHORT_BTC")
START = datetime(2026, 8, 24, tzinfo=UTC)
METADATA = {
    "stage": "C7A",
    "source_kind": "SYNTHETIC",
    "contains_real_market_rows": False,
    "network_access": False,
    "economic_run": False,
    "paper_state": "PAPER_CLOSED",
    "shadow_state": "SHADOW_CLOSED",
    "live_state": "LIVE_FORBIDDEN",
}
SAFETY = {
    "real_data_authorized": False,
    "network_execution_authorized": False,
    "economic_run_authorized": False,
    "paper_state": "PAPER_CLOSED",
    "shadow_state": "SHADOW_CLOSED",
    "live_state": "LIVE_FORBIDDEN",
}


def _num(value: Any, name: str) -> float:
    if value is None or isinstance(value, bool):
        raise ValueError(f"{name} must be numeric")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{name} must be finite")
    return result


def _iso(value: Any) -> str:
    stamp = value if isinstance(value, datetime) else datetime.fromisoformat(
        str(value).replace("Z", "+00:00")
    )
    stamp = stamp.replace(tzinfo=UTC) if stamp.tzinfo is None else stamp.astimezone(UTC)
    return stamp.isoformat().replace("+00:00", "Z")


def _times() -> tuple[str, ...]:
    return tuple(
        (START + timedelta(days=7 * i)).isoformat().replace("+00:00", "Z")
        for i in range(26)
    )


def _same(left: float, right: float, name: str) -> None:
    if not math.isclose(left, right, rel_tol=1e-12, abs_tol=1e-9):
        raise ValueError(f"reconciliation mismatch: {name}")


def _path(row: Mapping[str, Any], start: float, end: float, name: str) -> list[float]:
    path = row.get("equity_path")
    if not isinstance(path, Sequence) or isinstance(path, (str, bytes)) or len(path) != 169:
        raise ValueError(f"{name} hourly equity path coverage mismatch")
    values = [_num(value, f"{name} hourly equity") for value in path]
    if any(value <= 0 for value in values):
        raise ValueError(f"{name} hourly equity is non-positive")
    _same(values[0], start, f"{name} path start")
    _same(values[-1], end, f"{name} path end")
    return values


def _drawdown(values: Sequence[float]) -> float:
    peak, result = float(values[0]), 0.0
    for value in values:
        peak = max(peak, value)
        result = max(result, 1.0 - value / peak)
    return result


def _share(values: Sequence[float], top: int) -> float | None:
    positive = sorted((value for value in values if value > 0), reverse=True)
    total = sum(positive)
    return None if total <= 0 else sum(positive[:top]) / total


def _stats(values: Sequence[float]) -> dict[str, float]:
    if len(values) != 26:
        raise ValueError("weekly statistics coverage mismatch")
    data = tuple(_num(value, "weekly return") for value in values)
    mean = sum(data) / 26
    centered = tuple(value - mean for value in data)
    m2 = sum(value * value for value in centered)
    if m2 == 0:
        if mean != 0:
            raise ValueError("nonzero weekly mean with zero variance")
        return {"weekly_sharpe_annualized": 0.0, "weekly_psr": 0.0}
    raw = mean / math.sqrt(m2 / 25)
    variance = m2 / 26
    population_skew = (sum(value**3 for value in centered) / 26) / variance**1.5
    skewness = math.sqrt(26 * 25) / 24 * population_skew
    population_kurtosis = (sum(value**4 for value in centered) / 26) / variance**2
    kurtosis = (((26**2 - 1) * population_kurtosis - 3 * 25**2) / (24 * 23)) + 3
    radicand = 1 - skewness * raw + ((kurtosis - 1) / 4) * raw * raw
    if not math.isfinite(radicand) or radicand <= 0:
        raise ValueError("invalid weekly PSR radicand")
    z = raw * 5 / math.sqrt(radicand)
    return {
        "weekly_sharpe_annualized": raw * math.sqrt(52),
        "weekly_psr": 0.5 * (1 + math.erf(z / math.sqrt(2))),
    }


def _beta(strategy: Sequence[float], btc: Sequence[float]) -> float | None:
    mean_x, mean_y = sum(btc) / 26, sum(strategy) / 26
    sxx = sum((value - mean_x) ** 2 for value in btc)
    if sxx <= 0:
        return None
    return sum(
        (x - mean_x) * (y - mean_y)
        for x, y in zip(btc, strategy, strict=True)
    ) / sxx


def _candidate(rows: Sequence[Mapping[str, Any]], label: str) -> dict[str, Any]:
    if label not in COST_LABELS or len(rows) != 26:
        raise ValueError("candidate identity or coverage mismatch")
    curve: list[float] = []
    starts: list[float] = []
    ends: list[float] = []
    returns: list[float] = []
    pnl: list[float] = []
    btc: list[float] = []
    active: list[bool] = []
    orientations: list[str] = []
    funding_total = receipts_total = costs_total = turnover_total = 0.0
    carry = previous = None
    for index, (row, expected) in enumerate(zip(rows, _times(), strict=True)):
        if _iso(row.get("decision_time")) != expected or row.get("cost_label") != label:
            raise ValueError("candidate row identity mismatch")
        start = _num(row.get("starting_equity"), "starting equity")
        end = _num(row.get("ending_equity"), "ending equity")
        funding = _num(row.get("funding_pnl"), "funding PnL")
        receipts = _num(row.get("gross_funding_receipts"), "funding receipts")
        payments = _num(row.get("gross_funding_payments"), "funding payments")
        relative = _num(row.get("relative_price_pnl"), "relative-price PnL")
        negative = _num(row.get("negative_relative_price_pnl"), "negative relative PnL")
        traded = _num(row.get("traded_notional"), "traded notional")
        cost = _num(row.get("trading_cost"), "trading cost")
        turnover = _num(row.get("turnover"), "turnover")
        btc_return = _num(row.get("btc_mark_return"), "BTC return")
        if min(start, end) <= 0 or min(receipts, payments, traded, cost, turnover) < 0:
            raise ValueError("invalid candidate accounting value")
        if negative > 0 or negative > min(relative, 0.0) + 1e-9:
            raise ValueError("negative relative-price decomposition mismatch")
        if previous is not None:
            _same(start, previous, f"candidate equity chain {index}")
        _same(funding, receipts - payments, f"candidate funding {index}")
        _same(turnover, traded / start, f"candidate turnover {index}")
        _same(cost, traded * COST_RATES[label], f"candidate cost {index}")
        _same(end, start + funding + relative - cost, f"candidate accounting {index}")
        is_active, orientation = row.get("active"), row.get("orientation")
        if not isinstance(is_active, bool):
            raise ValueError("candidate active state invalid")
        if (is_active and orientation not in ORIENTATIONS) or (
            not is_active and orientation != "CASH"
        ):
            raise ValueError("candidate orientation invalid")
        if row.get("missing_decision") is not False or row.get(
            "unaccounted_funding_settlements"
        ) != 0:
            raise ValueError("candidate completeness evidence invalid")
        week_path = _path(row, start, end, f"candidate week {index}")
        if curve:
            _same(curve[-1], week_path[0], f"candidate path chain {index}")
            curve.extend(week_path[1:])
        else:
            curve.extend(week_path)
            carry = start
        starts.append(start)
        ends.append(end)
        returns.append(end / start - 1)
        pnl.append(end - start)
        btc.append(btc_return)
        active.append(is_active)
        orientations.append(str(orientation))
        funding_total += funding
        receipts_total += receipts
        costs_total += cost
        turnover_total += turnover
        carry *= 1 + (funding + negative - cost) / start
        if not math.isfinite(carry) or carry <= 0:
            raise ValueError("candidate carry-only equity invalid")
        previous = end
    active_count = sum(active)
    active_orientations = [value for value in orientations if value in ORIENTATIONS]
    orientation_share = (
        max(active_orientations.count(value) for value in ORIENTATIONS) / active_count
        if active_count
        else None
    )
    result = {
        "schema_version": 1,
        "stage": "C7A",
        "status": "PASS",
        "cost_label": label,
        "decision_times": list(_times()),
        "first_half_net_return": ends[12] / starts[0] - 1,
        "second_half_net_return": ends[-1] / starts[13] - 1,
        "aggregate_net_return": ends[-1] / starts[0] - 1,
        "maximum_drawdown": _drawdown(curve),
        "strategy_beta_to_btc": _beta(returns, btc),
        "aggregate_funding_pnl": funding_total,
        "gross_funding_receipts_to_costs": receipts_total / costs_total
        if costs_total > 0
        else None,
        "carry_only_stress_return": carry / starts[0] - 1,
        "active_weeks": active_count,
        "first_half_active_weeks": sum(active[:13]),
        "second_half_active_weeks": sum(active[13:]),
        "maximum_orientation_share": orientation_share,
        "annualized_one_way_turnover": turnover_total * 2,
        "maximum_positive_week_pnl_share": _share(pnl, 1),
        "maximum_top_three_positive_week_pnl_share": _share(pnl, 3),
        "missing_decision_count": 0,
        "unaccounted_funding_settlement_count": 0,
        "non_positive_equity_count": 0,
        **SAFETY,
    }
    result.update(_stats(returns))
    return result


def _comparator(rows: Sequence[Mapping[str, Any]], name: str) -> dict[str, Any]:
    if name not in COMPARATORS or len(rows) != 26:
        raise ValueError("comparator identity or coverage mismatch")
    curve: list[float] = []
    returns: list[float] = []
    previous = None
    for index, (row, expected) in enumerate(zip(rows, _times(), strict=True)):
        if _iso(row.get("decision_time")) != expected:
            raise ValueError("comparator decision-grid mismatch")
        start = _num(row.get("starting_equity"), "comparator starting equity")
        end = _num(row.get("ending_equity"), "comparator ending equity")
        if min(start, end) <= 0:
            raise ValueError("comparator equity invalid")
        if previous is not None:
            _same(start, previous, f"comparator equity chain {index}")
        week_path = _path(row, start, end, f"comparator week {index}")
        if curve:
            _same(curve[-1], week_path[0], f"comparator path chain {index}")
            curve.extend(week_path[1:])
        else:
            curve.extend(week_path)
        returns.append(end / start - 1)
        previous = end
    result = {
        "schema_version": 1,
        "stage": "C7A",
        "status": "PASS",
        "comparator_id": name,
        "decision_times": list(_times()),
        "aggregate_net_return": curve[-1] / curve[0] - 1,
        "maximum_drawdown": _drawdown(curve),
        **SAFETY,
    }
    result.update(_stats(returns))
    return result


def _decision(candidates: Mapping[str, Mapping[str, Any]], always: Mapping[str, Any]) -> dict[str, Any]:
    expected, one_five, two = (candidates[label] for label in COST_LABELS)
    if tuple(value.get("cost_label") for value in (expected, one_five, two)) != COST_LABELS:
        raise ValueError("aggregate cost identity mismatch")
    if always.get("comparator_id") != "always_on_funding_rank":
        raise ValueError("always-on comparator identity mismatch")
    if len({tuple(value.get("decision_times", ())) for value in (*candidates.values(), always)}) != 1:
        raise ValueError("aggregate decision-grid mismatch")
    checks = {
        "first_half_return": expected["first_half_net_return"] > 0,
        "second_half_return": expected["second_half_net_return"] > 0,
        "aggregate_expected_return": expected["aggregate_net_return"] > 0,
        "aggregate_1_5x_return": one_five["aggregate_net_return"] > 0,
        "aggregate_2_0x_return": two["aggregate_net_return"] >= 0,
        "weekly_sharpe": expected["weekly_sharpe_annualized"] >= 1,
        "weekly_psr": expected["weekly_psr"] >= 0.95,
        "maximum_drawdown": expected["maximum_drawdown"] <= 0.10,
        "strategy_beta_to_btc": expected["strategy_beta_to_btc"] is not None
        and abs(expected["strategy_beta_to_btc"]) <= 0.15,
        "aggregate_funding_pnl": expected["aggregate_funding_pnl"] > 0,
        "funding_receipts_to_costs": expected["gross_funding_receipts_to_costs"]
        is not None
        and expected["gross_funding_receipts_to_costs"] >= 2,
        "carry_only_stress": expected["carry_only_stress_return"] > 0,
        "always_on_return_increment": expected["aggregate_net_return"]
        > always["aggregate_net_return"],
        "always_on_sharpe_increment": expected["weekly_sharpe_annualized"]
        >= always["weekly_sharpe_annualized"] + 0.10,
        "active_weeks": expected["active_weeks"] >= 13,
        "first_half_active_weeks": expected["first_half_active_weeks"] >= 5,
        "second_half_active_weeks": expected["second_half_active_weeks"] >= 5,
        "orientation_concentration": expected["maximum_orientation_share"] is not None
        and expected["maximum_orientation_share"] <= 0.85,
        "annualized_turnover": expected["annualized_one_way_turnover"] <= 8,
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
        "schema_version": 1,
        "stage": "C7A",
        "status": "PASS",
        "decision": "SELECTED" if not failed else "REJECTED",
        "failed_gates": failed,
        "selected_policy": "C7ABetaNeutralFundingDispersion" if not failed else None,
        "c7b_state": "CLOSED",
        **SAFETY,
    }


def _compare(expected: Any, observed: Any, path: str, errors: list[str]) -> None:
    if isinstance(expected, Mapping):
        if not isinstance(observed, Mapping) or set(expected) != set(observed):
            errors.append(f"{path} key set mismatch")
            return
        for key in expected:
            _compare(expected[key], observed[key], f"{path}.{key}", errors)
    elif isinstance(expected, Sequence) and not isinstance(expected, (str, bytes)):
        if not isinstance(observed, Sequence) or isinstance(observed, (str, bytes)) or len(expected) != len(observed):
            errors.append(f"{path} sequence mismatch")
            return
        for index, (left, right) in enumerate(zip(expected, observed, strict=True)):
            _compare(left, right, f"{path}[{index}]", errors)
    elif isinstance(expected, float):
        try:
            matches = math.isclose(expected, float(observed), rel_tol=1e-12, abs_tol=1e-9)
        except (TypeError, ValueError):
            matches = False
        if not matches:
            errors.append(f"{path} value mismatch")
    elif expected != observed:
        errors.append(f"{path} value mismatch")


def review_weekly_evidence(evidence: Mapping[str, Any]) -> dict[str, Any]:
    errors: list[str] = []
    candidates: dict[str, Any] = {}
    comparators: dict[str, Any] = {}
    decision: dict[str, Any] | None = None
    try:
        required = {
            "metadata",
            "candidate_rows",
            "comparator_rows",
            "producer_candidate_aggregates",
            "producer_comparator_aggregates",
            "producer_decision",
        }
        if set(evidence) != required:
            raise ValueError("evidence section set mismatch")
        metadata = evidence["metadata"]
        if not isinstance(metadata, Mapping) or dict(metadata) != METADATA:
            raise ValueError("synthetic metadata mismatch")
        candidate_rows, comparator_rows = evidence["candidate_rows"], evidence["comparator_rows"]
        if not isinstance(candidate_rows, Mapping) or set(candidate_rows) != set(COST_LABELS):
            raise ValueError("candidate row set mismatch")
        if not isinstance(comparator_rows, Mapping) or set(comparator_rows) != set(COMPARATORS):
            raise ValueError("comparator row set mismatch")
        candidates = {label: _candidate(candidate_rows[label], label) for label in COST_LABELS}
        comparators = {name: _comparator(comparator_rows[name], name) for name in COMPARATORS}
        decision = _decision(candidates, comparators["always_on_funding_rank"])
        _compare(candidates, evidence["producer_candidate_aggregates"], "candidate", errors)
        _compare(comparators, evidence["producer_comparator_aggregates"], "comparator", errors)
        _compare(decision, evidence["producer_decision"], "decision", errors)
    except (KeyError, TypeError, ValueError) as exc:
        errors.append(str(exc))
    return {
        "schema_version": 1,
        "stage": "C7A_SYNTHETIC_WEEKLY_EVIDENCE_INDEPENDENT_REVIEW",
        "status": "PASS" if not errors else "FAIL",
        "errors": errors,
        "candidate_aggregates_recomputed": candidates,
        "comparator_aggregates_recomputed": comparators,
        "decision_recomputed": decision,
        **SAFETY,
    }
