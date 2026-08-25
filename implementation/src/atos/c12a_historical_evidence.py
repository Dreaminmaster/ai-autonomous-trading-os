"""Immutable C12A public-data, independent-recompute, and economic evidence."""

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

from atos.c7a_okx_public_data import PublicRequest
from atos.c12a_contract import SPOT_INSTRUMENTS, contract_decisions, safety_boundary
from atos.c12a_historical_capture import capture_plan, validate_c12a_public_request
from atos.c12a_historical_independent import (
    review_historical_window,
    review_pooled_summary,
)
from atos.c12a_historical_replay import (
    btc_weekly_benchmark_returns,
    build_market_inventory,
    replay_h1_h5,
    summarize_h1_h5,
)
from atos.c12a_historical_run_guard import (
    C12AHistoricalRunGuardError,
    validate_checkout_binding,
)

EXACT_SHA = re.compile(r"[0-9a-f]{40}")
SAFE_RUN_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,159}")
DESIGN_PATH = Path(
    "docs/architecture/phase-c/c12a-fixed-maturity-basis-carry/"
    "C12A_FIXED_MATURITY_BASIS_CARRY_CONTRACT_V1.md"
)
CONFIG_PATH = Path("implementation/config/c12a_fixed_maturity_basis_carry.json")
REGISTRY_PATH = Path("implementation/config/phase_c_research_program_registry_v3.json")
WORKFLOW_PATH = Path(".github/workflows/freqtrade-validation.yml")
SHARED_RUNTIME_PATHS = (
    Path("implementation/src/atos/c7a_okx_public_data.py"),
    Path("implementation/src/atos/c7a_historical_capture.py"),
    Path("implementation/src/atos/c9a_historical_capture.py"),
    Path("implementation/src/atos/c12a_research_program_guard.py"),
)
API_FAMILIES = {
    "OKX_HISTORY_CANDLES_API",
    "OKX_HISTORICAL_FUTURES_CHAIN_API",
}
RETRY_EVENTS = {"HTTP_429", "HTTP_500", "HTTP_502", "HTTP_503", "HTTP_504"}
CAPTURE_RECORD_KEYS = {
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
}


class C12AHistoricalEvidenceError(RuntimeError):
    """Raised when C12A evidence cannot be proven complete and immutable."""


class C12AHistoricalDataEvidenceError(C12AHistoricalEvidenceError):
    """Raised when retained official-public custody is invalid."""


def _canonical(value: Any) -> bytes:
    return (
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        + "\n"
    ).encode()


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise C12AHistoricalEvidenceError(f"invalid retained JSON: {path}") from exc


def _sync(path: Path) -> None:
    descriptor = os.open(
        path,
        os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0),
    )
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


class C12AEvidencePackage:
    """Exclusive, atomic, no-overwrite evidence writer."""

    def __init__(self, root: Path):
        self.root = Path(root)
        if self.root.exists():
            raise C12AHistoricalEvidenceError(
                f"evidence package already exists: {self.root}"
            )
        self.root.mkdir(parents=True, mode=0o700)
        _sync(self.root.parent)
        self._finalized = False

    def write_json(self, relative: str, value: Any) -> None:
        if self._finalized:
            raise C12AHistoricalEvidenceError("evidence package is finalized")
        path = Path(relative)
        if path.is_absolute() or not path.parts or ".." in path.parts:
            raise C12AHistoricalEvidenceError("evidence path escapes package")
        destination = self.root / path
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_name(f".{destination.name}.tmp")
        if destination.exists() or temporary.exists():
            raise C12AHistoricalEvidenceError(
                f"evidence file already exists: {relative}"
            )
        with temporary.open("xb") as handle:
            handle.write(_canonical(value))
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(temporary, destination)
        except FileExistsError as exc:
            raise C12AHistoricalEvidenceError(
                f"evidence file already exists: {relative}"
            ) from exc
        temporary.unlink()
        _sync(destination.parent)

    def finalize(self, *, implementation_sha: str) -> dict[str, Any]:
        if not EXACT_SHA.fullmatch(implementation_sha):
            raise C12AHistoricalEvidenceError("implementation SHA must be exact")
        entries = sorted(self.root.rglob("*"))
        if any(path.is_symlink() for path in entries):
            raise C12AHistoricalEvidenceError("evidence contains a symbolic link")
        files = []
        for path in (item for item in entries if item.is_file()):
            relative = path.relative_to(self.root).as_posix()
            if relative == "manifest.json":
                continue
            raw = path.read_bytes()
            files.append(
                {
                    "path": relative,
                    "size": len(raw),
                    "sha256": hashlib.sha256(raw).hexdigest(),
                }
            )
        if not files:
            raise C12AHistoricalEvidenceError("evidence package contains no files")
        manifest = {
            "schema_version": 1,
            "stage": "C12A_H1_H5_HISTORICAL_EVIDENCE_PACKAGE",
            "implementation_sha": implementation_sha,
            "file_count": len(files),
            "files": files,
            **safety_boundary(),
        }
        self.write_json("manifest.json", manifest)
        self._finalized = True
        return manifest


