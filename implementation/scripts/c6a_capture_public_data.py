#!/usr/bin/env python3
"""Guarded first capture of exact official public C6A objects.

This step resolves the first-download hash bootstrap without weakening later
immutability.  It verifies program authority before network access, refuses any
credential-bearing environment, downloads each frozen official OKX URL once to
an isolated directory, records SHA-256 and size, emits the immutable source
manifest, and writes a download report compatible with canonical preparation.
It performs no economic calculation.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import urllib.request
from pathlib import Path
from typing import Any, Mapping

from atos.c6a_contract import C6AError
from atos.c6a_source_plan import PublicSourcePlanEntry, validate_source_plan
from atos.c6a_sources import validate_source_manifest
from scripts import c6a_program_guard

IMPL = Path(__file__).resolve().parents[1]
DEFAULT_RAW = IMPL / "freqtrade_data/c6a_raw"
DEFAULT_MANIFEST = IMPL / "freqtrade_data/c6a_runtime/c6a_source_manifest.json"
DEFAULT_REPORT = IMPL / "freqtrade_data/c6a_runtime/c6a_download_report.json"
PROHIBITED_CREDENTIAL_ENV = (
    "OKX_API_KEY",
    "OKX_SECRET_KEY",
    "OKX_API_SECRET",
    "OKX_PASSPHRASE",
)
SAFE_NAME_RE = re.compile(r"[^A-Za-z0-9._-]+")
MAX_OBJECT_BYTES = 4 * 1024 * 1024 * 1024


class C6ACaptureError(RuntimeError):
    pass


def _assert_public_environment() -> None:
    present = [name for name in PROHIBITED_CREDENTIAL_ENV if os.environ.get(name)]
    if present:
        raise C6ACaptureError(
            f"refusing C6A public capture while credential variables are present: {present}"
        )


def _verify_program_authority(source_sha: str | None = None) -> dict[str, Any]:
    exact_sha = source_sha or c6a_program_guard._exact_sha()
    if not c6a_program_guard.SHA_RE.fullmatch(exact_sha):
        raise C6ACaptureError("C6A source SHA is not exact")
    try:
        config = json.loads(c6a_program_guard.CONFIG_PATH.read_text(encoding="utf-8"))
        if not isinstance(config, Mapping):
            raise C6ACaptureError("C6A configuration must be an object")
        payload = c6a_program_guard.verify_authorities(c6a_program_guard.ROOT, config)
    except (OSError, json.JSONDecodeError, C6AError, c6a_program_guard.C6AProgramGuardError) as exc:
        raise C6ACaptureError(f"C6A program guard failed before public capture: {exc}") from exc
    payload["source_head_sha"] = exact_sha
    payload["verified_before_market_access"] = True
    return payload


def _safe_filename(entry: PublicSourcePlanEntry) -> str:
    suffix = Path(urllib.request.url2pathname(entry.url.split("?", 1)[0])).suffix
    suffix = suffix if re.fullmatch(r"\.[A-Za-z0-9]{1,10}", suffix) else ".bin"
    stem = SAFE_NAME_RE.sub("_", entry.source_id).strip("._")
    if not stem:
        raise C6ACaptureError("source-plan ID does not produce a safe filename")
    return f"{stem}{suffix}"


def _open_url(entry: PublicSourcePlanEntry):
    request = urllib.request.Request(
        entry.url,
        headers={
            "User-Agent": "ai-autonomous-trading-os-c6a-public-capture/1.0",
            "Accept": "*/*",
        },
        method="GET",
    )
    return urllib.request.urlopen(request, timeout=120)  # noqa: S310 - validated official OKX HTTPS


def capture_entry(
    entry: PublicSourcePlanEntry,
    *,
    staging_dir: Path,
    opener=_open_url,
    maximum_bytes: int = MAX_OBJECT_BYTES,
) -> tuple[dict[str, Any], dict[str, Any]]:
    staging_dir.mkdir(parents=True, exist_ok=True)
    destination = staging_dir / _safe_filename(entry)
    if destination.exists():
        raise C6ACaptureError(f"duplicate captured destination: {destination.name}")
    temporary = destination.with_suffix(destination.suffix + ".part")
    digest = hashlib.sha256()
    size = 0
    try:
        with opener(entry) as response, temporary.open("wb") as handle:
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                if not isinstance(chunk, (bytes, bytearray)):
                    raise C6ACaptureError("public source returned non-byte content")
                size += len(chunk)
                if size > maximum_bytes:
                    raise C6ACaptureError(
                        f"public object exceeds maximum size: {entry.source_id}"
                    )
                digest.update(chunk)
                handle.write(chunk)
        if size == 0:
            raise C6ACaptureError(f"public object is empty: {entry.source_id}")
        temporary.replace(destination)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    observed_hash = digest.hexdigest()
    manifest_row = entry.manifest_fields(sha256=observed_hash)
    report_row = {
        "source_id": entry.source_id,
        "kind": entry.kind,
        "instrument": entry.instrument,
        "url": entry.url,
        "path": str(destination),
        "size": size,
        "sha256": observed_hash,
        "coverage_start": entry.coverage_start.isoformat(),
        "coverage_end_exclusive": entry.coverage_end_exclusive.isoformat(),
        "status": "PASS",
    }
    return manifest_row, report_row


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
    opener=_open_url,
) -> dict[str, Any]:
    _assert_public_environment()
    authority = _verify_program_authority(source_sha)
    try:
        entries = validate_source_plan(plan)
    except C6AError as exc:
        raise C6ACaptureError(str(exc)) from exc
    if raw_dir.exists() or manifest_path.exists() or report_path.exists():
        raise C6ACaptureError("refusing to overwrite an existing C6A capture")
    staging = raw_dir.with_name(raw_dir.name + ".staging")
    if staging.exists():
        shutil.rmtree(staging)
    manifest_rows: list[dict[str, Any]] = []
    report_rows: list[dict[str, Any]] = []
    try:
        for entry in entries:
            manifest_row, report_row = capture_entry(
                entry,
                staging_dir=staging,
                opener=opener,
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
        # Paths were recorded while staging.  Rebind only after the atomic
        # directory rename and before publishing the report.
        for row in report_rows:
            row["path"] = str(raw_dir / Path(str(row["path"])).name)
        report = {
            "schema_version": 1,
            "stage": "C6A",
            "status": "PASS",
            "authenticated": False,
            "program_guard": authority,
            "source_plan_sha256": hashlib.sha256(
                json.dumps(plan, sort_keys=True, separators=(",", ":")).encode("utf-8")
            ).hexdigest(),
            "source_count": len(report_rows),
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
        if raw_dir.exists() and not manifest_path.exists() and not report_path.exists():
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
        raise C6ACaptureError(f"invalid C6A source plan: {exc}") from exc
    if not isinstance(plan, Mapping):
        raise C6ACaptureError("C6A source plan must be an object")
    report = capture(
        plan=plan,
        raw_dir=args.raw_dir,
        manifest_path=args.manifest,
        report_path=args.report,
        source_sha=_verify_program_authority()["source_head_sha"],
    )
    print(
        "C6A first public capture PASS: "
        f"{report['source_count']} official objects / immutable SHA-256 manifest emitted"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
