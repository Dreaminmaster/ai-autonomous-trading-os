#!/usr/bin/env python3
"""Final authoritative C6A public capture entrypoint.

Exact behavior:
- verify the merged program authority and exact economic-source SHA before I/O;
- refuse all known OKX credential environment variables;
- capture trade/mark candles through exact paginated public endpoints while
  retaining every raw response byte and request URL;
- capture funding/metadata evidence only as exact official single objects;
- atomically publish raw objects, immutable source manifest, and download report;
- remove every partial path on any failure;
- perform no signal, portfolio, accounting, gate, or economic calculation.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import time
from pathlib import Path
from typing import Any, Mapping

from atos.c6a_contract import C6AError
from atos.c6a_source_plan import validate_source_plan
from atos.c6a_sources import validate_source_manifest
from scripts import c6a_capture_public_api as api_schema
from scripts import c6a_capture_public_api_authoritative as api_capture
from scripts import c6a_capture_public_data as object_capture

IMPL = Path(__file__).resolve().parents[1]
DEFAULT_RAW = IMPL / "freqtrade_data/c6a_raw"
DEFAULT_MANIFEST = IMPL / "freqtrade_data/c6a_runtime/c6a_source_manifest.json"
DEFAULT_REPORT = IMPL / "freqtrade_data/c6a_runtime/c6a_download_report.json"


class C6AAuthoritativeCaptureError(RuntimeError):
    pass


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    temporary.replace(path)


def capture(
    *,
    plan: Mapping[str, Any],
    raw_dir: Path,
    manifest_path: Path,
    report_path: Path,
    source_sha: str,
    object_opener=object_capture._open_url,
    api_network_opener=api_schema._open,
    api_sleep=time.sleep,
) -> dict[str, Any]:
    object_capture._assert_public_environment()
    authority = object_capture._verify_program_authority(source_sha)
    try:
        entries = validate_source_plan(plan)
    except C6AError as exc:
        raise C6AAuthoritativeCaptureError(str(exc)) from exc
    rows = plan.get("sources")
    if not isinstance(rows, list):
        raise C6AAuthoritativeCaptureError("C6A source-plan rows missing")
    by_id = {
        str(row.get("source_id")): row
        for row in rows
        if isinstance(row, Mapping)
    }
    if set(by_id) != {entry.source_id for entry in entries} or len(by_id) != len(rows):
        raise C6AAuthoritativeCaptureError("C6A source-plan ID mapping mismatch")
    if raw_dir.exists() or manifest_path.exists() or report_path.exists():
        raise C6AAuthoritativeCaptureError(
            "refusing to overwrite an existing C6A public capture"
        )
    staging = raw_dir.with_name(raw_dir.name + ".staging")
    shutil.rmtree(staging, ignore_errors=True)
    manifest_rows: list[dict[str, Any]] = []
    report_rows: list[dict[str, Any]] = []
    try:
        for entry in entries:
            row = by_id[entry.source_id]
            mode = str(row.get("request_mode", ""))
            if mode == "PAGINATED_PUBLIC_API":
                if entry.kind not in {
                    "spot_trade_candles",
                    "swap_trade_candles",
                    "swap_mark_candles",
                }:
                    raise C6AAuthoritativeCaptureError(
                        f"paginated public API mode is invalid for {entry.kind}"
                    )
                api_plan = api_schema.CandleApiPlan.from_mapping(
                    {**row, "endpoint": entry.url}
                )
                report_row = api_capture.capture_series_with_raw_transcript(
                    api_plan,
                    destination=staging / f"{entry.source_id}.jsonl",
                    transcript_path=staging
                    / "api_raw_transcripts"
                    / f"{entry.source_id}.jsonl",
                    network_opener=api_network_opener,
                    sleep=api_sleep,
                )
                manifest_row = entry.manifest_fields(
                    sha256=str(report_row["sha256"])
                )
            elif mode == "SINGLE_OBJECT":
                if entry.kind in {
                    "spot_trade_candles",
                    "swap_trade_candles",
                    "swap_mark_candles",
                }:
                    raise C6AAuthoritativeCaptureError(
                        f"candle source must use PAGINATED_PUBLIC_API: {entry.source_id}"
                    )
                manifest_row, report_row = object_capture.capture_entry(
                    entry,
                    staging_dir=staging,
                    opener=object_opener,
                )
            else:
                raise C6AAuthoritativeCaptureError(
                    f"invalid request_mode for {entry.source_id}: {mode!r}"
                )
            manifest_rows.append(manifest_row)
            report_rows.append(report_row)

        immutable_manifest = {
            "schema_version": 1,
            "stage": "C6A",
            "authenticated": False,
            "economic_boundary_exclusive": "2025-12-29T00:00:00Z",
            "sources": manifest_rows,
        }
        validate_source_manifest(immutable_manifest)
        staging.replace(raw_dir)
        for row in report_rows:
            original = Path(str(row["path"]))
            row["path"] = str(raw_dir / original.name)
            transcript = row.get("raw_transcript_path")
            if transcript:
                transcript_path = Path(str(transcript))
                row["raw_transcript_path"] = str(
                    raw_dir / "api_raw_transcripts" / transcript_path.name
                )
        report = {
            "schema_version": 1,
            "stage": "C6A",
            "status": "PASS",
            "authenticated": False,
            "program_guard": authority,
            "source_plan_sha256": hashlib.sha256(
                json.dumps(plan, sort_keys=True, separators=(",", ":")).encode(
                    "utf-8"
                )
            ).hexdigest(),
            "source_count": len(report_rows),
            "api_raw_response_transcripts_retained": all(
                row.get("kind")
                not in {
                    "spot_trade_candles",
                    "swap_trade_candles",
                    "swap_mark_candles",
                }
                or row.get("raw_response_bytes_retained") is True
                for row in report_rows
            ),
            "sources": report_rows,
            "economic_result_run": False,
            "c6b_state": "C6B_CLOSED",
            "c5b_state": "C5B_CLOSED_AND_UNTOUCHED",
            "holdout_state": "HOLDOUT_CLOSED",
            "paper_state": "PAPER_CLOSED",
            "shadow_state": "SHADOW_CLOSED",
            "live": "FORBIDDEN",
        }
        _write_json(manifest_path, immutable_manifest)
        _write_json(report_path, report)
        return report
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        shutil.rmtree(raw_dir, ignore_errors=True)
        manifest_path.unlink(missing_ok=True)
        report_path.unlink(missing_ok=True)
        raise


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--raw-dir", type=Path, default=DEFAULT_RAW)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    args = parser.parse_args(argv)
    try:
        plan = json.loads(args.plan.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise C6AAuthoritativeCaptureError(f"invalid C6A source plan: {exc}") from exc
    if not isinstance(plan, Mapping):
        raise C6AAuthoritativeCaptureError("C6A source plan must be an object")
    authority = object_capture._verify_program_authority()
    report = capture(
        plan=plan,
        raw_dir=args.raw_dir,
        manifest_path=args.manifest,
        report_path=args.report,
        source_sha=str(authority["source_head_sha"]),
    )
    print(
        "C6A authoritative public capture PASS: "
        f"{report['source_count']} sources / raw API transcripts retained"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
