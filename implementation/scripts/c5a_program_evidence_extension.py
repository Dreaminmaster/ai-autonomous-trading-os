#!/usr/bin/env python3
"""Bind the pre-data C5A program guard into primitive evidence."""
from __future__ import annotations

from typing import Any, Mapping

try:
    import scripts.c5a_evidence as evidence
except ModuleNotFoundError:  # pragma: no cover
    import c5a_evidence as evidence  # type: ignore

PROGRAM_GUARD_PATH = evidence.RUNTIME_ROOT / "c5a_program_guard.json"
RESULT_PATH = evidence.RESULTS / "program_guard.json"


class C5AProgramEvidenceError(RuntimeError):
    pass


def verify_program_guard(payload: Mapping[str, Any], source_sha: str) -> None:
    if payload.get("stage") != "C5A" or payload.get("status") != "PASS":
        raise C5AProgramEvidenceError("C5A program guard is not PASS")
    if payload.get("source_head_sha") != source_sha:
        raise C5AProgramEvidenceError("C5A program guard source SHA mismatch")
    if payload.get("config_canonical_sha256") != evidence.EXPECTED_CONFIG_CANONICAL_SHA256:
        raise C5AProgramEvidenceError("C5A program guard config hash mismatch")
    if int(payload.get("prior_stage_result_count", -1)) != 5:
        raise C5AProgramEvidenceError("C5A prior-result count mismatch")
    if int(payload.get("authority_file_count", -1)) != 6:
        raise C5AProgramEvidenceError("C5A authority-file count mismatch")
    if payload.get("c0c_development_test_opened") is not False:
        raise C5AProgramEvidenceError("C0C development test unexpectedly opened")
    if payload.get("prior_confirmation_stages_opened") != []:
        raise C5AProgramEvidenceError("a prior confirmation stage unexpectedly opened")
    if payload.get("prior_selected_policies") != []:
        raise C5AProgramEvidenceError("a prior rejected stage selected a policy")
    if payload.get("c5a_development_start") != "2025-07-07T00:00:00Z":
        raise C5AProgramEvidenceError("C5A development boundary drift")
    if payload.get("c5b_boundary_exclusive") != "2026-01-05T00:00:00Z":
        raise C5AProgramEvidenceError("C5B exclusive boundary drift")
    if payload.get("c5b_reserved_end") != "2026-07-06T00:00:00Z":
        raise C5AProgramEvidenceError("C5B reserved end drift")
    if (
        payload.get("confirmation_opened") is not False
        or payload.get("holdout_state") != "HOLDOUT_CLOSED"
        or payload.get("paper_state") != "PAPER_CLOSED"
        or payload.get("shadow_state") != "SHADOW_CLOSED"
        or payload.get("live") != "FORBIDDEN"
    ):
        raise C5AProgramEvidenceError("C5A program guard safety-state drift")


def main() -> int:
    source_sha = evidence.exact_sha("C5A_SOURCE_SHA")
    merge_sha = evidence.exact_sha("C5A_MERGE_REF_SHA")
    payload = evidence.read_json(PROGRAM_GUARD_PATH)
    if not isinstance(payload, Mapping):
        raise C5AProgramEvidenceError("C5A program guard must be an object")
    verify_program_guard(payload, source_sha)
    evidence.write_json(RESULT_PATH, payload)

    summary = evidence.read_json(evidence.RESULTS / "run_summary.json")
    if not isinstance(summary, dict) or summary.get("status") != "PASS":
        raise C5AProgramEvidenceError("C5A run summary is not PASS")
    if summary.get("source_head_sha") != source_sha or summary.get("merge_ref_sha") != merge_sha:
        raise C5AProgramEvidenceError("C5A run summary exact-SHA mismatch")
    summary.update(
        {
            "program_guard_status": "PASS",
            "prior_stage_result_count": 5,
            "program_authority_file_count": 6,
            "c0c_development_test_opened": False,
            "prior_confirmation_stages_opened": [],
            "prior_selected_policies": [],
            "c5b_boundary_exclusive": "2026-01-05T00:00:00Z",
        }
    )
    evidence.write_json(evidence.RESULTS / "run_summary.json", summary)
    evidence.write_json(
        evidence.RESULTS / "manifest.json",
        evidence.build_manifest(source_sha, merge_sha),
    )
    print("C5A program evidence PASS: prior authority bound before market access")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
