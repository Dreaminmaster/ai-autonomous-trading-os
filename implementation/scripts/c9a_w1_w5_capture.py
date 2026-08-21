"""One-shot official-public OKX capture for frozen C9A W1-W5."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from atos.c7a_historical_capture import C7AHistoricalCaptureError
from atos.c9a_contract import ALL_TRADE_INSTRUMENTS, SWAP_INSTRUMENTS
from atos.c9a_historical_capture import (
    C9ACapturePackage,
    C9AHistoricalCaptureError,
    FundingDownloadSpec,
    capture_funding_downloads,
    capture_historical_funding_range,
    capture_mark_range,
    capture_trade_range,
)
from atos.c9a_historical_run_guard import (
    C9AHistoricalRunGuardError,
    verify_checkout_binding,
)
from atos.c9a_historical_schedule import w1_w5_capture_plan


def _inventory(path: Path) -> tuple[FundingDownloadSpec, ...]:
    try:
        payload: Any = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise SystemExit(f"invalid funding inventory: {path}") from exc
    if not isinstance(payload, list):
        raise SystemExit("funding inventory must be a JSON array")
    specs = []
    for index, value in enumerate(payload):
        if not isinstance(value, dict) or set(value) != {
            "request_id",
            "instrument",
            "url",
            "column_map",
        }:
            raise SystemExit(f"funding inventory row {index} has schema drift")
        specs.append(FundingDownloadSpec(**value))
    return tuple(specs)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--implementation-sha", required=True)
    parser.add_argument("--funding-inventory", type=Path)
    parser.add_argument("--api-host", default="openapi.okx.com")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    binding = verify_checkout_binding(args.implementation_sha, repository_root=root)
    plan = w1_w5_capture_plan()
    package = C9ACapturePackage(args.output)
    package.write_json("checkout_binding.json", binding)
    for instrument in SWAP_INSTRUMENTS:
        capture_mark_range(
            package,
            instrument=instrument,
            start_inclusive=str(plan["mark_start_inclusive"]),
            end_exclusive=str(plan["mark_end_exclusive"]),
            host=args.api_host,
        )
    for instrument in ALL_TRADE_INSTRUMENTS:
        capture_trade_range(
            package,
            instrument=instrument,
            start_inclusive=str(plan["trade_start_inclusive"]),
            end_exclusive=str(plan["trade_end_exclusive"]),
            host=args.api_host,
        )
    if args.funding_inventory is None:
        capture_historical_funding_range(
            package,
            start_inclusive=str(plan["funding_start_inclusive"]),
            end_exclusive=str(plan["funding_end_exclusive"]),
            host=args.api_host,
        )
    else:
        capture_funding_downloads(
            package,
            specs=_inventory(args.funding_inventory),
            start_inclusive=str(plan["funding_start_inclusive"]),
            end_exclusive=str(plan["funding_end_exclusive"]),
        )
    manifest = package.finalize(
        implementation_sha=args.implementation_sha, capture_plan=plan
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
    try:
        return main()
    except (C7AHistoricalCaptureError, C9AHistoricalCaptureError) as exc:
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
    except C9AHistoricalRunGuardError as exc:
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
