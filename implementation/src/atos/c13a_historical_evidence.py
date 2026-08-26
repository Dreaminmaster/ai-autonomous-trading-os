"""Immutable C13A H1-H5 public-data and economic evidence package."""

from __future__ import annotations

import hashlib
import json
import os
import re
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlparse

from atos.c7a_okx_public_data import C7APublicDataError, PublicRequest
from atos.c13a_contract import (
    BTC_BETA_BENCHMARK,
    CANDIDATE_POOL,
    HISTORICAL_WINDOWS,
    capture_plan,
    safety_boundary,
)
from atos.c13a_historical_capture import validate_c13a_public_request
from atos.c13a_historical_independent import (
    review_historical_window,
    review_pooled_summary,
)
from atos.c13a_historical_replay import (
    evaluate_historical_window_matrix,
    summarize_h1_h5,
)
from atos.c13a_historical_run_guard import (
    C13AHistoricalRunGuardError,
    validate_checkout_binding,
)

EXACT_SHA = re.compile(r"[0-9a-f]{40}")
SAFE_RUN_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,159}")
DESIGN_PATH = Path(
    "docs/architecture/phase-c/c13a-cross-sectional-lottery-demand/"
    "C13A_CROSS_SECTIONAL_LOTTERY_DEMAND_CONTRACT_V1.md"
)
CONFIG_PATH = Path("implementation/config/c13a_cross_sectional_lottery_demand.json")
REGISTRY_PATH = Path("implementation/config/phase_c_research_program_registry_v4.json")
WORKFLOW_PATH = Path(".github/workflows/freqtrade-validation.yml")
SHARED_RUNTIME_PATHS = (
    Path("implementation/src/atos/c7a_okx_public_data.py"),
    Path("implementation/src/atos/c7a_historical_capture.py"),
    Path("implementation/src/atos/c13a_research_program_guard.py"),
)
API_FAMILIES = {
    "OKX_HISTORY_CANDLES_API",
    "OKX_HISTORY_MARK_PRICE_CANDLES_API",
    "OKX_FUNDING_RATE_HISTORY_API",
    "OKX_HISTORICAL_DATA_API",
}
RETRY_EVENTS = {"HTTP_429", "HTTP_500", "HTTP_502", "HTTP_503", "HTTP_504"}


class C13AHistoricalEvidenceError(RuntimeError):
    """Raised when final evidence cannot be proven complete and immutable."""


class C13AHistoricalDataEvidenceError(C13AHistoricalEvidenceError):
    """Raised when retained source custody or normalization is invalid."""


def _canonical_bytes(value: Any) -> bytes:
    return (
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        + "\n"
    ).encode()


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise C13AHistoricalEvidenceError(f"invalid retained JSON: {path}") from exc


def _sync_directory(path: Path) -> None:
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


class C13AEvidencePackage:
    """Exclusive, atomic, no-overwrite evidence writer."""

    def __init__(self, root: Path):
        self.root = Path(root)
        if self.root.exists():
            raise C13AHistoricalEvidenceError(
                f"evidence package already exists: {self.root}"
            )
        self.root.mkdir(parents=True, mode=0o700)
        _sync_directory(self.root.parent)
        self._finalized = False

    def write_json(self, relative: str, value: Any) -> None:
        if self._finalized:
            raise C13AHistoricalEvidenceError("evidence package is finalized")
        path = Path(relative)
        if path.is_absolute() or not path.parts or ".." in path.parts:
            raise C13AHistoricalEvidenceError("evidence path escapes package")
        destination = self.root / path
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_name(f".{destination.name}.tmp")
        if destination.exists() or temporary.exists():
            raise C13AHistoricalEvidenceError(
                f"evidence file already exists: {relative}"
            )
        with temporary.open("xb") as handle:
            handle.write(_canonical_bytes(value))
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(temporary, destination)
        except FileExistsError as exc:
            raise C13AHistoricalEvidenceError(
                f"evidence file already exists: {relative}"
            ) from exc
        temporary.unlink()
        _sync_directory(destination.parent)

    def finalize(self, *, implementation_sha: str) -> dict[str, Any]:
        if not EXACT_SHA.fullmatch(implementation_sha):
            raise C13AHistoricalEvidenceError("implementation SHA must be exact")
        entries = sorted(self.root.rglob("*"))
        if any(path.is_symlink() for path in entries):
            raise C13AHistoricalEvidenceError("evidence contains a symbolic link")
        files = []
        for path in (entry for entry in entries if entry.is_file()):
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
            raise C13AHistoricalEvidenceError("evidence package contains no files")
        manifest = {
            "schema_version": 1,
            "stage": "C13A_H1_H5_HISTORICAL_EVIDENCE_PACKAGE",
            "implementation_sha": implementation_sha,
            "file_count": len(files),
            "files": files,
            **safety_boundary(),
        }
        self.write_json("manifest.json", manifest)
        self._finalized = True
        return manifest


