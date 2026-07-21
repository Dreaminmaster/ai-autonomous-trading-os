from __future__ import annotations

import copy
from pathlib import Path

import pytest

from scripts import c5a_program_guard as guard
from test_c5a_derivatives_crowding import config


def _write_authorities(root: Path) -> None:
    for relative, markers in guard.AUTHORITIES:
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\n".join(markers), encoding="utf-8")


def test_program_guard_accepts_all_frozen_authorities(tmp_path: Path) -> None:
    _write_authorities(tmp_path)
    payload = guard.verify_authorities(tmp_path, config())
    assert payload["status"] == "PASS"
    assert payload["prior_stage_result_count"] == 5
    assert payload["authority_file_count"] == 6
    assert payload["c0c_development_test_opened"] is False
    assert payload["prior_confirmation_stages_opened"] == []
    assert payload["prior_selected_policies"] == []
    assert payload["c5b_boundary_exclusive"] == "2026-01-05T00:00:00Z"
    assert payload["confirmation_opened"] is False
    assert payload["live"] == "FORBIDDEN"


def test_program_guard_matches_repository_authority() -> None:
    payload = guard.verify_authorities(guard.ROOT, config())
    assert payload["status"] == "PASS"
    assert payload["authority_file_count"] == 6
    assert payload["prior_confirmation_stages_opened"] == []
    assert payload["prior_selected_policies"] == []


def test_program_guard_fails_on_missing_authority_marker(tmp_path: Path) -> None:
    _write_authorities(tmp_path)
    relative, markers = guard.AUTHORITIES[0]
    (tmp_path / relative).write_text("\n".join(markers[:-1]), encoding="utf-8")
    with pytest.raises(guard.C5AProgramGuardError, match="authority marker mismatch"):
        guard.verify_authorities(tmp_path, config())


def test_program_guard_fails_on_boundary_or_confirmation_drift(tmp_path: Path) -> None:
    _write_authorities(tmp_path)
    drifted = copy.deepcopy(config())
    drifted["reserved_confirmation"]["start"] = "2026-01-12T00:00:00Z"
    with pytest.raises(Exception):
        guard.verify_authorities(tmp_path, drifted)
