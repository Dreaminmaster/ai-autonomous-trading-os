from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import runpy

import pytest

import atos.c0c_walk_forward as c0c


_RUNNER = runpy.run_path(
    str(Path(__file__).resolve().parents[1] / "scripts" / "run_c0c_development.py")
)
parse_hyperopt_csv_output = _RUNNER["parse_hyperopt_csv_output"]
discover_official_hyperopt_result_file = _RUNNER[
    "discover_official_hyperopt_result_file"
]
validate_recursive_analysis_log = _RUNNER["validate_recursive_analysis_log"]


def _config():
    return {
        "candidate_id": "c0c-cost-aware-ema-v1", "strategy": "C0CCostAwareEMA",
        "live": "FORBIDDEN", "holdout_state": "HOLDOUT_CLOSED",
        "data_timerange": "20231101-20250701",
        "timeframe": "5m", "informative_timeframe": "1h",
        "pairs": ["BTC/USDT", "ETH/USDT", "SOL/USDT"],
        "expected_fee_rate": 0.0015, "fee_multipliers": [1.0, 1.5, 2.0],
        "startup_analysis": deepcopy(c0c.STARTUP_ANALYSIS),
        "hyperopt": deepcopy(c0c.HYPEROPT),
        "validation_gate": {
            "require_positive_expected_net": True,
            "require_nonnegative_1_5x_net": True,
            "minimum_profit_factor": 1.10,
            "maximum_drawdown_ratio": 0.15,
        },
        "parameter_ranges": {key: list(value) for key, value in c0c.PARAM_RANGES.items()},
        "folds": [
            {"id":"1","train_start":"2024-01-01","train_end":"2024-07-01","validation_start":"2024-07-01","validation_end":"2024-10-01","test_start":"2024-10-01","test_end":"2025-01-01"},
            {"id":"2","train_start":"2024-01-01","train_end":"2024-10-01","validation_start":"2024-10-01","validation_end":"2025-01-01","test_start":"2025-01-01","test_end":"2025-04-01"},
            {"id":"3","train_start":"2024-01-01","train_end":"2025-01-01","validation_start":"2025-01-01","validation_end":"2025-04-01","test_start":"2025-04-01","test_end":"2025-07-01"},
        ],
        "holdout": {"start":"2025-07-01","end":"2026-07-01"},
        "thresholds": {
            "minimum_profit_factor":1.1,"maximum_drawdown_ratio":0.15,"minimum_trades":30,
            "minimum_positive_pairs":2,"maximum_pair_profit_share":0.7,
            "minimum_positive_folds":2,"maximum_fold_profit_share":0.6,
            **c0c.CONCENTRATION_THRESHOLDS,
            "turnover_definition":"entry_plus_exit_notional_divided_by_starting_balance",
        },
    }


def _row(fold, role, cost, ret=0.02):
    net = ret * 1000
    return {
        "fold_id":str(fold),"role":role,"candidate_id":f"selected_{fold}",
        "cost_multiplier":float(cost),"fee_rate":0.0015*float(cost),
        "params_sha256":str(fold)*64,
        "starting_balance":1000.0,"trades":20,"net_profit_abs":net,"net_return_ratio":ret,
        "max_drawdown_ratio":0.08,"positive_profit_abs":100.0,"negative_profit_abs":-80.0,
        "profit_factor":1.25,
        "fee_binding":{"verified":True,"expected_fee_rate":0.0015*float(cost)},
        "turnover_notional_abs":2000.0,"turnover_ratio":2.0,
        "positive_trade_profits_abs":[10.0]*10,
        "exit_reason_summary":[{"exit_reason":"roi","trades":20,"net_profit_abs":net}],
        "pairs":[
            {"pair":"BTC/USDT","net_profit_abs":net*.4},
            {"pair":"ETH/USDT","net_profit_abs":net*.35},
            {"pair":"SOL/USDT","net_profit_abs":net*.25}],
    }


