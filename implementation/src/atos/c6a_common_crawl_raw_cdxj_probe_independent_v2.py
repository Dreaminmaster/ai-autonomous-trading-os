"""Frozen-inventory wrapper for the raw CDXJ independent reviewer.

This layer independently pins the exact canonical inventory bytes before
running the retained-evidence reviewer. It imports no producer, transport,
binary-search, or gzip execution code.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from atos.c6a_common_crawl_raw_cdxj_probe_independent_v3 import (
    review_probe as review_retained_evidence,
)

STAGE = "C6A_COMMON_CRAWL_RAW_CDXJ_ACCESS_PROBE"
FROZEN_INVENTORY_SHA256 = (
    "d68ba30bf038d9b9d497edcd26c550ac6c749864a2ca76c0e13981fabb0a897a"
)


def review_probe(root: Path) -> dict[str, Any]:
    errors: list[str] = []
    snapshot_path = root / "inventory_snapshot.json"
    result_path = root / "probe_result.json"
    try:
        snapshot_bytes = snapshot_path.read_bytes()
    except OSError as exc:
        errors.append(f"cannot read frozen inventory snapshot: {exc}")
        snapshot_bytes = b""
    observed_digest = hashlib.sha256(snapshot_bytes).hexdigest()
    if observed_digest != FROZEN_INVENTORY_SHA256:
        errors.append("independent frozen inventory digest mismatch")
    try:
        result = json.loads(result_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        errors.append(
            f"cannot read probe result for frozen binding: {exc}"
        )
        result = {}
    if not isinstance(result, dict):
        errors.append(
            "probe result for frozen binding is not an object"
        )
        result = {}
    if result.get("stage") != STAGE:
        errors.append("probe result stage drift in frozen binding")
    if result.get("inventory_sha256") != FROZEN_INVENTORY_SHA256:
        errors.append("probe result frozen inventory digest mismatch")

    retained = review_retained_evidence(root)
    retained_errors = retained.get("errors")
    if retained.get("status") != "PASS":
        if isinstance(retained_errors, list):
            errors.extend(str(error) for error in retained_errors)
        else:
            errors.append(
                "retained-evidence reviewer failed without errors"
            )
    output = dict(retained)
    output["status"] = "PASS" if not errors else "FAIL"
    output["errors"] = errors
    output["frozen_inventory_sha256"] = FROZEN_INVENTORY_SHA256
    return output
