#!/usr/bin/env python3
"""Independently verify explicit C5A contract-retention evidence."""
from __future__ import annotations

from typing import Any, Mapping, Sequence

try:
    import scripts.c5a_evidence as evidence
    import scripts.c5a_finalizer as finalizer
except ModuleNotFoundError:  # pragma: no cover
    import c5a_evidence as evidence  # type: ignore
    import c5a_finalizer as finalizer  # type: ignore

RETENTION_PATH = evidence.RESULTS / "contract_retention.json"
FINAL_PATH = evidence.RESULTS / "final_evidence.json"


class C5ARetentionFinalizerError(RuntimeError):
    pass


def _number(value: Any, label: str) -> float:
    if isinstance(value, bool):
        raise C5ARetentionFinalizerError(f"{label} must be numeric")
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise C5ARetentionFinalizerError(f"{label} must be numeric") from exc
    if result != result or result in {float("inf"), float("-inf")}:
        raise C5ARetentionFinalizerError(f"{label} must be finite")
    return result


def _concentration(values: Sequence[float], count: int) -> dict[str, Any]:
    positives = sorted((_number(value, "concentration input") for value in values if float(value) > 0), reverse=True)
    total = sum(positives)
    selected = sum(positives[:count])
    return {
        "positive_count": len(positives),
        "top_count": count,
        "numerator": selected if positives else None,
        "denominator": total if total > 0 else None,
        "share": selected / total if total > 0 else None,
    }


