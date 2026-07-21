#!/usr/bin/env python3
"""Retain C5A contract fields that are distributed across primitive evidence."""
from __future__ import annotations

from typing import Any, Mapping, Sequence

try:
    import scripts.c5a_evidence as evidence
except ModuleNotFoundError:  # pragma: no cover
    import c5a_evidence as evidence  # type: ignore

RESULT_PATH = evidence.RESULTS / "contract_retention.json"


class C5ARetentionEvidenceError(RuntimeError):
    pass


def _finite(value: Any, label: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise C5ARetentionEvidenceError(f"{label} must be numeric") from exc
    if result != result or result in {float("inf"), float("-inf")}:
        raise C5ARetentionEvidenceError(f"{label} must be finite")
    return result


def _positive_details(values: Sequence[float], *, top: int) -> dict[str, Any]:
    positive = sorted((_finite(value, "concentration value") for value in values if float(value) > 0), reverse=True)
    denominator = sum(positive)
    numerator = sum(positive[:top])
    return {
        "positive_count": len(positive),
        "top_count": top,
        "numerator": numerator if positive else None,
        "denominator": denominator if denominator > 0 else None,
        "share": numerator / denominator if denominator > 0 else None,
    }


def weekly_accounting_rows(policy_rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    retained: list[dict[str, Any]] = []
    for cell in policy_rows:
        decisions = cell.get("decisions")
        buckets = cell.get("weekly_buckets")
        events = cell.get("events")
        if not isinstance(decisions, list) or not isinstance(buckets, list) or not isinstance(events, list):
            raise C5ARetentionEvidenceError("policy cell decisions/buckets/events must be lists")
        if len(decisions) != 13 or len(buckets) != 13:
            raise C5ARetentionEvidenceError("each policy cell must contain 13 decisions and buckets")
        for decision, bucket in zip(decisions, buckets, strict=True):
            if not isinstance(decision, Mapping) or not isinstance(bucket, Mapping):
                raise C5ARetentionEvidenceError("decision and weekly bucket must be objects")
            execution_time = str(decision.get("execution_time", ""))
            if str(bucket.get("monday_execution_time", "")) != execution_time:
                raise C5ARetentionEvidenceError("weekly bucket and decision time mismatch")
            event_sequence = decision.get("event_sequence")
            if event_sequence is None:
                if decision.get("executed_rebalance") is not False:
                    raise C5ARetentionEvidenceError("no-event decision must be a no-trade decision")
                monday_fee = 0.0
                monday_post_trade_equity = _finite(decision.get("equity_at_open"), "no-trade equity")
            else:
                if not isinstance(event_sequence, int) or event_sequence < 0 or event_sequence >= len(events):
                    raise C5ARetentionEvidenceError("invalid scheduled event sequence")
                event = events[event_sequence]
                if not isinstance(event, Mapping):
                    raise C5ARetentionEvidenceError("scheduled event must be an object")
                if event.get("kind") != "SCHEDULED_REBALANCE" or event.get("time") != execution_time:
                    raise C5ARetentionEvidenceError("scheduled event identity mismatch")
                monday_fee = _finite(event.get("total_fee"), "Monday fee")
                monday_post_trade_equity = _finite(event.get("equity_after"), "Monday post-trade equity")
            retained.append(
                {
                    "policy_id": str(cell.get("policy_id")),
                    "window_id": str(cell.get("window_id")),
                    "cost_label": str(cell.get("cost_label")),
                    "monday_execution_time": execution_time,
                    "start_reference_time": str(bucket.get("start_reference_time")),
                    "start_reference_equity": _finite(bucket.get("start_reference_equity"), "weekly start equity"),
                    "monday_pre_trade_open_equity": _finite(decision.get("equity_at_open"), "Monday pre-trade equity"),
                    "boundary_gap_pnl": _finite(decision.get("boundary_gap_pnl"), "boundary gap PnL"),
                    "monday_fee": monday_fee,
                    "monday_post_trade_equity": monday_post_trade_equity,
                    "final_sunday_time": str(bucket.get("end_time")),
                    "final_sunday_post_close_equity": _finite(bucket.get("ending_equity"), "weekly ending equity"),
                    "net_pnl": _finite(bucket.get("net_pnl"), "weekly net PnL"),
                    "net_return": _finite(bucket.get("net_return"), "weekly net return"),
                    "executed_rebalance": bool(decision.get("executed_rebalance")),
                }
            )
    if len(retained) != 156:
        raise C5ARetentionEvidenceError(f"weekly accounting row count mismatch: {len(retained)}")
    return retained


def concentration_rows(aggregates: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for aggregate in aggregates:
        half_pnl = aggregate.get("half_pnl")
        weekly_pnl = aggregate.get("weekly_pnl")
        contributions = aggregate.get("asset_contributions")
        if not isinstance(half_pnl, list) or not isinstance(weekly_pnl, list) or not isinstance(contributions, Mapping):
            raise C5ARetentionEvidenceError("aggregate concentration inputs are incomplete")
        if len(half_pnl) != 2 or len(weekly_pnl) != 26:
            raise C5ARetentionEvidenceError("aggregate concentration vector count mismatch")
        rows.append(
            {
                "policy_id": str(aggregate.get("policy_id")),
                "cost_label": str(aggregate.get("cost_label")),
                "positive_half_pnl": _positive_details([float(value) for value in half_pnl], top=1),
                "positive_asset_pnl": _positive_details([float(value) for value in contributions.values()], top=1),
                "positive_single_week_pnl": _positive_details([float(value) for value in weekly_pnl], top=1),
                "positive_top_three_week_pnl": _positive_details([float(value) for value in weekly_pnl], top=3),
            }
        )
    if len(rows) != 6:
        raise C5ARetentionEvidenceError(f"concentration row count mismatch: {len(rows)}")
    return rows


def incremental_details(aggregates: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    by_key = {
        (str(row.get("policy_id")), str(row.get("cost_label"))): row
        for row in aggregates
    }
    candidate = by_key[("C5ADerivativesCrowdingFilteredRiskBalance", "1.0x")]
    ablation = by_key[("C5APriceOnlyRiskBalanceAblation", "1.0x")]
    candidate_sharpe = _finite(candidate.get("aggregate_sharpe_4h"), "candidate Sharpe")
    ablation_sharpe = _finite(ablation.get("aggregate_sharpe_4h"), "ablation Sharpe")
    candidate_drawdown = _finite(candidate.get("maximum_half_drawdown"), "candidate drawdown")
    ablation_drawdown = _finite(ablation.get("maximum_half_drawdown"), "ablation drawdown")
    candidate_turnover = _finite(candidate.get("annualized_one_way_turnover"), "candidate turnover")
    ablation_turnover = _finite(ablation.get("annualized_one_way_turnover"), "ablation turnover")
    return {
        "cost_label": "1.0x",
        "candidate_policy_id": "C5ADerivativesCrowdingFilteredRiskBalance",
        "ablation_policy_id": "C5APriceOnlyRiskBalanceAblation",
        "aggregate_sharpe_4h": {
            "candidate": candidate_sharpe,
            "ablation": ablation_sharpe,
            "candidate_minus_ablation": candidate_sharpe - ablation_sharpe,
            "gate_pass": candidate_sharpe > ablation_sharpe,
        },
        "maximum_half_drawdown": {
            "candidate": candidate_drawdown,
            "ablation": ablation_drawdown,
            "candidate_minus_ablation": candidate_drawdown - ablation_drawdown,
            "ablation_minus_candidate_gate_margin": ablation_drawdown - candidate_drawdown,
            "gate_pass": candidate_drawdown <= ablation_drawdown,
        },
        "annualized_one_way_turnover": {
            "candidate": candidate_turnover,
            "ablation": ablation_turnover,
            "candidate_minus_ablation": candidate_turnover - ablation_turnover,
            "ablation_minus_candidate_gate_margin": ablation_turnover - candidate_turnover,
            "gate_pass": candidate_turnover <= ablation_turnover,
        },
    }


def build_payload(
    policy_rows: Sequence[Mapping[str, Any]],
    aggregates: Sequence[Mapping[str, Any]],
    *,
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
        "weekly_accounting": weekly_accounting_rows(policy_rows),
        "concentration_row_count": 6,
        "concentration": concentration_rows(aggregates),
        "incremental_information": incremental_details(aggregates),
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
    policy_rows = evidence.read_json(evidence.RESULTS / "policy_rows.json")
    aggregates = evidence.read_json(evidence.RESULTS / "policy_aggregates.json")
    if not isinstance(policy_rows, list) or not isinstance(aggregates, list):
        raise C5ARetentionEvidenceError("retained policy rows and aggregates must be lists")
    payload = build_payload(policy_rows, aggregates, source_sha=source_sha, merge_sha=merge_sha)
    evidence.write_json(RESULT_PATH, payload)
    print("C5A retention evidence PASS: 156 weekly accounting rows / 6 concentration rows / exact incremental differences")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
