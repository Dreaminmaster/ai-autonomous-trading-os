#!/usr/bin/env python3
"""Rebuild and self-verify the final C3A manifest after inventory and finalization."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

try:  # pytest imports through the repository namespace; direct execution uses the script directory.
    import scripts.c3a_evidence as evidence
except ModuleNotFoundError:  # pragma: no cover - exercised by direct workflow execution
    import c3a_evidence as evidence  # type: ignore


RESULTS = evidence.RESULTS
MANIFEST_PATH = RESULTS / "manifest.json"
REQUIRED_LATE_FILES = ("source_inventory.json", "final_evidence.json")


class C3AManifestCompletionError(RuntimeError):
    pass


def read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise C3AManifestCompletionError(f"invalid JSON {path}: {exc}") from exc


def verify_final_manifest(payload: Mapping[str, Any], source_sha: str, merge_ref_sha: str) -> None:
    if payload.get("stage") != "C3A":
        raise C3AManifestCompletionError("final manifest stage mismatch")
    if payload.get("source_head_sha") != source_sha or payload.get("merge_ref_sha") != merge_ref_sha:
        raise C3AManifestCompletionError("final manifest exact-SHA mismatch")
    if payload.get("holdout_state") != "HOLDOUT_CLOSED" or payload.get("live") != "FORBIDDEN":
        raise C3AManifestCompletionError("final manifest safety drift")
    files = payload.get("files")
    if not isinstance(files, list) or int(payload.get("file_count", -1)) != len(files):
        raise C3AManifestCompletionError("final manifest file count mismatch")
    indexed = {str(item.get("path")): item for item in files if isinstance(item, Mapping)}
    for required in REQUIRED_LATE_FILES:
        if required not in indexed:
            raise C3AManifestCompletionError(f"final manifest omits {required}")
    for relative, item in indexed.items():
        path = RESULTS / relative
        if not path.is_file():
            raise C3AManifestCompletionError(f"final manifest file missing: {relative}")
        if path.stat().st_size != int(item.get("size", -1)):
            raise C3AManifestCompletionError(f"final manifest size mismatch: {relative}")
        if evidence.sha256_file(path) != item.get("sha256"):
            raise C3AManifestCompletionError(f"final manifest hash mismatch: {relative}")


def main() -> int:
    source_sha = evidence.exact_sha("C3A_SOURCE_SHA")
    merge_ref_sha = evidence.exact_sha("C3A_MERGE_REF_SHA")
    for relative in REQUIRED_LATE_FILES:
        path = RESULTS / relative
        if not path.is_file():
            raise C3AManifestCompletionError(f"required late evidence missing: {relative}")
    final_evidence = read_json(RESULTS / "final_evidence.json")
    source_inventory = read_json(RESULTS / "source_inventory.json")
    if not isinstance(final_evidence, Mapping) or final_evidence.get("status") != "PASS":
        raise C3AManifestCompletionError("final evidence is not PASS")
    if final_evidence.get("source_head_sha") != source_sha or final_evidence.get("merge_ref_sha") != merge_ref_sha:
        raise C3AManifestCompletionError("final evidence exact-SHA mismatch")
    if not isinstance(source_inventory, Mapping) or source_inventory.get("status") != "PASS":
        raise C3AManifestCompletionError("source inventory is not PASS")
    if source_inventory.get("source_head_sha") != source_sha:
        raise C3AManifestCompletionError("source inventory exact-SHA mismatch")

    payload = evidence.build_manifest(source_sha, merge_ref_sha)
    evidence.write_json(MANIFEST_PATH, payload)
    retained = read_json(MANIFEST_PATH)
    if not isinstance(retained, Mapping):
        raise C3AManifestCompletionError("final manifest must be an object")
    verify_final_manifest(retained, source_sha, merge_ref_sha)
    print(f"C3A final manifest PASS: {retained['file_count']} hash-bound files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
