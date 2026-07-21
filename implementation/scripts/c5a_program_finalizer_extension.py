#!/usr/bin/env python3
"""Independently verify the program-guard evidence after base finalization."""
from __future__ import annotations

from typing import Any, Mapping

try:
    import scripts.c5a_evidence as evidence
    import scripts.c5a_program_evidence_extension as program_evidence
except ModuleNotFoundError:  # pragma: no cover
    import c5a_evidence as evidence  # type: ignore
    import c5a_program_evidence_extension as program_evidence  # type: ignore

FINAL_PATH = evidence.RESULTS / "final_evidence.json"


class C5AProgramFinalizerError(RuntimeError):
    pass


def main() -> int:
    source_sha = evidence.exact_sha("C5A_SOURCE_SHA")
    merge_sha = evidence.exact_sha("C5A_MERGE_REF_SHA")
    final = evidence.read_json(FINAL_PATH)
    if not isinstance(final, dict) or final.get("status") != "PASS" or final.get("errors") != []:
        raise C5AProgramFinalizerError("base C5A final evidence is not PASS")
    if final.get("source_head_sha") != source_sha or final.get("merge_ref_sha") != merge_sha:
        raise C5AProgramFinalizerError("base C5A final evidence exact-SHA mismatch")

    guard = evidence.read_json(evidence.RESULTS / "program_guard.json")
    if not isinstance(guard, Mapping):
        raise C5AProgramFinalizerError("retained C5A program guard must be an object")
    program_evidence.verify_program_guard(guard, source_sha)

    summary = evidence.read_json(evidence.RESULTS / "run_summary.json")
    if not isinstance(summary, Mapping):
        raise C5AProgramFinalizerError("C5A run summary must be an object")
    expected = {
        "program_guard_status": "PASS",
        "prior_stage_result_count": 5,
        "program_authority_file_count": 6,
        "c0c_development_test_opened": False,
        "prior_confirmation_stages_opened": [],
        "prior_selected_policies": [],
        "c5b_boundary_exclusive": "2026-01-05T00:00:00Z",
    }
    for key, value in expected.items():
        if summary.get(key) != value:
            raise C5AProgramFinalizerError(f"run summary program field mismatch: {key}")

    checks = list(final.get("checks", []))
    extension_checks = [
        "program_guard:INDEPENDENT_PASS",
        "prior_stage_results:5_REJECTED",
        "prior_confirmations:NONE_OPEN",
        "prior_selected_policies:NONE",
        "c5b_boundary:CLOSED",
        "run_summary_program_binding:PASS",
    ]
    final.update(
        {
            "checks": checks + extension_checks,
            "checks_passed": len(checks) + len(extension_checks),
            "program_guard_checks": extension_checks,
            "errors": [],
            "status": "PASS",
            "confirmation_opened": False,
            "holdout_state": "HOLDOUT_CLOSED",
            "paper_state": "PAPER_CLOSED",
            "shadow_state": "SHADOW_CLOSED",
            "live": "FORBIDDEN",
        }
    )
    evidence.write_json(FINAL_PATH, final)
    print(f"C5A program finalizer PASS: {len(extension_checks)} governance checks")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
