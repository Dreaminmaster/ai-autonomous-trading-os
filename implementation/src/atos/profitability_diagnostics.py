"""C0A structured trade diagnostics for Freqtrade result exports."""
from __future__ import annotations

import argparse, csv, hashlib, json, zipfile
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Mapping, Sequence

SCHEMA_VERSION = 1


class ProfitabilityDiagnosticsError(RuntimeError):
    pass


def _d(value: Any, label: str) -> Decimal:
    if value is None or isinstance(value, bool):
        raise ProfitabilityDiagnosticsError(f"{label} must be numeric")
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ProfitabilityDiagnosticsError(f"{label} must be numeric: {value!r}") from exc
    if not result.is_finite():
        raise ProfitabilityDiagnosticsError(f"{label} must be finite")
    return result


def _t(value: Any, label: str) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, (int, float)) and not isinstance(value, bool):
        seconds = float(value) / (1000 if float(value) > 10_000_000_000 else 1)
        return datetime.fromtimestamp(seconds, tz=UTC)
    elif isinstance(value, str) and value.strip():
        try:
            parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError as exc:
            raise ProfitabilityDiagnosticsError(f"{label} invalid timestamp: {value!r}") from exc
    else:
        raise ProfitabilityDiagnosticsError(f"{label} must be a timestamp")
    return parsed.replace(tzinfo=UTC).astimezone(UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)


def sha256_file(path: str | Path) -> str:
    try:
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()
    except OSError as exc:
        raise ProfitabilityDiagnosticsError(f"unreadable file: {path}: {exc}") from exc


def _json(raw: bytes, label: str) -> dict[str, Any]:
    try:
        value = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProfitabilityDiagnosticsError(f"invalid JSON in {label}: {exc}") from exc
    if not isinstance(value, dict):
        raise ProfitabilityDiagnosticsError(f"{label} must contain an object")
    return value


def load_freqtrade_export(path: str | Path) -> dict[str, Any]:
    """Load the unique JSON containing ``strategy[*].trades`` from JSON/ZIP."""
    source = Path(path)
    if not source.is_file():
        raise ProfitabilityDiagnosticsError(f"export not found: {source}")
    if not zipfile.is_zipfile(source):
        return _json(source.read_bytes(), str(source))
    try:
        with zipfile.ZipFile(source) as archive:
            found: list[tuple[str, dict[str, Any]]] = []
            candidates: list[str] = []
            for name in sorted(archive.namelist()):
                lower = Path(name).name.lower()
                if not lower.endswith(".json") or "meta" in lower or "config" in lower:
                    continue
                candidates.append(name)
                value = _json(archive.read(name), f"{source}!{name}")
                strategies = value.get("strategy")
                if isinstance(strategies, dict) and any(
                    isinstance(v, dict) and isinstance(v.get("trades"), list)
                    for v in strategies.values()
                ):
                    found.append((name, value))
    except zipfile.BadZipFile as exc:
        raise ProfitabilityDiagnosticsError(f"invalid result ZIP: {source}") from exc
    if len(found) != 1:
        raise ProfitabilityDiagnosticsError(
            f"expected one authoritative result JSON in {source}, "
            f"found {[name for name, _ in found]} among candidates {candidates}"
        )
    return found[0][1]


def select_strategy_payload(export: Mapping[str, Any], name: str | None) -> tuple[str, dict[str, Any]]:
    strategies = export.get("strategy")
    if not isinstance(strategies, dict) or not strategies:
        raise ProfitabilityDiagnosticsError("export.strategy must be a non-empty mapping")
    if name:
        value = strategies.get(name)
        if not isinstance(value, dict):
            raise ProfitabilityDiagnosticsError(f"strategy not found: {name}")
        return name, value
    if len(strategies) != 1:
        raise ProfitabilityDiagnosticsError(f"strategy_name required: {sorted(strategies)}")
    key, value = next(iter(strategies.items()))
    if not isinstance(key, str) or not isinstance(value, dict):
        raise ProfitabilityDiagnosticsError("invalid strategy payload")
    return key, value


