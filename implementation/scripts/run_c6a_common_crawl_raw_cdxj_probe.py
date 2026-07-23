#!/usr/bin/env python3
"""Run one bounded raw Common Crawl CDXJ access probe."""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from atos.c6a_common_crawl_raw_cdxj_core import atomic_write_json
from atos.c6a_common_crawl_raw_cdxj_probe import build_manifest, run_probe
from atos.c6a_common_crawl_raw_cdxj_probe_independent import review_probe


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--inventory",
        type=Path,
        default=Path("config/c6a_common_crawl_raw_cdxj_probe_inventory_v1.json"),
    )
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    try:
        result = run_probe(args.inventory, args.output)
        review = review_probe(args.output)
        atomic_write_json(args.output / "independent_review.json", review)
        manifest = build_manifest(args.output)
        summary = {
            "probe_status": result["status"],
            "probe_result": result["result"],
            "independent_review_status": review["status"],
            "independent_probe_status": review["probe_status_recomputed"],
            "completed_query_count": result["completed_query_count"],
            "hit_query_count": result["hit_query_count"],
            "manifest_file_count": manifest["file_count"],
            "warc_retrieval_authorized": False,
            "third_full_capture_authorized": False,
            "economic_data_access_authorized": False,
            "live_state": "LIVE_FORBIDDEN",
        }
        print(json.dumps(summary, sort_keys=True))
        return 0 if result["status"] == "PASS" and review["status"] == "PASS" else 3
    except BaseException as exc:
        emergency = {
            "schema_version": 1,
            "stage": "C6A_COMMON_CRAWL_RAW_CDXJ_PROBE_EMERGENCY_FAILURE",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "error_type": type(exc).__name__,
            "error": str(exc),
            "direct_okx_access_authorized": False,
            "warc_retrieval_authorized": False,
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
