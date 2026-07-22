#!/usr/bin/env python3
"""Verify every retained C6A decision margin after strict finalization."""
from __future__ import annotations

import argparse
import json
from decimal import Decimal
from pathlib import Path
from typing import Any, Mapping

from atos.c6a_contract import C6AError, decimal_value
from atos.c6a_evidence import write_json_atomic

IMPL = Path(__file__).resolve().parents[1]
DEFAULT_RESULTS = IMPL / "freqtrade_data/c6a_results"
DEFAULT_STRICT_FINALIZER = IMPL / "freqtrade_data/c6a_runtime/c6a_strict_final_evidence.json"
DEFAULT_OUTPUT = IMPL / "freqtrade_data/c6a_runtime/c6a_decision_margin_guard.json"


class C6ADecisionMarginError(RuntimeError):
    pass


def _read(path: Path, label: str) -> Mapping[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise C6ADecisionMarginError(f"unable to load {label}: {exc}") from exc
    if not isinstance(payload, Mapping):
        raise C6ADecisionMarginError(f"{label} must be an object")
    return payload


def _decimal(value: Any, label: str) -> Decimal:
    try:
        return decimal_value(value, label)
    except C6AError as exc:
        raise C6ADecisionMarginError(str(exc)) from exc


def expected_margins(
    *,
    candidate_expected: Mapping[str, Any],
    candidate_stress: Mapping[str, Any],
    candidate_severe: Mapping[str, Any],
    always_on_expected: Mapping[str, Any],
) -> dict[str, Decimal]:
    candidate_statistics = candidate_expected.get("statistics")
    always_statistics = always_on_expected.get("statistics")
    if not isinstance(candidate_statistics, Mapping) or not isinstance(
        always_statistics, Mapping
    ):
        return {}
    expected_return = _decimal(
        candidate_expected.get("aggregate_return"), "candidate expected return"
    )
    stress_return = _decimal(
        candidate_stress.get("aggregate_return"), "candidate stress return"
    )
    severe_return = _decimal(
        candidate_severe.get("aggregate_return"), "candidate severe return"
    )
    always_return = _decimal(
        always_on_expected.get("aggregate_return"), "always-on return"
    )
    candidate_sharpe = _decimal(
        candidate_statistics.get("annualized_weekly_sharpe"), "candidate Sharpe"
    )
    always_sharpe = _decimal(
        always_statistics.get("annualized_weekly_sharpe"), "always-on Sharpe"
    )
    return {
        "expected_return_minus_zero": expected_return,
        "stress_return_minus_zero": stress_return,
        "severe_return_minus_zero": severe_return,
        "return_delta_vs_always_on": expected_return - always_return,
        "sharpe_delta_vs_always_on": candidate_sharpe - always_sharpe,
    }


def verify(
    *, result_dir: Path, strict_finalizer_path: Path
) -> dict[str, Any]:
    strict = _read(strict_finalizer_path, "C6A strict finalizer")
    if strict.get("status") != "PASS" or strict.get(
        "all_gate_driving_aggregate_fields_compared"
    ) is not True:
        raise C6ADecisionMarginError(
            "strict finalizer must PASS before decision-margin verification"
        )
    candidate_expected = _read(
        result_dir / "aggregates/C6AMarketNeutralFundingCarry/1.0x.json",
        "candidate expected aggregate",
    )
    candidate_stress = _read(
        result_dir / "aggregates/C6AMarketNeutralFundingCarry/1.5x.json",
        "candidate stress aggregate",
    )
    candidate_severe = _read(
        result_dir / "aggregates/C6AMarketNeutralFundingCarry/2.0x.json",
        "candidate severe aggregate",
    )
    always_expected = _read(
        result_dir / "aggregates/AlwaysOnDeltaNeutralComparator/1.0x.json",
        "always-on expected aggregate",
    )
    decision = _read(result_dir / "decision.json", "C6A decision")
    expected = expected_margins(
        candidate_expected=candidate_expected,
        candidate_stress=candidate_stress,
        candidate_severe=candidate_severe,
        always_on_expected=always_expected,
    )
    observed = decision.get("margins")
    if not isinstance(observed, Mapping) or set(observed) != set(expected):
        raise C6ADecisionMarginError(
            f"C6A decision margin key-set mismatch: expected={sorted(expected)} "
            f"observed={sorted(observed) if isinstance(observed, Mapping) else None}"
        )
    for key, value in expected.items():
        observed_value = _decimal(observed[key], f"decision margin {key}")
        if observed_value != value:
            raise C6ADecisionMarginError(
                f"C6A decision margin mismatch {key}: {observed_value} != {value}"
            )
    return {
        "schema_version": 1,
        "stage": "C6A",
        "status": "PASS",
        "margin_count": len(expected),
        "margins": {key: str(value) for key, value in expected.items()},
        "economic_result": decision.get("status"),
        "selected_policy": decision.get("selected_policy"),
        "confirmation_opened": False,
        "c6b_state": "C6B_CLOSED",
        "c5b_state": "C5B_CLOSED_AND_UNTOUCHED",
        "holdout_state": "HOLDOUT_CLOSED",
        "paper_state": "PAPER_CLOSED",
        "shadow_state": "SHADOW_CLOSED",
        "live": "FORBIDDEN",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--results", type=Path, default=DEFAULT_RESULTS)
    parser.add_argument(
        "--strict-finalizer", type=Path, default=DEFAULT_STRICT_FINALIZER
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args(argv)
    report = verify(
        result_dir=args.results,
        strict_finalizer_path=args.strict_finalizer,
    )
    write_json_atomic(args.output, report)
    print(
        "C6A decision-margin guard PASS: "
        f"{report['margin_count']} exact retained margins"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