def _verify_file_manifest(
    root: Path, manifest: Mapping[str, Any], *, manifest_name: str
) -> int:
    declared = manifest.get("files")
    if not isinstance(declared, list) or manifest.get("file_count") != len(declared):
        raise C12AHistoricalEvidenceError(f"{manifest_name} inventory is invalid")
    observed = {
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file() and path.name != "manifest.json"
    }
    paths = {str(row.get("path")) for row in declared if isinstance(row, Mapping)}
    if observed != paths or len(paths) != len(declared):
        raise C12AHistoricalEvidenceError(f"{manifest_name} path inventory mismatch")
    for row in declared:
        if not isinstance(row, Mapping):
            raise C12AHistoricalEvidenceError(f"{manifest_name} row is invalid")
        raw = (root / str(row.get("path"))).read_bytes()
        if len(raw) != row.get("size") or hashlib.sha256(raw).hexdigest() != row.get(
            "sha256"
        ):
            raise C12AHistoricalEvidenceError(
                f"{manifest_name} hash mismatch: {row.get('path')}"
            )
    return len(declared)


def verify_capture_package(
    capture_root: Path, *, implementation_sha: str
) -> dict[str, Any]:
    try:
        return _verify_capture_package(
            Path(capture_root), implementation_sha=implementation_sha
        )
    except C12AHistoricalEvidenceError as exc:
        raise C12AHistoricalDataEvidenceError(str(exc)) from exc


