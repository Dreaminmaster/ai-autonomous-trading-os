"""One-shot official-public OKX capture for the preregistered C7A H1-H5 range."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from atos.c7a_contract import INSTRUMENTS
from atos.c7a_historical_capture import (
    C7AHistoricalCaptureError,
    CapturePackage,
    FundingDownloadSpec,
    capture_funding_downloads,
    capture_historical_funding_range,
    capture_mark_range,
    capture_trade_range,
    h1_h5_capture_plan,
)
from atos.c7a_historical_run_guard import (
    C7AHistoricalRunGuardError,
    verify_checkout_binding,
)


def _inventory(path: Path) -> tuple[FundingDownloadSpec, ...]:
    try:
        payload: Any = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise SystemExit(f"invalid funding inventory: {path}") from exc
    if not isinstance(payload, list):
        raise SystemExit("funding inventory must be a JSON array")
    specs: list[FundingDownloadSpec] = []
    for index, value in enumerate(payload):
        if not isinstance(value, dict) or set(value) != {
            "request_id",
            "instrument",
            "url",
            "column_map",
        }:
            raise SystemExit(f"funding inventory row {index} has schema drift")
        specs.append(
            FundingDownloadSpec(
                request_id=value["request_id"],
                instrument=value["instrument"],
                url=value["url"],
                column_map=value["column_map"],
            )
        )
    return tuple(specs)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--implementation-sha", required=True)
    parser.add_argument(
        "--funding-inventory",
        type=Path,
        help="Optional reviewed fallback inventory; default discovers official OKX archives.",
    )
    parser.add_argument("--api-host", default="openapi.okx.com")
    args = parser.parse_args()

    checkout_binding = verify_checkout_binding(
        args.implementation_sha,
        repository_root=Path(__file__).resolve().parents[2],
    )
    plan = h1_h5_capture_plan()
    package = CapturePackage(args.output)
    package.write_json("checkout_binding.json", checkout_binding)
    for instrument in INSTRUMENTS:
        capture_mark_range(
            package,
            instrument=instrument,
            start_inclusive=plan["mark_start_inclusive"],
            end_exclusive=plan["scored_end_exclusive"],
            host=args.api_host,
        )
        capture_trade_range(
            package,
            instrument=instrument,
            start_inclusive=plan["trade_start_inclusive"],
            end_exclusive=plan["trade_end_exclusive"],
            host=args.api_host,
        )
    if args.funding_inventory is None:
        capture_historical_funding_range(
            package,
            start_inclusive=plan["funding_start_inclusive"],
            end_exclusive=plan["scored_end_exclusive"],
            host=args.api_host,
        )
    else:
        capture_funding_downloads(
            package,
            specs=_inventory(args.funding_inventory),
            start_inclusive=plan["funding_start_inclusive"],
            end_exclusive=plan["scored_end_exclusive"],
        )
    manifest = package.finalize(
        implementation_sha=args.implementation_sha,
        capture_plan=plan,
    )
    print(
        json.dumps(
            {
                "status": "CAPTURE_PASS",
                "output": str(args.output),
                "implementation_sha": args.implementation_sha,
                "file_count": manifest["file_count"],
                "authenticated": False,
                "contains_account_data": False,
                "contains_order_data": False,
                "live_state": "LIVE_FORBIDDEN",
            },
            sort_keys=True,
        )
    )
    return 0


def cli() -> int:
    """Emit a machine-readable distinction between data and program failures."""
    try:
        return main()
    except C7AHistoricalCaptureError as exc:
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