def verify_capture_package(
    capture_root: Path, *, implementation_sha: str
) -> dict[str, Any]:
    try:
        return _verify_capture_package(
            Path(capture_root), implementation_sha=implementation_sha
        )
    except C13AHistoricalEvidenceError as exc:
        raise C13AHistoricalDataEvidenceError(str(exc)) from exc


def verify_evidence_package(
    evidence_root: Path, *, implementation_sha: str
) -> dict[str, Any]:
    """Recompute the finalized evidence inventory and every retained digest."""

    root = Path(evidence_root)
    if root.is_symlink() or any(path.is_symlink() for path in root.rglob("*")):
        raise C13AHistoricalEvidenceError("evidence package contains a symbolic link")
    manifest = _read_json(root / "manifest.json")
    if not isinstance(manifest, Mapping) or (
        manifest.get("stage") != "C13A_H1_H5_HISTORICAL_EVIDENCE_PACKAGE"
        or manifest.get("implementation_sha") != implementation_sha
        or any(
            manifest.get(key) != value for key, value in safety_boundary().items()
        )
    ):
        raise C13AHistoricalEvidenceError("evidence manifest identity drift")
    declared = manifest.get("files")
    if not isinstance(declared, list) or manifest.get("file_count") != len(declared):
        raise C13AHistoricalEvidenceError("evidence manifest inventory is invalid")
    observed = {
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file() and path.name != "manifest.json"
    }
    declared_paths = {
        str(row.get("path")) for row in declared if isinstance(row, Mapping)
    }
    if observed != declared_paths or len(declared_paths) != len(declared):
        raise C13AHistoricalEvidenceError("evidence manifest path inventory mismatch")
    for row in declared:
        if not isinstance(row, Mapping):
            raise C13AHistoricalEvidenceError("evidence manifest row is invalid")
        data = (root / str(row["path"])).read_bytes()
        if len(data) != row.get("size") or hashlib.sha256(data).hexdigest() != row.get(
            "sha256"
        ):
            raise C13AHistoricalEvidenceError(
                f"evidence hash mismatch: {row.get('path')}"
            )
    return {
        "status": "PASS",
        "implementation_sha": implementation_sha,
        "manifest_sha256": hashlib.sha256(
            (root / "manifest.json").read_bytes()
        ).hexdigest(),
        "verified_file_count": len(declared),
        **safety_boundary(),
    }


