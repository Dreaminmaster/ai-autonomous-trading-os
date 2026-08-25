"""One-shot official-public OKX capture for frozen C12A H1-H5."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from atos.c7a_historical_capture import C7AHistoricalCaptureError
from atos.c12a_historical_capture import (
    C12ACapturePackage,
    C12AHistoricalCaptureError,
    capture_futures_archives,
    capture_plan,
    capture_spot_history,
)
from atos.c12a_historical_run_guard import (
    C12AHistoricalRunGuardError,
    verify_checkout_binding,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--implementation-sha", required=True)
    parser.add_argument("--api-host", default="openapi.okx.com")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    binding = verify_checkout_binding(args.implementation_sha, repository_root=root)
    plan = capture_plan()
    package = C12ACapturePackage(args.output)
    package.write_json("checkout_binding.json", binding)
    spot = capture_spot_history(package)
    futures = capture_futures_archives(package, host=args.api_host)
    manifest = package.finalize(
        implementation_sha=args.implementation_sha, frozen_capture_plan=plan
    )
    print(
        json.dumps(
            {
                "status": "CAPTURE_PASS",
                "output": str(args.output),
                "implementation_sha": args.implementation_sha,
                "spot_instruments": sorted(spot),
                "futures_instrument_count": len(futures),
                "file_count": manifest["file_count"],
                "authenticated": False,
                "contains_account_data": False,
                "contains_order_data": False,
                "paper_state": "PAPER_CLOSED",
                "shadow_state": "SHADOW_CLOSED",
                "live_state": "LIVE_FORBIDDEN",
            },
            sort_keys=True,
        )
    )
    return 0


def cli() -> int:
    try:
        return main()
    except (C7AHistoricalCaptureError, C12AHistoricalCaptureError) as exc:
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
    except C12AHistoricalRunGuardError as exc:
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