def _weekly_rows(policy_rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for cell in policy_rows:
        decisions = cell.get("decisions")
        buckets = cell.get("weekly_buckets")
        events = cell.get("events")
        if not isinstance(decisions, list) or not isinstance(buckets, list) or not isinstance(events, list):
            raise C5ARetentionFinalizerError("cell evidence vectors must be lists")
        if len(decisions) != 13 or len(buckets) != 13:
            raise C5ARetentionFinalizerError("cell weekly evidence count mismatch")
        for index in range(13):
            decision = decisions[index]
            bucket = buckets[index]
            if not isinstance(decision, Mapping) or not isinstance(bucket, Mapping):
                raise C5ARetentionFinalizerError("weekly evidence item must be an object")
            execution = str(decision.get("execution_time", ""))
            if bucket.get("monday_execution_time") != execution:
                raise C5ARetentionFinalizerError("decision/bucket execution mismatch")
            event_index = decision.get("event_sequence")
            if event_index is None:
                if decision.get("executed_rebalance") is not False:
                    raise C5ARetentionFinalizerError("missing event on executed decision")
                fee = 0.0
                post = _number(decision.get("equity_at_open"), "no-trade post equity")
            else:
                if not isinstance(event_index, int) or not 0 <= event_index < len(events):
                    raise C5ARetentionFinalizerError("event sequence is out of range")
                event = events[event_index]
                if not isinstance(event, Mapping):
                    raise C5ARetentionFinalizerError("event must be an object")
                if event.get("kind") != "SCHEDULED_REBALANCE" or event.get("time") != execution:
                    raise C5ARetentionFinalizerError("scheduled event mismatch")
                fee = _number(event.get("total_fee"), "scheduled fee")
                post = _number(event.get("equity_after"), "scheduled post equity")
            output.append(
                {
                    "policy_id": str(cell.get("policy_id")),
                    "window_id": str(cell.get("window_id")),
                    "cost_label": str(cell.get("cost_label")),
                    "monday_execution_time": execution,
                    "start_reference_time": str(bucket.get("start_reference_time")),
                    "start_reference_equity": _number(bucket.get("start_reference_equity"), "start equity"),
                    "monday_pre_trade_open_equity": _number(decision.get("equity_at_open"), "pre-trade equity"),
                    "boundary_gap_pnl": _number(decision.get("boundary_gap_pnl"), "boundary gap"),
                    "monday_fee": fee,
                    "monday_post_trade_equity": post,
                    "final_sunday_time": str(bucket.get("end_time")),
                    "final_sunday_post_close_equity": _number(bucket.get("ending_equity"), "ending equity"),
                    "net_pnl": _number(bucket.get("net_pnl"), "weekly PnL"),
                    "net_return": _number(bucket.get("net_return"), "weekly return"),
                    "executed_rebalance": bool(decision.get("executed_rebalance")),
                }
            )
    if len(output) != 156:
        raise C5ARetentionFinalizerError("weekly accounting total mismatch")
    return output


def _concentration_rows(aggregates: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for row in aggregates:
        half = row.get("half_pnl")
        weekly = row.get("weekly_pnl")
        assets = row.get("asset_contributions")
        if not isinstance(half, list) or not isinstance(weekly, list) or not isinstance(assets, Mapping):
            raise C5ARetentionFinalizerError("aggregate concentration evidence missing")
        output.append(
            {
                "policy_id": str(row.get("policy_id")),
                "cost_label": str(row.get("cost_label")),
                "positive_half_pnl": _concentration([float(value) for value in half], 1),
                "positive_asset_pnl": _concentration([float(value) for value in assets.values()], 1),
                "positive_single_week_pnl": _concentration([float(value) for value in weekly], 1),
                "positive_top_three_week_pnl": _concentration([float(value) for value in weekly], 3),
            }
        )
    if len(output) != 6:
        raise C5ARetentionFinalizerError("concentration aggregate count mismatch")
    return output


def _incremental(aggregates: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    index = {(str(row.get("policy_id")), str(row.get("cost_label"))): row for row in aggregates}
    candidate = index[("C5ADerivativesCrowdingFilteredRiskBalance", "1.0x")]
    ablation = index[("C5APriceOnlyRiskBalanceAblation", "1.0x")]
    cs = _number(candidate.get("aggregate_sharpe_4h"), "candidate Sharpe")
    as_ = _number(ablation.get("aggregate_sharpe_4h"), "ablation Sharpe")
    cd = _number(candidate.get("maximum_half_drawdown"), "candidate drawdown")
    ad = _number(ablation.get("maximum_half_drawdown"), "ablation drawdown")
    ct = _number(candidate.get("annualized_one_way_turnover"), "candidate turnover")
    at = _number(ablation.get("annualized_one_way_turnover"), "ablation turnover")
    return {
        "cost_label": "1.0x",
        "candidate_policy_id": "C5ADerivativesCrowdingFilteredRiskBalance",
        "ablation_policy_id": "C5APriceOnlyRiskBalanceAblation",
        "aggregate_sharpe_4h": {
            "candidate": cs,
            "ablation": as_,
            "candidate_minus_ablation": cs - as_,
            "gate_pass": cs > as_,
        },
        "maximum_half_drawdown": {
            "candidate": cd,
            "ablation": ad,
            "candidate_minus_ablation": cd - ad,
            "ablation_minus_candidate_gate_margin": ad - cd,
            "gate_pass": cd <= ad,
        },
        "annualized_one_way_turnover": {
            "candidate": ct,
            "ablation": at,
            "candidate_minus_ablation": ct - at,
            "ablation_minus_candidate_gate_margin": at - ct,
            "gate_pass": ct <= at,
        },
    }


def _expected_payload(
    policy_rows: Sequence[Mapping[str, Any]],
    aggregates: Sequence[Mapping[str, Any]],
    source_sha: str,
    merge_sha: str,
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "stage": "C5A",
        "status": "PASS",
        "source_head_sha": source_sha,
        "merge_ref_sha": merge_sha,
        "weekly_accounting_row_count": 156,
        "weekly_accounting": _weekly_rows(policy_rows),
        "concentration_row_count": 6,
        "concentration": _concentration_rows(aggregates),
        "incremental_information": _incremental(aggregates),
        "within_stage_dsr_used": False,
        "weekly_statistic": "PSR_NOT_DSR",
        "program_level_sequential_history_corrected": False,
        "program_level_claim": "C5A weekly PSR does not correct the sequential C0C-through-C5A research history.",
        "confirmation_opened": False,
        "holdout_state": "HOLDOUT_CLOSED",
        "paper_state": "PAPER_CLOSED",
        "shadow_state": "SHADOW_CLOSED",
        "live": "FORBIDDEN",
    }


def main() -> int:
    source_sha = evidence.exact_sha("C5A_SOURCE_SHA")
    merge_sha = evidence.exact_sha("C5A_MERGE_REF_SHA")
    retained = evidence.read_json(RETENTION_PATH)
    policy_rows = evidence.read_json(evidence.RESULTS / "policy_rows.json")
    aggregates = evidence.read_json(evidence.RESULTS / "policy_aggregates.json")
    if not isinstance(retained, Mapping) or not isinstance(policy_rows, list) or not isinstance(aggregates, list):
        raise C5ARetentionFinalizerError("retention and primitive evidence types are invalid")
    expected = _expected_payload(policy_rows, aggregates, source_sha, merge_sha)
    finalizer.compare("contract_retention", retained, expected)

    final = evidence.read_json(FINAL_PATH)
    if not isinstance(final, dict) or final.get("status") != "PASS" or final.get("errors") != []:
        raise C5ARetentionFinalizerError("base final evidence is not PASS")
    checks = list(final.get("checks", []))
    added = [
        "weekly_accounting_retention:156_INDEPENDENT_MATCH",
        "concentration_numerators_denominators:6_INDEPENDENT_MATCH",
        "incremental_differences:INDEPENDENT_MATCH",
        "psr_claim_boundary:PASS",
    ]
    final.update(
        {
            "checks": checks + added,
            "checks_passed": len(checks) + len(added),
            "retention_checks": added,
            "errors": [],
            "status": "PASS",
            "confirmation_opened": False,
            "holdout_state": "HOLDOUT_CLOSED",
            "paper_state": "PAPER_CLOSED",
            "shadow_state": "SHADOW_CLOSED",
            "live": "FORBIDDEN",
        }
    )
    evidence.write_json(FINAL_PATH, final)
    print("C5A retention finalizer PASS: explicit accounting, concentration, incremental, and PSR claim evidence")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
