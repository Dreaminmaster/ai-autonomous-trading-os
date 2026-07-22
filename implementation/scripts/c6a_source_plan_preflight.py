#!/usr/bin/env python3
"""Strict non-economic preflight for the reviewed C6A public source plan."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urlparse

from atos.c6a_contract import C6AError
from atos.c6a_source_plan import validate_source_plan
from scripts.c6a_capture_public_api import MARK_ENDPOINT, TRADE_ENDPOINT

IMPL = Path(__file__).resolve().parents[1]
DEFAULT_PLAN = IMPL / "config/c6a_public_source_plan.json"
PLACEHOLDER_TOKENS = (
    "example",
    "placeholder",
    "todo",
    "tbd",
    "fill-me",
    "replace-me",
)
CANDLE_KINDS = {
    "spot_trade_candles",
    "swap_trade_candles",
    "swap_mark_candles",
}


class C6ASourcePlanPreflightError(RuntimeError):
    pass


def preflight(plan: Mapping[str, Any]) -> dict[str, Any]:
    try:
        entries = validate_source_plan(plan)
    except C6AError as exc:
        raise C6ASourcePlanPreflightError(str(exc)) from exc
    raw_rows = plan.get("sources")
    if not isinstance(raw_rows, list):
        raise C6ASourcePlanPreflightError("C6A source-plan rows missing")
    by_id = {
        str(row.get("source_id")): row
        for row in raw_rows
        if isinstance(row, Mapping)
    }
    if set(by_id) != {entry.source_id for entry in entries} or len(by_id) != len(raw_rows):
        raise C6ASourcePlanPreflightError("C6A source-plan ID mapping mismatch")
    candle_entries = 0
    object_entries = 0
    for entry in entries:
        row = by_id[entry.source_id]
        lower = entry.url.lower()
        if any(token in lower for token in PLACEHOLDER_TOKENS):
            raise C6ASourcePlanPreflightError(
                f"placeholder source URL is forbidden: {entry.source_id}"
            )
        parsed = urlparse(entry.url)
        if not parsed.path or parsed.path == "/":
            raise C6ASourcePlanPreflightError(
                f"source URL path is not exact: {entry.source_id}"
            )
        mode = str(row.get("request_mode", ""))
        if entry.kind in CANDLE_KINDS:
            candle_entries += 1
            expected = MARK_ENDPOINT if entry.kind == "swap_mark_candles" else TRADE_ENDPOINT
            if mode != "PAGINATED_PUBLIC_API" or entry.url != expected:
                raise C6ASourcePlanPreflightError(
                    f"candle source mode/endpoint drift: {entry.source_id}"
                )
            if str(row.get("bar")) != "1H" or int(row.get("limit", -1)) != 100:
                raise C6ASourcePlanPreflightError(
                    f"candle pagination parameters drift: {entry.source_id}"
                )
            if entry.archive_member is not None:
                raise C6ASourcePlanPreflightError(
                    f"API candle source cannot have archive_member: {entry.source_id}"
                )
        else:
            object_entries += 1
            if mode != "SINGLE_OBJECT":
                raise C6ASourcePlanPreflightError(
                    f"funding/metadata source must be an exact object: {entry.source_id}"
                )
            suffix = Path(parsed.path).suffix.lower()
            if suffix in {".zip", ".gz", ".tar"} and not entry.archive_member:
                raise C6ASourcePlanPreflightError(
                    f"archive source lacks exact member: {entry.source_id}"
                )
            if entry.kind == "funding_history" and "fund" not in lower:
                raise C6ASourcePlanPreflightError(
                    f"funding source URL lacks funding identity: {entry.source_id}"
                )
            if entry.kind == "instrument_metadata" and not any(
                token in lower
                for token in ("instrument", "contract", "metadata", "specification")
            ):
                raise C6ASourcePlanPreflightError(
                    f"metadata source URL lacks instrument identity: {entry.source_id}"
                )
    if candle_entries != 6:
        raise C6ASourcePlanPreflightError(
            f"expected six paginated candle sources, observed {candle_entries}"
        )
    if object_entries < 6:
        raise C6ASourcePlanPreflightError(
            f"funding/metadata exact-object source count is too small: {object_entries}"
        )
    canonical = json.dumps(
        plan, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")
    return {
        "schema_version": 1,
        "stage": "C6A",
        "status": "PASS",
        "source_plan_sha256": hashlib.sha256(canonical).hexdigest(),
        "source_count": len(entries),
        "paginated_candle_source_count": candle_entries,
        "exact_object_source_count": object_entries,
        "placeholder_count": 0,
        "authenticated": False,
        "economic_result_run": False,
        "c6b_state": "C6B_CLOSED",
        "c5b_state": "C5B_CLOSED_AND_UNTOUCHED",
        "live": "FORBIDDEN",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", type=Path, default=DEFAULT_PLAN)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    try:
        payload = json.loads(args.plan.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise C6ASourcePlanPreflightError(f"invalid C6A source plan: {exc}") from exc
    if not isinstance(payload, Mapping):
        raise C6ASourcePlanPreflightError("C6A source plan must be an object")
    report = preflight(payload)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    print(
        "C6A source-plan preflight PASS: "
        f"{report['source_count']} exact public sources / no placeholders"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
