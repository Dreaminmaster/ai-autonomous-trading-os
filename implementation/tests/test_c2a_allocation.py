from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from atos.c2a_allocation import (
    COST_LABELS,
    PAIR_ORDER,
    POLICIES,
    C2AAllocationError,
    PortfolioState,
    _execute_target,
    aggregate_comparator,
    aggregate_policy,
    decide,
    prepare_market,
    simulate_buy_hold,
    simulate_window,
    validate_config,
)


ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = ROOT / "implementation/config/c2a_low_turnover_allocation.json"


def config() -> dict:
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def candles(*, shock_date: str | None = None, shock_multiple: float = 1.0) -> dict[str, list[dict]]:
    dates = pd.date_range("2023-05-01", "2024-09-30", freq="1D", tz="UTC")
    result: dict[str, list[dict]] = {}
    for pair_index, pair in enumerate(PAIR_ORDER):
        base = 100.0 + 25.0 * pair_index
        rows: list[dict] = []
        for day_index, when in enumerate(dates):
            trend = base * (1.0 + 0.0015 * day_index)
            seasonal = 1.0 + 0.015 * ((day_index % 17) - 8) / 8.0
            open_price = trend * seasonal
            close_price = open_price * (1.0 + 0.002 * ((day_index % 5) - 2))
            if shock_date and when.strftime("%Y-%m-%d") == shock_date:
                close_price *= shock_multiple
            rows.append(
                {
                    "date": when.isoformat(),
                    "open": open_price,
                    "high": max(open_price, close_price) * 1.01,
                    "low": min(open_price, close_price) * 0.99,
                    "close": close_price,
                    "volume": 1000.0 + day_index,
                }
            )
        result[pair] = rows
    return result


def test_frozen_config_identity() -> None:
    payload = config()
    validate_config(payload)
    assert payload["required_base_sha"] == "995dc9aac3c934c01e196270fc2d41d50278063b"
    assert tuple(payload["policies"]) == POLICIES
    assert tuple(payload["cost_rates"]) == COST_LABELS
    assert payload["live"] == "FORBIDDEN"
    assert payload["holdout_state"] == "HOLDOUT_CLOSED"
    assert payload["confirmation_opened"] is False


def test_prepare_market_rejects_duplicate_candles() -> None:
    payload = candles()
    payload["BTC/USDT"].append(dict(payload["BTC/USDT"][-1]))
    with pytest.raises(C2AAllocationError, match="duplicate"):
        prepare_market(payload)


def test_no_trade_band_cannot_create_invalid_target_sum() -> None:
    state = PortfolioState(
        cash=0.0,
        units={"BTC/USDT": 0.6, "ETH/USDT": 0.2, "SOL/USDT": 0.2},
    )
    event = _execute_target(
        state,
        {pair: 1000.0 for pair in PAIR_ORDER},
        {"BTC/USDT": 0.52, "ETH/USDT": 0.38, "SOL/USDT": 0.10},
        fee_rate=0.0015,
        no_trade_band=0.10,
        turnover_cap=0.50,
    )
    assert event["turnover_ratio"] <= 0.50 + 1e-9
    assert state.cash >= 0
    assert all(value >= 0 for value in state.units.values())


def test_window_uses_previous_completed_close_and_ends_in_cash() -> None:
    payload = config()
    base_market = prepare_market(candles())
    shocked_market = prepare_market(candles(shock_date="2024-01-01", shock_multiple=3.0))
    window = payload["screen_windows"][0]
    base = simulate_window(
        base_market,
        policy="C2AEqualWeightRiskOn",
        window=window,
        cost_label="1.0x",
        config=payload,
    )
    shocked = simulate_window(
        shocked_market,
        policy="C2AEqualWeightRiskOn",
        window=window,
        cost_label="1.0x",
        config=payload,
    )
    first_base = next(event for event in base["events"] if event["kind"] == "SCHEDULED_REBALANCE")
    first_shocked = next(event for event in shocked["events"] if event["kind"] == "SCHEDULED_REBALANCE")
    assert first_base["requested_targets"] == first_shocked["requested_targets"]
    assert first_base["date"].startswith("2024-01-01")
    assert base["daily"][-1]["terminal"] is True
    assert all(abs(value) < 1e-12 for value in base["daily"][-1]["units"].values())
    assert base["events"][-1]["kind"] == "TERMINAL_LIQUIDATION"