def _verify_capture_package(root: Path, *, implementation_sha: str) -> dict[str, Any]:
    if root.is_symlink() or any(path.is_symlink() for path in root.rglob("*")):
        raise C12AHistoricalEvidenceError("capture contains a symbolic link")
    manifest = _read_json(root / "manifest.json")
    index = _read_json(root / "capture_index.json")
    binding = _read_json(root / "checkout_binding.json")
    if not isinstance(manifest, Mapping) or not isinstance(index, Mapping):
        raise C12AHistoricalEvidenceError("capture authority is not an object")
    if (
        manifest.get("stage") != "C12A_HISTORICAL_CAPTURE_PACKAGE"
        or index.get("stage") != "C12A_HISTORICAL_CAPTURE"
        or manifest.get("implementation_sha") != implementation_sha
        or index.get("implementation_sha") != implementation_sha
        or index.get("capture_plan") != capture_plan()
        or manifest.get("real_public_data") is not True
        or manifest.get("economic_result") is not False
    ):
        raise C12AHistoricalEvidenceError("capture identity or plan drift")
    if any(
        manifest.get(key) != value or index.get(key) != value
        for key, value in safety_boundary().items()
    ):
        raise C12AHistoricalEvidenceError("capture safety boundary drift")
    try:
        validate_checkout_binding(binding, implementation_sha=implementation_sha)
    except C12AHistoricalRunGuardError as exc:
        raise C12AHistoricalEvidenceError(str(exc)) from exc
    count = _verify_file_manifest(root, manifest, manifest_name="capture manifest")
    records = index.get("records")
    if not isinstance(records, list) or not records:
        raise C12AHistoricalEvidenceError("capture records are missing")
    raw_paths: set[str] = set()
    request_ids: set[str] = set()
    for record in records:
        if not isinstance(record, Mapping) or set(record) != CAPTURE_RECORD_KEYS:
            raise C12AHistoricalEvidenceError("capture record schema is invalid")
        request_id = str(record.get("request_id", ""))
        source_family = str(record.get("source_family", ""))
        relative = str(record.get("relative_path", ""))
        expected_relative = f"raw/{source_family.lower()}/{request_id}.bin"
        if (
            not SAFE_RUN_ID.fullmatch(request_id)
            or request_id in request_ids
            or relative in raw_paths
            or relative != expected_relative
        ):
            raise C12AHistoricalEvidenceError("capture raw identity is invalid")
        request_ids.add(request_id)
        raw_paths.add(relative)
        raw = (root / relative).read_bytes()
        if len(raw) != record.get("size") or hashlib.sha256(
            raw
        ).hexdigest() != record.get("sha256"):
            raise C12AHistoricalEvidenceError("capture record/raw digest mismatch")
        for key in ("requested_url", "final_url"):
            validate_c12a_public_request(
                PublicRequest(
                    request_id=request_id,
                    source_family=source_family,
                    url=str(record.get(key, "")),
                )
            )
        if source_family in API_FAMILIES:
            requested = urlparse(str(record["requested_url"]))
            final = urlparse(str(record["final_url"]))
            if requested.path != final.path or sorted(
                parse_qsl(requested.query, keep_blank_values=True)
            ) != sorted(parse_qsl(final.query, keep_blank_values=True)):
                raise C12AHistoricalEvidenceError(
                    "capture API redirect changed path or query semantics"
                )
        try:
            stamp = datetime.fromisoformat(str(record.get("collected_at")))
        except ValueError as exc:
            raise C12AHistoricalEvidenceError("capture timestamp is invalid") from exc
        if stamp.tzinfo is None or stamp.utcoffset() != UTC.utcoffset(stamp):
            raise C12AHistoricalEvidenceError("capture timestamp is not UTC")
        attempts = record.get("attempt_count")
        retries = record.get("retry_events")
        media_type = record.get("media_type")
        if (
            type(attempts) is not int
            or not 1 <= attempts <= 5
            or not isinstance(retries, list)
            or len(retries) != attempts - 1
            or any(event not in RETRY_EVENTS for event in retries)
            or not isinstance(media_type, str)
            or not media_type
        ):
            raise C12AHistoricalEvidenceError("capture retry provenance drift")
        if source_family in API_FAMILIES and media_type not in {
            "application/json",
            "text/json",
        }:
            raise C12AHistoricalEvidenceError("capture API media type is not JSON")
    observed_raw = {
        path.relative_to(root).as_posix()
        for path in (root / "raw").rglob("*")
        if path.is_file()
    }
    if raw_paths != observed_raw:
        raise C12AHistoricalEvidenceError("capture raw inventory mismatch")
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
        "capture_file_count": count,
        "capture_record_count": len(records),
        "implementation_sha": implementation_sha,
    }


def verify_evidence_package(
    evidence_root: Path, *, implementation_sha: str
) -> dict[str, Any]:
    root = Path(evidence_root)
    if root.is_symlink() or any(path.is_symlink() for path in root.rglob("*")):
        raise C12AHistoricalEvidenceError("evidence contains a symbolic link")
    manifest = _read_json(root / "manifest.json")
    if not isinstance(manifest, Mapping) or (
        manifest.get("stage") != "C12A_H1_H5_HISTORICAL_EVIDENCE_PACKAGE"
        or manifest.get("implementation_sha") != implementation_sha
        or any(manifest.get(key) != value for key, value in safety_boundary().items())
    ):
        raise C12AHistoricalEvidenceError("evidence manifest identity drift")
    count = _verify_file_manifest(root, manifest, manifest_name="evidence manifest")
    return {
        "status": "PASS",
        "implementation_sha": implementation_sha,
        "manifest_sha256": hashlib.sha256(
            (root / "manifest.json").read_bytes()
        ).hexdigest(),
        "verified_file_count": count,
        **safety_boundary(),
    }


def _rows(root: Path, instruments: tuple[str, ...]) -> dict[str, list[dict[str, Any]]]:
    output: dict[str, list[dict[str, Any]]] = {}
    for instrument in instruments:
        value = _read_json(root / "normalized" / "trades" / f"{instrument}.json")
        if (
            not isinstance(value, list)
            or not value
            or any(not isinstance(row, dict) for row in value)
        ):
            raise C12AHistoricalDataEvidenceError(
                f"normalized C12A rows are invalid: {instrument}"
            )
        output[instrument] = value
    return output


