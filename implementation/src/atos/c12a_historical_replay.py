"""Frozen C12A source-ordered fixed-maturity basis-carry replay."""

from __future__ import annotations

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
    TOLERANCE,
    WINDOWS,
    C12AError,
    ContractDecision,
    base_quantity,
    contract_decisions,
    decimal_value,
    finite_float,
    iso_z,
    load_frozen_config,
    normalized_basis,
    utc_timestamp,
)
from atos.c12a_research_program_guard import bonferroni_adjusted_psr

HOUR = timedelta(hours=1)
WEEK = timedelta(days=7)
BUFFER_RATIO = Decimal("0.25")
SLEEVE_FRACTION = Decimal("0.50")


class C12AHistoricalReplayError(RuntimeError):
    """Raised when exact C12A replay cannot be proven."""


def _wrap(exc: Exception) -> C12AHistoricalReplayError:
    return C12AHistoricalReplayError(str(exc))


def _stamp(value: Any) -> datetime:
    try:
        return utc_timestamp(value)
    except C12AError as exc:
        raise _wrap(exc) from exc


def _price(value: Any, label: str) -> Decimal:
    try:
        return decimal_value(value, label, positive=True)
    except C12AError as exc:
        raise _wrap(exc) from exc


@dataclass(frozen=True)
class HourMark:
    timestamp: datetime
    spot: Decimal
    future: Decimal


@dataclass(frozen=True)
class DecisionMarket:
    decision: ContractDecision
    signal_spot: Decimal
    signal_future: Decimal
    entry_spot: Decimal
    entry_future: Decimal
    exit_spot: Decimal
    exit_future: Decimal
    marks: tuple[HourMark, ...]

    @property
    def basis(self) -> Decimal:
        try:
            return normalized_basis(
                futures_price=self.signal_future, spot_price=self.signal_spot
            )
        except C12AError as exc:
            raise _wrap(exc) from exc

    @property
    def enter(self) -> bool:
        return self.basis > ENTRY_THRESHOLD

    def mark_at(self, timestamp: datetime) -> HourMark:
        matches = [mark for mark in self.marks if mark.timestamp == timestamp]
        if len(matches) != 1:
            raise C12AHistoricalReplayError(
                f"missing unique C12A mark: {self.decision.futures_instrument} "
                f"{iso_z(timestamp)}"
            )
        return matches[0]


@dataclass(frozen=True)
class Position:
    market: DecisionMarket
    quantity: Decimal
    entry_cost: Decimal
    exit_cost: Decimal
    exit_timestamp: datetime
    exit_spot: Decimal
    exit_future: Decimal
    buffer_breach: bool

    @property
    def realized_pnl(self) -> Decimal:
        return (
            self.quantity * (self.exit_spot - self.market.entry_spot)
            - self.quantity * (self.exit_future - self.market.entry_future)
            - self.entry_cost
            - self.exit_cost
        )

    def pnl_at(self, timestamp: datetime) -> Decimal:
        if timestamp <= self.market.decision.entry_timestamp:
            return Decimal(0)
        if timestamp >= self.exit_timestamp:
            return self.realized_pnl
        mark = self.market.mark_at(timestamp)
        return (
            self.quantity * (mark.spot - self.market.entry_spot)
            - self.quantity * (mark.future - self.market.entry_future)
            - self.entry_cost
        )


@dataclass(frozen=True)
class SpotPosition:
    market: DecisionMarket
    quantity: Decimal
    entry_cost: Decimal
    exit_cost: Decimal
    exit_timestamp: datetime
    exit_spot: Decimal

    @property
    def realized_pnl(self) -> Decimal:
        return (
            self.quantity * (self.exit_spot - self.market.entry_spot)
            - self.entry_cost
            - self.exit_cost
        )

    def pnl_at(self, timestamp: datetime) -> Decimal:
        if timestamp <= self.market.decision.entry_timestamp:
            return Decimal(0)
        if timestamp >= self.exit_timestamp:
            return self.realized_pnl
        mark = self.market.mark_at(timestamp)
        return self.quantity * (mark.spot - self.market.entry_spot) - self.entry_cost


