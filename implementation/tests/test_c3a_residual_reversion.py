from __future__ import annotations

import json
import math
from pathlib import Path

import pandas as pd
import pytest

from atos.c3a_residual_reversion import (
    COMPARATORS,
    COST_LABELS,
    PAIR_ORDER,
    POLICIES,
    C3AResidualError,
    _entry_asset,
    compute_indicators,
    decide,
    prepare_market,
    run_screen,
    simulate_window,
    validate_config,
)


ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = ROOT / "implementation/config/c3a_residual_mean_reversion.json"


def config() -> dict:
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def candles(*, eth_shocks: dict[str, float] | None = None) -> dict[str, list[dict]]:
    dates = pd.date_range(
        "2023-09-01T00:00:00Z",
        "2024-09-30T20:00:00Z",
        freq="4h",
        tz="UTC",
    )
    shocks = eth_shocks or {}
    prices = {"BTC/USDT": 100.0, "ETH/USDT": 80.0, "SOL/USDT": 40.0}
    result = {pair: [] for pair in PAIR_ORDER}
    for index, timestamp in enumerate(dates):
        btc_return = 0.00035 + 0.0015 * math.sin(index / 13.0)
        returns = {
            "BTC/USDT": btc_return,
            "ETH/USDT": 1.10 * btc_return + 0.0012 * math.sin(index / 7.0),
            "SOL/USDT": 1.30 * btc_return + 0.0018 * math.cos(index / 9.0),
        }
        shock = shocks.get(timestamp.isoformat())
        if shock is not None:
            returns["ETH/USDT"] += shock
        for pair in PAIR_ORDER:
            open_price = prices[pair]
            close_price = open_price * math.exp(returns[pair])
            result[pair].append(
                {
                    "date": timestamp.isoformat(),
                    "open": open_price,
                    "high": max(open_price, close_price) * 1.001,
                    "low": min(open_price, close_price) * 0.999,
                    "close": close_price,
                    "volume": 1000.0 + index,
                }
            )
            prices[pair] = close_price
    return result


def eligible_aggregate(policy: str, label: str, **overrides: object) -> dict:
    row = {
        "policy_id": policy,
        "cost_label": label,
        "window_returns": {"S1": 0.03, "S2": 0.02, "S3": 0.01},
        "minimum_window_net_return": 0.01,
        "median_window_net_return": 0.02,
        "positive_windows": 3,
        "aggregate_net_return": 0.061106,
        "aggregate_sharpe": 1.25,
        "profit_factor": 1.35,
        "maximum_window_drawdown": 0.08,
        "closed_trades": 24,
        "minimum_window_closed_trades": 6,
        "exposure_ratio": 0.30,
        "annualized_one_way_turnover": 12.0,
        "maximum_window_positive_pnl_share": 0.50,
        "maximum_single_trade_positive_pnl_share": 0.15,
        "maximum_top_three_trade_positive_pnl_share": 0.40,
        "asset_pnl": {"ETH": 25.0, "SOL": 20.0},
        "maximum_asset_positive_pnl_share": 25.0 / 45.0,
        "status": "PASS",
    }
    row.update(overrides)
    return row


def test_frozen_config_identity_and_safety() -> None:
    payload = config()
    validate_config(payload)
    assert tuple(payload["policies"]) == POLICIES
    assert tuple(payload["comparators"]) == COMPARATORS
    assert tuple(payload["cost_rates"]) == COST_LABELS
    assert payload["required_design_main_sha"] == "f8bacea9785dc51783a51ba06948402dfed1a08f"
    assert payload["confirmation_opened"] is False
    assert payload["holdout_state"] == "HOLDOUT_CLOSED"
    assert payload["live"] == "FORBIDDEN"


def test_prepare_market_requires_identical_timestamp_sequences() -> None:
    payload = candles()
    payload["SOL/USDT"].pop(500)
    with pytest.raises(C3AResidualError, match="misaligned"):
        prepare_market(payload)


def test_indicator_history_is_future_invariant() -> None:
    payload = config()
    base_market = prepare_market(candles())
    changed = candles()
    future = pd.Timestamp("2024-08-01T00:00:00Z")
    for row in changed["ETH/USDT"]:
        if pd.Timestamp(row["date"]) == future:
            row["close"] *= 4.0
            break
    changed_market = prepare_market(changed)
    base = compute_indicators(base_market, payload)
    perturbed = compute_indicators(changed_market, payload)
    cutoff = future - pd.Timedelta(hours=4)
    pd.testing.assert_series_equal(base.loc[:cutoff, "z_ETH"], perturbed.loc[:cutoff, "z_ETH"])
    pd.testing.assert_series_equal(base.loc[:cutoff, "beta_ETH"], perturbed.loc[:cutoff, "beta_ETH"])


def test_strongest_laggard_uses_more_negative_z_and_eth_tie_break() -> None:
    payload = config()
    row = pd.Series({"btc_regime_on": True, "z_ETH": -2.4, "z_SOL": -2.8})
    assert _entry_asset("C3AStrongestLaggardResidualReversion", row, payload) == "SOL"
    tied = pd.Series({"btc_regime_on": True, "z_ETH": -2.5, "z_SOL": -2.5})
    assert _entry_asset("C3AStrongestLaggardResidualReversion", tied, payload) == "ETH"
    risk_off = pd.Series({"btc_regime_on": False, "z_ETH": -5.0, "z_SOL": -6.0})
    assert _entry_asset("C3AStrongestLaggardResidualReversion", risk_off, payload) is None


