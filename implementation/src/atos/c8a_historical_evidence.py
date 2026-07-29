"""Immutable C8A H1-H5 data-custody and economic evidence package."""

from __future__ import annotations

import hashlib
import json
import os
import re
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from atos.c8a_contract import INSTRUMENTS
from atos.c8a_historical_independent import (
    review_historical_window,
    review_pooled_summary,
)
from atos.c8a_historical_replay import evaluate_historical_window, summarize_h1_h5
from atos.c8a_historical_run_guard import (
    C8AHistoricalRunGuardError,
    validate_checkout_binding,
)
from atos.c8a_historical_schedule import HISTORICAL_WINDOWS, h1_h5_capture_plan

EXACT_SHA = re.compile(r"[0-9a-f]{40}")
SAFE_RUN_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,159}")
DESIGN_PATH = Path(
    "docs/architecture/phase-c/c8a-short-horizon-time-series-momentum/"
    "C8A_SHORT_HORIZON_TIME_SERIES_MOMENTUM_CONTRACT_V1.md"
)
WORKFLOW_PATH = Path(".github/workflows/freqtrade-validation.yml")


class C8AHistoricalEvidenceError(RuntimeError):
    """Raised when custody or final evidence cannot be proven complete."""


def _canonical_bytes(value: Any) -> bytes:
    return (
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        + "\n"
    ).encode()


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise C8AHistoricalEvidenceError(f"invalid retained JSON: {path}") from exc


def _fsync_directory(path: Path) -> None:
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


class C8AEvidencePackage:
    """Exclusive, atomic, no-overwrite evidence writer."""

    def __init__(self, root: Path):
        self.root = Path(root)
        if self.root.exists():
            raise C8AHistoricalEvidenceError(
                f"evidence package already exists: {self.root}"
            )
        self.root.mkdir(parents=True, mode=0o700)
        _fsync_directory(self.root.parent)
        self._finalized = False

    def write_json(self, relative: str, value: Any) -> None:
        if self._finalized:
            raise C8AHistoricalEvidenceError("evidence package is finalized")
        path = Path(relative)
        if path.is_absolute() or not path.parts or ".." in path.parts:
            raise C8AHistoricalEvidenceError("evidence path escapes package")
        destination = self.root / path
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_name(f".{destination.name}.tmp")
        if destination.exists() or temporary.exists():
            raise C8AHistoricalEvidenceError(
                f"evidence file already exists: {relative}"
            )
        with temporary.open("xb") as handle:
            handle.write(_canonical_bytes(value))
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(temporary, destination)
        except FileExistsError as exc:
            raise C8AHistoricalEvidenceError(
                f"evidence file already exists: {relative}"
            ) from exc
        temporary.unlink()
        _fsync_directory(destination.parent)

    def finalize(self, *, implementation_sha: str) -> dict[str, Any]:
        if not EXACT_SHA.fullmatch(implementation_sha):
            raise C8AHistoricalEvidenceError(
                "evidence implementation SHA must be exact"
            )
        entries = sorted(self.root.rglob("*"))
        if any(path.is_symlink() for path in entries):
            raise C8AHistoricalEvidenceError(
                "evidence package contains a symbolic link"
            )
        files = []
        for path in (item for item in entries if item.is_file()):
            relative = path.relative_to(self.root).as_posix()
            if relative == "manifest.json":
                continue
            data = path.read_bytes()
            files.append(
                {
                    "path": relative,
                    "size": len(data),
                    "sha256": hashlib.sha256(data).hexdigest(),
                }
            )
        if not files:
            raise C8AHistoricalEvidenceError("evidence package contains no files")
        manifest = {
            "schema_version": 1,
            "stage": "C8A_H1_H5_HISTORICAL_EVIDENCE_PACKAGE",
            "implementation_sha": implementation_sha,
            "file_count": len(files),
            "files": files,
            "authenticated": False,
            "contains_account_data": False,
            "contains_order_data": False,
            "paper_side_effect": False,
            "shadow_side_effect": False,
            "live_state": "LIVE_FORBIDDEN",
        }
        self.write_json("manifest.json", manifest)
        self._finalized = True
        return manifest


