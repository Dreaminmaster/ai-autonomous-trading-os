from __future__ import annotations

from pathlib import Path

import pytest

from atos.c6a_safe_aggregate_v2 import (
    aggregate_window_results_final,
    decide_candidate_safe,
)
from scripts import run_c6a_screen_authoritative as authoritative


def test_authoritative_runner_binds_safe_functions_and_restores_globals(
    tmp_path: Path, monkeypatch
) -> None:
    original_aggregate = authoritative.base.aggregate_window_results
    original_gate = authoritative.base.decide_candidate
    observed = {}

    def fake_run_screen(**kwargs):
        observed["aggregate"] = authoritative.base.aggregate_window_results
        observed["gate"] = authoritative.base.decide_candidate
        return {
            "economic_result": "REJECTED",
            "selected_policy": None,
        }

    monkeypatch.setattr(authoritative.base, "run_screen", fake_run_screen)
    result = authoritative.run_authoritative_screen(
        config={},
        prepare_report={},
        output_dir=tmp_path / "results",
        source_sha="a" * 40,
    )
    assert observed["aggregate"] is aggregate_window_results_final
    assert observed["gate"] is decide_candidate_safe
    assert authoritative.base.aggregate_window_results is original_aggregate
    assert authoritative.base.decide_candidate is original_gate
    assert result["undefined_statistics_fail_closed"] is True
    assert result["undefined_statistics_state"] == "UNDEFINED_WEEKLY_VARIANCE"
    assert result["selected_policy"] is None


def test_authoritative_runner_restores_globals_after_failure(
    tmp_path: Path, monkeypatch
) -> None:
    original_aggregate = authoritative.base.aggregate_window_results
    original_gate = authoritative.base.decide_candidate

    def failure(**kwargs):
        raise RuntimeError("screen failure")

    monkeypatch.setattr(authoritative.base, "run_screen", failure)
    with pytest.raises(RuntimeError, match="screen failure"):
        authoritative.run_authoritative_screen(
            config={},
            prepare_report={},
            output_dir=tmp_path / "results",
            source_sha="b" * 40,
        )
    assert authoritative.base.aggregate_window_results is original_aggregate
    assert authoritative.base.decide_candidate is original_gate
