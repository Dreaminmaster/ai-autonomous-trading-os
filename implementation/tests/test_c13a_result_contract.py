"""Freeze the exact C13A authority result and one-shot workflow closeout."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RESULT = (
    ROOT
    / "docs"
    / "architecture"
    / "phase-c"
    / "c13a-cross-sectional-lottery-demand"
    / "C13A_CROSS_SECTIONAL_LOTTERY_DEMAND_RESULT_V1.md"
)
WORKFLOW = ROOT / ".github" / "workflows" / "freqtrade-validation.yml"


def test_c13a_result_is_bound_to_exact_authority_evidence() -> None:
    result = RESULT.read_text(encoding="utf-8")

    assert "`C13A_ECONOMIC_FAIL`" in result
    assert "`1178918c5f31cb1f632ef8e25ce1028ee9408f8b`" in result
    assert "`cb401b3f6d9b0e71ef9beb887329962bae9eccbc`" in result
    assert "`32975423962`" in result
    assert "`98198866199`" in result
    assert "`9609883268`" in result
    assert (
        "sha256:d1f6afe6e101b253b4cc7b2ef35681c8478369dd76bcc6644bedb4d88ccb83c5"
        in result
    )
    assert (
        "`57d3ed01274f7a7894ca1e4a0b876bda0e783dc5830145f7ffa65854350dbd87`"
        in result
    )
    assert (
        "`176c73531a9bdac5293abb9352d905615ab8292daf74bb2e3b405dc2b14c67f5`"
        in result
    )
    assert "`RETUNING_NOT_AUTHORIZED`" in result
    assert "`AUTHORITATIVE_RERUN_NOT_AUTHORIZED`" in result
    assert "`PAPER_CLOSED`" in result
    assert "`SHADOW_CLOSED`" in result
    assert "`LIVE_FORBIDDEN`" in result


def test_c13a_one_shot_dispatch_is_closed_after_result() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")

    assert "c13a-h1-h5-authoritative" not in workflow
    assert "c13a_h1_h5_authoritative" not in workflow
    assert "scripts/c13a_h1_h5_capture.py" not in workflow
    assert "scripts/c13a_h1_h5_evaluate.py" not in workflow
