from __future__ import annotations

from copy import deepcopy

import pytest

import atos.c0b_matrix as matrix


STRATEGIES = ["C0BEMATrend", "C0BDonchianBreakout", "C0BMeanReversion"]
TIMEFRAMES = ["5m", "15m", "1h"]
PAIRS = ["BTC/USDT", "ETH/USDT", "SOL/USDT"]
MULTIPLIERS = [1.0, 1.5, 2.0]


def _config():
    return {
        "timerange": "20240101-20250701",
        "pairs": PAIRS,
        "timeframes": TIMEFRAMES,
        "expected_fee_rate": 0.0015,
        "fee_multipliers": MULTIPLIERS,
        "strategies": STRATEGIES,
        "thresholds": {
            "minimum_profit_factor": 1.1,
            "maximum_drawdown_ratio": 0.15,
            "minimum_trades": 30,
            "maximum_pair_profit_share": 0.7,
            "minimum_positive_pairs": 2,
        },
        "frozen_control_reference": {"classification": "FAILED_PLUMBING_CONTROL_NOT_AI_BASELINE"},
    }


def _specs():
    return [
        {
            "timeframe": timeframe,
            "fee_multiplier": multiplier,
            "export_path": f"{timeframe}-{multiplier}.json",
        }
        for timeframe in TIMEFRAMES
        for multiplier in MULTIPLIERS
    ]


def _row(strategy, timeframe, multiplier, *, return_ratio=-0.02):
    net_abs = return_ratio * 1000
    pair_values = [net_abs * 0.4, net_abs * 0.35, net_abs * 0.25]
    if return_ratio > 0:
        positive, negative = net_abs + 20, -20
    else:
        positive, negative = 20, net_abs - 20
    return {
        "strategy": strategy,
        "timeframe": timeframe,
        "fee_rate": 0.0015 * multiplier,
        "fee_multiplier": multiplier,
        "source_path": f"{timeframe}-{multiplier}.json",
        "source_sha256": "a" * 64,
        "trades": 60,
        "net_profit_abs": net_abs,
        "net_return_ratio": return_ratio,
        "max_drawdown_ratio": 0.08,
        "profit_factor": 1.2 if return_ratio > 0 else 0.8,
        "winrate": 0.5,
        "expectancy_abs": net_abs / 60,
        "sharpe": 0.5,
        "sortino": 0.6,
        "calmar": 0.4,
        "turnover_abs": 10000,
        "positive_profit_abs": positive,
        "negative_profit_abs": negative,
        "pairs": [
            {
                "pair": pair,
                "trades": 20,
                "net_profit_abs": value,
                "net_return_ratio": value / 1000,
            }
            for pair, value in zip(PAIRS, pair_values, strict=True)
        ],
    }


def _install_fake_results(monkeypatch, returns):
    def fake_summarize_result(
        *,
        export_path,
        timeframe,
        fee_rate,
        fee_multiplier,
        expected_strategies,
    ):
        rows = []
        for strategy in expected_strategies:
            value = returns.get((strategy, timeframe, fee_multiplier), -0.02)
            rows.append(_row(strategy, timeframe, fee_multiplier, return_ratio=value))
        return rows

    monkeypatch.setattr(matrix, "summarize_result", fake_summarize_result)


def test_strategy_timeframe_candidates_are_screened_independently(monkeypatch):
    returns = {}
    for multiplier in MULTIPLIERS:
        returns[("C0BEMATrend", "15m", multiplier)] = {
            1.0: 0.12,
            1.5: 0.04,
            2.0: 0.01,
        }[multiplier]
    _install_fake_results(monkeypatch, returns)

    report = matrix.build_matrix_report(run_specs=_specs(), config=_config())
    screening = {item["candidate_id"]: item for item in report["candidate_screening"]}

    assert screening["C0BEMATrend@15m"]["status"] == "SURVIVES_C0B_SCREEN"
    assert screening["C0BEMATrend@5m"]["status"] == "REJECTED"
    assert screening["C0BEMATrend@1h"]["status"] == "REJECTED"

    summary = {item["strategy"]: item for item in report["strategy_summary"]}
    assert summary["C0BEMATrend"]["status"] == "HAS_C0B_SURVIVOR"
    assert summary["C0BEMATrend"]["surviving_timeframes"] == ["15m"]


def test_strategy_summary_does_not_sum_incompatible_timeframes(monkeypatch):
    returns = {
        ("C0BEMATrend", "5m", 1.0): 0.20,
        ("C0BEMATrend", "5m", 1.5): 0.05,
        ("C0BEMATrend", "5m", 2.0): 0.01,
        ("C0BEMATrend", "15m", 1.0): -0.40,
        ("C0BEMATrend", "15m", 1.5): -0.45,
        ("C0BEMATrend", "15m", 2.0): -0.50,
        ("C0BEMATrend", "1h", 1.0): -0.30,
        ("C0BEMATrend", "1h", 1.5): -0.35,
        ("C0BEMATrend", "1h", 2.0): -0.40,
    }
    _install_fake_results(monkeypatch, returns)
    report = matrix.build_matrix_report(run_specs=_specs(), config=_config())
    summary = next(item for item in report["strategy_summary"] if item["strategy"] == "C0BEMATrend")
    assert summary["status"] == "HAS_C0B_SURVIVOR"
    assert summary["best_candidate_id"] == "C0BEMATrend@5m"
    assert summary["best_expected_net_return_ratio"] == pytest.approx(0.20)