def _spot_index(
    rows: Sequence[Mapping[str, Any]], *, instrument: str
) -> dict[datetime, dict[str, Decimal]]:
    output: dict[datetime, dict[str, Decimal]] = {}
    previous: datetime | None = None
    for row in rows:
        stamp = _stamp(row.get("timestamp"))
        if previous is not None and stamp <= previous:
            raise C12AHistoricalReplayError(f"{instrument} spot candles are unordered")
        previous = stamp
        if stamp in output:
            raise C12AHistoricalReplayError(f"{instrument} spot candle is duplicated")
        output[stamp] = {
            "open": _price(row.get("open"), "spot open"),
            "close": _price(row.get("close"), "spot close"),
        }
    if not output:
        raise C12AHistoricalReplayError(f"{instrument} spot candle series is empty")
    return output


def _future_rows(
    rows: Sequence[Mapping[str, Any]], *, instrument: str
) -> tuple[tuple[datetime, int, Decimal], ...]:
    output: list[tuple[datetime, int, Decimal]] = []
    seen: set[str] = set()
    previous: tuple[datetime, int] | None = None
    for row in rows:
        if row.get("instrument") != instrument:
            raise C12AHistoricalReplayError("futures normalized instrument drift")
        trade_id = str(row.get("trade_id", ""))
        if not trade_id.isdigit() or trade_id in seen:
            raise C12AHistoricalReplayError("futures normalized trade ID drift")
        seen.add(trade_id)
        parsed = (
            _stamp(row.get("timestamp")),
            int(trade_id),
            _price(row.get("price"), "futures trade price"),
        )
        order = parsed[:2]
        if previous is not None and order <= previous:
            raise C12AHistoricalReplayError(
                "futures normalized series is duplicated or unordered"
            )
        previous = order
        output.append(parsed)
    if not output:
        raise C12AHistoricalReplayError("futures normalized series is empty")
    return tuple(output)


def _future_indexes(
    rows: Sequence[tuple[datetime, int, Decimal]],
) -> dict[datetime, Decimal]:
    """Build exact closed-hour prices in one pass."""

    hourly_last: dict[datetime, Decimal] = {}
    for stamp, _, price in rows:
        hour = stamp.replace(minute=0, second=0, microsecond=0)
        hourly_last[hour] = price
    return hourly_last


def _execution_price(
    rows: Sequence[tuple[datetime, int, Decimal]], *, start: datetime, label: str
) -> Decimal:
    end = start + EXECUTION_MAX_DELAY
    for stamp, _, price in rows:
        if stamp < start:
            continue
        if stamp <= end:
            return price
        break
    raise C12AHistoricalReplayError(f"missing futures {label}: {iso_z(start)}")


def build_decision_market(
    decision: ContractDecision,
    *,
    spot_rows: Sequence[Mapping[str, Any]],
    futures_rows: Sequence[Mapping[str, Any]],
) -> DecisionMarket:
    spot = _spot_index(spot_rows, instrument=decision.spot_instrument)
    future = _future_rows(futures_rows, instrument=decision.futures_instrument)
    hourly_last = _future_indexes(future)

    def candle(stamp: datetime) -> dict[str, Decimal]:
        try:
            return spot[stamp]
        except KeyError as exc:
            raise C12AHistoricalReplayError(
                f"missing spot candle: {decision.spot_instrument} {iso_z(stamp)}"
            ) from exc

    signal_hour = decision.signal_cutoff - HOUR

    def hour_price(stamp: datetime, label: str) -> Decimal:
        try:
            return hourly_last[stamp]
        except KeyError as exc:
            raise C12AHistoricalReplayError(
                f"missing futures {label}: {iso_z(stamp)}"
            ) from exc

    marks: list[HourMark] = []
    current = decision.entry_timestamp
    while current < decision.exit_timestamp:
        marks.append(
            HourMark(
                timestamp=current + HOUR,
                spot=candle(current)["close"],
                future=hour_price(current, "carried hour"),
            )
        )
        current += HOUR
    return DecisionMarket(
        decision=decision,
        signal_spot=candle(signal_hour)["close"],
        signal_future=hour_price(signal_hour, "signal hour"),
        entry_spot=candle(decision.entry_timestamp)["open"],
        entry_future=_execution_price(
            future, start=decision.entry_timestamp, label="entry execution"
        ),
        exit_spot=candle(decision.exit_timestamp)["open"],
        exit_future=_execution_price(
            future, start=decision.exit_timestamp, label="exit execution"
        ),
        marks=tuple(marks),
    )


