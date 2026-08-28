"""Freeze the exact C14A authority result and one-shot workflow closeout."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RESULT = (
    ROOT
    / "docs"
    / "architecture"
    / "phase-c"
    / "c14a-cross-sectional-liquidity-risk"
    / "C14A_CROSS_SECTIONAL_LIQUIDITY_RISK_RESULT_V1.md"
)
WORKFLOW = ROOT / ".github" / "workflows" / "freqtrade-validation.yml"


def test_c14a_result_is_bound_to_exact_authority_evidence() -> None:
    result = RESULT.read_text(encoding="utf-8")

    assert "`C14A_ECONOMIC_FAIL`" in result
    assert "`655407ac9b46c6962c0a21e2d29d769ea3721b06`" in result
    assert "`ae454a4a0f65407c7b039e0575a08222be9e7e80`" in result
    assert "`33096963409`" in result
    assert "`98604287667`" in result
    assert "`9657445380`" in result
    assert (
        "sha256:c39c5d253997e8fbcc2b14b80995e640d0fb9688433f07140b64a2b38f5f5cb2"
        in result
    )
    assert (
        "`426b4e2bc243617d19723b3d6f45bcb90f105f9e34e192b1da2725d244442495`"
        in result
    )
    assert (
        "`542c590f57414a88d5a3682e139bab6afa9fb164d99a7cc884977c40da89638a`"
        in result
    )
    assert "`RETUNING_NOT_AUTHORIZED`" in result
    assert "`AUTHORITATIVE_RERUN_NOT_AUTHORIZED`" in result
    assert "`PAPER_CLOSED`" in result
    assert "`SHADOW_CLOSED`" in result
    assert "`LIVE_FORBIDDEN`" in result


def test_c14a_one_shot_dispatch_is_closed_after_result() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")

    assert "c14a-h1-h5-authoritative" not in workflow
    assert "c14a_h1_h5_authoritative" not in workflow
    assert "scripts/c14a_h1_h5_capture.py" not in workflow
    assert "scripts/c14a_h1_h5_evaluate.py" not in workflow
