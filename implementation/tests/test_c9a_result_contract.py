"""Freeze the exact C9A authority result and one-shot workflow closeout."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RESULT = (
    ROOT
    / "docs"
    / "architecture"
    / "phase-c"
    / "c9a-continuous-notional-funding-carry"
    / "C9A_CONTINUOUS_NOTIONAL_FUNDING_CARRY_RESULT_V1.md"
)
WORKFLOW = ROOT / ".github" / "workflows" / "freqtrade-validation.yml"


def test_c9a_result_is_bound_to_exact_authority_evidence() -> None:
    result = RESULT.read_text()

    assert "`C9A_ECONOMIC_FAIL`" in result
    assert "`883824b418d24c926423d2902681a9cf84006a26`" in result
    assert "`32446134777`" in result
    assert "`96665935258`" in result
    assert "`9434241599`" in result
    assert (
        "sha256:69ba943583699636dde16d82ac8306108750b9e58810c415cd80e0e83c881175"
        in result
    )
    assert "`RETUNING_NOT_AUTHORIZED`" in result
    assert "`RERUN_AFTER_INSPECTION_NOT_AUTHORIZED`" in result
    assert "`C9B_CLOSED`" in result
    assert "`PAPER_CLOSED`" in result
    assert "`SHADOW_CLOSED`" in result
    assert "`LIVE_FORBIDDEN`" in result


def test_c9a_one_shot_dispatch_is_closed_after_result() -> None:
    workflow = WORKFLOW.read_text()

    assert "c9a-w1-w5-authoritative" not in workflow
    assert "c9a_w1_w5_authoritative" not in workflow
    assert "scripts/c9a_w1_w5_capture.py" not in workflow
    assert "scripts/c9a_w1_w5_evaluate.py" not in workflow
