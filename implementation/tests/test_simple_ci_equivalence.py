import json
from pathlib import Path

import pytest

from atos.simple_ci_equivalence import (
    SimpleCIEquivalenceError,
    verify_same_run_ci_equivalence,
)

HEAD = "b" * 40
SOURCE = "a" * 40
RUN = "12345"

CI = """name: CI
on: [push, pull_request]
jobs:
  test:
    steps:
      - name: Install
        run: |
          cd implementation
          python -m pip install -e '.[dev]'
      - name: Tests
        run: |
          cd implementation
          python -m pytest
"""

VALIDATION = """name: Freqtrade Validation
jobs:
  atos-tests:
    steps:
      - name: Run pytest
        run: |
          cd implementation
          set -o pipefail; python -m pytest -v --tb=long 2>&1 | tee pytest.log
"""


def _paths(tmp_path: Path, *, ci=CI, validation=VALIDATION, manifest=None):
    ci_path = tmp_path / "ci.yml"
    validation_path = tmp_path / "validation.yml"
    manifest_path = tmp_path / "manifest.json"
    ci_path.write_text(ci)
    validation_path.write_text(validation)
    manifest_path.write_text(
        json.dumps(
            manifest
            or {
                "schema_version": 1,
                "run_id": RUN,
                "head_sha": HEAD,
                "job": "atos-tests",
            }
        )
    )
    return ci_path, validation_path, manifest_path


def _verify(tmp_path: Path, **overrides):
    ci, validation, manifest = _paths(
        tmp_path,
        ci=overrides.pop("ci", CI),
        validation=overrides.pop("validation", VALIDATION),
        manifest=overrides.pop("manifest", None),
    )
    args = dict(
        ci_workflow_path=ci,
        validation_workflow_path=validation,
        atos_manifest_path=manifest,
        head_sha=HEAD,
        run_id=RUN,
        atos_result="success",
        event_name="pull_request",
        pr_number=34,
        run_head_sha=SOURCE,
    )
    args.update(overrides)
    return verify_same_run_ci_equivalence(**args)


def test_valid_same_run_superset_passes(tmp_path):
    result = _verify(tmp_path)
    assert result["verified"] is True
    assert result["verification_mode"] == "same_run_atos_superset"
    assert result["head_sha"] == HEAD
    assert result["merge_commit_verified"] is True
    assert len(result["ci_contract_sha256"]) == 64


def test_atos_failure_is_rejected(tmp_path):
    with pytest.raises(SimpleCIEquivalenceError, match="not successful"):
        _verify(tmp_path, atos_result="failure")


@pytest.mark.parametrize(
    "manifest, message",
    [
        (
            {
                "schema_version": 1,
                "run_id": "wrong",
                "head_sha": HEAD,
                "job": "atos-tests",
            },
            "run_id mismatch",
        ),
        (
            {
                "schema_version": 1,
                "run_id": RUN,
                "head_sha": SOURCE,
                "job": "atos-tests",
            },
            "head_sha mismatch",
        ),
        (
            {
                "schema_version": 1,
                "run_id": RUN,
                "head_sha": HEAD,
                "job": "freqtrade",
            },
            "job mismatch",
        ),
    ],
)
def test_manifest_binding_is_fail_closed(tmp_path, manifest, message):
    with pytest.raises(SimpleCIEquivalenceError, match=message):
        _verify(tmp_path, manifest=manifest)


def test_ci_test_selection_drift_is_rejected(tmp_path):
    narrowed = CI.replace("python -m pytest", "python -m pytest tests/test_one.py")
    with pytest.raises(SimpleCIEquivalenceError, match="test contract drift"):
        _verify(tmp_path, ci=narrowed)


def test_atos_test_selection_drift_is_rejected(tmp_path):
    narrowed = VALIDATION.replace(
        "python -m pytest -v --tb=long",
        "python -m pytest tests/test_one.py -v --tb=long",
    )
    with pytest.raises(SimpleCIEquivalenceError, match="ATOS pytest contract drift"):
        _verify(tmp_path, validation=narrowed)


def test_invalid_pr_number_is_rejected(tmp_path):
    with pytest.raises(SimpleCIEquivalenceError, match="invalid pr_number"):
        _verify(tmp_path, pr_number=0)
