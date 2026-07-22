from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from scripts import c6a_program_guard as guard

CONFIG_PATH = Path(__file__).resolve().parents[1] / "config/c6a_market_neutral_funding_carry.json"


def config() -> dict:
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def write_authorities(root: Path) -> None:
    for _, authorities in (("prior", guard.PRIOR_AUTHORITIES), ("design", guard.DESIGN_AUTHORITIES)):
        for relative, markers in authorities:
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("\n".join(markers), encoding="utf-8")


def test_program_guard_accepts_exact_frozen_authorities(tmp_path: Path) -> None:
    write_authorities(tmp_path)
    payload = guard.verify_authorities(tmp_path, config())
    assert payload["status"] == "PASS"
    assert payload["prior_rejected_stage_count"] == 6
    assert payload["authority_file_count"] == 10
    assert payload["prior_selected_policies"] == []
    assert payload["prior_confirmation_stages_opened"] == []
    assert payload["c6b_state"] == "C6B_CLOSED"
    assert payload["c5b_state"] == "C5B_CLOSED_AND_UNTOUCHED"
    assert payload["live"] == "FORBIDDEN"


def test_program_guard_matches_repository_authority() -> None:
    payload = guard.verify_authorities(guard.ROOT, config())
    assert payload["status"] == "PASS"
    assert payload["authority_file_count"] == 10


def test_program_guard_fails_on_missing_marker(tmp_path: Path) -> None:
    write_authorities(tmp_path)
    relative, markers = guard.DESIGN_AUTHORITIES[-1]
    (tmp_path / relative).write_text("\n".join(markers[:-1]), encoding="utf-8")
    with pytest.raises(guard.C6AProgramGuardError, match="marker mismatch"):
        guard.verify_authorities(tmp_path, config())


def test_program_guard_fails_on_any_config_or_safety_drift(tmp_path: Path) -> None:
    write_authorities(tmp_path)
    drifted = copy.deepcopy(config())
    drifted["c5b_state"] = "OPEN"
    with pytest.raises(Exception):
        guard.verify_authorities(tmp_path, drifted)