def _authority_hashes(root: Path, implementation_sha: str) -> dict[str, Any]:
    files = list((root / "implementation" / "src" / "atos").glob("c12a_*.py"))
    files.extend((root / "implementation" / "scripts").glob("c12a_*.py"))
    files.extend(root / path for path in SHARED_RUNTIME_PATHS)
    files.extend(
        (
            root / DESIGN_PATH,
            root / CONFIG_PATH,
            root / REGISTRY_PATH,
            root / WORKFLOW_PATH,
        )
    )
    if any(not path.is_file() for path in files):
        raise C12AHistoricalEvidenceError("authority source inventory is incomplete")
    inventory = []
    for path in sorted(set(files)):
        raw = path.read_bytes()
        inventory.append(
            {
                "path": path.relative_to(root).as_posix(),
                "size": len(raw),
                "sha256": hashlib.sha256(raw).hexdigest(),
            }
        )
    return {
        "implementation_sha": implementation_sha,
        "source_inventory": inventory,
        "source_inventory_sha256": hashlib.sha256(_canonical(inventory)).hexdigest(),
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
        raise C12AHistoricalEvidenceError("implementation SHA or run ID is invalid")
    try:
        binding = validate_checkout_binding(
            evaluation_checkout_binding, implementation_sha=implementation_sha
        )
    except C12AHistoricalRunGuardError as exc:
        raise C12AHistoricalEvidenceError(str(exc)) from exc
    stamp = evaluated_at or datetime.now(tz=UTC)
    if stamp.tzinfo is None:
        raise C12AHistoricalEvidenceError("evaluation time must be timezone-aware")
    capture_root = Path(capture_root)
    capture_reference = verify_capture_package(
        capture_root, implementation_sha=implementation_sha
    )
    decisions = contract_decisions()
    spot = _rows(capture_root, SPOT_INSTRUMENTS)
    futures = _rows(capture_root, tuple(item.futures_instrument for item in decisions))
    markets = build_market_inventory(spot_series=spot, futures_series=futures)
    replay = replay_h1_h5(markets)
    independent = {
        window["window_id"]: review_historical_window(
            window, spot_series=spot, futures_series=futures
        )
        for window in replay["windows"]
    }
    pooled = summarize_h1_h5(
        replay, btc_weekly_returns=btc_weekly_benchmark_returns(spot["BTC-USDT"])
    )
    pooled_review = review_pooled_summary(
        pooled, replay=replay, btc_spot_rows=spot["BTC-USDT"]
    )
    independent_pass = (
        all(review["status"] == "PASS" for review in independent.values())
        and pooled_review["status"] == "PASS"
    )
    classification = (
        pooled["overall_economic_verdict"] if independent_pass else "PROGRAM_FAILURE"
    )
    passed = classification == "ECONOMIC_PASS"
    final = {
        "schema_version": 1,
        "stage": "C12A_H1_H5_FINAL_CLASSIFICATION",
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
    package = C12AEvidencePackage(Path(output_root))
    package.write_json(
        "metadata.json",
        {
            "schema_version": 1,
            "stage": "C12A_H1_H5_HISTORICAL_ECONOMIC_RUN",
            "authoritative_run_id": authoritative_run_id,
            "implementation_sha": implementation_sha,
            "evaluation_checkout_binding": binding,
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
            "spot": {instrument: len(rows) for instrument, rows in spot.items()},
            "futures": {instrument: len(rows) for instrument, rows in futures.items()},
        },
    )
    for window in replay["windows"]:
        window_id = str(window["window_id"])
        package.write_json(f"windows/{window_id}/producer.json", window)
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
        raise C12AHistoricalEvidenceError("post-finalization evidence audit drift")
    return final, manifest


__all__ = [
    "C12AEvidencePackage",
    "C12AHistoricalDataEvidenceError",
    "C12AHistoricalEvidenceError",
    "build_h1_h5_evidence_package",
    "verify_capture_package",
    "verify_evidence_package",
]
