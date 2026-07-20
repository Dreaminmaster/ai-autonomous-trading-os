"""Contract-hardening wrapper for the independent C4A reference implementation.

The plain-array reference keeps its economic engine separate from production.
This wrapper applies only the merged S3 forced-cash audit-record semantics so
reference evidence contains the pre-boundary signal while the economic target
remains cash.
"""
from __future__ import annotations

from typing import Any, Mapping, Sequence

from . import c4a_reference_recompute as _reference

_ORIGINAL_REFERENCE_SIMULATE_WINDOW = _reference.reference_simulate_window


def reference_simulate_window(
    market: _reference.ReferenceMarket,
    *,
    selected_pairs: Sequence[str],
    policy: str,
    window: Mapping[str, Any],
    cost_label: str,
    config: Mapping[str, Any],
) -> dict[str, Any]:
    row = _ORIGINAL_REFERENCE_SIMULATE_WINDOW(
        market,
        selected_pairs=selected_pairs,
        policy=policy,
        window=window,
        cost_label=cost_label,
        config=config,
    )
    if row["window_id"] != "S3":
        return row
    forced = [item for item in row["decisions"] if item.get("forced_cash")]
    if len(forced) != 1:
        raise _reference.C4AReferenceError("reference missing unique forced-stub record")
    execution_index = market.timestamps.index(_reference._timestamp("2024-09-30T00:00:00Z"))
    audit = _reference.reference_signal(
        market,
        execution_index=execution_index,
        selected_pairs=selected_pairs,
        policy=policy,
        config=config,
    )
    pre_override_targets = dict(audit["target_weights"])
    rows = []
    for item in audit["rows"]:
        enriched = dict(item)
        enriched["pre_boundary_selected_target"] = bool(item["selected_target"])
        enriched["selected_target"] = False
        rows.append(enriched)
    record = forced[0]
    record.update(audit)
    record["risk_on_before_boundary_override"] = bool(audit["risk_on"])
    record["pre_boundary_target_weights"] = pre_override_targets
    record["chosen_pairs"] = []
    record["target_weights"] = {}
    record["risk_on"] = False
    record["forced_cash"] = True
    record["rows"] = rows
    return row


_reference.reference_simulate_window = reference_simulate_window

C4AReferenceError = _reference.C4AReferenceError
CANDIDATE_PAIRS = _reference.CANDIDATE_PAIRS
POLICIES = _reference.POLICIES
COMPARATORS = _reference.COMPARATORS
COST_LABELS = _reference.COST_LABELS
verify_config = _reference.verify_config
reference_prepare_market = _reference.reference_prepare_market
reference_select_universe = _reference.reference_select_universe
reference_signal = _reference.reference_signal
reference_solve_post_cost = _reference.reference_solve_post_cost
reference_simulate_comparator = _reference.reference_simulate_comparator
reference_aggregate_policy = _reference.reference_aggregate_policy
reference_attach_dsr = _reference.reference_attach_dsr
reference_aggregate_comparator = _reference.reference_aggregate_comparator
reference_decide = _reference.reference_decide
reference_run_screen = _reference.reference_run_screen