def extract_trades(strategy: Mapping[str, Any]) -> list[dict[str, Any]]:
    trades = strategy.get("trades")
    if not isinstance(trades, list):
        raise ProfitabilityDiagnosticsError("strategy.trades must be a list")
    result: list[dict[str, Any]] = []
    for i, trade in enumerate(trades):
        if not isinstance(trade, dict):
            raise ProfitabilityDiagnosticsError(f"trade[{i}] must be an object")
        for field in ("pair", "open_date", "close_date", "open_rate", "close_rate"):
            if field not in trade:
                raise ProfitabilityDiagnosticsError(f"trade[{i}] missing {field}")
        opened, closed = _t(trade["open_date"], f"trade[{i}].open_date"), _t(
            trade["close_date"], f"trade[{i}].close_date"
        )
        if closed < opened:
            raise ProfitabilityDiagnosticsError(f"trade[{i}] close precedes open")
        _d(trade["open_rate"], f"trade[{i}].open_rate")
        _d(trade["close_rate"], f"trade[{i}].close_rate")
        if "profit_abs" not in trade and "profit_ratio" not in trade:
            raise ProfitabilityDiagnosticsError(f"trade[{i}] requires profit_abs or profit_ratio")
        result.append(dict(trade))
    return result


def _max_drawdown(equity: Sequence[Decimal]) -> tuple[Decimal, Decimal]:
    if not equity:
        return Decimal(0), Decimal(0)
    peak, max_abs, max_ratio = equity[0], Decimal(0), Decimal(0)
    for value in equity:
        peak = max(peak, value)
        absolute = peak - value
        ratio = absolute / peak if peak > 0 else Decimal(0)
        max_abs, max_ratio = max(max_abs, absolute), max(max_ratio, ratio)
    return max_abs, max_ratio


def _fee_abs(trade: Mapping[str, Any], i: int) -> Decimal:
    explicit = [trade.get(key) for key in ("fee_open_abs", "fee_close_abs")]
    if any(value is not None for value in explicit):
        return sum((_d(value, f"trade[{i}].fee_abs") for value in explicit if value is not None), Decimal(0))
    open_rate, close_rate = _d(trade.get("fee_open", 0), f"trade[{i}].fee_open"), _d(
        trade.get("fee_close", 0), f"trade[{i}].fee_close"
    )
    entry = exit_ = Decimal(0)
    orders = trade.get("orders", [])
    if not isinstance(orders, list):
        raise ProfitabilityDiagnosticsError(f"trade[{i}].orders must be a list")
    for j, order in enumerate(orders):
        if not isinstance(order, Mapping):
            raise ProfitabilityDiagnosticsError(f"trade[{i}].orders[{j}] must be an object")
        cost = _d(order.get("cost", 0), f"trade[{i}].orders[{j}].cost")
        if bool(order.get("ft_is_entry", False)):
            entry += cost
        else:
            exit_ += cost
    if entry == 0 and open_rate:
        entry = _d(trade.get("stake_amount", 0), f"trade[{i}].stake_amount")
    if exit_ == 0 and close_rate:
        exit_ = _d(trade.get("amount", 0), f"trade[{i}].amount") * _d(
            trade.get("close_rate", 0), f"trade[{i}].close_rate"
        )
    return entry * open_rate + exit_ * close_rate


def trade_equity_metrics(trades: Sequence[Mapping[str, Any]], starting_balance: Any) -> dict[str, Any]:
    start = _d(starting_balance, "starting_balance")
    if start <= 0:
        raise ProfitabilityDiagnosticsError("starting_balance must be positive")
    ordered = sorted(trades, key=lambda row: _t(row["close_date"], "close_date"))
    equity, total, gains, losses, fees = [start], Decimal(0), Decimal(0), Decimal(0), Decimal(0)
    wins = loss_count = draws = 0
    for i, trade in enumerate(ordered):
        profit = _d(trade["profit_abs"], f"trade[{i}].profit_abs") if "profit_abs" in trade else (
            _d(trade.get("stake_amount", start), f"trade[{i}].stake_amount")
            * _d(trade["profit_ratio"], f"trade[{i}].profit_ratio")
        )
        total += profit
        equity.append(start + total)
        if profit > 0:
            wins, gains = wins + 1, gains + profit
        elif profit < 0:
            loss_count, losses = loss_count + 1, losses + profit
        else:
            draws += 1
        fees += _fee_abs(trade, i)
    dd_abs, dd_ratio = _max_drawdown(equity)
    count = len(ordered)
    factor = gains / abs(losses) if losses < 0 else (Decimal(0) if gains == 0 else Decimal("Infinity"))
    return {
        "total_trades": count,
        "wins": wins,
        "losses": loss_count,
        "draws": draws,
        "winrate": wins / count if count else 0.0,
        "net_profit_abs": float(total),
        "net_profit_ratio": float(total / start),
        "expectancy_abs": float(total / count) if count else 0.0,
        "profit_factor": float(factor) if factor.is_finite() else None,
        "fee_total_abs": float(fees),
        "max_drawdown_abs": float(dd_abs),
        "max_drawdown_ratio": float(dd_ratio),
        "ending_balance": float(equity[-1]),
        "equity_curve": [float(value) for value in equity],
    }


