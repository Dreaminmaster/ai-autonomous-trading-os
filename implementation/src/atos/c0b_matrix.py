"""C0B deterministic baseline matrix aggregation and candidate screening."""

from __future__ import annotations

import hashlib
from collections import defaultdict
from pathlib import Path
from typing import Any, Mapping, Sequence

from atos.profitability_diagnostics import (
    ProfitabilityDiagnosticsError,
    load_freqtrade_export,
    select_strategy_payload,
    write_json_atomic,
)

SCHEMA_VERSION = 2


class C0BMatrixError(RuntimeError):
    """Raised when C0B evidence is malformed, incomplete, or contradictory."""


def sha256_file(path: str | Path) -> str:
    try:
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()
    except OSError as exc:
        raise C0BMatrixError(f"unreadable file: {path}: {exc}") from exc


def _number(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise C0BMatrixError(f"{label} must be numeric")
    result = float(value)
    if not (float("-inf") < result < float("inf")):
        raise C0BMatrixError(f"{label} must be finite")
    return result


def _strategy_row(
    *,
    strategy_name: str,
    payload: Mapping[str, Any],
    timeframe: str,
    fee_rate: float,
    fee_multiplier: float,
    source_path: str,
) -> dict[str, Any]:
    trades = payload.get("trades")
    if not isinstance(trades, list):
        raise C0BMatrixError(f"{strategy_name}.trades must be a list")

    positive_profit = 0.0
    negative_profit = 0.0
    for index, trade in enumerate(trades):
        if not isinstance(trade, Mapping):
            raise C0BMatrixError(f"{strategy_name}.trade[{index}] must be an object")
        profit = _number(
            trade.get("profit_abs"),
            f"{strategy_name}.trade[{index}].profit_abs",
        )
        if profit > 0:
            positive_profit += profit
        elif profit < 0:
            negative_profit += profit

    raw_pairs = payload.get("results_per_pair")
    if not isinstance(raw_pairs, list):
        raise C0BMatrixError(f"{strategy_name}.results_per_pair must be a list")
    pair_rows: list[dict[str, Any]] = []
    for index, item in enumerate(raw_pairs):
        if not isinstance(item, Mapping):
            raise C0BMatrixError(
                f"{strategy_name}.results_per_pair[{index}] must be an object"
            )
        pair = item.get("key")
        if pair == "TOTAL":
            continue
        if not isinstance(pair, str) or not pair:
            raise C0BMatrixError(
                f"{strategy_name}.results_per_pair[{index}].key must be a pair"
            )
        pair_rows.append(
            {
                "pair": pair,
                "trades": int(item.get("trades", 0)),
                "net_profit_abs": _number(
                    item.get("profit_total_abs", 0.0),
                    f"{strategy_name}.{pair}.profit_total_abs",
                ),
                "net_return_ratio": _number(
                    item.get("profit_total", 0.0),
                    f"{strategy_name}.{pair}.profit_total",
                ),
            }
        )

    return {
        "strategy": strategy_name,
        "timeframe": timeframe,
        "fee_rate": fee_rate,
        "fee_multiplier": fee_multiplier,
        "source_path": source_path,
        "source_sha256": sha256_file(source_path),
        "trades": int(payload.get("total_trades", len(trades))),
        "net_profit_abs": _number(
            payload.get("profit_total_abs", 0.0),
            f"{strategy_name}.profit_total_abs",
        ),
        "net_return_ratio": _number(
            payload.get("profit_total", 0.0),
            f"{strategy_name}.profit_total",
        ),
        "max_drawdown_ratio": _number(
            payload.get("max_drawdown_account", 0.0),
            f"{strategy_name}.max_drawdown_account",
        ),
        "profit_factor": _number(
            payload.get("profit_factor", 0.0),
            f"{strategy_name}.profit_factor",
        ),
        "winrate": _number(payload.get("winrate", 0.0), f"{strategy_name}.winrate"),
        "expectancy_abs": _number(
            payload.get("expectancy", 0.0),
            f"{strategy_name}.expectancy",
        ),
        "sharpe": _number(payload.get("sharpe", 0.0), f"{strategy_name}.sharpe"),
        "sortino": _number(payload.get("sortino", 0.0), f"{strategy_name}.sortino"),
        "calmar": _number(payload.get("calmar", 0.0), f"{strategy_name}.calmar"),
        "turnover_abs": _number(
            payload.get("total_volume", 0.0),
            f"{strategy_name}.total_volume",
        ),
        "positive_profit_abs": positive_profit,
        "negative_profit_abs": negative_profit,
        "pairs": pair_rows,
    }


def summarize_result(
    *,
    export_path: str | Path,
    timeframe: str,
    fee_rate: float,
    fee_multiplier: float,
    expected_strategies: Sequence[str],
) -> list[dict[str, Any]]:
    try:
        export = load_freqtrade_export(export_path)
    except ProfitabilityDiagnosticsError as exc:
        raise C0BMatrixError(str(exc)) from exc

    strategies = export.get("strategy")
    if not isinstance(strategies, Mapping):
        raise C0BMatrixError("export.strategy must be a mapping")
    actual = set(strategies)
    expected = set(expected_strategies)
    if actual != expected:
        raise C0BMatrixError(
            f"strategy set mismatch: actual={sorted(actual)} expected={sorted(expected)}"
        )

    rows: list[dict[str, Any]] = []
    for name in expected_strategies:
        _, payload = select_strategy_payload(export, name)
        rows.append(
            _strategy_row(
                strategy_name=name,
                payload=payload,
                timeframe=timeframe,
                fee_rate=fee_rate,
                fee_multiplier=fee_multiplier,
                source_path=str(export_path),
            )
        )
    return rows


def _cost_snapshot(row: Mapping[str, Any]) -> dict[str, Any]:
    gains = float(row["positive_profit_abs"])
    losses = float(row["negative_profit_abs"])
    pair_profit = {
        str(pair["pair"]): float(pair["net_profit_abs"])
        for pair in row["pairs"]
    }
    return {
        "fee_multiplier": float(row["fee_multiplier"]),
        "net_profit_abs": float(row["net_profit_abs"]),
        "net_return_ratio": float(row["net_return_ratio"]),
        "total_trades": int(row["trades"]),
        "profit_factor": gains / abs(losses) if losses < 0 else None,
        "max_drawdown_ratio": float(row["max_drawdown_ratio"]),
        "turnover_abs": float(row["turnover_abs"]),
        "pair_net_profit_abs": dict(sorted(pair_profit.items())),
    }


def _screen_candidate(
    *,
    strategy: str,
    timeframe: str,
    rows: Sequence[Mapping[str, Any]],
    thresholds: Mapping[str, Any],
) -> dict[str, Any]:
    by_multiplier: dict[float, Mapping[str, Any]] = {}
    for row in rows:
        multiplier = float(row["fee_multiplier"])
        if multiplier in by_multiplier:
            raise C0BMatrixError(
                f"duplicate candidate cost row: strategy={strategy} "
                f"timeframe={timeframe} multiplier={multiplier}"
            )
        if str(row["strategy"]) != strategy or str(row["timeframe"]) != timeframe:
            raise C0BMatrixError("candidate row identity mismatch")
        by_multiplier[multiplier] = row

    required = {1.0, 1.5, 2.0}
    if set(by_multiplier) != required:
        raise C0BMatrixError(
            f"{strategy}/{timeframe} cost matrix mismatch: "
            f"{sorted(by_multiplier)} != {sorted(required)}"
        )

    expected = _cost_snapshot(by_multiplier[1.0])
    cost_1_5 = _cost_snapshot(by_multiplier[1.5])
    cost_2 = _cost_snapshot(by_multiplier[2.0])

    reasons: list[str] = []
    if expected["net_profit_abs"] <= 0 or expected["net_return_ratio"] <= 0:
        reasons.append("EXPECTED_COST_NET_NOT_POSITIVE")

    minimum_profit_factor = float(thresholds.get("minimum_profit_factor", 1.10))
    if (
        expected["profit_factor"] is None
        or expected["profit_factor"] < minimum_profit_factor
    ):
        reasons.append("PROFIT_FACTOR_BELOW_THRESHOLD")

    maximum_drawdown = float(thresholds.get("maximum_drawdown_ratio", 0.15))
    if expected["max_drawdown_ratio"] > maximum_drawdown:
        reasons.append("DRAWDOWN_ABOVE_THRESHOLD")

    minimum_trades = int(thresholds.get("minimum_trades", 30))
    if expected["total_trades"] < minimum_trades:
        reasons.append("INSUFFICIENT_TRADES")

    if cost_1_5["net_profit_abs"] < 0:
        reasons.append("NEGATIVE_AT_1_5X_COST")

    positive_pairs = {
        pair: value
        for pair, value in expected["pair_net_profit_abs"].items()
        if value > 0
    }
    minimum_positive_pairs = int(thresholds.get("minimum_positive_pairs", 2))
    if len(positive_pairs) < minimum_positive_pairs:
        reasons.append("INSUFFICIENT_POSITIVE_PAIRS")

    total_positive = sum(positive_pairs.values())
    if total_positive > 0:
        largest_share = max(positive_pairs.values()) / total_positive
        if largest_share > float(
            thresholds.get("maximum_pair_profit_share", 0.70)
        ):
            reasons.append("PAIR_PROFIT_CONCENTRATION")
    else:
        largest_share = None

    return {
        "candidate_id": f"{strategy}@{timeframe}",
        "strategy": strategy,
        "timeframe": timeframe,
        "status": "SURVIVES_C0B_SCREEN" if not reasons else "REJECTED",
        "rejection_reasons": reasons,
        "walk_forward_required": True,
        "expected_cost": expected,
        "cost_1_5x": cost_1_5,
        "cost_2x": cost_2,
        "largest_positive_pair_share": largest_share,
        "positive_pairs": sorted(positive_pairs),
    }


def _strategy_summary(
    strategy: str,
    candidates: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    survivors = [
        item for item in candidates if item["status"] == "SURVIVES_C0B_SCREEN"
    ]
    best = max(
        candidates,
        key=lambda item: float(item["expected_cost"]["net_return_ratio"]),
    )
    return {
        "strategy": strategy,
        "status": "HAS_C0B_SURVIVOR" if survivors else "NO_C0B_SURVIVOR",
        "surviving_timeframes": sorted(str(item["timeframe"]) for item in survivors),
        "best_candidate_id": best["candidate_id"],
        "best_expected_net_return_ratio": float(
            best["expected_cost"]["net_return_ratio"]
        ),
    }


def build_matrix_report(
    *,
    run_specs: Sequence[Mapping[str, Any]],
    config: Mapping[str, Any],
) -> dict[str, Any]:
    strategies = config.get("strategies")
    timeframes = config.get("timeframes")
    pairs = config.get("pairs")
    fee_multipliers = config.get("fee_multipliers")
    expected_fee = _number(config.get("expected_fee_rate"), "expected_fee_rate")

    if not isinstance(strategies, list) or not strategies or not all(
        isinstance(value, str) and value for value in strategies
    ):
        raise C0BMatrixError("config.strategies must be a non-empty string list")
    if not isinstance(timeframes, list) or not timeframes or not all(
        isinstance(value, str) and value for value in timeframes
    ):
        raise C0BMatrixError("config.timeframes must be a non-empty string list")
    if not isinstance(pairs, list) or not pairs or not all(
        isinstance(value, str) and value for value in pairs
    ):
        raise C0BMatrixError("config.pairs must be a non-empty string list")
    if not isinstance(fee_multipliers, list):
        raise C0BMatrixError("config.fee_multipliers must be a list")

    normalized_multipliers = [
        _number(value, "fee_multiplier") for value in fee_multipliers
    ]
    if sorted(normalized_multipliers) != [1.0, 1.5, 2.0]:
        raise C0BMatrixError("fee_multipliers must equal [1.0, 1.5, 2.0]")

    expected_specs = {
        (timeframe, multiplier)
        for timeframe in timeframes
        for multiplier in normalized_multipliers
    }
    actual_specs: set[tuple[str, float]] = set()
    rows: list[dict[str, Any]] = []

    for spec in run_specs:
        timeframe = str(spec.get("timeframe"))
        multiplier = _number(
            spec.get("fee_multiplier"),
            "run_spec.fee_multiplier",
        )
        key = (timeframe, multiplier)
        if key in actual_specs:
            raise C0BMatrixError(f"duplicate run spec: {key}")
        actual_specs.add(key)
        rows.extend(
            summarize_result(
                export_path=str(spec.get("export_path")),
                timeframe=timeframe,
                fee_rate=expected_fee * multiplier,
                fee_multiplier=multiplier,
                expected_strategies=strategies,
            )
        )

    if actual_specs != expected_specs:
        raise C0BMatrixError(
            f"matrix coverage mismatch: actual={sorted(actual_specs)} "
            f"expected={sorted(expected_specs)}"
        )

    expected_pair_set = set(pairs)
    for row in rows:
        actual_pair_set = {str(item["pair"]) for item in row["pairs"]}
        if actual_pair_set != expected_pair_set:
            raise C0BMatrixError(
                f"{row['strategy']}/{row['timeframe']} pair coverage mismatch: "
                f"{sorted(actual_pair_set)} != {sorted(expected_pair_set)}"
            )

    grouped: dict[tuple[str, str], list[Mapping[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[(str(row["strategy"]), str(row["timeframe"]))].append(row)

    thresholds = config.get("thresholds", {})
    if not isinstance(thresholds, Mapping):
        raise C0BMatrixError("config.thresholds must be a mapping")

    screening = [
        _screen_candidate(
            strategy=strategy,
            timeframe=timeframe,
            rows=grouped[(strategy, timeframe)],
            thresholds=thresholds,
        )
        for strategy in strategies
        for timeframe in timeframes
    ]
    summaries = [
        _strategy_summary(
            strategy,
            [item for item in screening if item["strategy"] == strategy],
        )
        for strategy in strategies
    ]

    return {
        "schema_version": SCHEMA_VERSION,
        "live": "FORBIDDEN",
        "timerange": config.get("timerange"),
        "pairs": pairs,
        "timeframes": timeframes,
        "expected_fee_rate": expected_fee,
        "fee_multipliers": normalized_multipliers,
        "strategies": strategies,
        "rows": rows,
        "candidate_screening": screening,
        "strategy_summary": summaries,
        "control_reference": config.get("frozen_control_reference"),
    }


def render_markdown(report: Mapping[str, Any]) -> str:
    lines = [
        "# C0B Deterministic Baseline Matrix",
        "",
        f"- Timerange: `{report.get('timerange')}`",
        f"- Pairs: `{', '.join(report.get('pairs', []))}`",
        f"- Timeframes: `{', '.join(report.get('timeframes', []))}`",
        f"- Expected per-side fee: `{float(report.get('expected_fee_rate', 0)):.4%}`",
        "- LIVE: `FORBIDDEN`",
        "",
        "## Candidate screening",
        "",
        "| Strategy | Timeframe | Status | Expected return | PF | DD | 1.5x net | Reasons |",
        "|---|---|---|---:|---:|---:|---:|---|",
    ]
    for item in report.get("candidate_screening", []):
        expected = item["expected_cost"]
        factor = expected["profit_factor"]
        factor_text = "n/a" if factor is None else f"{factor:.3f}"
        reasons = ", ".join(item["rejection_reasons"]) or "none"
        lines.append(
            f"| {item['strategy']} | {item['timeframe']} | {item['status']} | "
            f"{expected['net_return_ratio']:.2%} | {factor_text} | "
            f"{expected['max_drawdown_ratio']:.2%} | "
            f"{item['cost_1_5x']['net_profit_abs']:.2f} | {reasons} |"
        )

    lines.extend(
        [
            "",
            "## Strategy summary",
            "",
            "| Strategy | Status | Survivors | Best candidate | Best expected return |",
            "|---|---|---|---|---:|",
        ]
    )
    for item in report.get("strategy_summary", []):
        survivors = ", ".join(item["surviving_timeframes"]) or "none"
        lines.append(
            f"| {item['strategy']} | {item['status']} | {survivors} | "
            f"{item['best_candidate_id']} | "
            f"{item['best_expected_net_return_ratio']:.2%} |"
        )

    lines.extend(
        [
            "",
            "C0B survival is not paper eligibility. Every surviving strategy/timeframe "
            "candidate still requires C0C walk-forward and untouched test evidence.",
            "",
        ]
    )
    return "\n".join(lines)


def write_report_files(
    report: Mapping[str, Any],
    *,
    json_path: str | Path,
    markdown_path: str | Path,
) -> None:
    write_json_atomic(json_path, report)
    Path(markdown_path).write_text(render_markdown(report), encoding="utf-8")
