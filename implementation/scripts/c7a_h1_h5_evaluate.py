"""One-shot H1-H5 economic evaluation over a verified public capture."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from atos.c7a_historical_evidence import (
    C7AHistoricalEvidenceError,
    build_h1_h5_evidence_package,
)
from atos.c7a_historical_replay import C7AHistoricalReplayError
from atos.c7a_historical_run_guard import (
    C7AHistoricalRunGuardError,
    verify_checkout_binding,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--capture", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--implementation-sha", required=True)
    parser.add_argument("--authoritative-run-id", required=True)
    args = parser.parse_args()

    checkout_binding = verify_checkout_binding(
        args.implementation_sha,
        repository_root=Path(__file__).resolve().parents[2],
    )
    final, manifest = build_h1_h5_evidence_package(
        args.output,
        capture_root=args.capture,
        implementation_sha=args.implementation_sha,
        authoritative_run_id=args.authoritative_run_id,
        evaluation_checkout_binding=checkout_binding,
    )
    print(
        json.dumps(
            {
                "status": final["status"],
                "classification": final["classification"],
                "shadow_eligible": final["shadow_eligible"],
                "output": str(args.output),
                "evidence_file_count": manifest["file_count"],
                "live_state": "LIVE_FORBIDDEN",
            },
            sort_keys=True,
        )
    )
    return 0 if final["status"] == "PASS" else 1


def cli() -> int:
    """Emit data, implementation, and economic outcomes as separate states."""
    try:
        return main()
    except (C7AHistoricalEvidenceError, C7AHistoricalReplayError) as exc:
        print(
            json.dumps(
                {
                    "status": "FAIL",
                    "classification": "DATA_FAILURE",
                    "error": str(exc),
                    "live_state": "LIVE_FORBIDDEN",
                },
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 2
    except C7AHistoricalRunGuardError as exc:
        print(
            json.dumps(
                {
                    "status": "FAIL",
                    "classification": "IMPLEMENTATION_FAILURE",
                    "error": str(exc),
                    "live_state": "LIVE_FORBIDDEN",
                },
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 3
    except Exception as exc:  # noqa: BLE001 - authoritative CLI failure boundary
        print(
            json.dumps(
                {
                    "status": "FAIL",
                    "classification": "IMPLEMENTATION_FAILURE",
                    "error_type": type(exc).__name__,
                    "live_state": "LIVE_FORBIDDEN",
                },
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 4


if __name__ == "__main__":
    raise SystemExit(cli())
