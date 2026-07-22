#!/usr/bin/env python3
"""Final authoritative C6A evidence packager with raw API transcripts.

Extends the acquisition-bound authoritative package by copying and verifying
every exact paginated API response transcript.  The outer manifest is rebuilt
after transcript insertion, so no raw market response used to construct the
hourly series is absent from the final evidence.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import re
import shutil
from pathlib import Path
from typing import Any, Mapping

from atos.c6a_evidence import build_manifest, manifest_payload, sha256_file, write_json_atomic
from scripts import c6a_pack_authoritative_evidence as base

IMPL = Path(__file__).resolve().parents[1]
DEFAULT_PLAN = base.DEFAULT_PLAN
DEFAULT_SOURCE_MANIFEST = base.DEFAULT_SOURCE_MANIFEST
DEFAULT_DOWNLOAD_REPORT = base.DEFAULT_DOWNLOAD_REPORT
DEFAULT_PREPARE_REPORT = base.DEFAULT_PREPARE_REPORT
DEFAULT_SOURCE_INVENTORY = base.DEFAULT_SOURCE_INVENTORY
DEFAULT_SOURCE_SNAPSHOT = base.DEFAULT_SOURCE_SNAPSHOT
DEFAULT_RESULTS = base.DEFAULT_RESULTS
DEFAULT_FINALIZER = base.DEFAULT_FINALIZER
DEFAULT_OUTPUT = base.DEFAULT_OUTPUT
SAFE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,199}$")


class C6AAuthoritativePackV2Error(RuntimeError):
    pass


def _read(path: Path, label: str) -> Mapping[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise C6AAuthoritativePackV2Error(f"unable to load {label}: {exc}") from exc
    if not isinstance(payload, Mapping):
        raise C6AAuthoritativePackV2Error(f"{label} must be an object")
    return payload


def verify_raw_transcript(row: Mapping[str, Any]) -> dict[str, Any]:
    source_id = str(row.get("source_id", ""))
    if not SAFE_ID_RE.fullmatch(source_id) or source_id in {".", ".."}:
        raise C6AAuthoritativePackV2Error(
            f"unsafe API transcript source ID: {source_id!r}"
        )
    path = Path(str(row.get("raw_transcript_path", "")))
    if not path.is_file() or path.is_symlink():
        raise C6AAuthoritativePackV2Error(
            f"raw API transcript missing or unsafe: {source_id}"
        )
    expected_size = int(row.get("raw_transcript_size", -1))
    expected_hash = str(row.get("raw_transcript_sha256", ""))
    expected_pages = int(row.get("raw_transcript_page_count", -1))
    if path.stat().st_size != expected_size or sha256_file(path) != expected_hash:
        raise C6AAuthoritativePackV2Error(
            f"raw API transcript hash/size mismatch: {source_id}"
        )
    count = 0
    try:
        with path.open("r", encoding="utf-8") as handle:
            for number, line in enumerate(handle, start=1):
                if not line.strip():
                    continue
                payload = json.loads(line)
                if not isinstance(payload, Mapping):
                    raise C6AAuthoritativePackV2Error(
                        f"raw API transcript row is not an object: {source_id}:{number}"
                    )
                encoded = payload.get("response_base64")
                if not isinstance(encoded, str):
                    raise C6AAuthoritativePackV2Error(
                        f"raw API response bytes missing: {source_id}:{number}"
                    )
                try:
                    raw = base64.b64decode(encoded, validate=True)
                except Exception as exc:  # noqa: BLE001 - normalized evidence error
                    raise C6AAuthoritativePackV2Error(
                        f"invalid raw API response base64: {source_id}:{number}"
                    ) from exc
                if (
                    len(raw) != int(payload.get("response_size", -1))
                    or hashlib.sha256(raw).hexdigest()
                    != payload.get("response_sha256")
                ):
                    raise C6AAuthoritativePackV2Error(
                        f"raw API response hash/size mismatch: {source_id}:{number}"
                    )
                url = str(payload.get("request_url", ""))
                if not url.startswith("https://www.okx.com/api/v5/market/"):
                    raise C6AAuthoritativePackV2Error(
                        f"raw API transcript URL drift: {source_id}:{number}"
                    )
                count += 1
    except json.JSONDecodeError as exc:
        raise C6AAuthoritativePackV2Error(
            f"invalid raw API transcript JSON: {source_id}: {exc}"
        ) from exc
    if count != expected_pages or count <= 0:
        raise C6AAuthoritativePackV2Error(
            f"raw API transcript page-count mismatch: {source_id}"
        )
    return {
        "source_id": source_id,
        "path": str(path),
        "size": expected_size,
        "sha256": expected_hash,
        "page_count": count,
        "status": "PASS",
    }


def pack_v2(
    *,
    plan_path: Path,
    source_manifest_path: Path,
    download_report_path: Path,
    prepare_report_path: Path,
    source_inventory_path: Path,
    source_snapshot_path: Path,
    results_path: Path,
    finalizer_path: Path,
    output_path: Path,
) -> dict[str, Any]:
    if output_path.exists():
        raise C6AAuthoritativePackV2Error(
            f"refusing to overwrite authoritative evidence V2: {output_path}"
        )
    download = _read(download_report_path, "C6A download report")
    if download.get("api_raw_response_transcripts_retained") is not True:
        raise C6AAuthoritativePackV2Error(
            "download report does not certify retained API raw responses"
        )
    sources = download.get("sources")
    if not isinstance(sources, list):
        raise C6AAuthoritativePackV2Error("download source list missing")
    transcript_records = [
        verify_raw_transcript(row)
        for row in sources
        if isinstance(row, Mapping) and row.get("raw_response_bytes_retained") is True
    ]
    expected_api_count = sum(
        1
        for row in sources
        if isinstance(row, Mapping)
        and row.get("kind")
        in {"spot_trade_candles", "swap_trade_candles", "swap_mark_candles"}
    )
    if len(transcript_records) != expected_api_count or expected_api_count != 6:
        raise C6AAuthoritativePackV2Error(
            "expected six retained C6A candle API transcripts"
        )
    intermediate = output_path.with_name(output_path.name + ".v1")
    staging = output_path.with_name(output_path.name + ".staging")
    shutil.rmtree(intermediate, ignore_errors=True)
    shutil.rmtree(staging, ignore_errors=True)
    try:
        base_report = base.pack_authoritative(
            plan_path=plan_path,
            source_manifest_path=source_manifest_path,
            download_report_path=download_report_path,
            prepare_report_path=prepare_report_path,
            source_inventory_path=source_inventory_path,
            source_snapshot_path=source_snapshot_path,
            results_path=results_path,
            finalizer_path=finalizer_path,
            output_path=intermediate,
        )
        shutil.copytree(intermediate, staging, symlinks=False)
        transcript_dir = staging / "api_raw_transcripts"
        transcript_dir.mkdir()
        for record in transcript_records:
            destination = transcript_dir / f"{record['source_id']}.jsonl"
            if destination.exists():
                raise C6AAuthoritativePackV2Error(
                    f"duplicate transcript destination: {destination.name}"
                )
            shutil.copyfile(Path(record["path"]), destination)
            if (
                destination.stat().st_size != record["size"]
                or sha256_file(destination) != record["sha256"]
            ):
                raise C6AAuthoritativePackV2Error(
                    f"copied raw API transcript mismatch: {record['source_id']}"
                )
        (staging / "manifest.json").unlink(missing_ok=True)
        summary_path = staging / "package_summary.json"
        summary = _read(summary_path, "authoritative package summary")
        updated = {
            **summary,
            "api_raw_response_transcript_count": len(transcript_records),
            "api_raw_response_page_count": sum(
                record["page_count"] for record in transcript_records
            ),
            "all_paginated_api_response_bytes_retained": True,
        }
        write_json_atomic(summary_path, updated)
        entries = build_manifest(staging)
        write_json_atomic(staging / "manifest.json", manifest_payload(entries))
        staging.replace(output_path)
        return {
            **base_report,
            **updated,
            "manifest_entry_count": len(entries),
            "output_path": str(output_path),
        }
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        shutil.rmtree(output_path, ignore_errors=True)
        raise
    finally:
        shutil.rmtree(intermediate, ignore_errors=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", type=Path, default=DEFAULT_PLAN)
    parser.add_argument(
        "--source-manifest", type=Path, default=DEFAULT_SOURCE_MANIFEST
    )
    parser.add_argument(
        "--download-report", type=Path, default=DEFAULT_DOWNLOAD_REPORT
    )
    parser.add_argument("--prepare-report", type=Path, default=DEFAULT_PREPARE_REPORT)
    parser.add_argument(
        "--source-inventory", type=Path, default=DEFAULT_SOURCE_INVENTORY
    )
    parser.add_argument("--source-snapshot", type=Path, default=DEFAULT_SOURCE_SNAPSHOT)
    parser.add_argument("--results", type=Path, default=DEFAULT_RESULTS)
    parser.add_argument("--finalizer", type=Path, default=DEFAULT_FINALIZER)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args(argv)
    report = pack_v2(
        plan_path=args.plan,
        source_manifest_path=args.source_manifest,
        download_report_path=args.download_report,
        prepare_report_path=args.prepare_report,
        source_inventory_path=args.source_inventory,
        source_snapshot_path=args.source_snapshot,
        results_path=args.results,
        finalizer_path=args.finalizer,
        output_path=args.output,
    )
    print(
        "C6A authoritative evidence V2 PASS: "
        f"{report['api_raw_response_transcript_count']} API transcripts / "
        f"{report['manifest_entry_count']} manifest files"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
