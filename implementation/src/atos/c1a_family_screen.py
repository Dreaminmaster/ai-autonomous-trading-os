"""Deterministic C1A family-screen aggregation, gates, and ranking."""
from __future__ import annotations

import math
import statistics
from collections import defaultdict
from typing import Any, Mapping, Sequence


class C1AFamilyScreenError(RuntimeError):
    """Raised when C1A evidence is missing, inconsistent, or contract-drifted."""


def _number(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise C1AFamilyScreenError(f"{label} must be numeric")
    result = float(value)
    if not math.isfinite(result):
        raise C1AFamilyScreenError(f"{label} must be finite")
    return result


def _integer(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise C1AFamilyScreenError(f"{label} must be an integer")
    return value


def _mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise C1AFamilyScreenError(f"{label} must be an object")
    return value


def validate_config(config: Mapping[str, Any]) -> dict[str, Any]:
    if config.get("stage") != "C1A":
        raise C1AFamilyScreenError("stage drift")
    if config.get("live") != "FORBIDDEN":
        raise C1AFamilyScreenError("LIVE must remain FORBIDDEN")
    if config.get("holdout_state") != "HOLDOUT_CLOSED":
        raise C1AFamilyScreenError("holdout must remain closed")
    if config.get("confirmation_opened") is not False:
        raise C1AFamilyScreenError("confirmation must remain closed")
    if config.get("required_base_sha") != "967497fe726452a60fb6d0e84c10f027873951bf":
        raise C1AFamilyScreenError("base SHA drift")
    strategies = config.get("strategies")
    expected_strategies = ["C1ARegimeBreakout", "C1ATrendPullback", "C1ADualMomentum"]
    if strategies != expected_strategies:
        raise C1AFamilyScreenError("strategy family drift")
    if config.get("pairs") != ["BTC/USDT", "ETH/USDT", "SOL/USDT"]:
        raise C1AFamilyScreenError("pair universe drift")
    if config.get("timeframe") != "1h" or config.get("informative_timeframe") != "1d":
        raise C1AFamilyScreenError("timeframe drift")
    if config.get("economic_boundary_exclusive") != "2024-10-01T00:00:00Z":
        raise C1AFamilyScreenError("screen boundary drift")
    if config.get("fee_multipliers") != [1.0, 1.5, 2.0]:
        raise C1AFamilyScreenError("fee multiplier drift")
    if _number(config.get("expected_fee_rate"), "expected_fee_rate") != 0.0015:
        raise C1AFamilyScreenError("expected fee drift")
    if _number(config.get("slippage_rate"), "slippage_rate") != 0.0:
        raise C1AFamilyScreenError("slippage policy drift")

    windows = config.get("screen_windows")
    if not isinstance(windows, list) or windows != [
        {"id": "S1", "start": "2024-01-01", "end": "2024-04-01"},
        {"id": "S2", "start": "2024-04-01", "end": "2024-07-01"},
        {"id": "S3", "start": "2024-07-01", "end": "2024-10-01"},
    ]:
        raise C1AFamilyScreenError("screen window drift")
    reserved = config.get("reserved_confirmation_windows")
    if not isinstance(reserved, list) or reserved != [
        {"id": "C1", "start": "2024-10-01", "end": "2025-01-01"},
        {"id": "C2", "start": "2025-01-01", "end": "2025-04-01"},
        {"id": "C3", "start": "2025-04-01", "end": "2025-07-01"},
    ]:
        raise C1AFamilyScreenError("reserved confirmation window drift")

    gate = _mapping(config.get("gate"), "gate")
    expected_gate = {
        "minimum_positive_windows": 2,
        "require_positive_median_window_return": True,
        "require_positive_aggregate_expected_return": True,
        "require_nonnegative_aggregate_1_5x_return": True,
        "minimum_profit_factor": 1.1,
        "maximum_window_drawdown_ratio": 0.15,
        "minimum_total_trades": 30,
        "minimum_trades_per_window": 5,
        "minimum_positive_pairs": 2,
        "maximum_pair_profit_share": 0.7,
        "maximum_window_profit_share": 0.6,
        "maximum_single_trade_profit_share": 0.25,
        "top_trade_cluster_size": 3,
        "maximum_top_trade_cluster_profit_share": 0.5,
    }
    if dict(gate) != expected_gate:
        raise C1AFamilyScreenError("gate drift")
    expected_selection = [
        "median_window_return_drawdown_ratio_desc",
        "aggregate_1_5x_net_return_desc",
        "aggregate_expected_profit_factor_desc",
        "maximum_window_drawdown_asc",
        "turnover_ratio_asc",
        "total_trades_desc",
        "family_id_asc",
    ]
    if config.get("selection_order") != expected_selection:
        raise C1AFamilyScreenError("selection order drift")
    return {
        "families": expected_strategies,
        "windows": [item["id"] for item in windows],
        "costs": [1.0, 1.5, 2.0],
        "pairs": list(config["pairs"]),
        "gate": expected_gate,
    }


def _normalize_pairs(value: Any, expected_pairs: Sequence[str], label: str) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise C1AFamilyScreenError(f"{label}.pairs must be a list")
    result: list[dict[str, Any]] = []
    for index, item in enumerate(value):
        row = _mapping(item, f"{label}.pairs[{index}]")
        pair = row.get("pair")
        if pair not in expected_pairs:
            raise C1AFamilyScreenError(f"{label}.pairs[{index}] unexpected pair")
        result.append(
            {
                "pair": pair,
                "trades": _integer(row.get("trades"), f"{label}.{pair}.trades"),
                "net_profit_abs": _number(
                    row.get("net_profit_abs"), f"{label}.{pair}.net_profit_abs"
                ),
            }
        )
    if {item["pair"] for item in result} != set(expected_pairs) or len(result) != len(expected_pairs):
        raise C1AFamilyScreenError(f"{label} pair coverage mismatch")
    return sorted(result, key=lambda item: item["pair"])


def normalize_row(
    row: Mapping[str, Any], *, families: Sequence[str], windows: Sequence[str], pairs: Sequence[str]
) -> dict[str, Any]:
    family = row.get("family_id")
    window = row.get("window_id")
    if family not in families:
        raise C1AFamilyScreenError("unexpected family_id")
    if window not in windows:
        raise C1AFamilyScreenError("unexpected window_id")
    cost = _number(row.get("cost_multiplier"), "cost_multiplier")
    if cost not in {1.0, 1.5, 2.0}:
        raise C1AFamilyScreenError("unexpected cost multiplier")
    expected_fee = 0.0015 * cost
    if _number(row.get("fee_rate"), "fee_rate") != expected_fee:
        raise C1AFamilyScreenError("fee rate not bound to cost multiplier")
    binding = _mapping(row.get("fee_binding"), "fee_binding")
    if binding.get("verified") is not True:
        raise C1AFamilyScreenError("fee binding not verified")
    if _number(binding.get("expected_fee_rate"), "fee_binding.expected_fee_rate") != expected_fee:
        raise C1AFamilyScreenError("fee binding expected rate drift")
    trades = _integer(row.get("trades"), "trades")
    if trades < 0:
        raise C1AFamilyScreenError("trades must be nonnegative")
    starting = _number(row.get("starting_balance"), "starting_balance")
    if starting <= 0:
        raise C1AFamilyScreenError("starting_balance must be positive")
    positives = row.get("positive_trade_profits_abs")
    if not isinstance(positives, list):
        raise C1AFamilyScreenError("positive_trade_profits_abs must be a list")
    normalized_positives = sorted(
        (_number(value, "positive trade profit") for value in positives), reverse=True
    )
    if any(value <= 0 for value in normalized_positives):
        raise C1AFamilyScreenError("positive trade profit must be positive")
    positive_sum = _number(row.get("positive_profit_abs"), "positive_profit_abs")
    if abs(sum(normalized_positives) - positive_sum) > 1e-7:
        raise C1AFamilyScreenError("positive trade list does not reconcile")
    negative_sum = _number(row.get("negative_profit_abs"), "negative_profit_abs")
    if negative_sum > 0:
        raise C1AFamilyScreenError("negative_profit_abs must be nonpositive")
    net_profit = _number(row.get("net_profit_abs"), "net_profit_abs")
    if abs((positive_sum + negative_sum) - net_profit) > 1e-7:
        raise C1AFamilyScreenError("profit components do not reconcile")
    net_return = _number(row.get("net_return_ratio"), "net_return_ratio")
    if abs(net_profit / starting - net_return) > 1e-7:
        raise C1AFamilyScreenError("net return does not reconcile to starting balance")
    return {
        "family_id": family,
        "window_id": window,
        "cost_multiplier": cost,
        "fee_rate": expected_fee,
        "fee_binding": dict(binding),
        "starting_balance": starting,
        "trades": trades,
        "net_profit_abs": net_profit,
        "net_return_ratio": net_return,
        "max_drawdown_ratio": _number(row.get("max_drawdown_ratio"), "max_drawdown_ratio"),
        "profit_factor": _number(row.get("profit_factor"), "profit_factor"),
        "positive_profit_abs": positive_sum,
        "negative_profit_abs": negative_sum,
        "positive_trade_profits_abs": normalized_positives,
        "pairs": _normalize_pairs(row.get("pairs"), pairs, f"{family}.{window}.{cost}"),
        "turnover_ratio": _number(row.get("turnover_ratio"), "turnover_ratio"),
        "export_sha256": row.get("export_sha256"),
        "command_sha256": row.get("command_sha256"),
    }


def _profit_factor(gains: float, losses: float) -> float:
    if losses < 0:
        return gains / abs(losses)
    return 0.0 if gains == 0 else 1e12


def evaluate_family(
    family_id: str,
    rows: Sequence[Mapping[str, Any]],
    *,
    config: Mapping[str, Any],
) -> dict[str, Any]:
    contract = validate_config(config)
    normalized = [
        normalize_row(
            row,
            families=contract["families"],
            windows=contract["windows"],
            pairs=contract["pairs"],
        )
        for row in rows
    ]
    family_rows = [row for row in normalized if row["family_id"] == family_id]
    expected_keys = {
        (window, cost) for window in contract["windows"] for cost in contract["costs"]
    }
    actual_keys = {(row["window_id"], row["cost_multiplier"]) for row in family_rows}
    if len(family_rows) != len(expected_keys) or actual_keys != expected_keys:
        raise C1AFamilyScreenError(f"{family_id} row coverage mismatch")

    by_key = {(row["window_id"], row["cost_multiplier"]): row for row in family_rows}
    expected_rows = [by_key[(window, 1.0)] for window in contract["windows"]]
    stress_rows = [by_key[(window, 1.5)] for window in contract["windows"]]
    positive_windows = sum(row["net_return_ratio"] > 0 for row in expected_rows)
    median_window_return = statistics.median(row["net_return_ratio"] for row in expected_rows)
    aggregate_expected_profit = sum(row["net_profit_abs"] for row in expected_rows)
    aggregate_stress_profit = sum(row["net_profit_abs"] for row in stress_rows)
    starting = expected_rows[0]["starting_balance"]
    if any(abs(row["starting_balance"] - starting) > 1e-9 for row in family_rows):
        raise C1AFamilyScreenError(f"{family_id} starting balance drift")
    aggregate_expected_return = aggregate_expected_profit / starting
    aggregate_stress_return = aggregate_stress_profit / starting
    gains = sum(row["positive_profit_abs"] for row in expected_rows)
    losses = sum(row["negative_profit_abs"] for row in expected_rows)
    aggregate_profit_factor = _profit_factor(gains, losses)
    max_window_drawdown = max(row["max_drawdown_ratio"] for row in expected_rows)
    total_trades = sum(row["trades"] for row in expected_rows)
    minimum_window_trades = min(row["trades"] for row in expected_rows)
    turnover_ratio = sum(row["turnover_ratio"] for row in expected_rows)

    pair_profit = defaultdict(float)
    pair_trades = defaultdict(int)
    for row in expected_rows:
        for pair in row["pairs"]:
            pair_profit[pair["pair"]] += pair["net_profit_abs"]
            pair_trades[pair["pair"]] += pair["trades"]
    positive_pair_profit = {pair: value for pair, value in pair_profit.items() if value > 0}
    total_positive_pair_profit = sum(positive_pair_profit.values())
    max_pair_share = (
        max(positive_pair_profit.values()) / total_positive_pair_profit
        if total_positive_pair_profit > 0
        else 0.0
    )
    positive_window_profits = [row["net_profit_abs"] for row in expected_rows if row["net_profit_abs"] > 0]
    total_positive_window_profit = sum(positive_window_profits)
    max_window_profit_share = (
        max(positive_window_profits) / total_positive_window_profit
        if total_positive_window_profit > 0
        else 0.0
    )
    positive_trades = sorted(
        [value for row in expected_rows for value in row["positive_trade_profits_abs"]],
        reverse=True,
    )
    total_positive_trade_profit = sum(positive_trades)
    largest_trade_share = (
        positive_trades[0] / total_positive_trade_profit
        if total_positive_trade_profit > 0 and positive_trades
        else 0.0
    )
    top_cluster_size = contract["gate"]["top_trade_cluster_size"]
    top_cluster_share = (
        sum(positive_trades[:top_cluster_size]) / total_positive_trade_profit
        if total_positive_trade_profit > 0
        else 0.0
    )
    ratios = [
        row["net_return_ratio"] / max(row["max_drawdown_ratio"], 1e-9)
        for row in expected_rows
    ]
    median_return_drawdown_ratio = statistics.median(ratios)

    gate = contract["gate"]
    checks = {
        "positive_windows": positive_windows >= gate["minimum_positive_windows"],
        "positive_median_window_return": median_window_return > 0,
        "positive_aggregate_expected_return": aggregate_expected_return > 0,
        "nonnegative_aggregate_1_5x_return": aggregate_stress_return >= 0,
        "minimum_profit_factor": aggregate_profit_factor >= gate["minimum_profit_factor"],
        "maximum_window_drawdown": max_window_drawdown <= gate["maximum_window_drawdown_ratio"],
        "minimum_total_trades": total_trades >= gate["minimum_total_trades"],
        "minimum_trades_per_window": minimum_window_trades >= gate["minimum_trades_per_window"],
        "minimum_positive_pairs": len(positive_pair_profit) >= gate["minimum_positive_pairs"],
        "maximum_pair_profit_share": max_pair_share <= gate["maximum_pair_profit_share"],
        "maximum_window_profit_share": max_window_profit_share <= gate["maximum_window_profit_share"],
        "maximum_single_trade_profit_share": largest_trade_share
        <= gate["maximum_single_trade_profit_share"],
        "maximum_top_trade_cluster_profit_share": top_cluster_share
        <= gate["maximum_top_trade_cluster_profit_share"],
    }
    eligible = all(checks.values())
    return {
        "family_id": family_id,
        "eligible": eligible,
        "checks": checks,
        "positive_windows": positive_windows,
        "median_window_return_ratio": median_window_return,
        "aggregate_expected_net_profit_abs": aggregate_expected_profit,
        "aggregate_expected_net_return_ratio": aggregate_expected_return,
        "aggregate_1_5x_net_profit_abs": aggregate_stress_profit,
        "aggregate_1_5x_net_return_ratio": aggregate_stress_return,
        "aggregate_expected_profit_factor": aggregate_profit_factor,
        "maximum_window_drawdown_ratio": max_window_drawdown,
        "total_trades": total_trades,
        "minimum_window_trades": minimum_window_trades,
        "turnover_ratio": turnover_ratio,
        "positive_pairs": sorted(positive_pair_profit),
        "pair_summary": [
            {
                "pair": pair,
                "trades": pair_trades[pair],
                "net_profit_abs": pair_profit[pair],
            }
            for pair in sorted(pair_profit)
        ],
        "maximum_pair_profit_share": max_pair_share,
        "maximum_window_profit_share": max_window_profit_share,
        "largest_positive_trade_share": largest_trade_share,
        "top_positive_trade_count": top_cluster_size,
        "top_positive_trade_share": top_cluster_share,
        "median_window_return_drawdown_ratio": median_return_drawdown_ratio,
        "window_rows": expected_rows,
        "stress_rows": stress_rows,
    }


def _rank_key(item: Mapping[str, Any]) -> tuple[Any, ...]:
    return (
        -_number(item["median_window_return_drawdown_ratio"], "rank median ratio"),
        -_number(item["aggregate_1_5x_net_return_ratio"], "rank stress return"),
        -_number(item["aggregate_expected_profit_factor"], "rank profit factor"),
        _number(item["maximum_window_drawdown_ratio"], "rank drawdown"),
        _number(item["turnover_ratio"], "rank turnover"),
        -_integer(item["total_trades"], "rank total trades"),
        str(item["family_id"]),
    )


def evaluate_screen(rows: Sequence[Mapping[str, Any]], config: Mapping[str, Any]) -> dict[str, Any]:
    contract = validate_config(config)
    decisions = [
        evaluate_family(family, rows, config=config) for family in contract["families"]
    ]
    eligible = sorted((item for item in decisions if item["eligible"]), key=_rank_key)
    selected = eligible[0]["family_id"] if eligible else None
    return {
        "schema_version": 1,
        "stage": "C1A",
        "status": "SELECTED" if selected else "REJECTED",
        "selected_family": selected,
        "confirmation_opened": False,
        "holdout_state": "HOLDOUT_CLOSED",
        "live": "FORBIDDEN",
        "family_decisions": decisions,
        "eligible_ranking": [item["family_id"] for item in eligible],
    }
