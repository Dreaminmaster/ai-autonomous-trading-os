#!/usr/bin/env python3
"""Run one bounded C6A execution-venue GLOBAL category preflight.

This command is intended for a separately authorized local or self-hosted venue.
It never runs the full source-authority capture.  A packaged probe PASS or probe
FAIL is a valid completed preflight; unexpected runtime or venue-review failure
returns non-zero after retaining evidence.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import atos.c6a_source_scope_probe as probe
from atos.c6a_source_authority_capture import atomic_write_json
from atos.c6a_source_scope_venue_preflight import (
    ALLOWED_EXECUTION_MODES,
    run_venue_preflight,
)
from atos.c6a_source_scope_venue_preflight_independent import review_venue_preflight


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--venue-label", required=True)
    parser.add_argument("--execution-mode", choices=ALLOWED_EXECUTION_MODES, required=True)
    parser.add_argument("--implementation-sha", required=True)
    parser.add_argument("--source-commit-sha", required=True)
    parser.add_argument("--validated-pr-merge-ref")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    try:
        attestation, result, probe_review, _manifest = run_venue_preflight(
            args.output,
            venue_label=args.venue_label,
            execution_mode=args.execution_mode,
            implementation_sha=args.implementation_sha,
            source_commit_sha=args.source_commit_sha,
            validated_pr_merge_ref=args.validated_pr_merge_ref,
        )
        venue_review = review_venue_preflight(
            args.output,
            expected_implementation_sha=args.implementation_sha,
            expected_source_commit_sha=args.source_commit_sha,
            expected_validated_pr_merge_ref=args.validated_pr_merge_ref,
        )
        atomic_write_json(args.output / "venue_independent_review.json", venue_review)
        manifest = probe.build_manifest(args.output)

        summary = {
            "venue_label": attestation["venue_label"],
            "execution_mode": attestation["execution_mode"],
            "probe_status": result["status"],
            "probe_result": result["result"],
            "probe_independent_review_status": probe_review["status"],
            "venue_independent_review_status": venue_review["status"],
            "manifest_file_count": manifest["file_count"],
            "article_expansion_authorized": False,
            "third_full_capture_authorized": False,
            "implementation_authorized": False,
            "economic_data_access_authorized": False,
            "paper_state": "PAPER_CLOSED",
            "shadow_state": "SHADOW_CLOSED",
            "live_state": "LIVE_FORBIDDEN",
        }
        print(json.dumps(summary, sort_keys=True))
        return 0 if venue_review["status"] == "PASS" else 3
    except BaseException as exc:
        emergency = {
            "schema_version": 1,
            "stage": "C6A_SOURCE_AUTHORITY_EXECUTION_VENUE_PREFLIGHT_EMERGENCY_FAILURE",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "error_type": type(exc).__name__,
            "error": str(exc),
            "article_expansion_authorized": False,
            "third_full_capture_authorized": False,
            "implementation_authorized": False,
            "economic_data_access_authorized": False,
            "paper_state": "PAPER_CLOSED",
            "shadow_state": "SHADOW_CLOSED",
            "live_state": "LIVE_FORBIDDEN",
        }
        atomic_write_json(args.output / "emergency_failure.json", emergency)
        print(json.dumps(emergency, sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