def _rows(ret=0.02):
    return [_row(f, role, cost, ret if cost==1.0 else ret/2)
            for f in (1,2,3) for role in ("validation","development_test") for cost in (1.0,1.5,2.0)]


def _bh():
    return {str(f): {"net_return_ratio":0.01,"max_drawdown_ratio":0.1,"pairs":{}} for f in (1,2,3)}


def test_config_freezes_holdout_folds_startup_and_shortlist():
    assert c0c.validate_config(_config())["holdout_start"] == "2025-07-01"
    cfg=deepcopy(_config()); cfg["startup_analysis"]["selected_startup_candles"]=999
    with pytest.raises(c0c.C0CWalkForwardError, match="startup_analysis drift"):
        c0c.validate_config(cfg)
    cfg=deepcopy(_config()); cfg["hyperopt"]["shortlist_size"]=1
    with pytest.raises(c0c.C0CWalkForwardError, match="hyperopt contract drift"):
        c0c.validate_config(cfg)


def test_holdout_or_fold_drift_fails_closed():
    cfg=deepcopy(_config()); cfg["holdout"]["start"]="2025-06-01"
    with pytest.raises(c0c.C0CWalkForwardError, match="holdout boundary"):
        c0c.validate_config(cfg)
    cfg=deepcopy(_config()); cfg["folds"][0]["validation_start"]="2024-07-02"
    with pytest.raises(c0c.C0CWalkForwardError, match="leakage or gaps"):
        c0c.validate_config(cfg)


def test_positive_development_stays_research_only_until_final_refit():
    report=c0c.build_development_report(rows=_rows(),config=_config(),buy_hold_by_fold=_bh())
    assert report["development_economic_pass"] is True
    assert report["status"] == "RESEARCH_ONLY"
    assert report["development_test_opened"] is True
    assert report["next_required"] == "FINAL_REFIT_AND_ANALYSES"
    assert report["aggregate"]["turnover_ratio"] == pytest.approx(2.0)
    assert report["aggregate"]["exit_reason_summary"][0]["trades"] == 60


def test_negative_development_is_rejected():
    report=c0c.build_development_report(rows=_rows(-0.02),config=_config(),buy_hold_by_fold=_bh())
    assert report["status"] == "REJECTED"
    assert "NET_RETURN_NOT_POSITIVE" in report["rejection_reasons"]


def test_trade_concentration_gates_are_prospective():
    rows=_rows()
    for row in rows:
        if row["role"]=="development_test" and row["cost_multiplier"]==1.0 and row["fold_id"]=="1":
            row["positive_trade_profits_abs"]=[80.0,20.0]
    report=c0c.build_development_report(rows=rows,config=_config(),buy_hold_by_fold=_bh())
    assert "SINGLE_TRADE_PROFIT_CONCENTRATION" in report["rejection_reasons"]

    rows=_rows()
    for row in rows:
        if row["role"]=="development_test" and row["cost_multiplier"]==1.0:
            row["positive_trade_profits_abs"]=[60.0,40.0]
    report=c0c.build_development_report(rows=rows,config=_config(),buy_hold_by_fold=_bh())
    assert "SINGLE_TRADE_PROFIT_CONCENTRATION" not in report["rejection_reasons"]
    assert "TOP_TRADE_CLUSTER_PROFIT_CONCENTRATION" in report["rejection_reasons"]


def test_missing_cell_parameter_lineage_and_fee_binding_fail_closed():
    with pytest.raises(c0c.C0CWalkForwardError, match="coverage mismatch"):
        c0c.build_development_report(rows=_rows()[:-1],config=_config(),buy_hold_by_fold=_bh())
    evidence=_rows(); evidence[0]["params_sha256"]="x"*64
    with pytest.raises(c0c.C0CWalkForwardError, match="lineage mismatch"):
        c0c.build_development_report(rows=evidence,config=_config(),buy_hold_by_fold=_bh())
    evidence=_rows(); evidence[0]["fee_binding"]["verified"]=False
    with pytest.raises(c0c.C0CWalkForwardError, match="fee binding"):
        c0c.build_development_report(rows=evidence,config=_config(),buy_hold_by_fold=_bh())


