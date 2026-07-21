#!/usr/bin/env python3
"""Rebuild and self-verify the complete C5A evidence manifest."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

try:
    import scripts.c5a_evidence as evidence
except ModuleNotFoundError:  # pragma: no cover
    import c5a_evidence as evidence  # type: ignore

RESULTS = evidence.RESULTS
MANIFEST = RESULTS / "manifest.json"
PREVERIFY = RESULTS / "pre_manifest_verification.json"
REQUIRED = (
    "source_inventory.json",
    "source_snapshot_index.json",
    "contract_retention.json",
    "final_evidence.json",
)


class C5AManifestError(RuntimeError):
    pass


def _read(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise C5AManifestError(f"invalid JSON {path}: {exc}") from exc


def verify(payload: Mapping[str, Any], source_sha: str, merge_sha: str) -> None:
    if payload.get("stage") != "C5A":
        raise C5AManifestError("final manifest stage mismatch")
    if payload.get("source_head_sha") != source_sha or payload.get("merge_ref_sha") != merge_sha:
        raise C5AManifestError("final manifest exact-SHA mismatch")
    if payload.get("holdout_state") != "HOLDOUT_CLOSED" or payload.get("live") != "FORBIDDEN":
        raise C5AManifestError("final manifest safety-state drift")
    files = payload.get("files")
    if not isinstance(files, list) or int(payload.get("file_count", -1)) != len(files):
        raise C5AManifestError("final manifest count mismatch")
    indexed = {str(item.get("path")): item for item in files if isinstance(item, Mapping)}
    for required in REQUIRED + (PREVERIFY.name,):
        if required not in indexed:
            raise C5AManifestError(f"final manifest omits {required}")
    for relative, item in indexed.items():
        path = RESULTS / relative
        if not path.is_file():
            raise C5AManifestError(f"manifest file missing: {relative}")
        if path.stat().st_size != int(item.get("size", -1)):
            raise C5AManifestError(f"manifest size mismatch: {relative}")
        if evidence.sha256_file(path) != item.get("sha256"):
            raise C5AManifestError(f"manifest hash mismatch: {relative}")


def main() -> int:
    source_sha = evidence.exact_sha("C5A_SOURCE_SHA")
    merge_sha = evidence.exact_sha("C5A_MERGE_REF_SHA")
    for relative in REQUIRED:
        if not (RESULTS / relative).is_file():
            raise C5AManifestError(f"required late evidence missing: {relative}")
    final = _read(RESULTS / "final_evidence.json")
    if not isinstance(final, Mapping) or final.get("status") != "PASS" or final.get("errors") != []:
        raise C5AManifestError("final evidence not PASS")
    if final.get("source_head_sha") != source_sha or final.get("merge_ref_sha") != merge_sha:
        raise C5AManifestError("final evidence exact-SHA mismatch")
    retention = _read(RESULTS / "contract_retention.json")
    if not isinstance(retention, Mapping) or retention.get("status") != "PASS":
        raise C5AManifestError("contract retention evidence not PASS")
    if retention.get("source_head_sha") != source_sha or retention.get("merge_ref_sha") != merge_sha:
        raise C5AManifestError("contract retention exact-SHA mismatch")

    files = []
    for path in sorted(RESULTS.rglob("*")):
        if path.is_file() and path.name not in {"manifest.json", PREVERIFY.name}:
            files.append(
                {
                    "path": str(path.relative_to(RESULTS)),
                    "size": path.stat().st_size,
                    "sha256": evidence.sha256_file(path),
                }
            )
    evidence.write_json(
        PREVERIFY,
        {
            "schema_version": 1,
            "stage": "C5A",
            "status": "PASS",
            "source_head_sha": source_sha,
            "merge_ref_sha": merge_sha,
            "pre_manifest_file_count": len(files),
            "pre_manifest_files": files,
            "confirmation_opened": False,
            "holdout_state": "HOLDOUT_CLOSED",
            "live": "FORBIDDEN",
        },
    )
    evidence.write_json(MANIFEST, evidence.build_manifest(source_sha, merge_sha))
    payload = _read(MANIFEST)
    if not isinstance(payload, Mapping):
        raise C5AManifestError("final manifest must be an object")
    verify(payload, source_sha, merge_sha)
    print(f"C5A final manifest PASS: {payload['file_count']} hash-bound files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
