"""Build a retained synthetic-only evidence package for C7A weekly evaluation."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any, Mapping, Sequence

from atos.c7a_contract import C7AError, assert_synthetic_only
from atos.c7a_weekly_evaluation import (
    COST_LABELS,
    aggregate_candidate_weekly,
    aggregate_comparator_weekly,
    decide_c7a,
)
from atos.c7a_weekly_independent import COMPARATORS, review_weekly_evidence


def canonical_bytes(value: Any) -> bytes:
    return (
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        + "\n"
    ).encode("utf-8")


def atomic_write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    data = canonical_bytes(value)
    with temporary.open("wb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def build_manifest(root: Path) -> dict[str, Any]:
    files = []
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        relative = path.relative_to(root).as_posix()
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
    manifest = {
        "schema_version": 1,
        "stage": "C7A_SYNTHETIC_WEEKLY_EVIDENCE_PACKAGE",
        "file_count": len(files),
        "files": files,
        "real_data_authorized": False,
        "network_execution_authorized": False,
        "economic_run_authorized": False,
        "paper_state": "PAPER_CLOSED",
        "shadow_state": "SHADOW_CLOSED",
        "live_state": "LIVE_FORBIDDEN",
    }
    atomic_write(root / "manifest.json", manifest)
    return manifest


def build_synthetic_evidence_package(
    output_root: Path,
    *,
    metadata: Mapping[str, Any],
    candidate_rows: Mapping[str, Sequence[Mapping[str, Any]]],
    comparator_rows: Mapping[str, Sequence[Mapping[str, Any]]],
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    if output_root.exists():
        raise C7AError(f"C7A evidence output already exists: {output_root}")
    assert_synthetic_only(metadata)
    if set(candidate_rows) != set(COST_LABELS):
        raise C7AError("C7A evidence candidate cost-label set mismatch")
    if set(comparator_rows) != set(COMPARATORS):
        raise C7AError("C7A evidence comparator set mismatch")

    candidate_aggregates = {
        label: aggregate_candidate_weekly(
            candidate_rows[label], cost_label=label, metadata=metadata
        )
        for label in COST_LABELS
    }
    comparator_aggregates = {
        comparator: aggregate_comparator_weekly(
            comparator_rows[comparator],
            comparator_id=comparator,
            metadata=metadata,
        )
        for comparator in COMPARATORS
    }
    decision = decide_c7a(
        expected=candidate_aggregates["1.0x"],
        stress_1_5x=candidate_aggregates["1.5x"],
        stress_2_0x=candidate_aggregates["2.0x"],
        always_on=comparator_aggregates["always_on_funding_rank"],
    )
    evidence = {
        "metadata": dict(metadata),
        "candidate_rows": {label: list(candidate_rows[label]) for label in COST_LABELS},
        "comparator_rows": {
            comparator: list(comparator_rows[comparator]) for comparator in COMPARATORS
        },
        "producer_candidate_aggregates": candidate_aggregates,
        "producer_comparator_aggregates": comparator_aggregates,
        "producer_decision": decision,
    }
    review = review_weekly_evidence(evidence)

    output_root.mkdir(parents=True, exist_ok=False)
    atomic_write(output_root / "metadata.json", evidence["metadata"])
    for label in COST_LABELS:
        atomic_write(
            output_root / "candidate_rows" / f"{label}.json",
            evidence["candidate_rows"][label],
        )
    for comparator in COMPARATORS:
        atomic_write(
            output_root / "comparator_rows" / f"{comparator}.json",
            evidence["comparator_rows"][comparator],
        )
    atomic_write(
        output_root / "producer_candidate_aggregates.json", candidate_aggregates
    )
    atomic_write(
        output_root / "producer_comparator_aggregates.json", comparator_aggregates
    )
    atomic_write(output_root / "producer_decision.json", decision)
    atomic_write(output_root / "independent_review.json", review)
    manifest = build_manifest(output_root)
    return decision, review, manifest
