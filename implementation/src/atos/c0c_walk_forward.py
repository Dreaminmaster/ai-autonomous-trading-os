"""C0C cost-aware EMA development walk-forward evidence."""
from __future__ import annotations

import hashlib
import json
import math
import re
import statistics
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, Mapping, Sequence

from atos.profitability_diagnostics import (
    ProfitabilityDiagnosticsError,
    buy_and_hold_metrics,
    extract_trades,
    load_freqtrade_export,
    select_strategy_payload,
)

SCHEMA_VERSION = 2
STRATEGY = "C0CCostAwareEMA"
STARTUP_CANDLE_COUNT = 1999
PARAM_RANGES = {
    "enter_spread_threshold": (0.001, 0.008),
    "enter_slow_slope_min": (0.001, 0.010),
    "enter_atr_ratio_min": (0.002, 0.012),
    "enter_htf_slope_min": (0.000, 0.010),
}
REQUIRED_COSTS = {1.0, 1.5, 2.0}
STARTUP_ANALYSIS = {
    "pairs": ["BTC/USDT", "ETH/USDT", "SOL/USDT"],
    "timerange": "20240101-20240201",
    "startup_candidates": [499, 999, 1999, 3999],
    "selected_startup_candles": STARTUP_CANDLE_COUNT,
    "max_variance_pct": 0.10,
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
HYPEROPT = {
    "loss": "MultiMetricHyperOptLoss",
    "space": "enter",
    "epochs": 200,
    "random_state": 20260715,
    "min_trades": 30,
    "fee_rate": 0.00225,
    "workers": 2,
    "shortlist_size": 3,
    "selection_policy": "top_loss_shortlist_validation_rank_v1",
}
CONCENTRATION_THRESHOLDS = {
    "maximum_single_trade_profit_share": 0.25,
    "top_trade_cluster_size": 3,
    "maximum_top_trade_cluster_profit_share": 0.50,
}


class C0CWalkForwardError(RuntimeError):
    """Raised when C0C evidence is incomplete, inconsistent, or leaked."""


def sha256_file(path: str | Path) -> str:
    try:
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()
    except OSError as exc:
        raise C0CWalkForwardError(f"unreadable file: {path}: {exc}") from exc


def _number(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise C0CWalkForwardError(f"{label} must be numeric")
    result = float(value)
    if not math.isfinite(result):
        raise C0CWalkForwardError(f"{label} must be finite")
    return result


def _positive_number(value: Any, label: str, *, allow_zero: bool = False) -> float:
    result = _number(value, label)
    if result < 0 or (result == 0 and not allow_zero):
        qualifier = "non-negative" if allow_zero else "positive"
        raise C0CWalkForwardError(f"{label} must be {qualifier}")
    return result


def _day(value: Any, label: str) -> date:
    if not isinstance(value, str):
        raise C0CWalkForwardError(f"{label} must be YYYY-MM-DD")
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise C0CWalkForwardError(f"{label} invalid: {value!r}") from exc


def validate_config(config: Mapping[str, Any]) -> dict[str, Any]:
    if config.get("candidate_id") != "c0c-cost-aware-ema-v1":
        raise C0CWalkForwardError("candidate_id drift")
    if config.get("live") != "FORBIDDEN":
        raise C0CWalkForwardError("LIVE must remain FORBIDDEN")
    if config.get("holdout_state") != "HOLDOUT_CLOSED":
        raise C0CWalkForwardError("development workflow requires HOLDOUT_CLOSED")
    if config.get("strategy") != STRATEGY or config.get("timeframe") != "5m":
        raise C0CWalkForwardError("strategy/timeframe drift")
    if config.get("informative_timeframe") != "1h":
        raise C0CWalkForwardError("informative timeframe drift")
    if config.get("pairs") != ["BTC/USDT", "ETH/USDT", "SOL/USDT"]:
        raise C0CWalkForwardError("pair universe drift")
    if config.get("data_timerange") != "20231101-20250701":
        raise C0CWalkForwardError("development data timerange drift")
    if config.get("fee_multipliers") != [1.0, 1.5, 2.0]:
        raise C0CWalkForwardError("fee multiplier drift")
    if _number(config.get("expected_fee_rate"), "expected_fee_rate") != 0.0015:
        raise C0CWalkForwardError("expected fee drift")
    if config.get("hyperopt") != HYPEROPT:
        raise C0CWalkForwardError("hyperopt contract drift")
    if config.get("startup_analysis") != STARTUP_ANALYSIS:
        raise C0CWalkForwardError("startup_analysis drift")
    if config.get("parameter_ranges") != {
        key: [low, high] for key, (low, high) in PARAM_RANGES.items()
    }:
        raise C0CWalkForwardError("parameter range drift")

    thresholds = config.get("thresholds")
    if not isinstance(thresholds, Mapping):
        raise C0CWalkForwardError("thresholds missing")
    for key, value in CONCENTRATION_THRESHOLDS.items():
        if thresholds.get(key) != value:
            raise C0CWalkForwardError(f"thresholds.{key} drift")
    if thresholds.get("turnover_definition") != "entry_plus_exit_notional_divided_by_starting_balance":
        raise C0CWalkForwardError("turnover definition drift")

    folds = config.get("folds")
    if not isinstance(folds, list) or len(folds) != 3:
        raise C0CWalkForwardError("exactly three folds required")
    normalized: list[dict[str, Any]] = []
    prior_test_end: date | None = None
    for index, fold in enumerate(folds, start=1):
        if not isinstance(fold, Mapping) or fold.get("id") != str(index):
            raise C0CWalkForwardError("fold identity drift")
        train_start = _day(fold.get("train_start"), f"fold {index} train_start")
        train_end = _day(fold.get("train_end"), f"fold {index} train_end")
        validation_start = _day(fold.get("validation_start"), f"fold {index} validation_start")
        validation_end = _day(fold.get("validation_end"), f"fold {index} validation_end")
        test_start = _day(fold.get("test_start"), f"fold {index} test_start")
        test_end = _day(fold.get("test_end"), f"fold {index} test_end")
        if not (train_start < train_end == validation_start < validation_end == test_start < test_end):
            raise C0CWalkForwardError(f"fold {index} has leakage or gaps")
        if prior_test_end is not None and test_end <= prior_test_end:
            raise C0CWalkForwardError("fold test endpoints must advance")
        prior_test_end = test_end
        normalized.append(dict(fold))

    holdout = config.get("holdout")
    if not isinstance(holdout, Mapping):
        raise C0CWalkForwardError("holdout missing")
    holdout_start = _day(holdout.get("start"), "holdout.start")
    holdout_end = _day(holdout.get("end"), "holdout.end")
    if holdout_start.isoformat() != "2025-07-01" or holdout_end.isoformat() != "2026-07-01":
        raise C0CWalkForwardError("holdout boundary drift")
    if prior_test_end != holdout_start:
        raise C0CWalkForwardError("development must end exactly where holdout begins")
    return {"folds": normalized, "holdout_start": holdout_start.isoformat()}


def _collect_params(value: Any, found: dict[str, float]) -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            if key in PARAM_RANGES:
                found[key] = _number(item, f"parameter {key}")
            else:
                _collect_params(item, found)
    elif isinstance(value, list):
        for item in value:
            _collect_params(item, found)


def validate_parameter_payload(payload: Mapping[str, Any]) -> dict[str, float]:
    if payload.get("strategy_name") != STRATEGY:
        raise C0CWalkForwardError("parameter strategy identity mismatch")
    found: dict[str, float] = {}
    _collect_params(payload.get("params"), found)
    if set(found) != set(PARAM_RANGES):
        raise C0CWalkForwardError(f"parameter set mismatch: {sorted(found)}")
    for key, value in found.items():
        low, high = PARAM_RANGES[key]
        if not low <= value <= high:
            raise C0CWalkForwardError(f"{key} outside preregistered range")
    return dict(sorted(found.items()))


def validate_parameter_file(path: str | Path) -> dict[str, float]:
    source = Path(path)
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise C0CWalkForwardError(f"invalid parameter file {source}: {exc}") from exc
    if not isinstance(payload, Mapping):
        raise C0CWalkForwardError("parameter file must contain an object")
    return validate_parameter_payload(payload)


def _profit_sums(trades: Sequence[Mapping[str, Any]]) -> tuple[float, float]:
    gains = losses = 0.0
    for index, trade in enumerate(trades):
        if not isinstance(trade, Mapping):
            raise C0CWalkForwardError(f"trade[{index}] must be an object")
        profit = _number(trade.get("profit_abs"), f"trade[{index}].profit_abs")
        if profit > 0:
            gains += profit
        elif profit < 0:
            losses += profit
    return gains, losses


def _verify_fee_binding(trades: Sequence[Mapping[str, Any]], expected_rate: float) -> dict[str, Any]:
    observed: set[float] = set()
    if not trades:
        return {
            "verified": True,
            "expected_fee_rate": expected_rate,
            "observed_fee_rates": [],
            "basis": "no_trades_no_fee_effect_command_bound",
        }
    for index, trade in enumerate(trades):
        for field in ("fee_open", "fee_close"):
            if field not in trade:
                raise C0CWalkForwardError(f"trade[{index}] missing {field} fee evidence")
            value = _number(trade.get(field), f"trade[{index}].{field}")
            if abs(value - expected_rate) > 1e-12:
                raise C0CWalkForwardError(
                    f"trade[{index}].{field} fee {value} != expected {expected_rate}"
                )
            observed.add(value)
    return {
        "verified": True,
        "expected_fee_rate": expected_rate,
        "observed_fee_rates": sorted(observed),
        "basis": "per_trade_export",
    }


def _trade_notional(trade: Mapping[str, Any], index: int) -> float:
    entry = exit_ = 0.0
    orders = trade.get("orders", [])
    if not isinstance(orders, list):
        raise C0CWalkForwardError(f"trade[{index}].orders must be a list")
    for order_index, order in enumerate(orders):
        if not isinstance(order, Mapping):
            raise C0CWalkForwardError(f"trade[{index}].orders[{order_index}] must be an object")
        cost = _positive_number(
            order.get("cost", 0.0), f"trade[{index}].orders[{order_index}].cost", allow_zero=True
        )
        if bool(order.get("ft_is_entry", False)):
            entry += cost
        else:
            exit_ += cost
    if entry <= 0:
        entry = _positive_number(trade.get("stake_amount"), f"trade[{index}].stake_amount")
    if exit_ <= 0:
        amount = _positive_number(trade.get("amount"), f"trade[{index}].amount")
        close_rate = _positive_number(trade.get("close_rate"), f"trade[{index}].close_rate")
        exit_ = amount * close_rate
    return entry + exit_


def _exit_reason_summary(trades: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}
    for index, trade in enumerate(trades):
        reason = trade.get("exit_reason")
        if not isinstance(reason, str) or not reason.strip():
            raise C0CWalkForwardError(f"trade[{index}] missing exit_reason")
        item = grouped.setdefault(reason, {"exit_reason": reason, "trades": 0, "net_profit_abs": 0.0})
        item["trades"] += 1
        item["net_profit_abs"] += _number(trade.get("profit_abs"), f"trade[{index}].profit_abs")
    return sorted(grouped.values(), key=lambda item: item["exit_reason"])


def _positive_profit_concentration(trades: Sequence[Mapping[str, Any]], cluster_size: int) -> dict[str, Any]:
    positives = sorted(
        (_number(trade.get("profit_abs"), f"trade[{index}].profit_abs") for index, trade in enumerate(trades)),
        reverse=True,
    )
    positives = [value for value in positives if value > 0]
    total = sum(positives)
    largest = positives[0] if positives else 0.0
    cluster = sum(positives[:cluster_size])
    return {
        "positive_trade_profits_abs": positives,
        "largest_positive_trade_profit_abs": largest,
        "largest_positive_trade_share": largest / total if total > 0 else 0.0,
        "top_positive_trade_count": cluster_size,
        "top_positive_trade_profit_abs": cluster,
        "top_positive_trade_share": cluster / total if total > 0 else 0.0,
    }


def summarize_export(
    *,
    export_path: str | Path,
    params_path: str | Path,
    fold_id: str,
    role: str,
    cost_multiplier: float,
    expected_pairs: Sequence[str],
    candidate_id: str | None = None,
    training_epoch: int | None = None,
    training_loss: float | None = None,
) -> dict[str, Any]:
    if role not in {"validation", "development_test", "final_validation"}:
        raise C0CWalkForwardError(f"invalid role: {role}")
    try:
        export = load_freqtrade_export(export_path)
        _, payload = select_strategy_payload(export, STRATEGY)
        trades = extract_trades(payload)
    except ProfitabilityDiagnosticsError as exc:
        raise C0CWalkForwardError(str(exc)) from exc
    if int(payload.get("total_trades", len(trades))) != len(trades):
        raise C0CWalkForwardError("summary/trade count mismatch")
    if payload.get("timeframe") != "5m":
        raise C0CWalkForwardError("export timeframe drift")
    gains, losses = _profit_sums(trades)
    expected_fee = 0.0015 * float(cost_multiplier)
    fee_binding = _verify_fee_binding(trades, expected_fee)
    raw_pairs = payload.get("results_per_pair")
    if not isinstance(raw_pairs, list):
        raise C0CWalkForwardError("results_per_pair missing")
    pairs: list[dict[str, Any]] = []
    for item in raw_pairs:
        if not isinstance(item, Mapping) or item.get("key") == "TOTAL":
            continue
        pairs.append({
            "pair": str(item.get("key")),
            "trades": int(item.get("trades", 0)),
            "net_profit_abs": _number(item.get("profit_total_abs", 0.0), "pair profit"),
            "net_return_ratio": _number(item.get("profit_total", 0.0), "pair return"),
        })
    if {item["pair"] for item in pairs} != set(expected_pairs):
        raise C0CWalkForwardError("pair coverage mismatch")
    parameters = validate_parameter_file(params_path)
    starting = _positive_number(payload.get("starting_balance"), "starting_balance")
    turnover_notional = sum(_trade_notional(trade, index) for index, trade in enumerate(trades))
    concentration = _positive_profit_concentration(
        trades, CONCENTRATION_THRESHOLDS["top_trade_cluster_size"]
    )
    row = {
        "fold_id": fold_id,
        "role": role,
        "candidate_id": candidate_id or "selected",
        "cost_multiplier": float(cost_multiplier),
        "fee_rate": expected_fee,
        "fee_binding": fee_binding,
        "export_path": str(export_path),
        "export_sha256": sha256_file(export_path),
        "params_path": str(params_path),
        "params_sha256": sha256_file(params_path),
        "parameters": parameters,
        "starting_balance": starting,
        "trades": len(trades),
        "net_profit_abs": _number(payload.get("profit_total_abs"), "profit_total_abs"),
        "net_return_ratio": _number(payload.get("profit_total"), "profit_total"),
        "max_drawdown_ratio": _number(payload.get("max_drawdown_account"), "max_drawdown_account"),
        "profit_factor": _number(payload.get("profit_factor", 0.0), "profit_factor"),
        "positive_profit_abs": gains,
        "negative_profit_abs": losses,
        "pairs": sorted(pairs, key=lambda item: item["pair"]),
        "market_change": _number(payload.get("market_change", 0.0), "market_change"),
        "turnover_notional_abs": turnover_notional,
        "turnover_ratio": turnover_notional / starting,
        "exit_reason_summary": _exit_reason_summary(trades),
        **concentration,
    }
    if training_epoch is not None:
        row["training_epoch"] = int(training_epoch)
    if training_loss is not None:
        row["training_loss"] = _number(training_loss, "training_loss")
    return row


def _flatten_json_values(value: Any) -> list[Mapping[str, Any]]:
    if isinstance(value, list):
        result: list[Mapping[str, Any]] = []
        for item in value:
            result.extend(_flatten_json_values(item))
        return result
    if isinstance(value, Mapping):
        for key in ("epochs", "results", "data"):
            nested = value.get(key)
            if isinstance(nested, list):
                return _flatten_json_values(nested)
        return [value]
    return []


def _json_values_from_text(text: str) -> list[Mapping[str, Any]]:
    values: list[Mapping[str, Any]] = []
    try:
        values.extend(_flatten_json_values(json.loads(text)))
    except json.JSONDecodeError:
        decoder = json.JSONDecoder()
        for line in text.splitlines():
            stripped = line.strip()
            for index, char in enumerate(stripped):
                if char not in "[{":
                    continue
                try:
                    value, _ = decoder.raw_decode(stripped[index:])
                except json.JSONDecodeError:
                    continue
                values.extend(_flatten_json_values(value))
                break
    return values


def _epoch_number(value: Any) -> int:
    if isinstance(value, bool):
        raise C0CWalkForwardError("hyperopt epoch must be an integer")
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str):
        match = re.match(r"\s*(\d+)", value)
        if match:
            return int(match.group(1))
    raise C0CWalkForwardError(f"invalid hyperopt epoch: {value!r}")


def parse_hyperopt_list_output(path: str | Path, shortlist_size: int) -> list[dict[str, Any]]:
    try:
        text = Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        raise C0CWalkForwardError(f"unable to read hyperopt-list output: {exc}") from exc
    records: dict[int, dict[str, Any]] = {}
    for item in _json_values_from_text(text):
        epoch_value = next((item.get(key) for key in ("current_epoch", "epoch", "index") if key in item), None)
        loss_value = next((item.get(key) for key in ("loss", "objective", "objective_value") if key in item), None)
        if epoch_value is None or loss_value is None:
            continue
        epoch = _epoch_number(epoch_value)
        loss = _number(loss_value, f"hyperopt epoch {epoch} loss")
        existing = records.get(epoch)
        if existing is not None and existing["loss"] != loss:
            raise C0CWalkForwardError(f"conflicting hyperopt epoch {epoch}")
        records[epoch] = {"epoch": epoch, "loss": loss}
    if len(records) < shortlist_size:
        raise C0CWalkForwardError(
            f"hyperopt shortlist requires {shortlist_size} epochs, found {len(records)}"
        )
    return sorted(records.values(), key=lambda item: (item["loss"], item["epoch"]))[:shortlist_size]


def validate_recursive_analysis_log(
    path: str | Path,
    *,
    startup_count: int,
    required_indicators: Sequence[str],
    max_variance_pct: float,
) -> dict[str, Any]:
    try:
        lines = Path(path).read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError as exc:
        raise C0CWalkForwardError(f"unable to read recursive analysis log: {exc}") from exc
    header_index = None
    headers: list[str] = []
    for index, line in enumerate(lines):
        if "indicators" in line.lower() and str(startup_count) in line and "|" in line:
            cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
            if "indicators" in [cell.lower() for cell in cells]:
                header_index = index
                headers = cells
                break
    if header_index is None:
        raise C0CWalkForwardError("recursive analysis table header missing")
    try:
        startup_column = headers.index(str(startup_count))
    except ValueError as exc:
        raise C0CWalkForwardError(f"recursive analysis missing startup column {startup_count}") from exc
    observed: dict[str, float] = {}
    for line in lines[header_index + 1:]:
        if "|" not in line:
            if observed:
                break
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) <= startup_column or not cells:
            continue
        indicator = cells[0]
        if not indicator or set(indicator) <= {"-", "+", "="}:
            continue
        if indicator not in required_indicators:
            continue
        raw = cells[startup_column].strip()
        if not raw or "nan" in raw.lower():
            raise C0CWalkForwardError(f"recursive analysis {indicator} is not calculable at {startup_count}")
        if raw == "-":
            variance = 0.0
        else:
            try:
                variance = abs(float(raw.rstrip("%")))
            except ValueError as exc:
                raise C0CWalkForwardError(
                    f"invalid recursive variance for {indicator}: {raw!r}"
                ) from exc
        if variance > max_variance_pct:
            raise C0CWalkForwardError(
                f"recursive variance {indicator}={variance}% exceeds {max_variance_pct}%"
            )
        observed[indicator] = variance
    missing = sorted(set(required_indicators) - set(observed))
    if missing:
        raise C0CWalkForwardError(f"recursive analysis missing indicators: {missing}")
    return {
        "status": "PASS",
        "startup_candle_count": startup_count,
        "max_variance_pct": max_variance_pct,
        "indicator_variance_pct": dict(sorted(observed.items())),
    }