def test_analysis_pass_can_only_promote_economically_valid_development():
    report=c0c.build_development_report(rows=_rows(),config=_config(),buy_hold_by_fold=_bh(),
                                        analysis_status={"lookahead":"PASS","recursive":"PASS"})
    assert report["status"] == "HOLDOUT_ELIGIBLE"
    failed=c0c.build_development_report(rows=_rows(-0.02),config=_config(),buy_hold_by_fold=_bh(),
                                        analysis_status={"lookahead":"PASS","recursive":"PASS"})
    assert failed["status"] == "REJECTED"


def test_equal_weight_buy_hold_uses_synchronized_portfolio_path():
    candles = {
        "BTC/USDT": [
            {"date": "2025-01-01T00:00:00Z", "close": 100},
            {"date": "2025-01-01T00:05:00Z", "close": 50},
            {"date": "2025-01-01T00:10:00Z", "close": 100},
        ],
        "ETH/USDT": [
            {"date": "2025-01-01T00:00:00Z", "close": 100},
            {"date": "2025-01-01T00:05:00Z", "close": 150},
            {"date": "2025-01-01T00:10:00Z", "close": 100},
        ],
        "SOL/USDT": [
            {"date": "2025-01-01T00:00:00Z", "close": 100},
            {"date": "2025-01-01T00:05:00Z", "close": 100},
            {"date": "2025-01-01T00:10:00Z", "close": 100},
        ],
    }
    result = c0c.equal_weight_buy_hold(candles)
    assert result["equity_curve"] == pytest.approx([1.0, 1.0, 1.0])
    assert result["max_drawdown_ratio"] == pytest.approx(0.0)


def _params(path):
    path.write_text(json.dumps({
        "strategy_name":"C0CCostAwareEMA",
        "params":{"enter":{
            "enter_spread_threshold":0.003,
            "enter_slow_slope_min":0.003,
            "enter_atr_ratio_min":0.004,
            "enter_htf_slope_min":0.002,
        }},
    }))


def _export(path, fee=0.0015):
    trade={
        "pair":"BTC/USDT","open_date":"2025-01-01T00:00:00Z","close_date":"2025-01-01T01:00:00Z",
        "open_rate":100.0,"close_rate":101.0,"profit_abs":1.0,"profit_ratio":0.01,
        "stake_amount":100.0,"amount":1.0,"fee_open":fee,"fee_close":fee,
        "exit_reason":"roi","orders":[
            {"ft_is_entry":True,"cost":100.0},{"ft_is_entry":False,"cost":101.0}
        ],
    }
    pairs=[
        {"key":"BTC/USDT","trades":1,"profit_total_abs":1.0,"profit_total":0.001},
        {"key":"ETH/USDT","trades":0,"profit_total_abs":0.0,"profit_total":0.0},
        {"key":"SOL/USDT","trades":0,"profit_total_abs":0.0,"profit_total":0.0},
        {"key":"TOTAL","trades":1,"profit_total_abs":1.0,"profit_total":0.001},
    ]
    payload={"strategy":{"C0CCostAwareEMA":{
        "trades":[trade],"total_trades":1,"timeframe":"5m","results_per_pair":pairs,
        "starting_balance":1000.0,"profit_total_abs":1.0,"profit_total":0.001,
        "max_drawdown_account":0.01,"profit_factor":1.2,"market_change":0.0,
    }}}
    path.write_text(json.dumps(payload))