def _verify_capture_package(root: Path, *, implementation_sha: str) -> dict[str, Any]:
    if root.is_symlink() or any(path.is_symlink() for path in root.rglob("*")):
        raise C13AHistoricalEvidenceError("capture package contains a symbolic link")
    manifest = _read_json(root / "manifest.json")
    index = _read_json(root / "capture_index.json")
    binding = _read_json(root / "checkout_binding.json")
    if not all(isinstance(value, Mapping) for value in (manifest, index)):
        raise C13AHistoricalEvidenceError("capture authority is not an object")
    if (
        manifest.get("stage") != "C13A_HISTORICAL_CAPTURE_PACKAGE"
        or index.get("stage") != "C13A_HISTORICAL_CAPTURE"
        or manifest.get("implementation_sha") != implementation_sha
        or index.get("implementation_sha") != implementation_sha
        or index.get("capture_plan") != capture_plan()
        or tuple(index.get("selected_universe", ())) != CANDIDATE_POOL
        or manifest.get("real_public_data") is not True
        or manifest.get("economic_result") is not False
    ):
        raise C13AHistoricalEvidenceError("capture identity, plan, or universe drift")
    if any(
        manifest.get(key) != value or index.get(key) != value
        for key, value in safety_boundary().items()
    ):
        raise C13AHistoricalEvidenceError("capture safety boundary drift")
    try:
        validate_checkout_binding(binding, implementation_sha=implementation_sha)
    except C13AHistoricalRunGuardError as exc:
        raise C13AHistoricalEvidenceError(str(exc)) from exc
    declared = manifest.get("files")
    if not isinstance(declared, list) or manifest.get("file_count") != len(declared):
        raise C13AHistoricalEvidenceError("capture manifest inventory is invalid")
    observed = {
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file() and path.name != "manifest.json"
    }
    paths = {str(row.get("path")) for row in declared if isinstance(row, Mapping)}
    if observed != paths or len(paths) != len(declared):
        raise C13AHistoricalEvidenceError("capture manifest path inventory mismatch")
    for row in declared:
        if not isinstance(row, Mapping):
            raise C13AHistoricalEvidenceError("capture manifest row is invalid")
        data = (root / str(row.get("path"))).read_bytes()
        if len(data) != row.get("size") or hashlib.sha256(data).hexdigest() != row.get(
            "sha256"
        ):
            raise C13AHistoricalEvidenceError(
                f"capture hash mismatch: {row.get('path')}"
            )
    records = index.get("records")
    if not isinstance(records, list) or not records:
        raise C13AHistoricalEvidenceError("capture request records are missing")
    request_ids = set()
    raw_paths = set()
    for record in records:
        if not isinstance(record, Mapping) or set(record) != {
            "request_id",
            "source_family",
            "requested_url",
            "final_url",
            "collected_at",
            "media_type",
            "size",
            "sha256",
            "relative_path",
            "attempt_count",
            "retry_events",
        }:
            raise C13AHistoricalEvidenceError("capture request record schema drift")
        request_id = str(record["request_id"])
        relative = str(record["relative_path"])
        if (
            not SAFE_RUN_ID.fullmatch(request_id)
            or request_id in request_ids
            or relative in raw_paths
        ):
            raise C13AHistoricalEvidenceError("capture request or raw path is duplicate")
        request_ids.add(request_id)
        raw_paths.add(relative)
        expected_relative = (
            f"raw/{str(record['source_family']).lower()}/{request_id}.bin"
        )
        if relative != expected_relative or relative not in observed:
            raise C13AHistoricalEvidenceError("capture raw path identity drift")
        raw = (root / relative).read_bytes()
        if (
            type(record["size"]) is not int
            or len(raw) != record["size"]
            or hashlib.sha256(raw).hexdigest() != record["sha256"]
        ):
            raise C13AHistoricalEvidenceError("capture record/raw digest mismatch")
        attempt_count = record["attempt_count"]
        retry_events = record["retry_events"]
        if (
            type(attempt_count) is not int
            or not 1 <= attempt_count <= 5
            or not isinstance(retry_events, list)
            or len(retry_events) != attempt_count - 1
            or any(value not in RETRY_EVENTS for value in retry_events)
        ):
            raise C13AHistoricalEvidenceError("capture retry provenance drift")
        try:
            collected_at = datetime.fromisoformat(str(record["collected_at"]))
        except ValueError as exc:
            raise C13AHistoricalEvidenceError(
                "capture collection time is invalid"
            ) from exc
        if (
            collected_at.tzinfo is None
            or collected_at.utcoffset() != UTC.utcoffset(collected_at)
            or not isinstance(record["media_type"], str)
            or not record["media_type"]
        ):
            raise C13AHistoricalEvidenceError("capture time or media type is invalid")
        requested = PublicRequest(
            request_id,
            str(record["source_family"]),
            str(record["requested_url"]),
        )
        final = PublicRequest(
            request_id,
            str(record["source_family"]),
            str(record["final_url"]),
        )
        try:
            validate_c13a_public_request(requested)
            validate_c13a_public_request(final)
        except C7APublicDataError as exc:
            raise C13AHistoricalEvidenceError(
                "capture request URL is outside public C13A policy"
            ) from exc
        if record["source_family"] in API_FAMILIES:
            if record["media_type"] not in {"application/json", "text/json"}:
                raise C13AHistoricalEvidenceError(
                    "capture API media type is not JSON"
                )
            requested_url = urlparse(requested.url)
            final_url = urlparse(final.url)
            if (
                requested_url.path != final_url.path
                or sorted(parse_qsl(requested_url.query, keep_blank_values=True))
                != sorted(parse_qsl(final_url.query, keep_blank_values=True))
            ):
                raise C13AHistoricalEvidenceError(
                    "capture API redirect changed path or query semantics"
                )
    if raw_paths != {path for path in observed if path.startswith("raw/")}:
        raise C13AHistoricalEvidenceError("capture raw record inventory mismatch")
    selected = tuple(str(value) for value in index.get("selected_universe", ()))
    if (
        selected != CANDIDATE_POOL
    ):
        raise C13AHistoricalEvidenceError("capture selected universe is invalid")
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
        "selected_universe": list(selected),
        "implementation_sha": implementation_sha,
    }


def _rows(root: Path, series: str, instruments: tuple[str, ...]) -> dict[str, list[dict[str, Any]]]:
    output = {}
    for instrument in instruments:
        value = _read_json(root / "normalized" / series / f"{instrument}.json")
        if (
            not isinstance(value, list)
            or not value
            or any(not isinstance(row, dict) for row in value)
        ):
            raise C13AHistoricalDataEvidenceError(
                f"normalized {series} rows are invalid: {instrument}"
            )
        output[instrument] = value
    return output


