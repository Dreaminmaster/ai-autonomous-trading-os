from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import atos.c0c_walk_forward as c0c
from atos.c0c_okx_startup import (
    OKX_5M_MAX_STARTUP_CANDLES,
    OKX_STARTUP_ANALYSIS,
    apply_okx_startup_contract,
)


ROOT = Path(__file__).resolve().parents[2]
CORE = ROOT / "implementation" / "scripts" / "c0c_development_core.py"
WORKFLOW = ROOT / ".github" / "workflows" / "c0c-cost-aware-ema.yml"


def test_okx_startup_contract_is_effective_and_idempotent() -> None:
    apply_okx_startup_contract()
    assert OKX_5M_MAX_STARTUP_CANDLES == 1499
    assert c0c.STARTUP_CANDLE_COUNT == 1499
    assert c0c.STARTUP_ANALYSIS == OKX_STARTUP_ANALYSIS
    assert c0c.STARTUP_ANALYSIS is not OKX_STARTUP_ANALYSIS
    assert c0c.STARTUP_ANALYSIS["startup_candidates"] == [499, 999, 1499]
    assert c0c.STARTUP_ANALYSIS["selected_startup_candles"] == 1499
    before = deepcopy(c0c.STARTUP_ANALYSIS)
    apply_okx_startup_contract()
    assert c0c.STARTUP_ANALYSIS == before


def test_parameter_path_matches_freqtrade_strategy_filename_export() -> None:
    source = CORE.read_text(encoding="utf-8")
    assert 'STRATEGY_PATH = Path("freqtrade_data/strategies/c0c_cost_aware_ema.py")' in source
    assert 'PARAM_PATH = STRATEGY_PATH.with_suffix(".json")' in source
    assert "C0CCostAwareEMA.json" not in source


def test_artifact_retains_runtime_config_and_coverage() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    assert "implementation/freqtrade_data/backtest_results/c0c_development/**" in workflow
    assert "implementation/freqtrade_data/c0c_runtime/**" in workflow
    assert "c0c_runtime/c0c_data_coverage.json" not in workflow
