from __future__ import annotations

import ast
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "implementation" / "freqtrade_data" / "strategies" / "c0c_cost_aware_ema.py"
WORKFLOW = ROOT / ".github" / "workflows" / "c0c-cost-aware-ema.yml"
RUNNER = ROOT / "implementation" / "scripts" / "run_c0c_development.py"
CORE = ROOT / "implementation" / "scripts" / "c0c_development_core.py"
FINALIZER = ROOT / "implementation" / "scripts" / "finalize_c0c_manifest.py"
COVERAGE = ROOT / "implementation" / "scripts" / "verify_c0c_data_coverage.py"
GATE = ROOT / "implementation" / "src" / "atos" / "c0c_validation_gate.py"
WALK = ROOT / "implementation" / "src" / "atos" / "c0c_walk_forward.py"
STARTUP = ROOT / "implementation" / "src" / "atos" / "c0c_okx_startup.py"
PACKAGE_INIT = ROOT / "implementation" / "src" / "atos" / "__init__.py"
CONFIG = ROOT / "implementation" / "config" / "c0c_cost_aware_ema.json"
PARAMS = {
    "enter_spread_threshold": (0.001, 0.008),
    "enter_slow_slope_min": (0.001, 0.010),
    "enter_atr_ratio_min": (0.002, 0.012),
    "enter_htf_slope_min": (0.000, 0.010),
}


def _class() -> ast.ClassDef:
    tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
    return next(
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "C0CCostAwareEMA"
    )


def _assignments() -> dict[str, ast.expr]:
    result: dict[str, ast.expr] = {}
    for node in _class().body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    result[target.id] = node.value
    return result


def test_fixed_strategy_identity_risk_and_startup_contract() -> None:
    values = _assignments()
    assert ast.literal_eval(values["timeframe"]) == "5m"
    assert ast.literal_eval(values["can_short"]) is False
    assert ast.literal_eval(values["startup_candle_count"]) == 1499
    assert ast.literal_eval(values["stoploss"]) == -0.05
    assert ast.literal_eval(values["minimal_roi"]) == {"0": 0.04, "720": 0.02, "1440": 0.0}


def test_exact_four_enter_parameters_and_ranges() -> None:
    values = _assignments()
    actual = {key: values[key] for key in values if key.startswith("enter_")}
    assert set(actual) == set(PARAMS)
    for name, call in actual.items():
        assert isinstance(call, ast.Call)
        low, high = (ast.literal_eval(call.args[0]), ast.literal_eval(call.args[1]))
        assert (low, high) == PARAMS[name]
        keywords = {item.arg: ast.literal_eval(item.value) for item in call.keywords}
        assert keywords["space"] == "enter"
        assert keywords["decimals"] == 3


def test_entry_is_event_based_and_parameters_do_not_change_indicators() -> None:
    source = SOURCE.read_text(encoding="utf-8")
    assert '(dataframe["ema_spread"].shift(1) <= threshold)' in source
    indicators = next(
        node
        for node in _class().body
        if isinstance(node, ast.FunctionDef) and node.name == "populate_indicators"
    )
    assert all(
        not (isinstance(node, ast.Attribute) and node.attr == "value")
        for node in ast.walk(indicators)
    )


def test_candidate_has_no_ai_network_or_live_path() -> None:
    source = SOURCE.read_text(encoding="utf-8").lower()
    for forbidden in (
        "providermanager",
        "openai",
        "requests.",
        "private okx",
        "dry_run = false",
        "leverage",
    ):
        assert forbidden not in source


def test_development_workflow_is_exact_source_and_holdout_closed() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    assert "C0C_DOWNLOAD_TIMERANGE: '20231001-20250701'" in workflow
    assert 'C0C_DOWNLOAD_TIMERANGE' in workflow
    assert "20260701" not in workflow
    assert "20250701-20260701" not in workflow
    assert "types: [ready_for_review]" in workflow
    assert "C0C_SOURCE_SHA: ${{ github.event.pull_request.head.sha || github.sha }}" in workflow
    assert "ref: ${{ env.C0C_SOURCE_SHA }}" in workflow
    assert "implementation/src/atos/c0c_okx_startup.py" in workflow
    assert "implementation/scripts/verify_c0c_data_coverage.py" in workflow
    assert "implementation/tests/test_c0c_data_coverage.py" in workflow
    assert "implementation/tests/test_c0c_okx_startup_contract.py" in workflow
    assert "python scripts/verify_c0c_data_coverage.py" in workflow
    assert "scripts/finalize_c0c_manifest.py" in workflow