def test_negative_at_1_5x_cost_rejects_candidate(monkeypatch):
    returns = {
        ("C0BEMATrend", "15m", 1.0): 0.10,
        ("C0BEMATrend", "15m", 1.5): -0.01,
        ("C0BEMATrend", "15m", 2.0): -0.04,
    }
    _install_fake_results(monkeypatch, returns)
    report = matrix.build_matrix_report(run_specs=_specs(), config=_config())
    item = next(
        candidate
        for candidate in report["candidate_screening"]
        if candidate["candidate_id"] == "C0BEMATrend@15m"
    )
    assert "NEGATIVE_AT_1_5X_COST" in item["rejection_reasons"]


def test_missing_matrix_cell_fails_closed(monkeypatch):
    _install_fake_results(monkeypatch, {})
    with pytest.raises(matrix.C0BMatrixError, match="matrix coverage mismatch"):
        matrix.build_matrix_report(run_specs=_specs()[:-1], config=_config())


def test_duplicate_matrix_cell_fails_closed(monkeypatch):
    _install_fake_results(monkeypatch, {})
    specs = _specs()
    with pytest.raises(matrix.C0BMatrixError, match="duplicate run spec"):
        matrix.build_matrix_report(run_specs=[*specs, specs[0]], config=_config())


def test_pair_coverage_mismatch_fails_closed(monkeypatch):
    def fake(**kwargs):
        rows = [
            _row(strategy, kwargs["timeframe"], kwargs["fee_multiplier"])
            for strategy in kwargs["expected_strategies"]
        ]
        rows[0]["pairs"] = rows[0]["pairs"][:-1]
        return rows

    monkeypatch.setattr(matrix, "summarize_result", fake)
    with pytest.raises(matrix.C0BMatrixError, match="pair coverage mismatch"):
        matrix.build_matrix_report(run_specs=_specs(), config=_config())


def test_insufficient_positive_pairs_rejects_candidate(monkeypatch):
    _install_fake_results(monkeypatch, {})
    rows = [
        _row("C0BEMATrend", "15m", multiplier, return_ratio=0.05)
        for multiplier in MULTIPLIERS
    ]
    for row in rows:
        row["pairs"] = [
            {"pair": "BTC/USDT", "trades": 20, "net_profit_abs": 50.0, "net_return_ratio": 0.05},
            {"pair": "ETH/USDT", "trades": 20, "net_profit_abs": -5.0, "net_return_ratio": -0.005},
            {"pair": "SOL/USDT", "trades": 20, "net_profit_abs": -5.0, "net_return_ratio": -0.005},
        ]
    item = matrix._screen_candidate(
        strategy="C0BEMATrend",
        timeframe="15m",
        rows=rows,
        thresholds=_config()["thresholds"],
    )
    assert "INSUFFICIENT_POSITIVE_PAIRS" in item["rejection_reasons"]


def test_cost_rows_require_exact_multipliers():
    rows = [
        _row("C0BEMATrend", "15m", multiplier, return_ratio=0.05)
        for multiplier in [1.0, 1.5]
    ]
    with pytest.raises(matrix.C0BMatrixError, match="cost matrix mismatch"):
        matrix._screen_candidate(
            strategy="C0BEMATrend",
            timeframe="15m",
            rows=rows,
            thresholds=_config()["thresholds"],
        )


def test_render_markdown_includes_candidate_timeframe(monkeypatch):
    _install_fake_results(monkeypatch, {})
    report = matrix.build_matrix_report(run_specs=_specs(), config=_config())
    markdown = matrix.render_markdown(report)
    assert "| C0BEMATrend | 5m |" in markdown
    assert "strategy/timeframe candidate" in markdown


def test_invalid_fee_matrix_fails_closed(monkeypatch):
    _install_fake_results(monkeypatch, {})
    config = deepcopy(_config())
    config["fee_multipliers"] = [1.0, 2.0]
    with pytest.raises(matrix.C0BMatrixError, match="fee_multipliers"):
        matrix.build_matrix_report(run_specs=_specs(), config=config)


def test_live_marker_is_frozen(monkeypatch):
    _install_fake_results(monkeypatch, {})
    report = matrix.build_matrix_report(run_specs=_specs(), config=_config())
    assert report["live"] == "FORBIDDEN"
    assert report["schema_version"] == 2