def build_market_inventory(
    *,
    spot_series: Mapping[str, Sequence[Mapping[str, Any]]],
    futures_series: Mapping[str, Sequence[Mapping[str, Any]]],
    config: dict[str, Any] | None = None,
) -> tuple[DecisionMarket, ...]:
    payload = config if config is not None else load_frozen_config()
    decisions = contract_decisions(payload)
    if set(spot_series) != {"BTC-USDT", "ETH-USDT"}:
        raise C12AHistoricalReplayError("C12A spot source inventory drift")
    if set(futures_series) != {item.futures_instrument for item in decisions}:
        raise C12AHistoricalReplayError("C12A futures source inventory drift")
    return tuple(
        build_decision_market(
            decision,
            spot_rows=spot_series[decision.spot_instrument],
            futures_rows=futures_series[decision.futures_instrument],
        )
        for decision in decisions
    )


def _effective_exit(
    market: DecisionMarket, *, quantity: Decimal
) -> tuple[datetime, Decimal, Decimal, bool]:
    for index, mark in enumerate(market.marks):
        margin = quantity * (Decimal(2) * market.entry_future - mark.future)
        ratio = margin / (quantity * mark.future)
        if ratio < BUFFER_RATIO:
            if index + 1 < len(market.marks):
                forced = market.marks[index + 1]
                return forced.timestamp, forced.spot, forced.future, True
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


def _portfolio_positions(
    markets: Sequence[DecisionMarket],
    *,
    cost_rate: Decimal,
    policy: str,
) -> tuple[Position, ...]:
    if policy not in {"candidate", "always_enter"}:
        raise C12AHistoricalReplayError("unknown C12A replay policy")
    positions: list[Position] = []
    equity = STARTING_EQUITY
    grouped: dict[datetime, list[DecisionMarket]] = {}
    for market in markets:
        grouped.setdefault(market.decision.entry_timestamp, []).append(market)
    for entry_timestamp, group in sorted(grouped.items()):
        if any(position.exit_timestamp > entry_timestamp for position in positions):
            raise C12AHistoricalReplayError("C12A contract positions overlap")
        equity = STARTING_EQUITY + sum(
            (position.realized_pnl for position in positions), Decimal(0)
        )
        if equity <= 0:
            raise C12AHistoricalReplayError("C12A equity became non-positive")
        sleeve = equity * SLEEVE_FRACTION
        for market in sorted(group, key=lambda item: item.decision.asset):
            if policy == "candidate" and not market.enter:
                continue
            try:
                quantity = base_quantity(
                    sleeve_equity=sleeve,
                    spot_entry=market.entry_spot,
                    futures_entry=market.entry_future,
                    cost_rate=COST_RATES["2.0x"],
                )
            except C12AError as exc:
                raise _wrap(exc) from exc
            entry_cost = (
                quantity * cost_rate * (market.entry_spot + market.entry_future)
            )
            if (
                quantity * (market.entry_spot + market.entry_future) + entry_cost
                > sleeve + TOLERANCE
            ):
                raise C12AHistoricalReplayError("C12A entry cash would be negative")
            exit_stamp, exit_spot, exit_future, breached = _effective_exit(
                market, quantity=quantity
            )
            exit_cost = quantity * cost_rate * (exit_spot + exit_future)
            positions.append(
                Position(
                    market=market,
                    quantity=quantity,
                    entry_cost=entry_cost,
                    exit_cost=exit_cost,
                    exit_timestamp=exit_stamp,
                    exit_spot=exit_spot,
                    exit_future=exit_future,
                    buffer_breach=breached,
                )
            )
    return tuple(positions)


