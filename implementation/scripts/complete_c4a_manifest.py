#!/usr/bin/env python3
"""Rebuild and self-verify the final C4A manifest after finalization."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

try:
    import scripts.c4a_evidence as evidence
except ModuleNotFoundError:  # pragma: no cover
    import c4a_evidence as evidence  # type: ignore

RESULTS = evidence.RESULTS
MANIFEST_PATH = RESULTS / "manifest.json"
PREVERIFY_PATH = RESULTS / "pre_manifest_verification.json"
REQUIRED_LATE_FILES = (
    "source_inventory.json",
    "source_snapshot_index.json",
    "final_evidence.json",
)


class C4AManifestCompletionError(RuntimeError):
    pass


def read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise C4AManifestCompletionError(f"invalid JSON {path}: {exc}") from exc


def verify_final_manifest(payload: Mapping[str, Any], source_sha: str, merge_ref_sha: str) -> None:
    if payload.get("stage") != "C4A":
        raise C4AManifestCompletionError("final manifest stage mismatch")
    if payload.get("source_head_sha") != source_sha or payload.get("merge_ref_sha") != merge_ref_sha:
        raise C4AManifestCompletionError("final manifest exact-SHA mismatch")
    if payload.get("holdout_state") != "HOLDOUT_CLOSED" or payload.get("live") != "FORBIDDEN":
        raise C4AManifestCompletionError("final manifest safety drift")
    files = payload.get("files")
    if not isinstance(files, list) or int(payload.get("file_count", -1)) != len(files):
        raise C4AManifestCompletionError("final manifest file-count mismatch")
    indexed = {str(item.get("path")): item for item in files if isinstance(item, Mapping)}
    for required in REQUIRED_LATE_FILES + (PREVERIFY_PATH.name,):
        if required not in indexed:
            raise C4AManifestCompletionError(f"final manifest omits {required}")
    for relative, item in indexed.items():
        path = RESULTS / relative
        if not path.is_file():
            raise C4AManifestCompletionError(f"final manifest file missing: {relative}")
        if path.stat().st_size != int(item.get("size", -1)):
            raise C4AManifestCompletionError(f"final manifest size mismatch: {relative}")
        if evidence.sha256_file(path) != item.get("sha256"):
            raise C4AManifestCompletionError(f"final manifest hash mismatch: {relative}")


def main() -> int:
    source_sha = evidence.exact_sha("C4A_SOURCE_SHA")
    merge_ref_sha = evidence.exact_sha("C4A_MERGE_REF_SHA")
    for relative in REQUIRED_LATE_FILES:
        if not (RESULTS / relative).is_file():
            raise C4AManifestCompletionError(f"required late evidence missing: {relative}")
    final_evidence = read_json(RESULTS / "final_evidence.json")
    inventory = read_json(RESULTS / "source_inventory.json")
    snapshots = read_json(RESULTS / "source_snapshot_index.json")
    if not isinstance(final_evidence, Mapping) or final_evidence.get("status") != "PASS":
        raise C4AManifestCompletionError("final evidence is not PASS")
    if final_evidence.get("source_head_sha") != source_sha or final_evidence.get("merge_ref_sha") != merge_ref_sha:
        raise C4AManifestCompletionError("final evidence exact-SHA mismatch")
    if not isinstance(inventory, Mapping) or inventory.get("status") != "PASS":
        raise C4AManifestCompletionError("source inventory is not PASS")
    if not isinstance(snapshots, Mapping) or snapshots.get("status") != "PASS":
        raise C4AManifestCompletionError("source snapshots are not PASS")
    if inventory.get("source_head_sha") != source_sha or snapshots.get("source_head_sha") != source_sha:
        raise C4AManifestCompletionError("source evidence exact-SHA mismatch")

    pre_files = []
    for path in sorted(RESULTS.rglob("*")):
        if path.is_file() and path.name not in {"manifest.json", PREVERIFY_PATH.name}:
            pre_files.append(
                {
                    "path": str(path.relative_to(RESULTS)),
                    "size": path.stat().st_size,
                    "sha256": evidence.sha256_file(path),
                }
            )
    evidence.write_json(
        PREVERIFY_PATH,
        {
            "schema_version": 1,
            "stage": "C4A",
            "status": "PASS",
            "source_head_sha": source_sha,
            "merge_ref_sha": merge_ref_sha,
            "pre_manifest_file_count": len(pre_files),
            "pre_manifest_files": pre_files,
            "confirmation_opened": False,
            "holdout_state": "HOLDOUT_CLOSED",
            "live": "FORBIDDEN",
        },
    )
    payload = evidence.build_manifest(source_sha, merge_ref_sha)
    evidence.write_json(MANIFEST_PATH, payload)
    retained = read_json(MANIFEST_PATH)
    if not isinstance(retained, Mapping):
        raise C4AManifestCompletionError("final manifest must be an object")
    verify_final_manifest(retained, source_sha, merge_ref_sha)
    print(f"C4A final manifest PASS: {retained['file_count']} hash-bound files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
