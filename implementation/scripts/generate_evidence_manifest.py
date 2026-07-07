#!/usr/bin/env python3
"""Generate evidence manifest for CI artifact provenance + preflight."""
import json, os, sys
job = sys.argv[1] if len(sys.argv) > 1 else "unknown"
run_id = os.environ["GITHUB_RUN_ID"]; head_sha = os.environ["GITHUB_SHA"]
manifest = {"schema_version": 1, "run_id": run_id, "head_sha": head_sha, "job": job}
with open("evidence_manifest.json", "w") as f: json.dump(manifest, f, indent=2)
print(f"Manifest written for job={job} run={run_id} sha={head_sha[:8]}")