def test_full_screen_has_exactly_27_economic_rows() -> None:
    payload = config()
    market = prepare_market(candles())
    rows = [
        simulate_window(
            market,
            policy=policy,
            window=window,
            cost_label=cost_label,
            config=payload,
        )
        for policy in POLICIES
        for window in payload["screen_windows"]
        for cost_label in COST_LABELS
    ]
    assert len(rows) == 27
    assert len({(row["policy_id"], row["window_id"], row["cost_label"]) for row in rows}) == 27
    aggregates = [
        aggregate_policy(rows, policy=policy, cost_label=cost_label, config=payload)
        for policy in POLICIES
        for cost_label in COST_LABELS
    ]
    assert len(aggregates) == 9
    assert all(item["status"] == "PASS" for item in aggregates)


def test_comparators_are_window_isolated_and_aggregate_deterministically() -> None:
    payload = config()
    market = prepare_market(candles())
    comparator_rows = [
        simulate_buy_hold(
            market,
            comparator_id=comparator,
            window=window,
            cost_label=cost_label,
            config=payload,
        )
        for comparator in ("cash", "btc_buy_hold", "equal_weight_buy_hold")
        for window in payload["screen_windows"]
        for cost_label in COST_LABELS
    ]
    assert len(comparator_rows) == 27
    cash = aggregate_comparator(comparator_rows, "cash", "1.0x")
    assert cash["aggregate_net_return"] == pytest.approx(0.0)
    assert cash["maximum_window_drawdown"] == pytest.approx(0.0)


def aggregate_row(policy: str, label: str, **overrides: object) -> dict:
    row = {
        "policy_id": policy,
        "cost_label": label,
        "window_returns": {"S1": 0.02, "S2": 0.03, "S3": 0.01},
        "minimum_window_net_return": 0.01,
        "median_window_net_return": 0.02,
        "positive_windows": 3,
        "aggregate_net_return": 0.061106,
        "aggregate_sharpe": 1.1,
        "maximum_window_drawdown": 0.08,
        "scheduled_nonzero_rebalances": 8,
        "minimum_window_nonzero_rebalances": 2,
        "annualized_one_way_turnover": 2.0,
        "asset_pnl": {"BTC/USDT": 25.0, "ETH/USDT": 20.0, "SOL/USDT": 15.0},
        "positive_assets": list(PAIR_ORDER),
        "maximum_asset_positive_pnl_share": 25.0 / 60.0,
        "maximum_window_positive_pnl_share": 0.50,
        "maximum_single_positive_daily_contribution_share": 0.10,
        "top_three_positive_daily_contribution_share": 0.25,
        "status": "PASS",
    }
    row.update(overrides)
    return row


def test_decision_selects_only_fully_eligible_policy() -> None:
    payload = config()
    policies: list[dict] = []
    for policy in POLICIES:
        policies.append(aggregate_row(policy, "1.0x"))
        policies.append(aggregate_row(policy, "1.5x", aggregate_net_return=0.04))
    policies[0]["aggregate_sharpe"] = 0.1
    policies[2]["maximum_asset_positive_pnl_share"] = 0.95
    comparators = [
        {
            "comparator_id": "equal_weight_buy_hold",
            "cost_label": "1.0x",
            "aggregate_net_return": 0.08,
            "maximum_window_drawdown": 0.12,
            "window_returns": {"S1": 0.03, "S2": 0.03, "S3": 0.02},
        }
    ]
    result = decide(policies, comparators, payload)
    assert result["economic_result"] == "SELECTED"
    assert result["selected_policy"] == "C2ATopTwoPersistentMomentum"
    assert result["confirmation_opened"] is False
    assert result["holdout_state"] == "HOLDOUT_CLOSED"
    assert result["live"] == "FORBIDDEN"


def test_decision_preserves_valid_rejection() -> None:
    payload = config()
    policies: list[dict] = []
    for policy in POLICIES:
        policies.append(aggregate_row(policy, "1.0x", positive_windows=1))
        policies.append(aggregate_row(policy, "1.5x", aggregate_net_return=-0.01))
    comparators = [
        {
            "comparator_id": "equal_weight_buy_hold",
            "cost_label": "1.0x",
            "aggregate_net_return": 0.08,
            "maximum_window_drawdown": 0.12,
            "window_returns": {"S1": 0.03, "S2": 0.03, "S3": 0.02},
        }
    ]
    result = decide(policies, comparators, payload)
    assert result["economic_result"] == "REJECTED"
    assert result["selected_policy"] is None
    assert result["ranking"] == []
