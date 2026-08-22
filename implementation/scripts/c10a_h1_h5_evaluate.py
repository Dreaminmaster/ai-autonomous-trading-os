"""One-shot C10A H1-H5 evaluation over verified official-public custody."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from atos.c10a_historical_evidence import (
    C10AHistoricalDataEvidenceError,
    C10AHistoricalEvidenceError,
    build_h1_h5_evidence_package,
)
from atos.c10a_historical_independent import C10AHistoricalIndependentError
from atos.c10a_historical_replay import C10AHistoricalReplayError
from atos.c10a_historical_run_guard import (
    C10AHistoricalRunGuardError,
    verify_checkout_binding,
)


def classification_exit_code(classification: str) -> int:
    if classification == "ECONOMIC_PASS":
        return 0
    if classification == "ECONOMIC_FAIL":
        return 1
    raise C10AHistoricalEvidenceError(
        "C10A independent recomputation failed after evidence retention"
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--capture", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--implementation-sha", required=True)
    parser.add_argument("--authoritative-run-id", required=True)
    args = parser.parse_args()
    repository_root = Path(__file__).resolve().parents[2]
    binding = verify_checkout_binding(
        args.implementation_sha, repository_root=repository_root
    )
    final, manifest = build_h1_h5_evidence_package(
        args.output,
        capture_root=args.capture,
        repository_root=repository_root,
        implementation_sha=args.implementation_sha,
        authoritative_run_id=args.authoritative_run_id,
        evaluation_checkout_binding=binding,
    )
    print(
        json.dumps(
            {
                "status": final["status"],
                "classification": final["classification"],
                "historical_economic_pass": final["historical_economic_pass"],
                "shadow_eligible": final["shadow_eligible"],
                "output": str(args.output),
                "evidence_file_count": manifest["file_count"],
                "live_state": "LIVE_FORBIDDEN",
            },
            sort_keys=True,
        )
    )
    return classification_exit_code(str(final["classification"]))


def cli() -> int:
    try:
        return main()
    except C10AHistoricalDataEvidenceError as exc:
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
    except (
        C10AHistoricalEvidenceError,
        C10AHistoricalIndependentError,
        C10AHistoricalReplayError,
        C10AHistoricalRunGuardError,
    ) as exc:
        print(
            json.dumps(
                {
                    "status": "FAIL",
                    "classification": "PROGRAM_FAILURE",
                    "error": str(exc),
                    "live_state": "LIVE_FORBIDDEN",
                },
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 3
    except Exception as exc:  # noqa: BLE001
        print(
            json.dumps(
                {
                    "status": "FAIL",
                    "classification": "PROGRAM_FAILURE",
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