def _candle_time(value: Any, label: str) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str) and value.strip():
        try:
            parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError as exc:
            raise C0CWalkForwardError(f"{label} invalid timestamp: {value!r}") from exc
    else:
        raise C0CWalkForwardError(f"{label} must be a timestamp")
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)


def _candle_close(value: Any, label: str) -> float:
    if value is None or isinstance(value, bool):
        raise C0CWalkForwardError(f"{label} must be positive numeric")
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise C0CWalkForwardError(f"{label} must be positive numeric") from exc
    if not 0 < result < float("inf"):
        raise C0CWalkForwardError(f"{label} must be positive finite")
    return result


def equal_weight_buy_hold(candles_by_pair: Mapping[str, Sequence[Mapping[str, Any]]]) -> dict[str, Any]:
    """Compute a synchronized equal-weight portfolio equity path."""
    required = {"BTC/USDT", "ETH/USDT", "SOL/USDT"}
    if set(candles_by_pair) != required:
        raise C0CWalkForwardError("buy-and-hold pair coverage mismatch")
    try:
        rows = {pair: buy_and_hold_metrics(candles, 1.0) for pair, candles in candles_by_pair.items()}
    except ProfitabilityDiagnosticsError as exc:
        raise C0CWalkForwardError(str(exc)) from exc

    aligned: dict[str, dict[datetime, float]] = {}
    for pair, candles in candles_by_pair.items():
        points: dict[datetime, float] = {}
        for index, candle in enumerate(candles):
            if not isinstance(candle, Mapping):
                raise C0CWalkForwardError(f"{pair} candle[{index}] must be an object")
            when = _candle_time(candle.get("date"), f"{pair} candle[{index}].date")
            if when in points:
                raise C0CWalkForwardError(f"duplicate buy-and-hold timestamp for {pair}: {when.isoformat()}")
            points[when] = _candle_close(candle.get("close"), f"{pair} candle[{index}].close")
        aligned[pair] = points

    common = sorted(set.intersection(*(set(points) for points in aligned.values())))
    if len(common) < 2:
        raise C0CWalkForwardError("buy-and-hold requires at least two common candle timestamps")
    first = {pair: aligned[pair][common[0]] for pair in required}
    equity = [
        sum(aligned[pair][when] / first[pair] for pair in required) / len(required)
        for when in common
    ]
    peak = equity[0]
    max_drawdown = 0.0
    for value in equity:
        peak = max(peak, value)
        max_drawdown = max(max_drawdown, (peak - value) / peak if peak > 0 else 0.0)
    return {
        "net_return_ratio": equity[-1] / equity[0] - 1.0,
        "max_drawdown_ratio": max_drawdown,
        "timestamps": [when.isoformat() for when in common],
        "equity_curve": equity,
        "pairs": dict(sorted(rows.items())),
    }


