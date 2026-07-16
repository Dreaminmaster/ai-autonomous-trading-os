from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from atos.c1a_family_screen import (
    C1AFamilyScreenError,
    evaluate_family,
    evaluate_screen,
    validate_config,
)


ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = ROOT / "implementation" / "config" / "c1a_strategy_family_screen.json"
FAMILIES = ["C1ARegimeBreakout", "C1ATrendPullback", "C1ADualMomentum"]
WINDOWS = ["S1", "S2", "S3"]
COSTS = [1.0, 1.5, 2.0]
PAIRS = ["BTC/USDT", "ETH/USDT", "SOL/USDT"]


def _config() -> dict:
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def _row(
    family: str,
    window: str,
    cost: float,
    *,
    net: float,
    gains: float,
    losses: float,
    trades: int = 10,
    drawdown: float = 0.05,
    turnover: float = 2.0,
    pair_profits: tuple[float, float, float] = (4.0, 4.0, 2.0),
) -> dict:
    assert abs(gains + losses - net) < 1e-9
    assert abs(sum(pair_profits) - net) < 1e-9
    positive_trade_count = 5
    positives = [gains / positive_trade_count] * positive_trade_count if gains > 0 else []
    pair_trades = [trades // 3 + (1 if index < trades % 3 else 0) for index in range(3)]
    return {
        "family_id": family,
        "window_id": window,
        "cost_multiplier": cost,
        "fee_rate": 0.0015 * cost,
        "fee_binding": {
            "verified": True,
            "expected_fee_rate": 0.0015 * cost,
            "observed_fee_rates": [0.0015 * cost] if trades else [],
        },
        "starting_balance": 1000.0,
        "trades": trades,
        "net_profit_abs": net,
        "net_return_ratio": net / 1000.0,
        "max_drawdown_ratio": drawdown,
        "profit_factor": gains / abs(losses) if losses < 0 else (0.0 if gains == 0 else 1e12),
        "positive_profit_abs": gains,
        "negative_profit_abs": losses,
        "positive_trade_profits_abs": positives,
        "pairs": [
            {"pair": pair, "trades": pair_trade_count, "net_profit_abs": profit}
            for pair, pair_trade_count, profit in zip(
                PAIRS, pair_trades, pair_profits, strict=True
            )
        ],
        "turnover_ratio": turnover,
        "export_sha256": "a" * 64,
        "command_sha256": "b" * 64,
        "log_sha256": "c" * 64,
    }


def _screen_rows(*, eligible_family: str | None = "C1ARegimeBreakout") -> list[dict]:
    rows: list[dict] = []
    for family in FAMILIES:
        for window in WINDOWS:
            for cost in COSTS:
                if family == eligible_family:
                    if cost == 1.0:
                        rows.append(_row(family, window, cost, net=10.0, gains=15.0, losses=-5.0))
                    elif cost == 1.5:
                        rows.append(
                            _row(
                                family,
                                window,
                                cost,
                                net=5.0,
                                gains=12.0,
                                losses=-7.0,
                                pair_profits=(2.0, 2.0, 1.0),
                            )
                        )
                    else:
                        rows.append(
                            _row(
                                family,
                                window,
                                cost,
                                net=0.0,
                                gains=8.0,
                                losses=-8.0,
                                pair_profits=(0.0, 0.0, 0.0),
                            )
                        )
                else:
                    rows.append(
                        _row(
                            family,
                            window,
                            cost,
                            net=-5.0,
                            gains=2.0,
                            losses=-7.0,
                            pair_profits=(-2.0, -2.0, -1.0),
                        )
                    )
    return rows


def test_config_is_exact_and_fail_closed() -> None:
    normalized = validate_config(_config())
    assert normalized["families"] == FAMILIES
    drifted = _config()
    drifted["gate"]["minimum_total_trades"] = 29
    with pytest.raises(C1AFamilyScreenError, match="gate drift"):
        validate_config(drifted)
    drifted = _config()
    drifted["coverage_history_candles"]["1d"] = 119
    with pytest.raises(C1AFamilyScreenError, match="coverage history drift"):
        validate_config(drifted)


def test_screen_selects_only_eligible_family() -> None:
    report = evaluate_screen(_screen_rows(), _config())
    assert report["status"] == "SELECTED"
    assert report["selected_family"] == "C1ARegimeBreakout"
    assert report["eligible_ranking"] == ["C1ARegimeBreakout"]
    assert report["confirmation_opened"] is False
    assert report["holdout_state"] == "HOLDOUT_CLOSED"
    decision = next(
        item for item in report["family_decisions"] if item["family_id"] == "C1ARegimeBreakout"
    )
    assert decision["eligible"] is True
    assert decision["total_trades"] == 30
    assert decision["positive_windows"] == 3
    assert decision["aggregate_expected_profit_factor"] == 3.0


def test_valid_negative_screen_is_rejected_without_opening_confirmation() -> None:
    report = evaluate_screen(_screen_rows(eligible_family=None), _config())
    assert report["status"] == "REJECTED"
    assert report["selected_family"] is None
    assert report["eligible_ranking"] == []
    assert report["confirmation_opened"] is False
    assert all(not item["eligible"] for item in report["family_decisions"])


def test_ranking_uses_frozen_order_and_family_id_last() -> None:
    rows = _screen_rows(eligible_family="C1ARegimeBreakout")
    for row in rows:
        if row["family_id"] == "C1ATrendPullback":
            source = next(
                candidate
                for candidate in rows
                if candidate["family_id"] == "C1ARegimeBreakout"
                and candidate["window_id"] == row["window_id"]
                and candidate["cost_multiplier"] == row["cost_multiplier"]
            )
            row.clear()
            row.update(copy.deepcopy(source))
            row["family_id"] = "C1ATrendPullback"
    report = evaluate_screen(rows, _config())
    assert report["eligible_ranking"] == ["C1ARegimeBreakout", "C1ATrendPullback"]
    assert report["selected_family"] == "C1ARegimeBreakout"


def test_missing_duplicate_or_unverified_evidence_fails_closed() -> None:
    rows = _screen_rows()
    with pytest.raises(C1AFamilyScreenError, match="row coverage mismatch"):
        evaluate_screen(rows[:-1], _config())
    duplicated = rows + [copy.deepcopy(rows[0])]
    with pytest.raises(C1AFamilyScreenError, match="row coverage mismatch"):
        evaluate_screen(duplicated, _config())
    unverified = copy.deepcopy(rows)
    unverified[0]["fee_binding"]["verified"] = False
    with pytest.raises(C1AFamilyScreenError, match="fee binding not verified"):
        evaluate_screen(unverified, _config())
    wrong_fee = copy.deepcopy(rows)
    wrong_fee[0]["fee_rate"] = 0.0
    with pytest.raises(C1AFamilyScreenError, match="fee rate"):
        evaluate_screen(wrong_fee, _config())


def test_pair_reconciliation_and_hashes_fail_closed() -> None:
    rows = _screen_rows()
    bad_trades = copy.deepcopy(rows)
    bad_trades[0]["pairs"][0]["trades"] -= 1
    with pytest.raises(C1AFamilyScreenError, match="pair trade counts"):
        evaluate_screen(bad_trades, _config())
    bad_profit = copy.deepcopy(rows)
    bad_profit[0]["pairs"][0]["net_profit_abs"] += 1.0
    with pytest.raises(C1AFamilyScreenError, match="pair profits"):
        evaluate_screen(bad_profit, _config())
    bad_hash = copy.deepcopy(rows)
    bad_hash[0]["log_sha256"] = "not-a-digest"
    with pytest.raises(C1AFamilyScreenError, match="lowercase SHA-256"):
        evaluate_screen(bad_hash, _config())


def test_concentration_gate_rejects_single_pair_dependence() -> None:
    rows = _screen_rows()
    for row in rows:
        if row["family_id"] == "C1ARegimeBreakout" and row["cost_multiplier"] == 1.0:
            row["pairs"] = [
                {"pair": "BTC/USDT", "trades": 8, "net_profit_abs": 9.0},
                {"pair": "ETH/USDT", "trades": 1, "net_profit_abs": 0.5},
                {"pair": "SOL/USDT", "trades": 1, "net_profit_abs": 0.5},
            ]
    decision = evaluate_family("C1ARegimeBreakout", rows, config=_config())
    assert decision["eligible"] is False
    assert decision["checks"]["maximum_pair_profit_share"] is False
