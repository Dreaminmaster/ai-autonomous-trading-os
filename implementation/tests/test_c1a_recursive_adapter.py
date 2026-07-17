from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "implementation" / "scripts"


def _adapter_module():
    sys.path.insert(0, str(SCRIPTS))
    try:
        sys.modules.pop("run_c0c_development", None)
        return importlib.import_module("run_c0c_development")
    finally:
        sys.path.remove(str(SCRIPTS))


def test_explicit_zero_variance_without_table_is_valid_evidence(tmp_path: Path) -> None:
    module = _adapter_module()
    log = tmp_path / "recursive.log"
    log.write_text(
        "\n".join(
            [
                "Calculating indicators using startup candle of 499.",
                "Calculating indicators using startup candle of 999.",
                "Calculating indicators using startup candle of 1499.",
                "No variance on indicator(s) found due to recursive formula.",
                "No lookahead bias on indicators found.",
            ]
        ),
        encoding="utf-8",
    )

    result = module.validate_recursive_analysis_log(
        log,
        startup_count=1499,
        required_indicators=["atr_14", "donchian_high_480"],
        max_variance_pct=0.1,
    )

    assert result["status"] == "PASS"
    assert result["explicit_zero_variance_marker"] is True
    assert result["selected_startup_execution_proved"] is True
    assert result["indicator_variance_pct"] == {
        "atr_14": 0.0,
        "donchian_high_480": 0.0,
    }
    assert set(result["indicator_evidence_basis"].values()) == {
        "FREQTRADE_EXPLICIT_NO_RECURSIVE_VARIANCE_MARKER"
    }


def test_explicit_zero_variance_requires_selected_startup_execution(tmp_path: Path) -> None:
    module = _adapter_module()
    log = tmp_path / "recursive.log"
    log.write_text(
        "No variance on indicator(s) found due to recursive formula.\n"
        "No lookahead bias on indicators found.\n",
        encoding="utf-8",
    )

    with pytest.raises(module.C0CWalkForwardError, match="missing selected startup 1499"):
        module.validate_recursive_analysis_log(
            log,
            startup_count=1499,
            required_indicators=["atr_14"],
            max_variance_pct=0.1,
        )


def test_explicit_zero_variance_does_not_override_lookahead_failure(tmp_path: Path) -> None:
    module = _adapter_module()
    log = tmp_path / "recursive.log"
    log.write_text(
        "Calculating indicators using startup candle of 1499.\n"
        "No variance on indicator(s) found due to recursive formula.\n"
        "=> found lookahead in indicator atr_14\n"
        "No lookahead bias on indicators found.\n",
        encoding="utf-8",
    )

    with pytest.raises(module.C0CWalkForwardError, match="reported indicator lookahead"):
        module.validate_recursive_analysis_log(
            log,
            startup_count=1499,
            required_indicators=["atr_14"],
            max_variance_pct=0.1,
        )


def test_numeric_table_output_still_uses_frozen_parser(tmp_path: Path) -> None:
    module = _adapter_module()
    log = tmp_path / "recursive.log"
    log.write_text(
        "┃ indicators ┃ 499 ┃ 999 ┃ 1499 ┃\n"
        "┃ atr_14     ┃ -   ┃ -   ┃ 0.01% ┃\n"
        "No lookahead bias on indicators found.\n",
        encoding="utf-8",
    )

    result = module.validate_recursive_analysis_log(
        log,
        startup_count=1499,
        required_indicators=["atr_14"],
        max_variance_pct=0.1,
    )
    assert result["status"] == "PASS"
    assert result["indicator_variance_pct"]["atr_14"] == pytest.approx(0.01)
    assert result["indicator_evidence_basis"]["atr_14"] == "NUMERIC_RICH_TABLE_VALUE"
