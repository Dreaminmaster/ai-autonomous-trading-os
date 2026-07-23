#!/usr/bin/env python3
"""Run the bounded C6A GLOBAL Help Center source-scope probe."""
from __future__ import annotations

import argparse
from pathlib import Path

from atos.c6a_source_scope_probe import atomic_write_json, build_manifest, run_probe
from atos.c6a_source_scope_probe_independent import review_probe


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    result = run_probe(args.output)
    review = review_probe(args.output)
    atomic_write_json(args.output / "independent_review.json", review)
    manifest = build_manifest(args.output)

    print(f"probe_status={result['status']}")
    print(f"probe_result={result['result']}")
    print(
        "reproducible_passing_profiles="
        + ",".join(result.get("reproducible_passing_profiles", []))
    )
    print(f"independent_review_status={review['status']}")
    print(f"independent_probe_status={review['probe_status_recomputed']}")
    print(f"manifest_file_count={manifest['file_count']}")
    print("implementation_authorized=false")
    print("economic_data_access_authorized=false")
    print("third_full_capture_authorized=false")
    print("live_state=LIVE_FORBIDDEN")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