def _authority_hashes(root: Path, implementation_sha: str) -> dict[str, Any]:
    files = [
        path
        for path in (root / "implementation" / "src" / "atos").glob("c13a_*.py")
        if path.is_file()
    ]
    files.extend(
        path
        for path in (root / "implementation" / "scripts").glob("c13a_*.py")
        if path.is_file()
    )
    files.extend(root / path for path in SHARED_RUNTIME_PATHS)
    files.extend(
        (root / DESIGN_PATH, root / CONFIG_PATH, root / REGISTRY_PATH, root / WORKFLOW_PATH)
    )
    if any(not path.is_file() for path in files):
        raise C13AHistoricalEvidenceError("authority source inventory is incomplete")
    inventory = []
    for path in sorted(set(files)):
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
        raise C13AHistoricalEvidenceError("implementation SHA or run ID is invalid")
    try:
        evaluation_binding = validate_checkout_binding(
            evaluation_checkout_binding, implementation_sha=implementation_sha
        )
    except C13AHistoricalRunGuardError as exc:
        raise C13AHistoricalEvidenceError(str(exc)) from exc
    stamp = evaluated_at or datetime.now(tz=UTC)
    if stamp.tzinfo is None:
        raise C13AHistoricalEvidenceError("evaluation time must be timezone-aware")
    capture_root = Path(capture_root)
    capture_reference = verify_capture_package(
        capture_root, implementation_sha=implementation_sha
    )
    selected = tuple(capture_reference["selected_universe"])
    trades = _rows(capture_root, "trades", selected)
    marks = _rows(
        capture_root,
        "marks",
        tuple(sorted({*selected, BTC_BETA_BENCHMARK})),
    )
    funding = _rows(capture_root, "funding", selected)
    windows: dict[str, Any] = {}
    independent: dict[str, Any] = {}
    for window in HISTORICAL_WINDOWS:
        producer = evaluate_historical_window_matrix(
            window,
            selected_universe=selected,
            trade_rows=trades,
            mark_rows=marks,
            funding_rows=funding,
        )
        windows[window.window_id] = producer
        independent[window.window_id] = review_historical_window(
            producer,
            trade_rows=trades,
            mark_rows=marks,
            funding_rows=funding,
        )
    pooled = summarize_h1_h5(windows)
    pooled_review = review_pooled_summary(pooled, windows)
    independent_pass = all(
        review["status"] == "PASS" for review in independent.values()
    ) and pooled_review["status"] == "PASS"
    classification = (
        pooled["overall_economic_verdict"] if independent_pass else "PROGRAM_FAILURE"
    )
    passed = classification == "ECONOMIC_PASS"
    final = {
        "schema_version": 1,
        "stage": "C13A_H1_H5_FINAL_CLASSIFICATION",
        "status": "PASS" if passed else "FAIL",
        "classification": classification,
        "authoritative_run_id": authoritative_run_id,
        "implementation_sha": implementation_sha,
        "data_custody_passed": True,
        "independent_recompute_passed": independent_pass,
        "historical_economic_pass": passed,
        "retuning_authorized": False,
        "authoritative_rerun_authorized": False,
        "best_window_selection_performed": False,
        "shadow_eligible": passed,
        **safety_boundary(),
    }
    package = C13AEvidencePackage(Path(output_root))
    package.write_json(
        "metadata.json",
        {
            "schema_version": 1,
            "stage": "C13A_H1_H5_HISTORICAL_ECONOMIC_RUN",
            "authoritative_run_id": authoritative_run_id,
            "implementation_sha": implementation_sha,
            "evaluation_checkout_binding": evaluation_binding,
            "evaluated_at": stamp.astimezone(UTC).isoformat().replace("+00:00", "Z"),
            "source_kind": "OFFICIAL_PUBLIC_OKX",
            **safety_boundary(),
        },
    )
    package.write_json(
        "authority_hashes.json",
        _authority_hashes(Path(repository_root), implementation_sha),
    )
    package.write_json("capture_reference.json", capture_reference)
    package.write_json(
        "normalized_coverage.json",
        {
            series: {instrument: len(values) for instrument, values in rows.items()}
            for series, rows in (
                ("trades", trades),
                ("marks", marks),
                ("funding", funding),
            )
        },
    )
    for window_id, producer in windows.items():
        package.write_json(f"windows/{window_id}/producer.json", producer)
        package.write_json(
            f"windows/{window_id}/independent_review.json",
            independent[window_id],
        )
    package.write_json("pooled_summary.json", pooled)
    package.write_json("pooled_independent_review.json", pooled_review)
    package.write_json("final_classification.json", final)
    manifest = package.finalize(implementation_sha=implementation_sha)
    verification = verify_evidence_package(
        output_root, implementation_sha=implementation_sha
    )
    if verification["verified_file_count"] != manifest["file_count"]:
        raise C13AHistoricalEvidenceError("post-finalization evidence audit drift")
    return final, manifest


__all__ = [
    "C13AEvidencePackage",
    "C13AHistoricalDataEvidenceError",
    "C13AHistoricalEvidenceError",
    "build_h1_h5_evidence_package",
    "verify_capture_package",
    "verify_evidence_package",
]