def _ratio(value: float, drawdown: float) -> float:
    if drawdown <= 0:
        return 1e12 if value > 0 else 0.0
    return value / drawdown


def _aggregate_exit_reasons(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}
    for row in rows:
        summary = row.get("exit_reason_summary")
        if not isinstance(summary, list):
            raise C0CWalkForwardError("exit_reason_summary missing")
        for item in summary:
            if not isinstance(item, Mapping):
                raise C0CWalkForwardError("invalid exit_reason_summary item")
            reason = str(item.get("exit_reason"))
            target = grouped.setdefault(reason, {"exit_reason": reason, "trades": 0, "net_profit_abs": 0.0})
            target["trades"] += int(item.get("trades", 0))
            target["net_profit_abs"] += _number(item.get("net_profit_abs", 0.0), "exit reason profit")
    return sorted(grouped.values(), key=lambda item: item["exit_reason"])


def build_development_report(
    *,
    rows: Sequence[Mapping[str, Any]],
    config: Mapping[str, Any],
    buy_hold_by_fold: Mapping[str, Mapping[str, Any]],
    analysis_status: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    validated = validate_config(config)
    fold_ids = {fold["id"] for fold in validated["folds"]}
    expected_cells = {
        (fold_id, role, multiplier)
        for fold_id in fold_ids
        for role in ("validation", "development_test")
        for multiplier in REQUIRED_COSTS
    }
    actual_cells: set[tuple[str, str, float]] = set()
    normalized_rows: list[dict[str, Any]] = []
    for raw in rows:
        row = dict(raw)
        key = (str(row.get("fold_id")), str(row.get("role")), float(row.get("cost_multiplier")))
        if key in actual_cells:
            raise C0CWalkForwardError(f"duplicate evidence cell: {key}")
        fee_binding = row.get("fee_binding", {})
        if not isinstance(fee_binding, Mapping) or fee_binding.get("verified") is not True:
            raise C0CWalkForwardError(f"fee binding not verified: {key}")
        expected_fee = 0.0015 * float(row.get("cost_multiplier"))
        if abs(_number(row.get("fee_rate"), "fee_rate") - expected_fee) > 1e-12:
            raise C0CWalkForwardError(f"fee rate drift: {key}")
        if abs(_number(fee_binding.get("expected_fee_rate"), "bound fee rate") - expected_fee) > 1e-12:
            raise C0CWalkForwardError(f"fee binding rate drift: {key}")
        if _number(row.get("turnover_notional_abs"), "turnover_notional_abs") < 0:
            raise C0CWalkForwardError(f"negative turnover: {key}")
        exit_summary = row.get("exit_reason_summary")
        if not isinstance(exit_summary, list):
            raise C0CWalkForwardError(f"exit reason summary missing: {key}")
        if sum(int(item.get("trades", 0)) for item in exit_summary if isinstance(item, Mapping)) != int(row.get("trades", 0)):
            raise C0CWalkForwardError(f"exit reason trade count mismatch: {key}")
        positive_values = row.get("positive_trade_profits_abs")
        if not isinstance(positive_values, list):
            raise C0CWalkForwardError(f"positive trade profits missing: {key}")
        positive_sum = sum(_number(value, "positive trade profit") for value in positive_values)
        if abs(positive_sum - _number(row.get("positive_profit_abs"), "positive_profit_abs")) > 1e-8:
            raise C0CWalkForwardError(f"positive trade profit attribution mismatch: {key}")
        actual_cells.add(key)
        normalized_rows.append(row)
    if actual_cells != expected_cells:
        raise C0CWalkForwardError(
            f"walk-forward coverage mismatch: actual={sorted(actual_cells)} expected={sorted(expected_cells)}"
        )
    if set(buy_hold_by_fold) != fold_ids:
        raise C0CWalkForwardError("buy-and-hold fold coverage mismatch")
    for fold_id in fold_ids:
        hashes = {
            row["params_sha256"]
            for row in normalized_rows
            if row["fold_id"] == fold_id
        }
        candidate_ids = {
            row["candidate_id"]
            for row in normalized_rows
            if row["fold_id"] == fold_id
        }
        if len(hashes) != 1 or len(candidate_ids) != 1:
            raise C0CWalkForwardError(f"parameter lineage mismatch in fold {fold_id}")

    expected = [
        row for row in normalized_rows
        if row["role"] == "development_test" and row["cost_multiplier"] == 1.0
    ]
    stress = [
        row for row in normalized_rows
        if row["role"] == "development_test" and row["cost_multiplier"] == 1.5
    ]
    start_total = sum(float(row["starting_balance"]) for row in expected)
    net_abs = sum(float(row["net_profit_abs"]) for row in expected)
    net_ratio = net_abs / start_total
    stress_net_abs = sum(float(row["net_profit_abs"]) for row in stress)
    gains = sum(float(row["positive_profit_abs"]) for row in expected)
    losses = sum(float(row["negative_profit_abs"]) for row in expected)
    profit_factor = gains / abs(losses) if losses < 0 else (1e12 if gains > 0 else 0.0)
    fold_returns = {str(row["fold_id"]): float(row["net_return_ratio"]) for row in expected}
    max_drawdown = max(float(row["max_drawdown_ratio"]) for row in expected)
    trades = sum(int(row["trades"]) for row in expected)

    pair_profit: dict[str, float] = {pair: 0.0 for pair in config["pairs"]}
    for row in expected:
        for item in row["pairs"]:
            pair_profit[str(item["pair"])] += float(item["net_profit_abs"])
    positive_pairs = {pair: value for pair, value in pair_profit.items() if value > 0}
    positive_pair_total = sum(positive_pairs.values())
    pair_concentration = max(positive_pairs.values()) / positive_pair_total if positive_pair_total > 0 else None
    positive_folds = {fold: value for fold, value in fold_returns.items() if value > 0}
    positive_fold_total = sum(positive_folds.values())
    fold_concentration = max(positive_folds.values()) / positive_fold_total if positive_fold_total > 0 else None

    buy_hold_return = statistics.mean(
        float(buy_hold_by_fold[fold]["net_return_ratio"]) for fold in sorted(fold_ids)
    )
    buy_hold_drawdown = max(
        float(buy_hold_by_fold[fold]["max_drawdown_ratio"]) for fold in fold_ids
    )
    positive_trade_profits = sorted(
        (
            float(value)
            for row in expected
            for value in row.get("positive_trade_profits_abs", [])
            if float(value) > 0
        ),
        reverse=True,
    )
    total_positive_trade_profit = sum(positive_trade_profits)
    cluster_size = int(config["thresholds"]["top_trade_cluster_size"])
    largest_trade_share = (
        positive_trade_profits[0] / total_positive_trade_profit if total_positive_trade_profit > 0 else 0.0
    )
    top_cluster_share = (
        sum(positive_trade_profits[:cluster_size]) / total_positive_trade_profit
        if total_positive_trade_profit > 0 else 0.0
    )
    turnover_notional = sum(float(row["turnover_notional_abs"]) for row in expected)
    turnover_ratio = turnover_notional / start_total
    exit_reasons = _aggregate_exit_reasons(expected)

    reasons: list[str] = []
    thresholds = config["thresholds"]
    if net_ratio <= 0:
        reasons.append("NET_RETURN_NOT_POSITIVE")
    if statistics.median(fold_returns.values()) <= 0:
        reasons.append("MEDIAN_FOLD_NOT_POSITIVE")
    if profit_factor < float(thresholds["minimum_profit_factor"]):
        reasons.append("PROFIT_FACTOR_BELOW_THRESHOLD")
    if max_drawdown > float(thresholds["maximum_drawdown_ratio"]):
        reasons.append("DRAWDOWN_ABOVE_THRESHOLD")
    if _ratio(net_ratio, max_drawdown) <= _ratio(buy_hold_return, buy_hold_drawdown):
        reasons.append("RETURN_DRAWDOWN_NOT_ABOVE_BUY_HOLD")
    if stress_net_abs < 0:
        reasons.append("NEGATIVE_AT_1_5X_COST")
    if len(positive_pairs) < int(thresholds["minimum_positive_pairs"]):
        reasons.append("INSUFFICIENT_POSITIVE_PAIRS")
    if pair_concentration is not None and pair_concentration > float(thresholds["maximum_pair_profit_share"]):
        reasons.append("PAIR_PROFIT_CONCENTRATION")
    if len(positive_folds) < int(thresholds["minimum_positive_folds"]):
        reasons.append("INSUFFICIENT_POSITIVE_FOLDS")
    if fold_concentration is not None and fold_concentration > float(thresholds["maximum_fold_profit_share"]):
        reasons.append("FOLD_PROFIT_CONCENTRATION")
    if trades < int(thresholds["minimum_trades"]):
        reasons.append("INSUFFICIENT_TRADES")
    if largest_trade_share > float(thresholds["maximum_single_trade_profit_share"]):
        reasons.append("SINGLE_TRADE_PROFIT_CONCENTRATION")
    if top_cluster_share > float(thresholds["maximum_top_trade_cluster_profit_share"]):
        reasons.append("TOP_TRADE_CLUSTER_PROFIT_CONCENTRATION")

    statuses = dict(analysis_status or {"lookahead": "NOT_RUN", "recursive": "NOT_RUN"})
    economic_pass = not reasons
    status = "REJECTED" if not economic_pass else "RESEARCH_ONLY"
    if economic_pass and statuses == {"lookahead": "PASS", "recursive": "PASS"}:
        status = "HOLDOUT_ELIGIBLE"

    return {
        "schema_version": SCHEMA_VERSION,
        "candidate_id": config["candidate_id"],
        "live": "FORBIDDEN",
        "holdout_state": "HOLDOUT_CLOSED",
        "development_test_opened": True,
        "status": status,
        "next_required": None if not economic_pass else (None if status == "HOLDOUT_ELIGIBLE" else "FINAL_REFIT_AND_ANALYSES"),
        "development_economic_pass": economic_pass,
        "rejection_reasons": reasons,
        "analysis_status": statuses,
        "aggregate": {
            "net_profit_abs": net_abs,
            "net_return_ratio": net_ratio,
            "median_fold_return_ratio": statistics.median(fold_returns.values()),
            "profit_factor": profit_factor,
            "max_drawdown_ratio": max_drawdown,
            "stress_1_5x_net_profit_abs": stress_net_abs,
            "trades": trades,
            "pair_net_profit_abs": dict(sorted(pair_profit.items())),
            "positive_pairs": sorted(positive_pairs),
            "largest_positive_pair_share": pair_concentration,
            "fold_net_return_ratio": dict(sorted(fold_returns.items())),
            "positive_folds": sorted(positive_folds),
            "largest_positive_fold_share": fold_concentration,
            "buy_hold_return_ratio": buy_hold_return,
            "buy_hold_max_drawdown_ratio": buy_hold_drawdown,
            "strategy_return_drawdown_ratio": _ratio(net_ratio, max_drawdown),
            "buy_hold_return_drawdown_ratio": _ratio(buy_hold_return, buy_hold_drawdown),
            "turnover_notional_abs": turnover_notional,
            "turnover_ratio": turnover_ratio,
            "turnover_definition": thresholds["turnover_definition"],
            "largest_positive_trade_share": largest_trade_share,
            "top_trade_cluster_size": cluster_size,
            "top_trade_cluster_profit_share": top_cluster_share,
            "exit_reason_summary": exit_reasons,
        },
        "buy_and_hold_by_fold": dict(sorted(buy_hold_by_fold.items())),
        "rows": sorted(
            normalized_rows,
            key=lambda row: (row["fold_id"], row["role"], row["cost_multiplier"]),
        ),
    }


def render_markdown(report: Mapping[str, Any]) -> str:
    aggregate = report["aggregate"]
    lines = [
        "# C0C Cost-Aware EMA Development Walk-Forward",
        "",
        f"- Status: `{report['status']}`",
        f"- Holdout: `{report['holdout_state']}`",
        f"- Net return: `{aggregate['net_return_ratio']:.2%}`",
        f"- Median fold: `{aggregate['median_fold_return_ratio']:.2%}`",
        f"- Profit factor: `{aggregate['profit_factor']:.3f}`",
        f"- Maximum drawdown: `{aggregate['max_drawdown_ratio']:.2%}`",
        f"- 1.5x cost net: `{aggregate['stress_1_5x_net_profit_abs']:.2f}`",
        f"- Trades: `{aggregate['trades']}`",
        f"- Turnover: `{aggregate['turnover_ratio']:.2f}x`",
        f"- Largest positive trade share: `{aggregate['largest_positive_trade_share']:.2%}`",
        f"- Top-{aggregate['top_trade_cluster_size']} positive trade share: `{aggregate['top_trade_cluster_profit_share']:.2%}`",
        f"- Rejection reasons: `{', '.join(report['rejection_reasons']) or 'none'}`",
        "- LIVE: `FORBIDDEN`",
        "",
        "| Fold | Role | Cost | Trades | Return | PF | DD | Params SHA |",
        "|---|---|---:|---:|---:|---:|---:|---|",
    ]
    for row in report["rows"]:
        lines.append(
            f"| {row['fold_id']} | {row['role']} | {row['cost_multiplier']:.1f}x | "
            f"{row['trades']} | {row['net_return_ratio']:.2%} | "
            f"{row['profit_factor']:.3f} | {row['max_drawdown_ratio']:.2%} | "
            f"`{row['params_sha256'][:12]}` |"
        )
    lines.extend([
        "",
        "A development PASS does not evaluate or authorize the fresh holdout. "
        "The holdout remains closed until final refit and required analyses complete.",
        "",
    ])
    return "\n".join(lines)


def write_report_files(
    report: Mapping[str, Any], *, json_path: str | Path, markdown_path: str | Path
) -> None:
    destination = Path(json_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(destination.name + ".tmp")
    temporary.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    temporary.replace(destination)
    Path(markdown_path).write_text(render_markdown(report), encoding="utf-8")