def test_startup_analysis_is_prospective_exchange_reproducible_and_fail_closed() -> None:
    config = json.loads(CONFIG.read_text(encoding="utf-8"))
    startup = config["startup_analysis"]
    assert startup == {
        "pairs": ["BTC/USDT", "ETH/USDT", "SOL/USDT"],
        "timerange": "20240101-20240201",
        "startup_candidates": [499, 999, 1499],
        "selected_startup_candles": 1499,
        "max_variance_pct": 0.1,
        "required_indicators": [
            "ema_fast_20",
            "ema_slow_50",
            "ema_spread",
            "slow_slope_12",
            "atr_ratio_14",
            "close_1h",
            "htf_ema_100_1h",
            "htf_slope_6_1h",
        ],
    }
    assert startup["selected_startup_candles"] in startup["startup_candidates"]
    assert startup["selected_startup_candles"] <= 1499
    assert all(value % 2 == 1 for value in startup["startup_candidates"])
    core = CORE.read_text(encoding="utf-8")
    walk = WALK.read_text(encoding="utf-8")
    startup_contract = STARTUP.read_text(encoding="utf-8")
    package_init = PACKAGE_INIT.read_text(encoding="utf-8")
    coverage = COVERAGE.read_text(encoding="utf-8")
    assert "OKX_5M_MAX_STARTUP_CANDLES = 1499" in startup_contract
    assert "apply_okx_startup_contract()" in package_init
    assert '"recursive-analysis"' in core
    assert '"--startup-candle"' in core
    assert "validate_recursive_analysis_log" in core
    assert "recursive analysis missing indicators" in walk
    assert "exceeds" in walk
    assert 'FROZEN_DOWNLOAD_TIMERANGE = "20231001-20250701"' in coverage
    assert "required_rows" in coverage
    assert "duplicate candles" in coverage
    assert "candle gap" in coverage
    assert "contains holdout candle" in coverage


def test_three_candidate_shortlist_is_selected_on_validation_only() -> None:
    config = json.loads(CONFIG.read_text(encoding="utf-8"))
    hyperopt = config["hyperopt"]
    assert hyperopt["shortlist_size"] == 3
    assert hyperopt["selection_policy"] == "top_loss_shortlist_validation_rank_v1"
    core = CORE.read_text(encoding="utf-8")
    gate = GATE.read_text(encoding="utf-8")
    assert '"--disable-param-export"' in core
    assert '"hyperopt-list"' in core
    assert '"hyperopt-show"' in core
    assert "parse_hyperopt_list_output" in core
    assert "expected_return_drawdown_ratio" in gate
    assert "training_loss" in gate
    decision_gate = gate.index('if all(item["selected"] for item in fold_decisions):')
    test_backtest = gate.index('role="development_test"', decision_gate)
    assert decision_gate < test_backtest


def test_cost_attribution_and_provenance_are_contract_bound() -> None:
    core = CORE.read_text(encoding="utf-8")
    walk = WALK.read_text(encoding="utf-8")
    gate = GATE.read_text(encoding="utf-8")
    finalizer = FINALIZER.read_text(encoding="utf-8")
    assert '"freqtrade", "--version"' in core
    assert "command_sha256" in core
    assert "official_hyperopt_result_files" in core
    assert "fee_open" in walk and "fee_close" in walk
    assert "turnover_notional_abs" in walk
    assert "exit_reason_summary" in walk
    assert "largest_positive_trade_share" in walk
    assert "top_trade_cluster_profit_share" in walk
    assert "fold_artifacts" in gate
    assert "source_head_sha" in gate
    assert "source_files" in gate
    assert "manifest source SHA does not match C0C_SOURCE_SHA" in finalizer
    assert "src/atos/c0c_okx_startup.py" in finalizer
    assert "scripts/verify_c0c_data_coverage.py" in finalizer
    assert "tests/test_c0c_data_coverage.py" in finalizer
    assert 'payload["data_coverage"]' in finalizer
    assert "coverage source SHA does not match C0C_SOURCE_SHA" in finalizer
    assert "prior_run_reached_hyperopt" in finalizer


def test_all_entrypoints_preserve_the_gate() -> None:
    runner = RUNNER.read_text(encoding="utf-8")
    core = CORE.read_text(encoding="utf-8")
    assert "run_gated_development" in runner
    assert "run_gated_development" in core
    assert "Never bypass the gated orchestrator" in core
