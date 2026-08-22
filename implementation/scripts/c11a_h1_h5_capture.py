"""One-shot official-public OKX capture for frozen C11A H1-H5."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from atos.c7a_historical_capture import C7AHistoricalCaptureError
from atos.c11a_contract import BTC_BETA_BENCHMARK, CANDIDATE_POOL, capture_plan
from atos.c11a_historical_capture import (
    C11ACapturePackage,
    C11AHistoricalCaptureError,
    capture_historical_funding_range,
    capture_mark_range,
    capture_trade_range,
    select_formation_universe,
)
from atos.c11a_historical_run_guard import (
    C11AHistoricalRunGuardError,
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
    package = C11ACapturePackage(args.output)
    package.write_json("checkout_binding.json", binding)
    formation = {}
    for instrument in CANDIDATE_POOL:
        formation[instrument] = capture_trade_range(
            package,
            series_type="formation_trades",
            instrument=instrument,
            start_inclusive=str(plan["formation_trade_start_inclusive"]),
            end_exclusive=str(plan["formation_trade_end_exclusive"]),
            host=args.api_host,
        )
    selected = package.freeze_universe(select_formation_universe(formation))
    for instrument in selected:
        capture_trade_range(
            package,
            series_type="trades",
            instrument=instrument,
            start_inclusive=str(plan["selected_trade_start_inclusive"]),
            end_exclusive=str(plan["selected_trade_end_exclusive"]),
            host=args.api_host,
        )
    for instrument in sorted({*selected, BTC_BETA_BENCHMARK}):
        capture_mark_range(
            package,
            instrument=instrument,
            start_inclusive=str(plan["mark_start_inclusive"]),
            end_exclusive=str(plan["mark_end_exclusive"]),
            host=args.api_host,
        )
    capture_historical_funding_range(
        package,
        selected_universe=selected,
        start_inclusive=str(plan["funding_start_inclusive"]),
        end_exclusive=str(plan["funding_end_exclusive"]),
        host=args.api_host,
    )
    manifest = package.finalize(
        implementation_sha=args.implementation_sha,
        capture_plan_value=plan,
    )
    print(
        json.dumps(
            {
                "status": "CAPTURE_PASS",
                "output": str(args.output),
                "implementation_sha": args.implementation_sha,
                "selected_universe": list(selected),
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
    except (C7AHistoricalCaptureError, C11AHistoricalCaptureError) as exc:
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
    except C11AHistoricalRunGuardError as exc:
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
