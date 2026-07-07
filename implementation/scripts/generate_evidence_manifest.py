#!/usr/bin/env python3
"""Generate evidence manifest for CI artifact provenance."""
import json, os, sys
from pathlib import Path

job = sys.argv[1] if len(sys.argv) > 1 else "unknown"
manifest = {
    "schema_version": 1,
    "run_id": os.environ.get("GITHUB_RUN_ID", "local"),
    "head_sha": os.environ.get("GITHUB_SHA", "local"),
    "job": job,
}
Path("implementation/evidence_manifest.json").write_text(json.dumps(manifest, indent=2))
print(f"Manifest written for job={job} run={manifest['run_id']} sha={manifest['head_sha'][:8]}")
