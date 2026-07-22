"""C6A evidence matrix, atomic JSON, and complete manifest guards."""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from atos.c6a_contract import C6AError

POLICY_IDS = (
    "C6AMarketNeutralFundingCarry",
    "AlwaysOnDeltaNeutralComparator",
    "CashComparator",
    "SpotBuyAndHoldComparator",
)
COST_LABELS = ("1.0x", "1.5x", "2.0x")
WINDOW_IDS = ("W1", "W2", "W3", "W4", "W5")
EXPECTED_RESULT_CELLS = len(POLICY_IDS) * len(COST_LABELS) * len(WINDOW_IDS)


@dataclass(frozen=True)
class ManifestEntry:
    path: str
    size: int
    sha256: str


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_json_atomic(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False),
        encoding="utf-8",
    )
    temporary.replace(path)


def build_manifest(
    root: Path,
    *,
    relative_paths: Iterable[str] | None = None,
    exclude: Sequence[str] = ("manifest.json", "manifest.pre.json"),
) -> tuple[ManifestEntry, ...]:
    root = root.resolve()
    if relative_paths is None:
        candidates = [path for path in root.rglob("*") if path.is_file()]
    else:
        candidates = [root / relative for relative in relative_paths]
    entries: list[ManifestEntry] = []
    seen: set[str] = set()
    for candidate in sorted(candidates, key=lambda path: path.as_posix()):
        if candidate.is_symlink():
            raise C6AError(f"evidence manifest forbids symlink: {candidate}")
        try:
            resolved = candidate.resolve(strict=True)
        except OSError as exc:
            raise C6AError(f"evidence file missing: {candidate}") from exc
        try:
            relative = resolved.relative_to(root).as_posix()
        except ValueError as exc:
            raise C6AError(f"evidence path escapes root: {candidate}") from exc
        if relative in exclude:
            continue
        if relative in seen:
            raise C6AError(f"duplicate evidence manifest path: {relative}")
        if not resolved.is_file():
            raise C6AError(f"evidence path is not a regular file: {relative}")
        seen.add(relative)
        entries.append(
            ManifestEntry(
                path=relative,
                size=resolved.stat().st_size,
                sha256=sha256_file(resolved),
            )
        )
    if not entries:
        raise C6AError("evidence manifest cannot be empty")
    return tuple(entries)


def verify_manifest(root: Path, entries: Sequence[ManifestEntry | Mapping[str, Any]]) -> None:
    root = root.resolve()
    normalized = tuple(
        entry
        if isinstance(entry, ManifestEntry)
        else ManifestEntry(
            path=str(entry.get("path", "")),
            size=int(entry.get("size", -1)),
            sha256=str(entry.get("sha256", "")),
        )
        for entry in entries
    )
    paths = [entry.path for entry in normalized]
    if paths != sorted(paths) or len(paths) != len(set(paths)):
        raise C6AError("manifest paths must be sorted and unique")
    for entry in normalized:
        path = (root / entry.path).resolve()
        try:
            path.relative_to(root)
        except ValueError as exc:
            raise C6AError(f"manifest path escapes root: {entry.path}") from exc
        if not path.is_file() or path.is_symlink():
            raise C6AError(f"manifest file missing or unsafe: {entry.path}")
        if path.stat().st_size != entry.size:
            raise C6AError(f"manifest size mismatch: {entry.path}")
        if sha256_file(path) != entry.sha256:
            raise C6AError(f"manifest SHA-256 mismatch: {entry.path}")


def validate_result_matrix(results: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    if len(results) != EXPECTED_RESULT_CELLS:
        raise C6AError(
            f"C6A result matrix must contain {EXPECTED_RESULT_CELLS} cells, found {len(results)}"
        )
    expected = {
        (policy, cost, window)
        for policy in POLICY_IDS
        for cost in COST_LABELS
        for window in WINDOW_IDS
    }
    observed: dict[tuple[str, str, str], Mapping[str, Any]] = {}
    for row in results:
        key = (
            str(row.get("policy_id", "")),
            str(row.get("cost_label", "")),
            str(row.get("window_id", "")),
        )
        if key in observed:
            raise C6AError(f"duplicate C6A result cell: {key}")
        observed[key] = row
        if row.get("status") != "PASS":
            raise C6AError(f"non-PASS C6A result cell: {key}")
        if (
            row.get("c5b_state") != "C5B_CLOSED_AND_UNTOUCHED"
            or row.get("holdout_state") != "HOLDOUT_CLOSED"
            or row.get("paper_state") != "PAPER_CLOSED"
            or row.get("shadow_state") != "SHADOW_CLOSED"
            or row.get("live") != "FORBIDDEN"
        ):
            raise C6AError(f"safety-state drift in result cell: {key}")
        buckets = row.get("weekly_buckets")
        if not isinstance(buckets, list) or len(buckets) != 26:
            raise C6AError(f"weekly evidence count mismatch in cell: {key}")
    missing = sorted(expected - set(observed))
    extra = sorted(set(observed) - expected)
    if missing or extra:
        raise C6AError(f"C6A result matrix key mismatch: missing={missing} extra={extra}")
    return {
        "schema_version": 1,
        "stage": "C6A",
        "status": "PASS",
        "result_cell_count": len(observed),
        "policy_count": len(POLICY_IDS),
        "cost_count": len(COST_LABELS),
        "window_count": len(WINDOW_IDS),
        "keys": ["/".join(key) for key in sorted(observed)],
        "c6b_state": "C6B_CLOSED",
        "c5b_state": "C5B_CLOSED_AND_UNTOUCHED",
        "live": "FORBIDDEN",
    }


def validate_decision(payload: Mapping[str, Any]) -> None:
    status = payload.get("status")
    selected = payload.get("selected_policy")
    if status not in {"SELECTED", "REJECTED"}:
        raise C6AError("C6A decision status is invalid")
    if status == "SELECTED" and selected != "C6AMarketNeutralFundingCarry":
        raise C6AError("C6A selected decision has wrong policy")
    if status == "REJECTED" and selected is not None:
        raise C6AError("rejected C6A decision must retain null selected policy")
    if (
        payload.get("c6b_state") != "C6B_CLOSED"
        or payload.get("c5b_state") != "C5B_CLOSED_AND_UNTOUCHED"
        or payload.get("holdout_state") != "HOLDOUT_CLOSED"
        or payload.get("paper_state") != "PAPER_CLOSED"
        or payload.get("shadow_state") != "SHADOW_CLOSED"
        or payload.get("live") != "FORBIDDEN"
    ):
        raise C6AError("C6A decision safety-state drift")


def manifest_payload(entries: Sequence[ManifestEntry]) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "stage": "C6A",
        "status": "PASS",
        "entry_count": len(entries),
        "entries": [asdict(entry) for entry in entries],
        "c6b_state": "C6B_CLOSED",
        "c5b_state": "C5B_CLOSED_AND_UNTOUCHED",
        "holdout_state": "HOLDOUT_CLOSED",
        "paper_state": "PAPER_CLOSED",
        "shadow_state": "SHADOW_CLOSED",
        "live": "FORBIDDEN",
    }