def verify_capture_package(
    capture_root: Path, *, implementation_sha: str
) -> dict[str, Any]:
    root = Path(capture_root)
    if root.is_symlink() or any(path.is_symlink() for path in root.rglob("*")):
        raise C8AHistoricalEvidenceError("capture package contains a symbolic link")
    manifest = _read_json(root / "manifest.json")
    index = _read_json(root / "capture_index.json")
    binding = _read_json(root / "checkout_binding.json")
    if not isinstance(manifest, Mapping) or not isinstance(index, Mapping):
        raise C8AHistoricalEvidenceError("capture manifest or index is not an object")
    expected_boundary = {
        "authenticated": False,
        "contains_account_data": False,
        "contains_order_data": False,
        "paper_side_effect": False,
        "shadow_side_effect": False,
        "live_state": "LIVE_FORBIDDEN",
    }
    if (
        manifest.get("stage") != "C8A_HISTORICAL_CAPTURE_PACKAGE"
        or index.get("stage") != "C8A_HISTORICAL_CAPTURE"
    ):
        raise C8AHistoricalEvidenceError("capture stage identity drift")
    if any(
        manifest.get(key) != value or index.get(key) != value
        for key, value in expected_boundary.items()
    ):
        raise C8AHistoricalEvidenceError("capture safety boundary drift")
    if (
        manifest.get("implementation_sha") != implementation_sha
        or index.get("implementation_sha") != implementation_sha
    ):
        raise C8AHistoricalEvidenceError("capture implementation SHA mismatch")
    if index.get("capture_plan") != h1_h5_capture_plan():
        raise C8AHistoricalEvidenceError(
            "capture plan is not the frozen C8A H1-H5 plan"
        )
    try:
        validate_checkout_binding(binding, implementation_sha=implementation_sha)
    except C8AHistoricalRunGuardError as exc:
        raise C8AHistoricalEvidenceError(str(exc)) from exc
    declared = manifest.get("files")
    if not isinstance(declared, list) or manifest.get("file_count") != len(declared):
        raise C8AHistoricalEvidenceError("capture manifest inventory is invalid")
    observed = {
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file() and path.name != "manifest.json"
    }
    paths = {str(item.get("path")) for item in declared if isinstance(item, Mapping)}
    if observed != paths or len(paths) != len(declared):
        raise C8AHistoricalEvidenceError("capture manifest path inventory mismatch")
    for item in declared:
        if not isinstance(item, Mapping):
            raise C8AHistoricalEvidenceError("capture manifest entry is invalid")
        data = (root / str(item["path"])).read_bytes()
        if len(data) != item.get("size") or hashlib.sha256(
            data
        ).hexdigest() != item.get("sha256"):
            raise C8AHistoricalEvidenceError(
                f"capture hash mismatch: {item.get('path')}"
            )
    return {
        "capture_manifest_sha256": hashlib.sha256(
            (root / "manifest.json").read_bytes()
        ).hexdigest(),
        "capture_index_sha256": hashlib.sha256(
            (root / "capture_index.json").read_bytes()
        ).hexdigest(),
        "capture_checkout_binding_sha256": hashlib.sha256(
            (root / "checkout_binding.json").read_bytes()
        ).hexdigest(),
        "capture_file_count": len(declared),
        "implementation_sha": implementation_sha,
    }


def _normalized_rows(
    capture_root: Path, series: str
) -> dict[str, list[dict[str, Any]]]:
    output = {}
    for instrument in INSTRUMENTS:
        value = _read_json(capture_root / "normalized" / series / f"{instrument}.json")
        if (
            not isinstance(value, list)
            or not value
            or any(not isinstance(row, dict) for row in value)
        ):
            raise C8AHistoricalEvidenceError(
                f"normalized {series} rows are invalid: {instrument}"
            )
        output[instrument] = value
    return output


def _authority_hashes(repository_root: Path, implementation_sha: str) -> dict[str, Any]:
    root = Path(repository_root)
    files = [
        path
        for path in (root / "implementation" / "src" / "atos").glob("c8a_*.py")
        if path.is_file()
    ]
    files.extend(
        path
        for path in (root / "implementation" / "scripts").glob("c8a_*.py")
        if path.is_file()
    )
    files.extend((root / DESIGN_PATH, root / WORKFLOW_PATH))
    if any(not path.is_file() for path in files):
        raise C8AHistoricalEvidenceError("authority source inventory is incomplete")
    inventory = []
    for path in sorted(files):
        data = path.read_bytes()
        inventory.append(
            {
                "path": path.relative_to(root).as_posix(),
                "size": len(data),
                "sha256": hashlib.sha256(data).hexdigest(),
            }
        )
    return {
        "implementation_sha": implementation_sha,
        "design_path": DESIGN_PATH.as_posix(),
        "design_sha256": hashlib.sha256((root / DESIGN_PATH).read_bytes()).hexdigest(),
        "workflow_path": WORKFLOW_PATH.as_posix(),
        "workflow_sha256": hashlib.sha256(
            (root / WORKFLOW_PATH).read_bytes()
        ).hexdigest(),
        "source_inventory": inventory,
        "source_inventory_sha256": hashlib.sha256(
            _canonical_bytes(inventory)
        ).hexdigest(),
    }


