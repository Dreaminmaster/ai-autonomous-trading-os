#!/usr/bin/env python3
"""Run the one-time C6A public source-authority attempt.

A packaged gate FAIL is a valid completed attempt and therefore exits zero; a
workflow should upload the artifact first and enforce the recorded gate status
in a later step.  Unexpected implementation errors exit non-zero after writing
a minimal emergency diagnostic into the output directory.
"""
from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from atos.c6a_source_authority_attempt import run_source_authority_attempt
from atos.c6a_source_authority_capture import atomic_write_json


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--inventory",
        type=Path,
        default=Path("config/c6a_source_authority_query_inventory_v1.json"),
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--source-commit-sha",
        default=os.environ.get("GITHUB_SHA", ""),
    )
    parser.add_argument(
        "--pr-merge-ref",
        default=os.environ.get("C6A_PR_MERGE_REF") or None,
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    try:
        summary = run_source_authority_attempt(
            inventory_path=args.inventory,
            output_root=args.output,
            source_commit_sha=args.source_commit_sha,
            pr_merge_ref=args.pr_merge_ref,
        )
        atomic_write_json(args.output / "run_summary.json", summary)
        print(json.dumps(summary, sort_keys=True))
        return 0
    except BaseException as exc:
        emergency = {
            "schema_version": 1,
            "stage": "C6A_SOURCE_AUTHORITY_GATE_EMERGENCY_FAILURE",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "error_type": type(exc).__name__,
            "error": str(exc),
            "implementation_authorized": False,
            "economic_data_access_authorized": False,
            "live_state": "LIVE_FORBIDDEN",
        }
        atomic_write_json(args.output / "emergency_failure.json", emergency)
        print(json.dumps(emergency, sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
