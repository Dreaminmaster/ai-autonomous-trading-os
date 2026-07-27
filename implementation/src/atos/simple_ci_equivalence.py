"""Prove that the same-run ATOS job subsumes the repository's simple CI contract."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import yaml

EXPECTED_CI_WORKFLOW_ID = 305746223
EXPECTED_CI_WORKFLOW_PATH = ".github/workflows/ci.yml"
EXPECTED_VALIDATION_WORKFLOW_PATH = ".github/workflows/freqtrade-validation.yml"


class SimpleCIEquivalenceError(RuntimeError):
    """Raised when same-run evidence cannot prove the simple CI contract."""


def _load_yaml(path: str | Path) -> tuple[dict[str, Any], bytes]:
    candidate = Path(path)
    try:
        raw = candidate.read_bytes()
    except OSError as exc:
        raise SimpleCIEquivalenceError(f"workflow unreadable: {candidate}: {exc}") from exc
    try:
        payload = yaml.safe_load(raw)
    except yaml.YAMLError as exc:
        raise SimpleCIEquivalenceError(f"workflow YAML invalid: {candidate}: {exc}") from exc
    if not isinstance(payload, dict):
        raise SimpleCIEquivalenceError(f"workflow payload is not a mapping: {candidate}")
    return payload, raw


def _load_manifest(path: str | Path) -> dict[str, Any]:
    candidate = Path(path)
    try:
        payload = json.loads(candidate.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise SimpleCIEquivalenceError(f"ATOS manifest invalid: {candidate}: {exc}") from exc
    if not isinstance(payload, dict):
        raise SimpleCIEquivalenceError("ATOS manifest is not a mapping")
    return payload


def _normalise_run(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    return "\n".join(line.strip() for line in value.strip().splitlines() if line.strip())


def _named_step(
    workflow: dict[str, Any], job_name: str, step_name: str
) -> dict[str, Any]:
    jobs = workflow.get("jobs")
    if not isinstance(jobs, dict):
        raise SimpleCIEquivalenceError("workflow jobs mapping missing")
    job = jobs.get(job_name)
    if not isinstance(job, dict):
        raise SimpleCIEquivalenceError(f"workflow job missing: {job_name}")
    steps = job.get("steps")
    if not isinstance(steps, list):
        raise SimpleCIEquivalenceError(f"workflow steps missing: {job_name}")
    matches = [
        step
        for step in steps
        if isinstance(step, dict) and step.get("name") == step_name
    ]
    if len(matches) != 1:
        raise SimpleCIEquivalenceError(
            f"expected one {job_name}/{step_name} step, found {len(matches)}"
        )
    return matches[0]


def _named_step_run(workflow: dict[str, Any], job_name: str, step_name: str) -> str:
    run = _normalise_run(_named_step(workflow, job_name, step_name).get("run"))
    if not run:
        raise SimpleCIEquivalenceError(f"run command missing: {job_name}/{step_name}")
    return run


def verify_same_run_ci_equivalence(
    *,
    ci_workflow_path: str | Path,
    validation_workflow_path: str | Path,
    atos_manifest_path: str | Path,
    head_sha: str,
    run_id: str,
    atos_result: str,
    event_name: str,
    pr_number: int | None,
    run_head_sha: str,
) -> dict[str, Any]:
    """Return legacy-compatible evidence after a fail-closed same-run proof.

    The Freqtrade Validation ``atos-tests`` job runs full pytest on the exact
    checked-out commit and uploads a manifest bound to the same workflow run.
    This function proves that the ATOS command is a logging/verbosity superset
    of the repository's simple CI test selection, while also pinning the simple
    CI wrapper that preserves pytest's exit status and enforces failure.
    """
    if not isinstance(head_sha, str) or len(head_sha) < 7:
        raise SimpleCIEquivalenceError(f"invalid head_sha: {head_sha!r}")
    if not isinstance(run_head_sha, str) or len(run_head_sha) < 7:
        raise SimpleCIEquivalenceError(f"invalid run_head_sha: {run_head_sha!r}")
    if not isinstance(run_id, str) or not run_id.strip():
        raise SimpleCIEquivalenceError(f"invalid run_id: {run_id!r}")
    if atos_result != "success":
        raise SimpleCIEquivalenceError(f"atos-tests not successful: {atos_result}")
    if pr_number is not None and (type(pr_number) is not int or pr_number <= 0):
        raise SimpleCIEquivalenceError(f"invalid pr_number: {pr_number!r}")

    ci, ci_raw = _load_yaml(ci_workflow_path)
    validation, validation_raw = _load_yaml(validation_workflow_path)
    manifest = _load_manifest(atos_manifest_path)

    if ci.get("name") != "CI":
        raise SimpleCIEquivalenceError("simple CI workflow name drift")
    if validation.get("name") != "Freqtrade Validation":
        raise SimpleCIEquivalenceError("validation workflow name drift")

    ci_install = _named_step_run(ci, "test", "Install")
    ci_test_step = _named_step(ci, "test", "Tests")
    ci_tests = _normalise_run(ci_test_step.get("run"))
    ci_enforce_step = _named_step(ci, "test", "Enforce test result")
    ci_enforce = _normalise_run(ci_enforce_step.get("run"))
    atos_test_step = _named_step(validation, "atos-tests", "Run pytest")
    atos_tests = _normalise_run(atos_test_step.get("run"))

    expected_install = "cd implementation\npython -m pip install -e '.[dev]'"
    expected_ci_tests = (
        "cd implementation\n"
        "set +e\n"
        "python -m pytest 2>&1 | tee pytest.log\n"
        "status=${PIPESTATUS[0]}\n"
        'echo "exit_code=${status}" >> "$GITHUB_OUTPUT"\n'
        'exit "$status"'
    )
    expected_atos_tests = (
        "cd implementation\n"
        "set -o pipefail; python -m pytest -v --tb=long 2>&1 | tee pytest.log"
    )
    if ci_install != expected_install:
        raise SimpleCIEquivalenceError("simple CI install contract drift")
    if ci_tests != expected_ci_tests:
        raise SimpleCIEquivalenceError("simple CI test contract drift")
    if ci_test_step.get("id") != "tests":
        raise SimpleCIEquivalenceError("simple CI test step id drift")
    if ci_test_step.get("continue-on-error") is not True:
        raise SimpleCIEquivalenceError("simple CI test capture contract drift")
    if ci_enforce_step.get("if") != "steps.tests.outcome == 'failure'":
        raise SimpleCIEquivalenceError("simple CI failure-enforcement condition drift")
    if ci_enforce != "exit 1":
        raise SimpleCIEquivalenceError("simple CI failure-enforcement command drift")
    if atos_tests != expected_atos_tests:
        raise SimpleCIEquivalenceError("same-run ATOS pytest contract drift")
    if atos_test_step.get("continue-on-error") not in (None, False):
        raise SimpleCIEquivalenceError("same-run ATOS pytest may not continue on error")

    expected_manifest = {
        "schema_version": 1,
        "run_id": run_id,
        "head_sha": head_sha,
        "job": "atos-tests",
    }
    for key, expected in expected_manifest.items():
        if manifest.get(key) != expected:
            raise SimpleCIEquivalenceError(
                f"ATOS manifest {key} mismatch: {manifest.get(key)!r} != {expected!r}"
            )

    return {
        "schema_version": 1,
        "workflow_id": EXPECTED_CI_WORKFLOW_ID,
        "workflow_name": "CI",
        "workflow_path": EXPECTED_CI_WORKFLOW_PATH,
        "run_id": run_id,
        "head_sha": head_sha,
        "run_head_sha": run_head_sha,
        "event": event_name,
        "pr_number": pr_number,
        "pr_association_mode": "same_run_atos_superset",
        "provenance_mode": "same_run_exact_checkout",
        "merge_commit_verified": event_name != "pull_request" or head_sha != run_head_sha,
        "status": "completed",
        "conclusion": "success",
        "verified": True,
        "verification_mode": "same_run_atos_superset",
        "ci_failure_enforcement_verified": True,
        "evidence_workflow_path": EXPECTED_VALIDATION_WORKFLOW_PATH,
        "source_job": "atos-tests",
        "ci_contract_sha256": hashlib.sha256(ci_raw).hexdigest(),
        "validation_contract_sha256": hashlib.sha256(validation_raw).hexdigest(),
    }