def test_summarize_export_binds_fees_turnover_exit_and_trade_concentration(tmp_path):
    params=tmp_path/"params.json"; export=tmp_path/"export.json"
    _params(params); _export(export)
    row=c0c.summarize_export(
        export_path=export,params_path=params,fold_id="1",role="validation",
        cost_multiplier=1.0,expected_pairs=["BTC/USDT","ETH/USDT","SOL/USDT"],
        candidate_id="rank_01_epoch_1",training_epoch=1,training_loss=0.2,
    )
    assert row["fee_binding"]["basis"] == "per_trade_export"
    assert row["turnover_notional_abs"] == pytest.approx(201.0)
    assert row["exit_reason_summary"] == [{"exit_reason":"roi","trades":1,"net_profit_abs":1.0}]
    assert row["largest_positive_trade_share"] == pytest.approx(1.0)

    _export(export,fee=0.0014)
    with pytest.raises(c0c.C0CWalkForwardError, match="fee"):
        c0c.summarize_export(
            export_path=export,params_path=params,fold_id="1",role="validation",
            cost_multiplier=1.0,expected_pairs=["BTC/USDT","ETH/USDT","SOL/USDT"],
        )


def test_hyperopt_csv_parser_uses_loss_then_epoch_and_filters_min_trades(tmp_path):
    path=tmp_path/"epochs.csv"
    path.write_text("\n".join([
        "Epoch,Trades,Objective",
        "1,1,",
        "7,40,0.3",
        "2,35,0.1",
        "1,31,0.1",
        "9,29,",
        "10,50,100000",
    ]))
    assert parse_hyperopt_csv_output(path,shortlist_size=3,min_trades=30) == [
        {"epoch":1,"loss":0.1},{"epoch":2,"loss":0.1},{"epoch":7,"loss":0.3}
    ]


def test_hyperopt_csv_parser_fails_closed_on_schema_and_shortlist(tmp_path):
    path=tmp_path/"epochs.csv"
    path.write_text("Epoch,Trades\n1,40\n")
    with pytest.raises(c0c.C0CWalkForwardError,match="missing columns"):
        parse_hyperopt_csv_output(path,shortlist_size=1,min_trades=30)
    path.write_text("Epoch,Trades,Objective\n1,29,\n")
    with pytest.raises(c0c.C0CWalkForwardError,match="eligible epochs"):
        parse_hyperopt_csv_output(path,shortlist_size=1,min_trades=30)
    path.write_text("Epoch,Trades,Objective\n1,30,\n")
    with pytest.raises(c0c.C0CWalkForwardError,match="must be numeric"):
        parse_hyperopt_csv_output(path,shortlist_size=1,min_trades=30)


def test_hyperopt_result_discovery_uses_official_pointer_and_ignores_cache(tmp_path):
    result = tmp_path/"strategy_C0CCostAwareEMA_2026-07-15_19-40-27.fthypt"
    result.write_text("epoch\n")
    (tmp_path/"hyperopt_tickerdata.pkl").write_bytes(b"cache")
    (tmp_path/".last_result.json").write_text(json.dumps({
        "latest_hyperopt": result.name,
    }))

    assert discover_official_hyperopt_result_file(tmp_path) == result


def test_hyperopt_result_discovery_fails_closed_on_pointer_or_result_ambiguity(tmp_path):
    result = tmp_path/"strategy_one.fthypt"
    result.write_text("epoch\n")
    pointer = tmp_path/".last_result.json"

    pointer.write_text(json.dumps({"latest_hyperopt": "../strategy_one.fthypt"}))
    with pytest.raises(c0c.C0CWalkForwardError, match="unsafe or unsupported"):
        discover_official_hyperopt_result_file(tmp_path)

    pointer.write_text(json.dumps({"latest_hyperopt": result.name}))
    (tmp_path/"strategy_two.fthypt").write_text("epoch\n")
    with pytest.raises(c0c.C0CWalkForwardError, match="exactly one authoritative"):
        discover_official_hyperopt_result_file(tmp_path)


def _recursive_rich_table(value: str = "0.010%") -> str:
    indicators=c0c.STARTUP_ANALYSIS["required_indicators"]
    rows=[
        "No lookahead bias on indicators found.",
        "                         Recursive Analysis",
        "┏━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━┳━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━┓",
        "┃ Indicators         ┃    499 ┃    999 ┃ 1999 (from strategy) ┃   3999 ┃",
        "┡━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━╇━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━┩",
    ]
    rows.extend(
        f"│ {name:<18} │ 0.500% │ 0.200% │ {value:<20} │ -      │"
        for name in indicators
    )
    rows.append("└────────────────────┴────────┴────────┴──────────────────────┴────────┘")
    return "\n".join(rows)