def buy_and_hold_metrics(candles: Sequence[Mapping[str, Any]], starting_balance: Any = 1) -> dict[str, Any]:
    start = _d(starting_balance, "starting_balance")
    if start <= 0 or len(candles) < 2:
        raise ProfitabilityDiagnosticsError("buy-and-hold requires positive balance and two candles")
    ordered = sorted(candles, key=lambda row: _t(row["date"], "candle.date"))
    first = _d(ordered[0]["close"], "first close")
    if first <= 0:
        raise ProfitabilityDiagnosticsError("first close must be positive")
    equity = [start * _d(row["close"], "candle.close") / first for row in ordered]
    if any(value <= 0 for value in equity):
        raise ProfitabilityDiagnosticsError("candle close must be positive")
    dd_abs, dd_ratio = _max_drawdown(equity)
    return {
        "start": float(equity[0]),
        "end": float(equity[-1]),
        "net_return_ratio": float(equity[-1] / equity[0] - 1),
        "max_drawdown_abs": float(dd_abs),
        "max_drawdown_ratio": float(dd_ratio),
        "equity_curve": [float(value) for value in equity],
    }


def trade_path_diagnostics(trade: Mapping[str, Any], candles: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    opened, closed = _t(trade["open_date"], "trade.open_date"), _t(trade["close_date"], "trade.close_date")
    if closed < opened:
        raise ProfitabilityDiagnosticsError("trade close precedes open")
    rate = _d(trade["open_rate"], "trade.open_rate")
    if rate <= 0:
        raise ProfitabilityDiagnosticsError("trade.open_rate must be positive")
    window = [row for row in candles if opened <= _t(row["date"], "candle.date") <= closed]
    if not window:
        raise ProfitabilityDiagnosticsError(f"no candles for trade window {trade.get('pair')}")
    short, excursions = bool(trade.get("is_short", False)), []
    for row in window:
        when, high, low = _t(row["date"], "candle.date"), _d(row["high"], "high"), _d(row["low"], "low")
        favorable = (rate - low) / rate if short else (high - rate) / rate
        adverse = (rate - high) / rate if short else (low - rate) / rate
        excursions.append((when, favorable, adverse))
    mfe, mae = max(excursions, key=lambda row: row[1]), min(excursions, key=lambda row: row[2])
    realized = _d(trade.get("profit_ratio", 0), "trade.profit_ratio")
    return {
        "pair": trade.get("pair"),
        "open_date": opened.isoformat(),
        "close_date": closed.isoformat(),
        "enter_tag": trade.get("enter_tag"),
        "exit_reason": trade.get("exit_reason"),
        "is_short": short,
        "realized_profit_ratio": float(realized),
        "mfe_ratio": float(mfe[1]),
        "mae_ratio": float(mae[2]),
        "mfe_time": mfe[0].isoformat(),
        "mae_time": mae[0].isoformat(),
        "path_order": "SAME_CANDLE_AMBIGUOUS" if mfe[0] == mae[0] else ("MFE_BEFORE_MAE" if mfe[0] < mae[0] else "MAE_BEFORE_MFE"),
        "exit_efficiency": float(realized / mfe[1]) if mfe[1] > 0 else 0.0,
        "candles_observed": len(window),
    }


def enrich_trade_paths(trades: Sequence[Mapping[str, Any]], candles_by_pair: Mapping[str, Sequence[Mapping[str, Any]]]) -> list[dict[str, Any]]:
    result = []
    for i, trade in enumerate(trades):
        candles = candles_by_pair.get(str(trade.get("pair")))
        if candles is None:
            raise ProfitabilityDiagnosticsError(f"missing candles for trade[{i}] pair {trade.get('pair')}")
        result.append(trade_path_diagnostics(trade, candles))
    return result


def _pct(strategy: Mapping[str, Any], direct: str, ratio: str) -> float:
    if direct in strategy:
        return float(_d(strategy[direct], direct))
    if ratio in strategy:
        return float(_d(strategy[ratio], ratio) * 100)
    raise ProfitabilityDiagnosticsError(f"strategy summary missing {direct}/{ratio}")


def canonical_reproduction(strategy: Mapping[str, Any], expected: Mapping[str, Any]) -> dict[str, Any]:
    actual = {
        "total_trades": int(_d(strategy.get("total_trades"), "total_trades")),
        "profit_total_pct": _pct(strategy, "profit_total_pct", "profit_total"),
        "winrate_pct": _pct(strategy, "winrate_pct", "winrate"),
        "max_drawdown_pct": _pct(strategy, "max_drawdown_pct", "max_drawdown_account"),
        "profit_factor": float(_d(strategy.get("profit_factor"), "profit_factor")),
    }
    errors: list[str] = []
    if actual["total_trades"] != expected.get("total_trades"):
        errors.append(f"total_trades {actual['total_trades']} != {expected.get('total_trades')}")
    tolerances = expected.get("tolerances", {})
    for key in ("profit_total_pct", "winrate_pct", "max_drawdown_pct", "profit_factor"):
        target, tolerance = _d(expected.get(key), f"expected.{key}"), _d(tolerances.get(key, 0), f"tolerances.{key}")
        delta = abs(_d(actual[key], f"actual.{key}") - target)
        if delta > tolerance:
            errors.append(f"{key} {actual[key]} differs from {float(target)} by {float(delta)} (tolerance {float(tolerance)})")
    return {"schema_version": 1, "status": "PASS" if not errors else "FAIL", "actual": actual, "expected": dict(expected), "errors": errors}


def build_manifest(*, run_id: str, head_sha: str, strategy_name: str, export_path: str | Path,
                   config_path: str | Path | None = None, policy_path: str | Path | None = None,
                   data_files: Sequence[str | Path] = (), generated_at: str) -> dict[str, Any]:
    if not run_id.strip() or not head_sha.strip() or not strategy_name.strip():
        raise ProfitabilityDiagnosticsError("run_id, head_sha and strategy_name are required")
    _t(generated_at, "generated_at")
    item = lambda path: {"path": str(path), "sha256": sha256_file(path)}
    return {
        "schema_version": 1, "run_id": run_id, "head_sha": head_sha,
        "strategy_name": strategy_name, "generated_at": generated_at,
        "export": item(export_path),
        "config": item(config_path) if config_path is not None else None,
        "policy": item(policy_path) if policy_path is not None else None,
        "data_files": [item(path) for path in sorted((Path(p) for p in data_files), key=str)],
        "live": "FORBIDDEN",
    }


def load_candles(path: str | Path) -> list[dict[str, Any]]:
    source = Path(path)
    if not source.is_file():
        raise ProfitabilityDiagnosticsError(f"candle file not found: {source}")
    if source.suffix.lower() == ".csv":
        with source.open(newline="", encoding="utf-8") as handle:
            return [dict(row) for row in csv.DictReader(handle)]
    if source.suffix.lower() == ".json":
        value = json.loads(source.read_text(encoding="utf-8"))
        value = value.get("candles") if isinstance(value, dict) else value
        if not isinstance(value, list):
            raise ProfitabilityDiagnosticsError("candle JSON must be a list")
        return [dict(row) for row in value if isinstance(row, dict)]
    if source.suffix.lower() == ".feather":
        try:
            import pandas as pd  # type: ignore
        except ImportError as exc:
            raise ProfitabilityDiagnosticsError("pandas/pyarrow required for Feather") from exc
        return pd.read_feather(source).to_dict(orient="records")
    raise ProfitabilityDiagnosticsError(f"unsupported candle format: {source.suffix}")


def discover_candle_file(data_dir: str | Path, pair: str, timeframe: str) -> Path:
    tokens = {pair.replace("/", "_"), pair.replace("/", "-"), pair.replace("/", "")}
    found = [
        path for path in Path(data_dir).rglob("*")
        if path.is_file() and path.suffix.lower() in {".feather", ".json", ".csv"}
        and timeframe in path.name and any(token in path.name for token in tokens)
    ]
    if len(found) != 1:
        raise ProfitabilityDiagnosticsError(f"expected one candle file for {pair} {timeframe}, found {[str(p) for p in found]}")
    return found[0]


def analyze_export(*, export_path: str | Path, strategy_name: str | None,
                   starting_balance: Any | None = None,
                   candles_by_pair: Mapping[str, Sequence[Mapping[str, Any]]] | None = None,
                   expected: Mapping[str, Any] | None = None) -> dict[str, Any]:
    export = load_freqtrade_export(export_path)
    name, strategy = select_strategy_payload(export, strategy_name)
    trades = extract_trades(strategy)
    balance = starting_balance if starting_balance is not None else strategy.get("starting_balance")
    if balance is None:
        raise ProfitabilityDiagnosticsError("starting balance missing")
    if int(strategy.get("total_trades", len(trades))) != len(trades):
        raise ProfitabilityDiagnosticsError(f"summary total_trades {strategy.get('total_trades')} != trades length {len(trades)}")
    keys = ("total_trades", "profit_total", "profit_total_abs", "winrate", "max_drawdown_account",
            "max_drawdown_abs", "profit_factor", "expectancy", "sharpe", "sortino", "calmar",
            "timeframe", "timeframe_detail", "timerange", "starting_balance", "final_balance", "pairlist")
    report: dict[str, Any] = {
        "schema_version": 1, "strategy_name": name,
        "source_summary": {key: strategy.get(key) for key in keys},
        "computed_trade_metrics": trade_equity_metrics(trades, balance),
        "trade_paths": None, "buy_and_hold": {},
        "canonical_reproduction": canonical_reproduction(strategy, expected) if expected else None,
        "live": "FORBIDDEN",
    }
    if candles_by_pair is not None:
        report["trade_paths"] = enrich_trade_paths(trades, candles_by_pair)
        report["buy_and_hold"] = {pair: buy_and_hold_metrics(candles, balance) for pair, candles in sorted(candles_by_pair.items())}
    return report


def write_json_atomic(path: str | Path, payload: Mapping[str, Any]) -> None:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(destination.name + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    temporary.replace(destination)


def _cli() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    for flag in ("export", "report", "manifest", "run-id", "head-sha", "generated-at"):
        parser.add_argument(f"--{flag}", required=True)
    parser.add_argument("--strategy", default="AISupervisedStrategy")
    parser.add_argument("--starting-balance")
    parser.add_argument("--expected")
    parser.add_argument("--candles", action="append", default=[], metavar="PAIR=PATH")
    parser.add_argument("--config")
    parser.add_argument("--policy")
    args = parser.parse_args()
    candle_paths, candles = [], {}
    for spec in args.candles:
        if "=" not in spec:
            raise ProfitabilityDiagnosticsError("--candles must use PAIR=PATH")
        pair, raw = spec.split("=", 1)
        path = Path(raw)
        candle_paths.append(path)
        candles[pair] = load_candles(path)
    expected = None
    if args.expected:
        expected = json.loads(Path(args.expected).read_text(encoding="utf-8"))
        if not isinstance(expected, dict):
            raise ProfitabilityDiagnosticsError("expected canonical file must be an object")
    report = analyze_export(export_path=args.export, strategy_name=args.strategy,
                            starting_balance=args.starting_balance,
                            candles_by_pair=candles or None, expected=expected)
    manifest = build_manifest(run_id=args.run_id, head_sha=args.head_sha,
                              strategy_name=args.strategy, export_path=args.export,
                              config_path=args.config, policy_path=args.policy,
                              data_files=candle_paths, generated_at=args.generated_at)
    report["manifest_sha256"] = hashlib.sha256(json.dumps(manifest, sort_keys=True).encode()).hexdigest()
    write_json_atomic(args.report, report)
    write_json_atomic(args.manifest, manifest)
    reproduction = report.get("canonical_reproduction")
    if reproduction and reproduction.get("status") != "PASS":
        return 1
    print(f"C0A diagnostics PASS: strategy={args.strategy} trades={report['computed_trade_metrics']['total_trades']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli())
