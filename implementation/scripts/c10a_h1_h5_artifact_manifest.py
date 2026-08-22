"""Seal the complete outer C10A authority directory with SHA-256 custody."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any

from atos.c10a_contract import safety_boundary

EXACT_SHA = re.compile(r"[0-9a-f]{40}")
SAFE_RUN_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,159}")


class C10AArtifactManifestError(RuntimeError):
    """Raised unless the outer authority artifact can be sealed exactly once."""


def _canonical_bytes(value: Any) -> bytes:
    return (
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        + "\n"
    ).encode()


def seal_authority_artifact(
    root: Path, *, implementation_sha: str, authoritative_run_id: str
) -> dict[str, Any]:
    if not EXACT_SHA.fullmatch(implementation_sha) or not SAFE_RUN_ID.fullmatch(
        authoritative_run_id
    ):
        raise C10AArtifactManifestError("implementation SHA or run ID is invalid")
    authority = Path(root)
    if authority.is_symlink():
        raise C10AArtifactManifestError("authority artifact root is a symbolic link")
    authority.mkdir(parents=True, exist_ok=True, mode=0o700)
    destination = authority / "artifact_manifest.json"
    temporary = authority / ".artifact_manifest.json.tmp"
    if destination.exists() or temporary.exists():
        raise C10AArtifactManifestError("authority artifact is already sealed")
    entries = sorted(authority.rglob("*"))
    if any(path.is_symlink() for path in entries):
        raise C10AArtifactManifestError("authority artifact contains a symbolic link")
    files = []
    for path in (entry for entry in entries if entry.is_file()):
        data = path.read_bytes()
        files.append(
            {
                "path": path.relative_to(authority).as_posix(),
                "size": len(data),
                "sha256": hashlib.sha256(data).hexdigest(),
            }
        )
    manifest = {
        "schema_version": 1,
        "stage": "C10A_H1_H5_OUTER_AUTHORITY_ARTIFACT",
        "implementation_sha": implementation_sha,
        "authoritative_run_id": authoritative_run_id,
        "file_count": len(files),
        "files": files,
        **safety_boundary(),
    }
    with temporary.open("xb") as handle:
        handle.write(_canonical_bytes(manifest))
        handle.flush()
        os.fsync(handle.fileno())
    try:
        os.link(temporary, destination)
    except FileExistsError as exc:
        raise C10AArtifactManifestError(
            "authority artifact is already sealed"
        ) from exc
    temporary.unlink()
    descriptor = os.open(
        authority,
        os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0),
    )
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--implementation-sha", required=True)
    parser.add_argument("--authoritative-run-id", required=True)
    args = parser.parse_args()
    manifest = seal_authority_artifact(
        args.root,
        implementation_sha=args.implementation_sha,
        authoritative_run_id=args.authoritative_run_id,
    )
    print(
        json.dumps(
            {
                "status": "SEALED",
                "file_count": manifest["file_count"],
                "implementation_sha": args.implementation_sha,
                "authoritative_run_id": args.authoritative_run_id,
                "live_state": "LIVE_FORBIDDEN",
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
