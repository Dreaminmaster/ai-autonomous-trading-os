#!/usr/bin/env python3
"""Build a self-contained, hash-complete C6A final evidence directory.

Packaging performs no economic calculation.  It copies and verifies the exact
public raw objects, canonical primitives, source snapshots, production results,
and independent finalizer report, then emits a complete outer manifest.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
from pathlib import Path
from typing import Any, Mapping

from atos.c6a_contract import C6AError
from atos.c6a_evidence import build_manifest, manifest_payload, sha256_file, write_json_atomic

IMPL = Path(__file__).resolve().parents[1]
DEFAULT_DOWNLOAD_REPORT = IMPL / "freqtrade_data/c6a_runtime/c6a_download_report.json"
DEFAULT_PREPARE_REPORT = IMPL / "freqtrade_data/c6a_runtime/c6a_prepare_report.json"
DEFAULT_SOURCE_INVENTORY = IMPL / "freqtrade_data/c6a_runtime/c6a_source_inventory.json"
DEFAULT_SOURCE_SNAPSHOT = IMPL / "freqtrade_data/c6a_source_snapshot"
DEFAULT_RESULTS = IMPL / "freqtrade_data/c6a_results"
DEFAULT_FINALIZER = IMPL / "freqtrade_data/c6a_runtime/c6a_final_evidence.json"
DEFAULT_OUTPUT = IMPL / "freqtrade_data/c6a_final_evidence"
SAFE_COMPONENT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,199}$")
SAFE_SUFFIX_RE = re.compile(r"^\.[A-Za-z0-9]{1,10}$")


class C6APackError(RuntimeError):
    pass


def _read_object(path: Path, label: str) -> Mapping[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise C6APackError(f"unable to load {label}: {exc}") from exc
    if not isinstance(payload, Mapping):
        raise C6APackError(f"{label} must be a JSON object")
    return payload


def _safe_component(value: Any, label: str) -> str:
    result = str(value)
    if (
        not SAFE_COMPONENT_RE.fullmatch(result)
        or result in {".", ".."}
        or "/" in result
        or "\\" in result
    ):
        raise C6APackError(f"unsafe {label}: {result!r}")
    return result


def _safe_suffix(path: Path) -> str:
    suffix = path.suffix
    return suffix if SAFE_SUFFIX_RE.fullmatch(suffix) else ".bin"


def _contained_destination(root: Path, *components: str) -> Path:
    destination = root.joinpath(*components)
    resolved_root = root.resolve()
    resolved_destination = destination.resolve()
    try:
        resolved_destination.relative_to(resolved_root)
    except ValueError as exc:
        raise C6APackError(f"evidence destination escapes package root: {destination}") from exc
    return destination


def _copy_verified_file(
    source: Path,
    destination: Path,
    *,
    package_root: Path,
    expected_sha256: str,
    expected_size: int,
) -> dict[str, Any]:
    if not source.is_file() or source.is_symlink():
        raise C6APackError(f"evidence source missing or unsafe: {source}")
    try:
        destination.resolve().relative_to(package_root.resolve())
    except ValueError as exc:
        raise C6APackError(f"evidence destination escapes package root: {destination}") from exc
    if destination.exists():
        raise C6APackError(f"duplicate evidence destination: {destination}")
    if source.stat().st_size != expected_size or sha256_file(source) != expected_sha256:
        raise C6APackError(f"evidence source hash/size mismatch: {source}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, destination)
    if destination.stat().st_size != expected_size or sha256_file(destination) != expected_sha256:
        raise C6APackError(f"copied evidence hash/size mismatch: {destination}")
    return {
        "path": destination.relative_to(package_root).as_posix(),
        "size": expected_size,
        "sha256": expected_sha256,
        "status": "PASS",
    }


def _copy_tree(source: Path, destination: Path, *, package_root: Path) -> None:
    if not source.is_dir() or source.is_symlink():
        raise C6APackError(f"evidence tree missing or unsafe: {source}")
    try:
        destination.resolve().relative_to(package_root.resolve())
    except ValueError as exc:
        raise C6APackError(f"evidence tree destination escapes package root: {destination}") from exc
    if destination.exists():
        raise C6APackError(f"refusing to overwrite evidence tree: {destination}")
    if any(path.is_symlink() for path in source.rglob("*")):
        raise C6APackError(f"source evidence tree contains symlink: {source}")
    shutil.copytree(source, destination, symlinks=False)
    if any(path.is_symlink() for path in destination.rglob("*")):
        raise C6APackError(f"copied evidence tree contains symlink: {destination}")


def pack(
    *,
    download_report_path: Path,
    prepare_report_path: Path,
    source_inventory_path: Path,
    source_snapshot_path: Path,
    results_path: Path,
    finalizer_path: Path,
    output_path: Path,
) -> dict[str, Any]:
    download = _read_object(download_report_path, "C6A download report")
    prepare = _read_object(prepare_report_path, "C6A prepare report")
    inventory = _read_object(source_inventory_path, "C6A source inventory")
    finalizer = _read_object(finalizer_path, "C6A finalizer report")
    if any(payload.get("status") != "PASS" for payload in (download, prepare, inventory, finalizer)):
        raise C6APackError("all C6A prerequisite reports must be PASS")
    source_sha = str(finalizer.get("source_head_sha", ""))
    if inventory.get("source_head_sha") != source_sha:
        raise C6APackError("source inventory/finalizer SHA mismatch")
    guard = download.get("program_guard")
    if not isinstance(guard, Mapping) or guard.get("source_head_sha") != source_sha:
        raise C6APackError("download program-guard/source SHA mismatch")
    if (
        finalizer.get("cell_check_count") != 60
        or finalizer.get("aggregate_check_count") != 12
        or finalizer.get("weekly_row_count") != 1560
        or finalizer.get("decision_row_count") != 780
    ):
        raise C6APackError("C6A finalizer evidence counts are incomplete")
    if output_path.exists():
        raise C6APackError(f"refusing to overwrite final evidence: {output_path}")
    staging = output_path.with_name(output_path.name + ".staging")
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True)
    try:
        reports = _contained_destination(staging, "reports")
        reports.mkdir()
        for source, name in (
            (download_report_path, "download_report.json"),
            (prepare_report_path, "prepare_report.json"),
            (source_inventory_path, "source_inventory.json"),
            (finalizer_path, "independent_finalizer.json"),
        ):
            destination = _contained_destination(staging, "reports", name)
            if not source.is_file() or source.is_symlink():
                raise C6APackError(f"report source missing or unsafe: {source}")
            shutil.copyfile(source, destination)
        _copy_tree(
            source_snapshot_path,
            _contained_destination(staging, "source_snapshot"),
            package_root=staging,
        )
        _copy_tree(
            results_path,
            _contained_destination(staging, "production_results"),
            package_root=staging,
        )

        raw_copies = []
        raw_rows = download.get("sources")
        if not isinstance(raw_rows, list) or not raw_rows:
            raise C6APackError("C6A download report raw source list missing")
        seen_raw_names: set[str] = set()
        for row in raw_rows:
            if not isinstance(row, Mapping):
                raise C6APackError("C6A download source row is invalid")
            source_id = _safe_component(row.get("source_id", ""), "source_id")
            source = Path(str(row.get("path", "")))
            filename = f"{source_id}{_safe_suffix(source)}"
            if filename in seen_raw_names:
                raise C6APackError(f"duplicate raw evidence filename: {filename}")
            seen_raw_names.add(filename)
            destination = _contained_destination(staging, "public_raw", filename)
            raw_copies.append(
                _copy_verified_file(
                    source,
                    destination,
                    package_root=staging,
                    expected_sha256=str(row.get("sha256", "")),
                    expected_size=int(row.get("size", -1)),
                )
            )

        canonical_copies = []
        canonical_rows = prepare.get("outputs")
        if not isinstance(canonical_rows, list) or not canonical_rows:
            raise C6APackError("C6A prepare report canonical output list missing")
        seen_canonical: set[tuple[str, str]] = set()
        for row in canonical_rows:
            if not isinstance(row, Mapping):
                raise C6APackError("C6A canonical output row is invalid")
            kind = _safe_component(row.get("kind", ""), "canonical kind")
            instrument = _safe_component(
                row.get("instrument", ""), "canonical instrument"
            )
            key = (kind, instrument)
            if key in seen_canonical:
                raise C6APackError(f"duplicate canonical evidence destination: {key}")
            seen_canonical.add(key)
            source = Path(str(row.get("path", "")))
            destination = _contained_destination(
                staging, "canonical", kind, f"{instrument}.jsonl"
            )
            canonical_copies.append(
                _copy_verified_file(
                    source,
                    destination,
                    package_root=staging,
                    expected_sha256=str(row.get("sha256", "")),
                    expected_size=int(row.get("size", -1)),
                )
            )
        package_summary = {
            "schema_version": 1,
            "stage": "C6A",
            "status": "PASS",
            "source_head_sha": source_sha,
            "economic_result": finalizer.get("economic_result"),
            "selected_policy": finalizer.get("selected_policy"),
            "public_raw_object_count": len(raw_copies),
            "canonical_object_count": len(canonical_copies),
            "source_snapshot_file_count": inventory.get("snapshot_file_count"),
            "result_cell_count": finalizer.get("cell_check_count"),
            "aggregate_count": finalizer.get("aggregate_check_count"),
            "weekly_row_count": finalizer.get("weekly_row_count"),
            "decision_row_count": finalizer.get("decision_row_count"),
            "confirmation_opened": False,
            "c6b_state": "C6B_CLOSED",
            "c5b_state": "C5B_CLOSED_AND_UNTOUCHED",
            "holdout_state": "HOLDOUT_CLOSED",
            "paper_state": "PAPER_CLOSED",
            "shadow_state": "SHADOW_CLOSED",
            "live": "FORBIDDEN",
        }
        write_json_atomic(staging / "package_summary.json", package_summary)
        entries = build_manifest(staging)
        write_json_atomic(staging / "manifest.json", manifest_payload(entries))
        staging.replace(output_path)
        return {
            **package_summary,
            "manifest_entry_count": len(entries),
            "output_path": str(output_path),
        }
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--download-report", type=Path, default=DEFAULT_DOWNLOAD_REPORT)
    parser.add_argument("--prepare-report", type=Path, default=DEFAULT_PREPARE_REPORT)
    parser.add_argument("--source-inventory", type=Path, default=DEFAULT_SOURCE_INVENTORY)
    parser.add_argument("--source-snapshot", type=Path, default=DEFAULT_SOURCE_SNAPSHOT)
    parser.add_argument("--results", type=Path, default=DEFAULT_RESULTS)
    parser.add_argument("--finalizer", type=Path, default=DEFAULT_FINALIZER)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args(argv)
    try:
        summary = pack(
            download_report_path=args.download_report,
            prepare_report_path=args.prepare_report,
            source_inventory_path=args.source_inventory,
            source_snapshot_path=args.source_snapshot,
            results_path=args.results,
            finalizer_path=args.finalizer,
            output_path=args.output,
        )
    except C6AError as exc:
        raise C6APackError(str(exc)) from exc
    print(
        "C6A final evidence package PASS: "
        f"{summary['manifest_entry_count']} manifest entries / "
        f"{summary['economic_result']} / selected={summary['selected_policy']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
