#!/usr/bin/env python3
"""Authoritative C6A screen entry point.

The original runner remains a readable implementation scaffold. This entry
point binds its aggregation and gate call sites to fail-closed production
implementations. Zero weekly variance and zero positive-concentration
denominators become an explicit economic rejection, never infrastructure
failure. The independent strict finalizer does not import these functions.
"""
from __future__ import annotations

import argparse
from pathlib import Path

from atos.c6a_safe_aggregate_v2 import (
    aggregate_window_results_final,
    decide_candidate_safe,
)
from scripts import run_c6a_screen as base


class C6AAuthoritativeScreenError(RuntimeError):
    pass


def run_authoritative_screen(
    *,
    config,
    prepare_report,
    output_dir: Path,
    source_sha: str,
):
    original_aggregate = base.aggregate_window_results
    original_gate = base.decide_candidate
    base.aggregate_window_results = aggregate_window_results_final
    base.decide_candidate = decide_candidate_safe
    try:
        summary = base.run_screen(
            config=config,
            prepare_report=prepare_report,
            output_dir=output_dir,
            source_sha=source_sha,
        )
    finally:
        base.aggregate_window_results = original_aggregate
        base.decide_candidate = original_gate
    summary["authoritative_screen_entrypoint"] = (
        "scripts/run_c6a_screen_authoritative.py"
    )
    summary["undefined_statistics_fail_closed"] = True
    summary["undefined_statistics_state"] = "UNDEFINED_WEEKLY_VARIANCE"
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=base.DEFAULT_CONFIG)
    parser.add_argument(
        "--prepare-report", type=Path, default=base.DEFAULT_PREPARE_REPORT
    )
    parser.add_argument("--output-dir", type=Path, default=base.DEFAULT_OUTPUT)
    args = parser.parse_args(argv)
    source_sha = base._exact_source_sha()
    config = base._read_object(args.config, "C6A config")
    prepare_report = base._read_object(args.prepare_report, "C6A prepare report")
    summary = run_authoritative_screen(
        config=config,
        prepare_report=prepare_report,
        output_dir=args.output_dir,
        source_sha=source_sha,
    )
    print(
        "C6A authoritative screen complete: "
        f"{summary['economic_result']} / selected={summary['selected_policy']} / "
        "undefined statistics reject cleanly"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