def build_h1_h5_evidence_package(
    output_root: Path,
    *,
    capture_root: Path,
    repository_root: Path,
    implementation_sha: str,
    authoritative_run_id: str,
    evaluation_checkout_binding: Mapping[str, Any],
    evaluated_at: datetime | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    if not EXACT_SHA.fullmatch(implementation_sha) or not SAFE_RUN_ID.fullmatch(
        authoritative_run_id
    ):
        raise C8AHistoricalEvidenceError(
            "implementation SHA or authoritative run ID is invalid"
        )
    try:
        evaluation_binding = validate_checkout_binding(
            evaluation_checkout_binding, implementation_sha=implementation_sha
        )
    except C8AHistoricalRunGuardError as exc:
        raise C8AHistoricalEvidenceError(str(exc)) from exc
    stamp = evaluated_at or datetime.now(tz=UTC)
    if stamp.tzinfo is None:
        raise C8AHistoricalEvidenceError("evaluation timestamp must be timezone-aware")
    capture_reference = verify_capture_package(
        capture_root, implementation_sha=implementation_sha
    )
    authority_hashes = _authority_hashes(Path(repository_root), implementation_sha)
    marks = _normalized_rows(Path(capture_root), "marks")
    trades = _normalized_rows(Path(capture_root), "trades")
    funding = _normalized_rows(Path(capture_root), "funding")
    windows: dict[str, Any] = {}
    independent: dict[str, Any] = {}
    for window in HISTORICAL_WINDOWS:
        producer = evaluate_historical_window(
            window_id=window.window_id,
            mark_rows=marks,
            trade_rows=trades,
            funding_rows=funding,
        )
        windows[window.window_id] = producer
        independent[window.window_id] = review_historical_window(
            producer, mark_rows=marks, trade_rows=trades, funding_rows=funding
        )
    pooled = summarize_h1_h5(windows)
    pooled_independent = review_pooled_summary(pooled, windows)
    independent_pass = (
        all(value["status"] == "PASS" for value in independent.values())
        and pooled_independent["status"] == "PASS"
    )
    classification = (
        pooled["overall_economic_verdict"]
        if independent_pass
        else "IMPLEMENTATION_FAILURE"
    )
    passed = classification == "ECONOMIC_PASS"
    final = {
        "schema_version": 1,
        "stage": "C8A_H1_H5_FINAL_CLASSIFICATION",
        "status": "PASS" if passed else "FAIL",
        "classification": classification,
        "authoritative_run_id": authoritative_run_id,
        "implementation_sha": implementation_sha,
        "independent_recompute_passed": independent_pass,
        "data_custody_passed": True,
        "historical_economic_pass": passed,
        "retuning_authorized": False,
        "rerun_after_economic_inspection_authorized": False,
        "best_window_selection_performed": False,
        "shadow_eligible": False,
        "paper_state": "PAPER_CLOSED",
        "shadow_state": "SHADOW_CLOSED",
        "live_state": "LIVE_FORBIDDEN",
    }
    package = C8AEvidencePackage(Path(output_root))
    package.write_json(
        "metadata.json",
        {
            "schema_version": 1,
            "stage": "C8A_H1_H5_HISTORICAL_ECONOMIC_RUN",
            "authoritative_run_id": authoritative_run_id,
            "implementation_sha": implementation_sha,
            "evaluation_checkout_binding": evaluation_binding,
            "evaluated_at": stamp.astimezone(UTC).isoformat().replace("+00:00", "Z"),
            "source_kind": "OFFICIAL_PUBLIC_OKX",
            "historical_data_status": "HISTORICAL_DEVELOPMENT_ONLY",
            "authenticated": False,
            "contains_account_data": False,
            "contains_order_data": False,
            "paper_side_effect": False,
            "shadow_side_effect": False,
            "live_state": "LIVE_FORBIDDEN",
        },
    )
    package.write_json("authority_hashes.json", authority_hashes)
    package.write_json("capture_reference.json", capture_reference)
    package.write_json(
        "normalized_coverage.json",
        {
            series: {instrument: len(rows[instrument]) for instrument in INSTRUMENTS}
            for series, rows in (
                ("marks", marks),
                ("trades", trades),
                ("funding", funding),
            )
        },
    )
    for window_id, producer in windows.items():
        package.write_json(f"windows/{window_id}/producer.json", producer)
        package.write_json(
            f"windows/{window_id}/independent_review.json", independent[window_id]
        )
    package.write_json("pooled_summary.json", pooled)
    package.write_json("pooled_independent_review.json", pooled_independent)
    package.write_json("final_classification.json", final)
    manifest = package.finalize(implementation_sha=implementation_sha)
    return final, manifest
