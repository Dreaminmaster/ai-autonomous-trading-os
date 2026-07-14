from __future__ import annotations

import json
import zipfile
from datetime import UTC, datetime
from pathlib import Path

import pytest

from atos.profitability_diagnostics import (
    ProfitabilityDiagnosticsError,
    analyze_export,
    build_manifest,
    buy_and_hold_metrics,
    canonical_reproduction,
    discover_candle_file,
    load_freqtrade_export,
    trade_equity_metrics,
    trade_path_diagnostics,
)


def _trade(*, profit_abs=10.0, profit_ratio=0.01, pair="BTC/USDT", open_date="2025-01-01T00:00:00+00:00", close_date="2025-01-01T00:10:00+00:00"):
    return {
        "pair": pair,
        "open_date": open_date,
        "close_date": close_date,
        "open_rate": 100.0,
        "close_rate": 101.0,
        "profit_abs": profit_abs,
        "profit_ratio": profit_ratio,
        "stake_amount": 1000.0,
        "trade_duration": 10,
        "enter_tag": "test_entry",
        "exit_reason": "test_exit",
        "is_short": False,
        "fee_open_abs": 0.1,
        "fee_close_abs": 0.1,
    }


def _export(trades=None):
    trades = trades if trades is not None else [_trade()]
    return {
        "strategy": {
            "AISupervisedStrategy": {
                "trades": trades,
                "total_trades": len(trades),
                "profit_total": sum(t["profit_abs"] for t in trades) / 1000.0,
                "profit_total_abs": sum(t["profit_abs"] for t in trades),
                "winrate": sum(t["profit_abs"] > 0 for t in trades) / len(trades) if trades else 0,
                "max_drawdown_account": 0.0,
                "max_drawdown_abs": 0.0,
                "profit_factor": 1.0,
                "starting_balance": 1000.0,
                "final_balance": 1000.0 + sum(t["profit_abs"] for t in trades),
                "timeframe": "5m",
                "pairlist": ["BTC/USDT"],
            }
        },
        "strategy_comparison": [],
    }


def test_load_plain_and_mislabeled_zip(tmp_path):
    payload = _export()
    plain = tmp_path / "result.json"
    plain.write_text(json.dumps(payload))
    assert load_freqtrade_export(plain) == payload

    mislabeled = tmp_path / "copied_result.json"
    with zipfile.ZipFile(mislabeled, "w") as archive:
        archive.writestr("backtest-result.json", json.dumps(payload))
        archive.writestr("backtest-result.meta.json", "{}")
        archive.writestr("backtest-result_config.json", "{}")
        archive.writestr("backtest-result_AISupervisedStrategy.json", '{"buy": 1}')
    assert load_freqtrade_export(mislabeled) == payload


def test_zip_rejects_ambiguous_authoritative_json(tmp_path):
    path = tmp_path / "bad.zip"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("one.json", "{}")
        archive.writestr("two.json", "{}")
    with pytest.raises(ProfitabilityDiagnosticsError, match="expected one"):
        load_freqtrade_export(path)


def test_trade_equity_metrics_compute_real_drawdown():
    trades = [
        _trade(profit_abs=100, close_date="2025-01-01T00:10:00+00:00"),
        _trade(profit_abs=-150, close_date="2025-01-01T00:20:00+00:00"),
        _trade(profit_abs=50, close_date="2025-01-01T00:30:00+00:00"),
    ]
    metrics = trade_equity_metrics(trades, 1000)
    assert metrics["total_trades"] == 3
    assert metrics["net_profit_abs"] == pytest.approx(0)
    assert metrics["profit_factor"] == pytest.approx(1.0)
    assert metrics["max_drawdown_abs"] == pytest.approx(150)
    assert metrics["max_drawdown_ratio"] == pytest.approx(150 / 1100)
    assert metrics["fee_total_abs"] == pytest.approx(0.6)


def test_official_freqtrade_fee_rates_use_order_costs():
    trade = _trade()
    trade.pop("fee_open_abs")
    trade.pop("fee_close_abs")
    trade.update(
        fee_open=0.001,
        fee_close=0.002,
        amount=10.0,
        orders=[
            {"ft_is_entry": True, "cost": 1000.0},
            {"ft_is_entry": False, "cost": 1010.0},
        ],
    )
    metrics = trade_equity_metrics([trade], 1000)
    assert metrics["fee_total_abs"] == pytest.approx(3.02)


def test_official_freqtrade_fee_rates_fall_back_to_trade_notional():
    trade = _trade()
    trade.pop("fee_open_abs")
    trade.pop("fee_close_abs")
    trade.update(fee_open=0.001, fee_close=0.002, amount=10.0, orders=[])
    metrics = trade_equity_metrics([trade], 1000)
    assert metrics["fee_total_abs"] == pytest.approx(3.02)


