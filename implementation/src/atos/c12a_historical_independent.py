"""Physically separate C12A recomputation over retained normalized public data.

This module deliberately does not import the producer replay engine.  It rebuilds
prices, decisions, positions, weekly equity and pooled gates from the retained
rows so an implementation error in the producer cannot self-certify.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from statistics import fmean
from typing import Any

from scipy.stats import kurtosis, norm, skew

from atos.c12a_contract import (
    COST_RATES,
    ENTRY_THRESHOLD,
    EXECUTION_MAX_DELAY,
    STARTING_EQUITY,
    WINDOWS,
    ContractDecision,
    contract_decisions,
    decimal_value,
    iso_z,
    utc_timestamp,
)

HOUR = timedelta(hours=1)
WEEK = timedelta(days=7)
BUFFER_RATIO = Decimal("0.25")
SLEEVE_FRACTION = Decimal("0.50")
TRIAL_COUNT = Decimal(628)


class C12AHistoricalIndependentError(RuntimeError):
    """Raised when independent C12A recomputation cannot prove equivalence."""


def _canonical(value: Any) -> bytes:
    return (
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        + "\n"
    ).encode()


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _stamp(value: Any) -> datetime:
    try:
        return utc_timestamp(value)
    except RuntimeError as exc:
        raise C12AHistoricalIndependentError(str(exc)) from exc


def _price(value: Any, label: str) -> Decimal:
    try:
        return decimal_value(value, label, positive=True)
    except RuntimeError as exc:
        raise C12AHistoricalIndependentError(str(exc)) from exc


@dataclass(frozen=True)
class _Mark:
    timestamp: datetime
    spot: Decimal
    future: Decimal


@dataclass(frozen=True)
class _Market:
    decision: ContractDecision
    signal_spot: Decimal
    signal_future: Decimal
    entry_spot: Decimal
    entry_future: Decimal
    exit_spot: Decimal
    exit_future: Decimal
    marks: tuple[_Mark, ...]

    @property
    def basis(self) -> Decimal:
        return (self.signal_future - self.signal_spot) / (
            self.signal_future + self.signal_spot
        )

    def mark_at(self, stamp: datetime) -> _Mark:
        found = [mark for mark in self.marks if mark.timestamp == stamp]
        if len(found) != 1:
            raise C12AHistoricalIndependentError(
                f"independent mark is missing: {self.decision.futures_instrument} "
                f"{iso_z(stamp)}"
            )
        return found[0]


@dataclass(frozen=True)
class _Position:
    market: _Market
    quantity: Decimal
    entry_cost: Decimal
    exit_cost: Decimal
    exit_timestamp: datetime
    exit_spot: Decimal
    exit_future: Decimal
    buffer_breach: bool

    @property
    def pnl(self) -> Decimal:
        return (
            self.quantity * (self.exit_spot - self.market.entry_spot)
            - self.quantity * (self.exit_future - self.market.entry_future)
            - self.entry_cost
            - self.exit_cost
        )

    def pnl_at(self, stamp: datetime) -> Decimal:
        if stamp <= self.market.decision.entry_timestamp:
            return Decimal(0)
        if stamp >= self.exit_timestamp:
            return self.pnl
        mark = self.market.mark_at(stamp)
        return (
            self.quantity * (mark.spot - self.market.entry_spot)
            - self.quantity * (mark.future - self.market.entry_future)
            - self.entry_cost
        )


def _spot_rows(rows: Sequence[Mapping[str, Any]]) -> dict[datetime, dict[str, Decimal]]:
    output: dict[datetime, dict[str, Decimal]] = {}
    previous: datetime | None = None
    for row in rows:
        stamp = _stamp(row.get("timestamp"))
        if previous is not None and stamp <= previous:
            raise C12AHistoricalIndependentError(
                "independent spot rows are duplicate or unordered"
            )
        previous = stamp
        output[stamp] = {
            "open": _price(row.get("open"), "independent spot open"),
            "close": _price(row.get("close"), "independent spot close"),
        }
    if not output:
        raise C12AHistoricalIndependentError("independent spot rows are empty")
    return output


def _future_rows(
    rows: Sequence[Mapping[str, Any]], *, instrument: str
) -> tuple[tuple[datetime, int, Decimal], ...]:
    output: list[tuple[datetime, int, Decimal]] = []
    seen: set[str] = set()
    previous: tuple[datetime, int] | None = None
    for row in rows:
        trade_id = str(row.get("trade_id", ""))
        if (
            row.get("instrument") != instrument
            or not trade_id.isdigit()
            or trade_id in seen
        ):
            raise C12AHistoricalIndependentError("independent futures identity drift")
        seen.add(trade_id)
        parsed = (
            _stamp(row.get("timestamp")),
            int(trade_id),
            _price(row.get("price"), "independent futures price"),
        )
        order = parsed[:2]
        if previous is not None and order <= previous:
            raise C12AHistoricalIndependentError(
                "independent futures rows are duplicate or unordered"
            )
        previous = order
        output.append(parsed)
    if not output:
        raise C12AHistoricalIndependentError(
            "independent futures rows are empty"
        )
    return tuple(output)


def _market(
    decision: ContractDecision,
    *,
    spot_rows: Sequence[Mapping[str, Any]],
    futures_rows: Sequence[Mapping[str, Any]],
) -> _Market:
    spot = _spot_rows(spot_rows)
    future = _future_rows(futures_rows, instrument=decision.futures_instrument)
    hourly_last: dict[datetime, Decimal] = {}
    for stamp, _, price in future:
        hourly_last[stamp.replace(minute=0, second=0, microsecond=0)] = price

    def candle(stamp: datetime) -> dict[str, Decimal]:
        try:
            return spot[stamp]
        except KeyError as exc:
            raise C12AHistoricalIndependentError(
                f"independent spot hour missing: {iso_z(stamp)}"
            ) from exc

    def hour_price(stamp: datetime) -> Decimal:
        try:
            return hourly_last[stamp]
        except KeyError as exc:
            raise C12AHistoricalIndependentError(
                f"independent futures hour missing: {iso_z(stamp)}"
            ) from exc

    def execution_price(stamp: datetime) -> Decimal:
        end = stamp + EXECUTION_MAX_DELAY
        for observed, _, price in future:
            if observed < stamp:
                continue
            if observed <= end:
                return price
            break
        raise C12AHistoricalIndependentError(
            f"independent execution interval missing: {iso_z(stamp)}"
        )

    marks: list[_Mark] = []
    current = decision.entry_timestamp
    while current < decision.exit_timestamp:
        marks.append(
            _Mark(
                timestamp=current + HOUR,
                spot=candle(current)["close"],
                future=hour_price(current),
            )
        )
        current += HOUR
    signal_hour = decision.signal_cutoff - HOUR
    return _Market(
        decision=decision,
        signal_spot=candle(signal_hour)["close"],
        signal_future=hour_price(signal_hour),
        entry_spot=candle(decision.entry_timestamp)["open"],
        entry_future=execution_price(decision.entry_timestamp),
        exit_spot=candle(decision.exit_timestamp)["open"],
        exit_future=execution_price(decision.exit_timestamp),
        marks=tuple(marks),
    )


def _effective_exit(
    market: _Market, quantity: Decimal
) -> tuple[datetime, Decimal, Decimal, bool]:
    for index, mark in enumerate(market.marks):
        ratio = (quantity * (Decimal(2) * market.entry_future - mark.future)) / (
            quantity * mark.future
        )
        if ratio < BUFFER_RATIO:
            if index + 1 < len(market.marks):
                next_mark = market.marks[index + 1]
                return next_mark.timestamp, next_mark.spot, next_mark.future, True
            return (
                market.decision.exit_timestamp,
                market.exit_spot,
                market.exit_future,
                True,
            )
    return (
        market.decision.exit_timestamp,
        market.exit_spot,
        market.exit_future,
        False,
    )


def _positions(
    markets: Sequence[_Market], *, cost_rate: Decimal, always: bool
) -> tuple[_Position, ...]:
    output: list[_Position] = []
    groups: dict[datetime, list[_Market]] = {}
    for market in markets:
        groups.setdefault(market.decision.entry_timestamp, []).append(market)
    for entry, group in sorted(groups.items()):
        if any(position.exit_timestamp > entry for position in output):
            raise C12AHistoricalIndependentError(
                "independent contract positions overlap"
            )
        equity = STARTING_EQUITY + sum(
            (position.pnl for position in output), Decimal(0)
        )
        if equity <= 0:
            raise C12AHistoricalIndependentError("independent equity is non-positive")
        sleeve = equity * SLEEVE_FRACTION
        for market in sorted(group, key=lambda item: item.decision.asset):
            if not always and market.basis <= ENTRY_THRESHOLD:
                continue
            quantity = sleeve / (
                (market.entry_spot + market.entry_future)
                * (Decimal(1) + COST_RATES["2.0x"])
            )
            entry_cost = (
                quantity * cost_rate * (market.entry_spot + market.entry_future)
            )
            if quantity * (
                market.entry_spot + market.entry_future
            ) + entry_cost > sleeve + Decimal("1e-10"):
                raise C12AHistoricalIndependentError(
                    "independent entry cash would be negative"
                )
            exit_stamp, exit_spot, exit_future, breached = _effective_exit(
                market, quantity
            )
            output.append(
                _Position(
                    market=market,
                    quantity=quantity,
                    entry_cost=entry_cost,
                    exit_cost=quantity * cost_rate * (exit_spot + exit_future),
                    exit_timestamp=exit_stamp,
                    exit_spot=exit_spot,
                    exit_future=exit_future,
                    buffer_breach=breached,
                )
            )
    return tuple(output)


def _equity(stamp: datetime, positions: Sequence[_Position]) -> Decimal:
    value = STARTING_EQUITY + sum(
        (position.pnl_at(stamp) for position in positions), Decimal(0)
    )
    if not value.is_finite() or value <= 0:
        raise C12AHistoricalIndependentError("independent equity path is invalid")
    return value


def _maximum_drawdown(values: Sequence[Decimal]) -> Decimal:
    peak = values[0]
    result = Decimal(0)
    for value in values:
        peak = max(peak, value)
        result = max(result, (peak - value) / peak)
    return result


def _policy(
    window_id: str, markets: Sequence[_Market], cost_label: str, always: bool
) -> dict[str, Any]:
    window = next(item for item in WINDOWS if item.window_id == window_id)
    positions = _positions(markets, cost_rate=COST_RATES[cost_label], always=always)
    boundaries = tuple(window.start + index * WEEK for index in range(27))
    equities = tuple(_equity(stamp, positions) for stamp in boundaries)
    weekly = tuple(
        equities[index] / equities[index - 1] - Decimal(1)
        for index in range(1, len(equities))
    )
    final = _equity(window.end, positions)
    turnover = sum(
        (
            position.quantity
            * (
                position.market.entry_spot
                + position.market.entry_future
                + position.exit_spot
                + position.exit_future
            )
            for position in positions
        ),
        Decimal(0),
    )
    mean_equity = Decimal(str(fmean(float(value) for value in equities)))
    one_way = Decimal("0.5") * turnover / mean_equity * Decimal(52) / Decimal(26)
    total_pnl = sum((position.pnl for position in positions), Decimal(0))
    contract_pnl = {
        position.market.decision.futures_instrument: position.pnl
        for position in positions
    }
    asset_pnl = {
        asset: sum(
            (
                position.pnl
                for position in positions
                if position.market.decision.asset == asset
            ),
            Decimal(0),
        )
        for asset in ("BTC", "ETH")
    }
    tolerance = Decimal("1e-10")
    if (
        abs(final - STARTING_EQUITY - total_pnl) > tolerance
        or abs(sum(contract_pnl.values(), Decimal(0)) - total_pnl) > tolerance
        or abs(sum(asset_pnl.values(), Decimal(0)) - total_pnl) > tolerance
    ):
        raise C12AHistoricalIndependentError(
            "independent price/cost attribution does not reconcile"
        )
    return {
        "policy": "always_enter" if always else "candidate",
        "window_id": window_id,
        "cost_label": cost_label,
        "starting_equity": str(STARTING_EQUITY),
        "final_equity": str(final),
        "return": str(final / STARTING_EQUITY - Decimal(1)),
        "weekly_returns": [str(value) for value in weekly],
        "weekly_equities": [str(value) for value in equities[1:]],
        "maximum_drawdown": str(_maximum_drawdown(equities)),
        "annualized_one_way_turnover": str(one_way),
        "position_count": len(positions),
        "buffer_breaches": sum(position.buffer_breach for position in positions),
        "base_hedge_mismatches": 0,
        "reconciliation_errors": 0,
        "contract_pnl": {key: str(value) for key, value in contract_pnl.items()},
        "asset_pnl": {key: str(value) for key, value in asset_pnl.items()},
    }


def _spot_only(
    positions: Sequence[_Position], cost_rate: Decimal, end: datetime
) -> dict[str, Any]:
    pnl = sum(
        (
            position.quantity * (position.exit_spot - position.market.entry_spot)
            - position.quantity
            * cost_rate
            * (position.market.entry_spot + position.exit_spot)
            for position in positions
            if position.exit_timestamp <= end
        ),
        Decimal(0),
    )
    final = STARTING_EQUITY + pnl
    return {
        "final_equity": str(final),
        "return": str(final / STARTING_EQUITY - Decimal(1)),
        "position_count": len(positions),
    }


def _window(
    window_id: str,
    *,
    spot_series: Mapping[str, Sequence[Mapping[str, Any]]],
    futures_series: Mapping[str, Sequence[Mapping[str, Any]]],
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    decisions = [
        decision
        for decision in contract_decisions(config)
        if decision.window_id == window_id
    ]
    markets = tuple(
        _market(
            decision,
            spot_rows=spot_series[decision.spot_instrument],
            futures_rows=futures_series[decision.futures_instrument],
        )
        for decision in decisions
    )
    rows = [
        {
            "asset": market.decision.asset,
            "futures_instrument": market.decision.futures_instrument,
            "signal_cutoff": iso_z(market.decision.signal_cutoff),
            "entry_timestamp": iso_z(market.decision.entry_timestamp),
            "exit_timestamp": iso_z(market.decision.exit_timestamp),
            "normalized_basis": str(market.basis),
            "entered": market.basis > ENTRY_THRESHOLD,
        }
        for market in markets
    ]
    cells: dict[str, Any] = {}
    window = next(item for item in WINDOWS if item.window_id == window_id)
    for label, rate in COST_RATES.items():
        candidate_positions = _positions(markets, cost_rate=rate, always=False)
        cells[label] = {
            "candidate": _policy(window_id, markets, label, False),
            "cash_comparator": {
                "final_equity": str(STARTING_EQUITY),
                "return": "0",
                "position_count": 0,
            },
            "always_enter_comparator": _policy(window_id, markets, label, True),
            "spot_only_comparator": _spot_only(candidate_positions, rate, window.end),
        }
    return {
        "schema_version": 1,
        "stage": "C12A_WINDOW_REPLAY",
        "window_id": window_id,
        "decisions": rows,
        "cost_cells": cells,
    }


def review_historical_window(
    producer: Mapping[str, Any],
    *,
    spot_series: Mapping[str, Sequence[Mapping[str, Any]]],
    futures_series: Mapping[str, Sequence[Mapping[str, Any]]],
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    window_id = str(producer.get("window_id", ""))
    if window_id not in {window.window_id for window in WINDOWS}:
        raise C12AHistoricalIndependentError(
            "independent producer window identity drift"
        )
    expected = _window(
        window_id,
        spot_series=spot_series,
        futures_series=futures_series,
        config=config,
    )
    if dict(producer) != expected:
        raise C12AHistoricalIndependentError(
            f"independent window recomputation mismatch: {window_id}"
        )
    return {
        "schema_version": 1,
        "stage": "C12A_WINDOW_INDEPENDENT_REVIEW",
        "window_id": window_id,
        "status": "PASS",
        "producer_sha256": _digest(producer),
        "independent_sha256": _digest(expected),
        "decision_count": len(expected["decisions"]),
        "cost_cell_count": len(expected["cost_cells"]),
    }


def _statistics(values: Sequence[Decimal]) -> dict[str, Any]:
    raw = [float(value) for value in values]
    average = fmean(raw)
    variance = sum((value - average) ** 2 for value in raw) / (len(raw) - 1)
    sample_std = math.sqrt(variance)
    if not math.isfinite(sample_std) or sample_std <= 0:
        return {
            "n": len(raw),
            "mean": average,
            "sample_std": sample_std,
            "weekly_sharpe": 0.0,
            "annualized_weekly_sharpe": 0.0,
            "unbiased_skewness": 0.0,
            "unbiased_ordinary_kurtosis": 0.0,
            "psr_probability": 0.0,
            "valid": False,
        }
    weekly_sharpe = average / sample_std
    asymmetry = float(skew(raw, bias=False))
    ordinary_kurtosis = float(kurtosis(raw, fisher=False, bias=False))
    radicand = (
        1 - asymmetry * weekly_sharpe + ((ordinary_kurtosis - 1) / 4) * weekly_sharpe**2
    )
    valid = math.isfinite(radicand) and radicand > 0
    probability = (
        float(norm.cdf(weekly_sharpe * math.sqrt(len(raw) - 1) / math.sqrt(radicand)))
        if valid
        else 0.0
    )
    return {
        "n": len(raw),
        "mean": average,
        "sample_std": sample_std,
        "weekly_sharpe": weekly_sharpe,
        "annualized_weekly_sharpe": weekly_sharpe * math.sqrt(52),
        "unbiased_skewness": asymmetry,
        "unbiased_ordinary_kurtosis": ordinary_kurtosis,
        "psr_probability": probability if valid else 0.0,
        "valid": valid
        and all(
            math.isfinite(value)
            for value in (asymmetry, ordinary_kurtosis, probability)
        ),
    }


def _positive_share(values: Sequence[Decimal], count: int = 1) -> Decimal | None:
    positive = sorted((max(value, Decimal(0)) for value in values), reverse=True)
    total = sum(positive, Decimal(0))
    return None if total <= 0 else sum(positive[:count], Decimal(0)) / total


def _adjusted_psr(probability: Decimal) -> Decimal:
    return max(Decimal(0), Decimal(1) - TRIAL_COUNT * (Decimal(1) - probability))


def _pooled(
    windows: Sequence[Mapping[str, Any]], policy: str, label: str
) -> dict[str, Any]:
    rows = [window["cost_cells"][label][policy] for window in windows]
    weekly = [Decimal(str(value)) for row in rows for value in row["weekly_returns"]]
    stats = _statistics(weekly)
    finals = [Decimal(str(row["final_equity"])) for row in rows]
    window_pnl = [value - STARTING_EQUITY for value in finals]
    contract_pnl: dict[str, Decimal] = {}
    asset_pnl = {"BTC": Decimal(0), "ETH": Decimal(0)}
    weekly_pnl: list[Decimal] = []
    for row in rows:
        for instrument, value in row["contract_pnl"].items():
            contract_pnl[instrument] = contract_pnl.get(
                instrument, Decimal(0)
            ) + Decimal(str(value))
        for asset, value in row["asset_pnl"].items():
            asset_pnl[asset] += Decimal(str(value))
        previous = STARTING_EQUITY
        for value in row["weekly_equities"]:
            equity = Decimal(str(value))
            weekly_pnl.append(equity - previous)
            previous = equity
    return {
        "policy": policy,
        "cost_label": label,
        "aggregate_return": str(sum(finals, Decimal(0)) / Decimal(5000) - Decimal(1)),
        "window_returns": {
            str(window["window_id"]): str(row["return"])
            for window, row in zip(windows, rows, strict=True)
        },
        "window_pnl": [str(value) for value in window_pnl],
        "weekly_returns": [str(value) for value in weekly],
        "weekly_pnl": [str(value) for value in weekly_pnl],
        "statistics": stats,
        "bonferroni_adjusted_psr": str(
            _adjusted_psr(Decimal(str(stats["psr_probability"])))
        ),
        "maximum_drawdown": str(
            max(Decimal(str(row["maximum_drawdown"])) for row in rows)
        ),
        "annualized_one_way_turnover": str(
            sum(
                (Decimal(str(row["annualized_one_way_turnover"])) for row in rows),
                Decimal(0),
            )
            / Decimal(5)
        ),
        "position_count": sum(int(row["position_count"]) for row in rows),
        "buffer_breaches": sum(int(row["buffer_breaches"]) for row in rows),
        "base_hedge_mismatches": sum(int(row["base_hedge_mismatches"]) for row in rows),
        "reconciliation_errors": sum(int(row["reconciliation_errors"]) for row in rows),
        "contract_pnl": {
            key: str(value) for key, value in sorted(contract_pnl.items())
        },
        "asset_pnl": {key: str(value) for key, value in sorted(asset_pnl.items())},
    }


def _benchmark(rows: Sequence[Mapping[str, Any]]) -> tuple[Decimal, ...]:
    spot = _spot_rows(rows)
    output: list[Decimal] = []
    for window in WINDOWS:
        prices = [
            spot[window.start + index * WEEK - HOUR]["close"] for index in range(27)
        ]
        output.extend(
            prices[index] / prices[index - 1] - Decimal(1) for index in range(1, 27)
        )
    if len(output) != 130:
        raise C12AHistoricalIndependentError("independent BTC benchmark coverage drift")
    return tuple(output)


def _summary(
    replay: Mapping[str, Any], btc_rows: Sequence[Mapping[str, Any]]
) -> dict[str, Any]:
    windows = replay.get("windows")
    if not isinstance(windows, list) or len(windows) != 5:
        raise C12AHistoricalIndependentError(
            "independent pooled window inventory drift"
        )
    pooled = {
        policy: {label: _pooled(windows, policy, label) for label in COST_RATES}
        for policy in ("candidate", "always_enter_comparator")
    }
    candidate = pooled["candidate"]["1.5x"]
    always = pooled["always_enter_comparator"]["1.5x"]
    weekly = [Decimal(value) for value in candidate["weekly_returns"]]
    benchmark = _benchmark(btc_rows)
    candidate_mean = sum(weekly, Decimal(0)) / Decimal(130)
    benchmark_mean = sum(benchmark, Decimal(0)) / Decimal(130)
    beta = sum(
        (
            (left - candidate_mean) * (right - benchmark_mean)
            for left, right in zip(weekly, benchmark, strict=True)
        ),
        Decimal(0),
    ) / sum(((value - benchmark_mean) ** 2 for value in benchmark), Decimal(0))
    asset_pnl = [Decimal(value) for value in candidate["asset_pnl"].values()]
    contract_pnl = [Decimal(value) for value in candidate["contract_pnl"].values()]
    window_pnl = [Decimal(value) for value in candidate["window_pnl"]]
    week_pnl = [Decimal(value) for value in candidate["weekly_pnl"]]
    shares = (
        _positive_share(asset_pnl),
        _positive_share(window_pnl),
        _positive_share(contract_pnl),
        _positive_share(week_pnl),
        _positive_share(week_pnl, 3),
    )
    entered = {
        str(window["window_id"]): sum(
            bool(row["entered"]) for row in window["decisions"]
        )
        for window in windows
    }
    candidate_sharpe = Decimal(str(candidate["statistics"]["annualized_weekly_sharpe"]))
    always_sharpe = Decimal(str(always["statistics"]["annualized_weekly_sharpe"]))
    gates = {
        "all_five_windows_positive": all(
            Decimal(value) > 0 for value in candidate["window_returns"].values()
        ),
        "aggregate_expected_return_positive": Decimal(candidate["aggregate_return"])
        > 0,
        "aggregate_1_0x_return_positive": Decimal(
            pooled["candidate"]["1.0x"]["aggregate_return"]
        )
        > 0,
        "aggregate_2_0x_return_nonnegative": Decimal(
            pooled["candidate"]["2.0x"]["aggregate_return"]
        )
        >= 0,
        "annualized_weekly_sharpe": candidate_sharpe >= Decimal("1.00"),
        "weekly_psr": Decimal(str(candidate["statistics"]["psr_probability"]))
        >= Decimal("0.95"),
        "bonferroni_adjusted_psr": Decimal(candidate["bonferroni_adjusted_psr"])
        >= Decimal("0.95"),
        "maximum_window_drawdown": Decimal(candidate["maximum_drawdown"])
        <= Decimal("0.15"),
        "absolute_btc_beta": abs(beta) <= Decimal("0.10"),
        "annualized_one_way_turnover": Decimal(candidate["annualized_one_way_turnover"])
        <= Decimal("6.0"),
        "minimum_active_asset_contracts": candidate["position_count"] >= 10,
        "minimum_active_asset_contracts_per_window": all(
            value >= 1 for value in entered.values()
        ),
        "positive_asset_contributions": sum(value > 0 for value in asset_pnl) >= 2,
        "asset_concentration": shares[0] is not None and shares[0] <= Decimal("0.70"),
        "window_concentration": shares[1] is not None and shares[1] <= Decimal("0.35"),
        "contract_concentration": shares[2] is not None
        and shares[2] <= Decimal("0.25"),
        "week_concentration": shares[3] is not None and shares[3] <= Decimal("0.25"),
        "top_three_week_concentration": shares[4] is not None
        and shares[4] <= Decimal("0.50"),
        "return_delta_vs_always_enter": Decimal(candidate["aggregate_return"])
        - Decimal(always["aggregate_return"])
        > 0,
        "sharpe_delta_vs_always_enter": candidate_sharpe - always_sharpe > 0,
        "drawdown_no_worse_than_always_enter": Decimal(candidate["maximum_drawdown"])
        <= Decimal(always["maximum_drawdown"]),
        "turnover_no_greater_than_always_enter": Decimal(
            candidate["annualized_one_way_turnover"]
        )
        <= Decimal(always["annualized_one_way_turnover"]),
        "zero_margin_buffer_breaches": candidate["buffer_breaches"] == 0,
        "zero_base_hedge_mismatches": candidate["base_hedge_mismatches"] == 0,
        "zero_reconciliation_errors": candidate["reconciliation_errors"] == 0,
        "required_contract_decisions": sum(
            len(window["decisions"]) for window in windows
        )
        == 20,
        "required_weekly_return_buckets": len(weekly) == 130,
    }
    passed = all(gates.values())
    return {
        "schema_version": 1,
        "stage": "C12A_H1_H5_POOLED_SUMMARY",
        "pooled": pooled,
        "btc_weekly_returns": [str(value) for value in benchmark],
        "candidate_btc_beta": str(beta),
        "entered_by_window": entered,
        "concentration_metrics": {
            "maximum_positive_asset_pnl_share": None
            if shares[0] is None
            else str(shares[0]),
            "maximum_positive_window_pnl_share": None
            if shares[1] is None
            else str(shares[1]),
            "maximum_positive_contract_pnl_share": None
            if shares[2] is None
            else str(shares[2]),
            "maximum_positive_week_pnl_share": None
            if shares[3] is None
            else str(shares[3]),
            "maximum_top_three_positive_week_pnl_share": None
            if shares[4] is None
            else str(shares[4]),
        },
        "eligibility_gates": gates,
        "rejection_reasons": [key for key, value in gates.items() if not value],
        "selected_policy": "C12AFixedMaturityBasisCarry" if passed else None,
        "overall_economic_verdict": "ECONOMIC_PASS" if passed else "ECONOMIC_FAIL",
        "within_stage_candidate_count": 1,
        "declared_program_familywise_trial_count": 628,
        "program_level_bonferroni_corrected": True,
    }


def review_pooled_summary(
    producer: Mapping[str, Any],
    *,
    replay: Mapping[str, Any],
    btc_spot_rows: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    expected = _summary(replay, btc_spot_rows)
    if dict(producer) != expected:
        raise C12AHistoricalIndependentError(
            "independent pooled recomputation mismatch"
        )
    return {
        "schema_version": 1,
        "stage": "C12A_POOLED_INDEPENDENT_REVIEW",
        "status": "PASS",
        "producer_sha256": _digest(producer),
        "independent_sha256": _digest(expected),
        "window_count": len(replay["windows"]),
        "weekly_return_count": 130,
        "classification": expected["overall_economic_verdict"],
    }


__all__ = [
    "C12AHistoricalIndependentError",
    "review_historical_window",
    "review_pooled_summary",
]
