"""Freeze the exact C8A authority result and one-shot workflow closeout."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RESULT = (
    ROOT
    / "docs"
    / "architecture"
    / "phase-c"
    / "c8a-short-horizon-time-series-momentum"
    / "C8A_SHORT_HORIZON_TIME_SERIES_MOMENTUM_RESULT_V1.md"
)
WORKFLOW = ROOT / ".github" / "workflows" / "freqtrade-validation.yml"


def test_c8a_result_is_bound_to_exact_authority_evidence() -> None:
    result = RESULT.read_text()

    assert "`C8A_ECONOMIC_FAIL`" in result
    assert "`f37125f83ef6d35923bbd0a41f6d750e9d40e396`" in result
    assert "`32426312094`" in result
    assert "`96608863918`" in result
    assert "`9427676298`" in result
    assert (
        "sha256:d669ac623ce7bf05b356e8d872a878b3b65dc36ef3a454171604bdb9a7798337"
        in result
    )
    assert "`RETUNING_NOT_AUTHORIZED`" in result
    assert "`RERUN_AFTER_INSPECTION_NOT_AUTHORIZED`" in result
    assert "`SHADOW_CLOSED`" in result
    assert "`LIVE_FORBIDDEN`" in result


def test_c8a_one_shot_dispatch_is_closed_after_result() -> None:
    workflow = WORKFLOW.read_text()

    assert "c8a-h1-h5-authoritative" not in workflow
    assert "c8a_h1_h5_authoritative" not in workflow
    assert "scripts/c8a_h1_h5_capture.py" not in workflow
    assert "scripts/c8a_h1_h5_evaluate.py" not in workflow