def test_buy_and_hold_drawdown_uses_equity_path_not_absolute_return():
    candles = [
        {"date": "2025-01-01T00:00:00Z", "close": 100},
        {"date": "2025-01-01T00:05:00Z", "close": 120},
        {"date": "2025-01-01T00:10:00Z", "close": 90},
        {"date": "2025-01-01T00:15:00Z", "close": 110},
    ]
    result = buy_and_hold_metrics(candles, 1000)
    assert result["net_return_ratio"] == pytest.approx(0.10)
    assert result["max_drawdown_ratio"] == pytest.approx(0.25)
    assert result["max_drawdown_abs"] == pytest.approx(300)


def test_trade_path_long_and_short():
    candles = [
        {"date": "2025-01-01T00:00:00Z", "high": 101, "low": 99, "close": 100},
        {"date": "2025-01-01T00:05:00Z", "high": 110, "low": 95, "close": 105},
        {"date": "2025-01-01T00:10:00Z", "high": 106, "low": 97, "close": 101},
    ]
    long_trade = _trade()
    long_result = trade_path_diagnostics(long_trade, candles)
    assert long_result["mfe_ratio"] == pytest.approx(0.10)
    assert long_result["mae_ratio"] == pytest.approx(-0.05)
    assert long_result["candles_observed"] == 3
    assert long_result["path_order"] == "SAME_CANDLE_AMBIGUOUS"

    short_trade = dict(long_trade, is_short=True, profit_ratio=0.02)
    short_result = trade_path_diagnostics(short_trade, candles)
    assert short_result["mfe_ratio"] == pytest.approx(0.05)
    assert short_result["mae_ratio"] == pytest.approx(-0.10)


def test_analyze_export_requires_summary_trade_count_binding(tmp_path):
    payload = _export()
    payload["strategy"]["AISupervisedStrategy"]["total_trades"] = 2
    path = tmp_path / "result.json"
    path.write_text(json.dumps(payload))
    with pytest.raises(ProfitabilityDiagnosticsError, match="trades length"):
        analyze_export(export_path=path, strategy_name="AISupervisedStrategy")


def test_canonical_reproduction_passes_and_fails():
    strategy = {
        "total_trades": 244,
        "profit_total": -0.1612,
        "winrate": 0.4467,
        "max_drawdown_account": 0.1785,
        "profit_factor": 0.7524,
    }
    expected = {
        "total_trades": 244,
        "profit_total_pct": -16.12,
        "winrate_pct": 44.67,
        "max_drawdown_pct": 17.85,
        "profit_factor": 0.7524,
        "tolerances": {
            "profit_total_pct": 0.01,
            "winrate_pct": 0.01,
            "max_drawdown_pct": 0.01,
            "profit_factor": 0.0001,
        },
    }
    assert canonical_reproduction(strategy, expected)["status"] == "PASS"
    expected["total_trades"] = 245
    result = canonical_reproduction(strategy, expected)
    assert result["status"] == "FAIL"
    assert "total_trades" in result["errors"][0]


def test_manifest_binds_exact_files(tmp_path):
    export = tmp_path / "result.json"
    config = tmp_path / "config.json"
    policy = tmp_path / "policy.json"
    data = tmp_path / "BTC_USDT-5m.csv"
    for path, content in [
        (export, "{}"),
        (config, '{"a":1}'),
        (policy, '{"mode":"paper"}'),
        (data, "date,close\n2025-01-01,1\n"),
    ]:
        path.write_text(content)
    manifest = build_manifest(
        run_id="123",
        head_sha="a" * 40,
        strategy_name="AISupervisedStrategy",
        export_path=export,
        config_path=config,
        policy_path=policy,
        data_files=[data],
        generated_at="2025-01-01T00:00:00Z",
    )
    assert manifest["export"]["sha256"]
    assert manifest["data_files"][0]["sha256"]
    assert manifest["live"] == "FORBIDDEN"


def test_discover_candle_file_is_fail_closed(tmp_path):
    target = tmp_path / "spot" / "BTC_USDT-5m.feather"
    target.parent.mkdir()
    target.write_bytes(b"x")
    assert discover_candle_file(tmp_path, "BTC/USDT", "5m") == target
    duplicate = tmp_path / "BTC-USDT-5m.csv"
    duplicate.write_text("date,close\n")
    with pytest.raises(ProfitabilityDiagnosticsError, match="expected one"):
        discover_candle_file(tmp_path, "BTC/USDT", "5m")


def test_extract_rejects_trade_time_reversal(tmp_path):
    payload = _export([
        _trade(
            open_date="2025-01-01T00:10:00+00:00",
            close_date="2025-01-01T00:00:00+00:00",
        )
    ])
    path = tmp_path / "result.json"
    path.write_text(json.dumps(payload))
    with pytest.raises(ProfitabilityDiagnosticsError, match="close precedes open"):
        analyze_export(export_path=path, strategy_name="AISupervisedStrategy")


def test_datetime_candles_from_feather_are_supported():
    candles = [
        {"date": datetime(2025, 1, 1, 0, 0, tzinfo=UTC), "close": 100},
        {"date": datetime(2025, 1, 1, 0, 5), "close": 90},
    ]
    result = buy_and_hold_metrics(candles, 1000)
    assert result["net_return_ratio"] == pytest.approx(-0.10)