def test_extreme_residual_enters_next_open_and_terminally_liquidates() -> None:
    payload = config()
    shock_time = "2024-01-10T00:00:00+00:00"
    market = prepare_market(candles(eth_shocks={shock_time: -0.16}))
    row = simulate_window(
        market,
        policy="C3AEthResidualReversion",
        window=payload["screen_windows"][0],
        cost_label="1.0x",
        config=payload,
    )
    entries = [event for event in row["events"] if event["kind"] == "ENTRY"]
    assert entries
    assert pd.Timestamp(entries[0]["time"]) > pd.Timestamp(shock_time)
    assert pd.Timestamp(entries[0]["time"]) - pd.Timestamp(shock_time) == pd.Timedelta(hours=4)
    assert entries[0]["post_cost_asset_share"] == pytest.approx(0.5)
    assert row["daily"][-1]["asset"] is None
    assert row["final_equity"] > 0
    assert row["live"] == "FORBIDDEN"


def test_exact_holding_period_and_cooldown_boundaries() -> None:
    payload = config()
    market = prepare_market(candles(eth_shocks={
        "2024-01-10T00:00:00+00:00": -0.16,
        "2024-01-14T04:00:00+00:00": -0.16,
    }))
    row = simulate_window(
        market,
        policy="C3AEthResidualReversion",
        window=payload["screen_windows"][0],
        cost_label="1.0x",
        config=payload,
    )
    for trade in row["trades"]:
        if trade["reason"] == "TIME_EXIT":
            assert trade["held_bars"] == 18
            assert pd.Timestamp(trade["exit_time"]) - pd.Timestamp(trade["entry_time"]) == pd.Timedelta(hours=72)
    events = row["events"]
    for index, event in enumerate(events):
        if event["kind"] != "EXIT":
            continue
        later_entries = [item for item in events[index + 1 :] if item["kind"] == "ENTRY"]
        if later_entries:
            assert pd.Timestamp(later_entries[0]["time"]) - pd.Timestamp(event["time"]) >= pd.Timedelta(hours=24)


def test_cost_stress_is_monotonic_for_identical_trade_path() -> None:
    payload = config()
    market = prepare_market(candles(eth_shocks={"2024-01-10T00:00:00+00:00": -0.16}))
    cells = [
        simulate_window(
            market,
            policy="C3AEthResidualReversion",
            window=payload["screen_windows"][0],
            cost_label=label,
            config=payload,
        )
        for label in COST_LABELS
    ]
    paths = [[(item["kind"], item["time"], item.get("asset"), item.get("reason")) for item in cell["events"]] for cell in cells]
    assert paths[0] == paths[1] == paths[2]
    assert cells[0]["final_equity"] >= cells[1]["final_equity"] >= cells[2]["final_equity"]


def test_complete_screen_has_exact_contract_counts_and_remains_closed() -> None:
    payload = config()
    market = prepare_market(candles())
    result = run_screen(market, payload)
    assert result["counts"] == {
        "policy_rows": 27,
        "comparator_rows": 36,
        "result_pointers": 63,
        "result_exports": 63,
    }
    assert len(result["policy_aggregates"]) == 9
    assert len(result["comparator_aggregates"]) == 12
    assert result["decision"]["economic_result"] == "REJECTED"
    assert result["decision"]["confirmation_opened"] is False
    assert result["holdout_state"] == "HOLDOUT_CLOSED"
    assert result["live"] == "FORBIDDEN"


def test_decision_selects_only_fully_eligible_policy() -> None:
    payload = config()
    aggregates: list[dict] = []
    for policy in POLICIES:
        aggregates.append(eligible_aggregate(policy, "1.0x"))
        aggregates.append(eligible_aggregate(policy, "1.5x", aggregate_net_return=0.04))
        aggregates.append(eligible_aggregate(policy, "2.0x", aggregate_net_return=0.02))
    aggregates[0]["aggregate_sharpe"] = 0.2
    aggregates[3]["maximum_window_positive_pnl_share"] = 0.95
    result = decide(aggregates, payload)
    assert result["economic_result"] == "SELECTED"
    assert result["selected_policy"] == "C3AStrongestLaggardResidualReversion"
    assert result["confirmation_opened"] is False
    assert result["holdout_state"] == "HOLDOUT_CLOSED"
    assert result["live"] == "FORBIDDEN"


def test_decision_preserves_valid_rejection_without_gate_mutation() -> None:
    payload = config()
    aggregates: list[dict] = []
    for policy in POLICIES:
        aggregates.append(eligible_aggregate(policy, "1.0x", positive_windows=1))
        aggregates.append(eligible_aggregate(policy, "1.5x", aggregate_net_return=-0.01))
        aggregates.append(eligible_aggregate(policy, "2.0x", aggregate_net_return=-0.03))
    result = decide(aggregates, payload)
    assert result["economic_result"] == "REJECTED"
    assert result["selected_policy"] is None
    assert result["ranking"] == []
