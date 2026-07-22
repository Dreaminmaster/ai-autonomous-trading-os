#!/usr/bin/env python3
"""Build the authoritative self-contained C6A evidence package.

This wrapper extends the base package with the reviewed first-capture source
plan and the immutable SHA-256 source manifest.  It verifies the plan hash
recorded by the download report, validates both acquisition contracts, checks
that every manifest object agrees with the download report, and rebuilds the
outer manifest after adding those files.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from pathlib import Path
from typing import Any, Mapping

from atos.c6a_evidence import build_manifest, manifest_payload, write_json_atomic
from atos.c6a_source_plan import validate_source_plan
from atos.c6a_sources import validate_source_manifest
from scripts import c6a_pack_final_evidence as base

IMPL = Path(__file__).resolve().parents[1]
DEFAULT_PLAN = IMPL / "config/c6a_public_source_plan.json"
DEFAULT_SOURCE_MANIFEST = IMPL / "freqtrade_data/c6a_runtime/c6a_source_manifest.json"
DEFAULT_DOWNLOAD_REPORT = IMPL / "freqtrade_data/c6a_runtime/c6a_download_report.json"
DEFAULT_PREPARE_REPORT = IMPL / "freqtrade_data/c6a_runtime/c6a_prepare_report.json"
DEFAULT_SOURCE_INVENTORY = IMPL / "freqtrade_data/c6a_runtime/c6a_source_inventory.json"
DEFAULT_SOURCE_SNAPSHOT = IMPL / "freqtrade_data/c6a_source_snapshot"
DEFAULT_RESULTS = IMPL / "freqtrade_data/c6a_results"
DEFAULT_FINALIZER = IMPL / "freqtrade_data/c6a_runtime/c6a_strict_final_evidence.json"
DEFAULT_OUTPUT = IMPL / "freqtrade_data/c6a_final_evidence"


class C6AAuthoritativePackError(RuntimeError):
    pass


def _read(path: Path, label: str) -> Mapping[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise C6AAuthoritativePackError(f"unable to load {label}: {exc}") from exc
    if not isinstance(payload, Mapping):
        raise C6AAuthoritativePackError(f"{label} must be an object")
    return payload


def _canonical_sha256(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def verify_acquisition_evidence(
    *,
    plan: Mapping[str, Any],
    source_manifest: Mapping[str, Any],
    download_report: Mapping[str, Any],
) -> dict[str, Any]:
    plan_entries = validate_source_plan(plan)
    manifest_entries = validate_source_manifest(source_manifest)
    if download_report.get("status") != "PASS":
        raise C6AAuthoritativePackError("download report is not PASS")
    observed_plan_hash = _canonical_sha256(plan)
    if download_report.get("source_plan_sha256") != observed_plan_hash:
        raise C6AAuthoritativePackError("source-plan/download-report hash mismatch")
    report_rows = download_report.get("sources")
    if not isinstance(report_rows, list):
        raise C6AAuthoritativePackError("download-report source list missing")
    report_by_id = {
        str(row.get("source_id")): row
        for row in report_rows
        if isinstance(row, Mapping)
    }
    manifest_by_id = {entry.source_id: entry for entry in manifest_entries}
    plan_by_id = {entry.source_id: entry for entry in plan_entries}
    if not (
        set(report_by_id) == set(manifest_by_id) == set(plan_by_id)
        and len(report_by_id) == len(report_rows)
    ):
        raise C6AAuthoritativePackError(
            "source plan, immutable manifest, and download-report ID sets differ"
        )
    for source_id, entry in manifest_by_id.items():
        report = report_by_id[source_id]
        planned = plan_by_id[source_id]
        if (
            entry.kind != planned.kind
            or entry.instrument != planned.instrument
            or entry.url != planned.url
            or entry.coverage_start != planned.coverage_start
            or entry.coverage_end_exclusive != planned.coverage_end_exclusive
            or entry.archive_member != planned.archive_member
        ):
            raise C6AAuthoritativePackError(
                f"immutable manifest drift from plan: {source_id}"
            )
        if (
            report.get("status") != "PASS"
            or report.get("sha256") != entry.sha256
            or report.get("url") != entry.url
            or report.get("kind") != entry.kind
            or report.get("instrument") != entry.instrument
        ):
            raise C6AAuthoritativePackError(
                f"download report drift from immutable manifest: {source_id}"
            )
    return {
        "schema_version": 1,
        "stage": "C6A",
        "status": "PASS",
        "source_plan_sha256": observed_plan_hash,
        "source_count": len(plan_entries),
        "id_sets_equal": True,
        "immutable_manifest_matches_plan": True,
        "download_report_matches_manifest": True,
        "authenticated": False,
        "economic_result_run": False,
        "c6b_state": "C6B_CLOSED",
        "c5b_state": "C5B_CLOSED_AND_UNTOUCHED",
        "live": "FORBIDDEN",
    }


def pack_authoritative(
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
    plan = _read(plan_path, "C6A source plan")
    source_manifest = _read(source_manifest_path, "C6A immutable source manifest")
    download_report = _read(download_report_path, "C6A download report")
    acquisition = verify_acquisition_evidence(
        plan=plan,
        source_manifest=source_manifest,
        download_report=download_report,
    )
    if output_path.exists():
        raise C6AAuthoritativePackError(
            f"refusing to overwrite authoritative evidence: {output_path}"
        )
    intermediate = output_path.with_name(output_path.name + ".base")
    staging = output_path.with_name(output_path.name + ".staging")
    shutil.rmtree(intermediate, ignore_errors=True)
    shutil.rmtree(staging, ignore_errors=True)
    try:
        base_summary = base.pack(
            download_report_path=download_report_path,
            prepare_report_path=prepare_report_path,
            source_inventory_path=source_inventory_path,
            source_snapshot_path=source_snapshot_path,
            results_path=results_path,
            finalizer_path=finalizer_path,
            output_path=intermediate,
        )
        shutil.copytree(intermediate, staging, symlinks=False)
        acquisition_dir = staging / "acquisition"
        acquisition_dir.mkdir()
        shutil.copyfile(plan_path, acquisition_dir / "source_plan.json")
        shutil.copyfile(
            source_manifest_path, acquisition_dir / "immutable_source_manifest.json"
        )
        write_json_atomic(
            acquisition_dir / "acquisition_verification.json", acquisition
        )
        (staging / "manifest.json").unlink(missing_ok=True)
        summary_path = staging / "package_summary.json"
        summary = _read(summary_path, "base package summary")
        updated_summary = {
            **summary,
            "authoritative_acquisition_evidence": True,
            "source_plan_sha256": acquisition["source_plan_sha256"],
            "source_plan_entry_count": acquisition["source_count"],
            "immutable_source_manifest_retained": True,
        }
        write_json_atomic(summary_path, updated_summary)
        entries = build_manifest(staging)
        write_json_atomic(staging / "manifest.json", manifest_payload(entries))
        staging.replace(output_path)
        return {
            **base_summary,
            **updated_summary,
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
    report = pack_authoritative(
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
        "C6A authoritative evidence package PASS: "
        f"{report['manifest_entry_count']} files / acquisition plan and immutable "
        "manifest retained"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
