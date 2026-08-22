"""Freeze the exact C11A authority result and one-shot workflow closeout."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RESULT = (
    ROOT
    / "docs"
    / "architecture"
    / "phase-c"
    / "c11a-cross-sectional-idiosyncratic-volatility"
    / "C11A_CROSS_SECTIONAL_IDIOSYNCRATIC_VOLATILITY_RESULT_V1.md"
)
WORKFLOW = ROOT / ".github" / "workflows" / "freqtrade-validation.yml"


def test_c11a_result_is_bound_to_exact_authority_evidence() -> None:
    result = RESULT.read_text(encoding="utf-8")

    assert "`C11A_ECONOMIC_FAIL`" in result
    assert "`55defac09a2001acfa644da9f68e7aa0d8f13caa`" in result
    assert "`32566697392`" in result
    assert "`97016244490`" in result
    assert "`9474465568`" in result
    assert (
        "sha256:83a0b6ecdcd64c04ef3116cb62e54b819444aa7a70cada45266381c81411edbb"
        in result
    )
    assert (
        "`97d84912a21629fe82cf83998ef2acc4829d214add8e5796f00f64990bccc248`"
        in result
    )
    assert (
        "`95afe47c84b4171a5bbddf6ac2243ff402cbe24c3f763ef34739dc7ac7acf5f8`"
        in result
    )
    assert "`RETUNING_NOT_AUTHORIZED`" in result
    assert "`AUTHORITATIVE_RERUN_NOT_AUTHORIZED`" in result
    assert "`PAPER_CLOSED`" in result
    assert "`SHADOW_CLOSED`" in result
    assert "`LIVE_FORBIDDEN`" in result


def test_c11a_one_shot_dispatch_is_closed_after_result() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")

    assert "c11a-h1-h5-authoritative" not in workflow
    assert "c11a_h1_h5_authoritative" not in workflow
    assert "scripts/c11a_h1_h5_capture.py" not in workflow
    assert "scripts/c11a_h1_h5_evaluate.py" not in workflow