def _recursive_sparse_run4_table() -> str:
    return "\n".join([
        "No variance on indicator(s) found due to recursive formula.",
        "No lookahead bias on indicators found.",
        "                     Recursive Analysis",
        "┏━━━━━━━━━━━━━━━━┳━━━━━━━━━┳━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━┓",
        "┃ Indicators     ┃     499 ┃     999 ┃ 1499 (from strategy) ┃",
        "┡━━━━━━━━━━━━━━━━╇━━━━━━━━━╇━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━┩",
        "│ ema_slow_50    │ -0.000% │       - │                    - │",
        "│ ema_spread     │ -0.000% │       - │                    - │",
        "│ slow_slope_12  │ -0.000% │       - │                    - │",
        "│ htf_ema_100_1h │  0.000% │  0.000% │                    - │",
        "│ htf_slope_6_1h │ -0.012% │ -0.000% │                    - │",
        "└────────────────┴─────────┴─────────┴──────────────────────┘",
    ])


def test_recursive_analysis_parser_supports_current_rich_table(tmp_path):
    path=tmp_path/"recursive.log"
    indicators=c0c.STARTUP_ANALYSIS["required_indicators"]
    path.write_text(_recursive_rich_table())
    result=validate_recursive_analysis_log(
        path,startup_count=1999,required_indicators=indicators,max_variance_pct=0.1
    )
    assert result["status"] == "PASS"
    assert result["lookahead_status"] == "PASS"
    assert set(result["indicator_variance_pct"]) == set(indicators)
    assert result["omitted_as_zero_variance"] == []


def test_recursive_analysis_parser_accepts_official_sparse_zero_variance_output(tmp_path):
    path=tmp_path/"recursive.log"
    indicators=[
        "ema_fast_20",
        "ema_slow_50",
        "ema_spread",
        "slow_slope_12",
        "atr_ratio_14",
        "close_1h",
        "htf_ema_100_1h",
        "htf_slope_6_1h",
    ]
    path.write_text(_recursive_sparse_run4_table())
    result=validate_recursive_analysis_log(
        path,startup_count=1499,required_indicators=indicators,max_variance_pct=0.1
    )
    assert result["status"] == "PASS"
    assert result["output_semantics"] == (
        "FREQTRADE_2026_6_ONLY_DIFFERING_INDICATORS_EMITTED"
    )
    assert result["omitted_as_zero_variance"] == [
        "atr_ratio_14",
        "close_1h",
        "ema_fast_20",
    ]
    assert result["dash_as_zero_variance"] == [
        "ema_slow_50",
        "ema_spread",
        "htf_ema_100_1h",
        "htf_slope_6_1h",
        "slow_slope_12",
    ]
    assert all(result["indicator_variance_pct"][name] == 0.0 for name in indicators)


def test_recursive_analysis_parser_fails_closed(tmp_path):
    path=tmp_path/"recursive.log"
    indicators=c0c.STARTUP_ANALYSIS["required_indicators"]
    path.write_text(_recursive_rich_table("0.110%"))
    with pytest.raises(c0c.C0CWalkForwardError,match="exceeds"):
        validate_recursive_analysis_log(
            path,startup_count=1999,required_indicators=indicators,max_variance_pct=0.1
        )

    path.write_text(_recursive_sparse_run4_table().replace(
        "No lookahead bias on indicators found.",
        "=> found lookahead in indicator ema_fast_20",
    ))
    with pytest.raises(c0c.C0CWalkForwardError, match="reported indicator lookahead"):
        validate_recursive_analysis_log(
            path,startup_count=1499,required_indicators=indicators,max_variance_pct=0.1
        )