def _spot_positions(
    candidate_positions: Sequence[Position], *, cost_rate: Decimal
) -> tuple[SpotPosition, ...]:
    return tuple(
        SpotPosition(
            market=position.market,
            quantity=position.quantity,
            entry_cost=position.quantity * cost_rate * position.market.entry_spot,
            exit_cost=position.quantity * cost_rate * position.exit_spot,
            exit_timestamp=position.exit_timestamp,
            exit_spot=position.exit_spot,
        )
        for position in candidate_positions
    )


def _equity_at(
    timestamp: datetime,
    *,
    positions: Sequence[Position] | Sequence[SpotPosition],
) -> Decimal:
    equity = STARTING_EQUITY + sum(
        (position.pnl_at(timestamp) for position in positions), Decimal(0)
    )
    if not equity.is_finite() or equity <= 0:
        raise C12AHistoricalReplayError(
            "C12A equity path is non-positive or non-finite"
        )
    return equity


def _maximum_drawdown(equities: Sequence[Decimal]) -> Decimal:
    peak = equities[0]
    maximum = Decimal(0)
    for equity in equities:
        peak = max(peak, equity)
        maximum = max(maximum, (peak - equity) / peak)
    return maximum


def _replay_policy(
    *,
    window_id: str,
    markets: Sequence[DecisionMarket],
    cost_label: str,
    policy: str,
) -> dict[str, Any]:
    window = next((item for item in WINDOWS if item.window_id == window_id), None)
    if window is None or cost_label not in COST_RATES:
        raise C12AHistoricalReplayError("C12A replay identity drift")
    cost_rate = COST_RATES[cost_label]
    positions = _portfolio_positions(markets, cost_rate=cost_rate, policy=policy)
    boundaries = tuple(window.start + index * WEEK for index in range(27))
    equities = tuple(_equity_at(stamp, positions=positions) for stamp in boundaries)
    returns = tuple(
        (equities[index] / equities[index - 1]) - Decimal(1)
        for index in range(1, len(equities))
    )
    final_equity = _equity_at(window.end, positions=positions)
    turnover_notional = sum(
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
    mean_equity = Decimal(
        str(fmean(finite_float(value, "equity") for value in equities))
    )
    one_way_turnover = (
        Decimal("0.5") * turnover_notional / mean_equity * Decimal(52) / Decimal(26)
    )
    total_pnl = sum((position.realized_pnl for position in positions), Decimal(0))
    contract_pnl = {
        position.market.decision.futures_instrument: position.realized_pnl
        for position in positions
    }
    asset_pnl = {
        asset: sum(
            (
                position.realized_pnl
                for position in positions
                if position.market.decision.asset == asset
            ),
            Decimal(0),
        )
        for asset in ("BTC", "ETH")
    }
    if (
        abs(final_equity - STARTING_EQUITY - total_pnl) > TOLERANCE
        or abs(sum(contract_pnl.values(), Decimal(0)) - total_pnl) > TOLERANCE
        or abs(sum(asset_pnl.values(), Decimal(0)) - total_pnl) > TOLERANCE
    ):
        raise C12AHistoricalReplayError(
            "C12A price/cost attribution does not reconcile"
        )
    return {
        "policy": policy,
        "window_id": window_id,
        "cost_label": cost_label,
        "starting_equity": str(STARTING_EQUITY),
        "final_equity": str(final_equity),
        "return": str(final_equity / STARTING_EQUITY - Decimal(1)),
        "weekly_returns": [str(value) for value in returns],
        "weekly_equities": [str(value) for value in equities[1:]],
        "maximum_drawdown": str(_maximum_drawdown(equities)),
        "annualized_one_way_turnover": str(one_way_turnover),
        "position_count": len(positions),
        "buffer_breaches": sum(position.buffer_breach for position in positions),
        "base_hedge_mismatches": 0,
        "reconciliation_errors": 0,
        "contract_pnl": {key: str(value) for key, value in contract_pnl.items()},
        "asset_pnl": {key: str(value) for key, value in asset_pnl.items()},
    }


def replay_window(
    *, window_id: str, markets: Sequence[DecisionMarket]
) -> dict[str, Any]:
    selected = tuple(
        market for market in markets if market.decision.window_id == window_id
    )
    if len(selected) != 4:
        raise C12AHistoricalReplayError("C12A window requires four decision markets")
    decisions = [
        {
            "asset": market.decision.asset,
            "futures_instrument": market.decision.futures_instrument,
            "signal_cutoff": iso_z(market.decision.signal_cutoff),
            "entry_timestamp": iso_z(market.decision.entry_timestamp),
            "exit_timestamp": iso_z(market.decision.exit_timestamp),
            "normalized_basis": str(market.basis),
            "entered": market.enter,
        }
        for market in selected
    ]
    cells: dict[str, Any] = {}
    for cost_label in COST_RATES:
        candidate = _replay_policy(
            window_id=window_id,
            markets=selected,
            cost_label=cost_label,
            policy="candidate",
        )
        always = _replay_policy(
            window_id=window_id,
            markets=selected,
            cost_label=cost_label,
            policy="always_enter",
        )
        candidate_positions = _portfolio_positions(
            selected, cost_rate=COST_RATES[cost_label], policy="candidate"
        )
        spot_positions = _spot_positions(
            candidate_positions, cost_rate=COST_RATES[cost_label]
        )
        window = next(item for item in WINDOWS if item.window_id == window_id)
        spot_final = _equity_at(window.end, positions=spot_positions)
        cells[cost_label] = {
            "candidate": candidate,
            "cash_comparator": {
                "final_equity": str(STARTING_EQUITY),
                "return": "0",
                "position_count": 0,
            },
            "always_enter_comparator": always,
            "spot_only_comparator": {
                "final_equity": str(spot_final),
                "return": str(spot_final / STARTING_EQUITY - Decimal(1)),
                "position_count": len(spot_positions),
            },
        }
    return {
        "schema_version": 1,
        "stage": "C12A_WINDOW_REPLAY",
        "window_id": window_id,
        "decisions": decisions,
        "cost_cells": cells,
    }


def replay_h1_h5(markets: Sequence[DecisionMarket]) -> dict[str, Any]:
    if len(markets) != 20:
        raise C12AHistoricalReplayError("C12A requires twenty decision markets")
    windows = [
        replay_window(window_id=item.window_id, markets=markets) for item in WINDOWS
    ]
    return {
        "schema_version": 1,
        "stage": "C12A_H1_H5_REPLAY",
        "candidate_id": "C12AFixedMaturityBasisCarry",
        "windows": windows,
        "economic_result": False,
    }


def btc_weekly_benchmark_returns(
    spot_rows: Sequence[Mapping[str, Any]],
) -> tuple[Decimal, ...]:
    """Build the exact 130 completed-hour BTC benchmark returns."""

    spot = _spot_index(spot_rows, instrument="BTC-USDT")
    output: list[Decimal] = []
    for window in WINDOWS:
        prices: list[Decimal] = []
        for index in range(27):
            boundary = window.start + index * WEEK
            try:
                prices.append(spot[boundary - HOUR]["close"])
            except KeyError as exc:
                raise C12AHistoricalReplayError(
                    f"missing BTC benchmark hour: {iso_z(boundary - HOUR)}"
                ) from exc
        output.extend(
            prices[index] / prices[index - 1] - Decimal(1)
            for index in range(1, len(prices))
        )
    if len(output) != 130:
        raise C12AHistoricalReplayError("BTC benchmark weekly coverage drift")
    return tuple(output)


def _statistics(values: Sequence[Decimal]) -> dict[str, Any]:
    raw = [finite_float(value, "weekly return") for value in values]
    if len(raw) != 130:
        raise C12AHistoricalReplayError("pooled weekly return coverage is invalid")
    average = fmean(raw)
    sample_variance = sum((value - average) ** 2 for value in raw) / (len(raw) - 1)
    sample_std = math.sqrt(sample_variance)
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
    sample_skew = float(skew(raw, bias=False))
    ordinary_kurtosis = float(kurtosis(raw, fisher=False, bias=False))
    radicand = (
        1
        - sample_skew * weekly_sharpe
        + ((ordinary_kurtosis - 1) / 4) * weekly_sharpe**2
    )
    valid = math.isfinite(radicand) and radicand > 0
    probability = (
        float(norm.cdf(weekly_sharpe * math.sqrt(len(raw) - 1) / math.sqrt(radicand)))
        if valid
        else 0.0
    )
    valid = valid and all(
        math.isfinite(value) for value in (sample_skew, ordinary_kurtosis, probability)
    )
    return {
        "n": len(raw),
        "mean": average,
        "sample_std": sample_std,
        "weekly_sharpe": weekly_sharpe,
        "annualized_weekly_sharpe": weekly_sharpe * math.sqrt(52),
        "unbiased_skewness": sample_skew,
        "unbiased_ordinary_kurtosis": ordinary_kurtosis,
        "psr_probability": probability if valid else 0.0,
        "valid": valid,
    }


def _positive_share(values: Sequence[Decimal], *, count: int = 1) -> Decimal | None:
    positive = sorted((max(value, Decimal(0)) for value in values), reverse=True)
    denominator = sum(positive, Decimal(0))
    return None if denominator <= 0 else sum(positive[:count], Decimal(0)) / denominator


def _pool_policy(
    windows: Sequence[Mapping[str, Any]], *, policy_key: str, cost_label: str
) -> dict[str, Any]:
    rows = [window["cost_cells"][cost_label][policy_key] for window in windows]
    weekly_returns = [
        Decimal(str(value)) for row in rows for value in row["weekly_returns"]
    ]
    statistics = _statistics(weekly_returns)
    final_equities = [Decimal(str(row["final_equity"])) for row in rows]
    window_pnl = [equity - STARTING_EQUITY for equity in final_equities]
    contract_pnl: dict[str, Decimal] = {}
    asset_pnl = {"BTC": Decimal(0), "ETH": Decimal(0)}
    for row in rows:
        for instrument, value in row["contract_pnl"].items():
            contract_pnl[instrument] = contract_pnl.get(
                instrument, Decimal(0)
            ) + Decimal(str(value))
        for asset, value in row["asset_pnl"].items():
            asset_pnl[asset] += Decimal(str(value))
    weekly_pnl: list[Decimal] = []
    for row in rows:
        previous = STARTING_EQUITY
        for equity_text in row["weekly_equities"]:
            equity = Decimal(str(equity_text))
            weekly_pnl.append(equity - previous)
            previous = equity
    psr = Decimal(str(statistics["psr_probability"]))
    return {
        "policy": policy_key,
        "cost_label": cost_label,
        "aggregate_return": str(
            sum(final_equities, Decimal(0)) / Decimal(5000) - Decimal(1)
        ),
        "window_returns": {
            str(window["window_id"]): str(row["return"])
            for window, row in zip(windows, rows, strict=True)
        },
        "window_pnl": [str(value) for value in window_pnl],
        "weekly_returns": [str(value) for value in weekly_returns],
        "weekly_pnl": [str(value) for value in weekly_pnl],
        "statistics": statistics,
        "bonferroni_adjusted_psr": str(bonferroni_adjusted_psr(psr)),
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


def _btc_beta(candidate: Sequence[Decimal], benchmark: Sequence[Decimal]) -> Decimal:
    if len(candidate) != 130 or len(benchmark) != 130:
        raise C12AHistoricalReplayError("BTC beta return coverage is invalid")
    candidate_mean = sum(candidate, Decimal(0)) / Decimal(130)
    benchmark_mean = sum(benchmark, Decimal(0)) / Decimal(130)
    covariance = sum(
        (
            (left - candidate_mean) * (right - benchmark_mean)
            for left, right in zip(candidate, benchmark, strict=True)
        ),
        Decimal(0),
    )
    variance = sum(((value - benchmark_mean) ** 2 for value in benchmark), Decimal(0))
    if variance <= 0:
        raise C12AHistoricalReplayError("BTC beta benchmark variance is invalid")
    beta = covariance / variance
    if not beta.is_finite():
        raise C12AHistoricalReplayError("BTC beta is non-finite")
    return beta


def summarize_h1_h5(
    replay: Mapping[str, Any], *, btc_weekly_returns: Sequence[Decimal]
) -> dict[str, Any]:
    """Pool independent capital and apply every preregistered C12A gate."""

    windows = replay.get("windows")
    if not isinstance(windows, list) or [row.get("window_id") for row in windows] != [
        window.window_id for window in WINDOWS
    ]:
        raise C12AHistoricalReplayError("C12A summary requires ordered H1-H5")
    pooled = {
        policy: {
            cost_label: _pool_policy(windows, policy_key=policy, cost_label=cost_label)
            for cost_label in COST_RATES
        }
        for policy in ("candidate", "always_enter_comparator")
    }
    candidate = pooled["candidate"]["1.5x"]
    always = pooled["always_enter_comparator"]["1.5x"]
    candidate_weekly = [Decimal(value) for value in candidate["weekly_returns"]]
    benchmark = tuple(btc_weekly_returns)
    beta = _btc_beta(candidate_weekly, benchmark)
    asset_pnl = [Decimal(value) for value in candidate["asset_pnl"].values()]
    contract_pnl = [Decimal(value) for value in candidate["contract_pnl"].values()]
    window_pnl = [Decimal(value) for value in candidate["window_pnl"]]
    week_pnl = [Decimal(value) for value in candidate["weekly_pnl"]]
    asset_share = _positive_share(asset_pnl)
    contract_share = _positive_share(contract_pnl)
    window_share = _positive_share(window_pnl)
    week_share = _positive_share(week_pnl)
    top_three_week_share = _positive_share(week_pnl, count=3)
    candidate_sharpe = Decimal(str(candidate["statistics"]["annualized_weekly_sharpe"]))
    always_sharpe = Decimal(str(always["statistics"]["annualized_weekly_sharpe"]))
    entered_by_window = {
        str(window["window_id"]): sum(
            bool(decision["entered"]) for decision in window["decisions"]
        )
        for window in windows
    }
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
            value >= 1 for value in entered_by_window.values()
        ),
        "positive_asset_contributions": sum(value > 0 for value in asset_pnl) >= 2,
        "asset_concentration": asset_share is not None
        and asset_share <= Decimal("0.70"),
        "window_concentration": window_share is not None
        and window_share <= Decimal("0.35"),
        "contract_concentration": contract_share is not None
        and contract_share <= Decimal("0.25"),
        "week_concentration": week_share is not None and week_share <= Decimal("0.25"),
        "top_three_week_concentration": top_three_week_share is not None
        and top_three_week_share <= Decimal("0.50"),
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
        "required_weekly_return_buckets": len(candidate_weekly) == 130,
    }
    passed = all(gates.values())
    return {
        "schema_version": 1,
        "stage": "C12A_H1_H5_POOLED_SUMMARY",
        "pooled": pooled,
        "btc_weekly_returns": [str(value) for value in benchmark],
        "candidate_btc_beta": str(beta),
        "entered_by_window": entered_by_window,
        "concentration_metrics": {
            "maximum_positive_asset_pnl_share": (
                None if asset_share is None else str(asset_share)
            ),
            "maximum_positive_window_pnl_share": (
                None if window_share is None else str(window_share)
            ),
            "maximum_positive_contract_pnl_share": (
                None if contract_share is None else str(contract_share)
            ),
            "maximum_positive_week_pnl_share": (
                None if week_share is None else str(week_share)
            ),
            "maximum_top_three_positive_week_pnl_share": (
                None if top_three_week_share is None else str(top_three_week_share)
            ),
        },
        "eligibility_gates": gates,
        "rejection_reasons": [key for key, value in gates.items() if not value],
        "selected_policy": "C12AFixedMaturityBasisCarry" if passed else None,
        "overall_economic_verdict": "ECONOMIC_PASS" if passed else "ECONOMIC_FAIL",
        "within_stage_candidate_count": 1,
        "declared_program_familywise_trial_count": 628,
        "program_level_bonferroni_corrected": True,
    }


__all__ = [
    "BUFFER_RATIO",
    "C12AHistoricalReplayError",
    "DecisionMarket",
    "HourMark",
    "Position",
    "SpotPosition",
    "btc_weekly_benchmark_returns",
    "build_decision_market",
    "build_market_inventory",
    "replay_h1_h5",
    "replay_window",
    "summarize_h1_h5",
]
