"""Independent C5A contract validation and calibration recomputation.

No exchange-account, private-API, order, paper, shadow, leverage, short, or live path.
"""
from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Mapping, Sequence

import numpy as np

SPOT_INSTRUMENTS = ("BTC-USDT", "ETH-USDT", "SOL-USDT")
SWAP_INSTRUMENTS = ("BTC-USDT-SWAP", "ETH-USDT-SWAP", "SOL-USDT-SWAP")
SPOT_TO_SWAP = dict(zip(SPOT_INSTRUMENTS, SWAP_INSTRUMENTS, strict=True))
CANDIDATE_ID = "C5ADerivativesCrowdingFilteredRiskBalance"
ABLATION_ID = "C5APriceOnlyRiskBalanceAblation"
COMPARATORS = ("cash", "btc_buy_hold", "btc_eth_sol_equal_weight_buy_hold")
COST_LABELS = ("1.0x", "1.5x", "2.0x")
EXPECTED_CONFIG_CANONICAL_SHA256 = "6b9229830a6211d2b3e73094c0bd9e2f7df9e3ab045cffc3a42ed23ffec73747"
STEP = timedelta(hours=4)
DOWNLOAD_START = datetime(2024, 9, 2, tzinfo=UTC)
BOUNDARY = datetime(2026, 1, 5, tzinfo=UTC)
SECONDS_PER_YEAR = 365 * 24 * 60 * 60
ANNUAL_4H_BARS = 6 * 365


class C5AReferenceError(RuntimeError):
    """Raised when a frozen C5A invariant fails."""


def _timestamp(value: Any) -> datetime:
    if isinstance(value, datetime):
        result = value
    elif isinstance(value, str) and value.strip():
        result = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    elif isinstance(value, (int, float)) and not isinstance(value, bool):
        raw = float(value)
        result = datetime.fromtimestamp(raw / (1000 if raw > 10_000_000_000 else 1), tz=UTC)
    else:
        raise C5AReferenceError(f"invalid timestamp: {value!r}")
    return result.replace(tzinfo=UTC) if result.tzinfo is None else result.astimezone(UTC)


def _finite(value: Any, label: str) -> float:
    if value is None or isinstance(value, bool):
        raise C5AReferenceError(f"{label} must be numeric")
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise C5AReferenceError(f"{label} must be numeric") from exc
    if not math.isfinite(result):
        raise C5AReferenceError(f"{label} must be finite")
    return result


def canonical_sha256(payload: Any) -> str:
    encoded = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def validate_config(config: Mapping[str, Any]) -> None:
    if canonical_sha256(config) != EXPECTED_CONFIG_CANONICAL_SHA256:
        raise C5AReferenceError("C5A semantic configuration drift")
    if config.get("schema_version") != 1 or config.get("stage") != "C5A":
        raise C5AReferenceError("C5A identity drift")
    if config.get("required_design_main_sha") != "77e1796bd70b3e646595972af772c91af6c8f8a9":
        raise C5AReferenceError("C5A design-main drift")
    if config.get("spot_instruments") != list(SPOT_INSTRUMENTS):
        raise C5AReferenceError("C5A spot instrument drift")
    if config.get("swap_instruments") != list(SWAP_INSTRUMENTS):
        raise C5AReferenceError("C5A swap instrument drift")
    if config.get("candidate_id") != CANDIDATE_ID or config.get("ablation_id") != ABLATION_ID:
        raise C5AReferenceError("C5A candidate identity drift")
    if config.get("comparators") != list(COMPARATORS):
        raise C5AReferenceError("C5A comparator drift")
    if config.get("timeframe") != "4H":
        raise C5AReferenceError("C5A timeframe drift")
    if config.get("economic_boundary_exclusive") != "2026-01-05T00:00:00Z":
        raise C5AReferenceError("C5A boundary drift")
    if config.get("confirmation_opened") is not False:
        raise C5AReferenceError("C5B must remain closed")
    if (
        config.get("holdout_state") != "HOLDOUT_CLOSED"
        or config.get("paper_state") != "PAPER_CLOSED"
        or config.get("shadow_state") != "SHADOW_CLOSED"
        or config.get("live") != "FORBIDDEN"
    ):
        raise C5AReferenceError("C5A safety state drift")


def expected_timestamps() -> tuple[datetime, ...]:
    count = int((BOUNDARY - DOWNLOAD_START) / STEP)
    values = tuple(DOWNLOAD_START + index * STEP for index in range(count))
    if len(values) != 2940 or values[-1] != BOUNDARY - STEP:
        raise C5AReferenceError("internal C5A timestamp-grid mismatch")
    return values


@dataclass(frozen=True)
class C5AMarket:
    timestamps: tuple[datetime, ...]
    spot_open: Mapping[str, np.ndarray]
    spot_high: Mapping[str, np.ndarray]
    spot_low: Mapping[str, np.ndarray]
    spot_close: Mapping[str, np.ndarray]
    spot_quote_volume: Mapping[str, np.ndarray]
    swap_quote_volume: Mapping[str, np.ndarray]
    mark_close: Mapping[str, np.ndarray]


def _rows_by_timestamp(
    rows: Sequence[Mapping[str, Any]],
    *,
    label: str,
    fields: Sequence[str],
) -> tuple[tuple[datetime, ...], dict[str, np.ndarray]]:
    if not rows:
        raise C5AReferenceError(f"empty series: {label}")
    timestamps = tuple(_timestamp(row.get("date")) for row in rows)
    if timestamps != tuple(sorted(timestamps)) or len(set(timestamps)) != len(timestamps):
        raise C5AReferenceError(f"unordered or duplicate timestamps: {label}")
    if timestamps != expected_timestamps():
        raise C5AReferenceError(f"exact retained coverage mismatch: {label}")
    arrays: dict[str, np.ndarray] = {}
    for field in fields:
        array = np.asarray(
            [_finite(row.get(field), f"{label} {field}") for row in rows],
            dtype=float,
        )
        if len(array) != len(timestamps) or not np.isfinite(array).all():
            raise C5AReferenceError(f"invalid series: {label} {field}")
        arrays[field] = array
    return timestamps, arrays


def prepare_market(datasets: Mapping[str, Any]) -> C5AMarket:
    if set(datasets) != {"spot", "swap", "mark"}:
        raise C5AReferenceError("C5A dataset sections must be spot/swap/mark")
    spot = datasets["spot"]
    swap = datasets["swap"]
    mark = datasets["mark"]
    if not isinstance(spot, Mapping) or set(spot) != set(SPOT_INSTRUMENTS):
        raise C5AReferenceError("C5A spot dataset set mismatch")
    if not isinstance(swap, Mapping) or set(swap) != set(SWAP_INSTRUMENTS):
        raise C5AReferenceError("C5A swap dataset set mismatch")
    if not isinstance(mark, Mapping) or set(mark) != set(SWAP_INSTRUMENTS):
        raise C5AReferenceError("C5A mark dataset set mismatch")

    timestamps: tuple[datetime, ...] | None = None
    spot_open: dict[str, np.ndarray] = {}
    spot_high: dict[str, np.ndarray] = {}
    spot_low: dict[str, np.ndarray] = {}
    spot_close: dict[str, np.ndarray] = {}
    spot_quote_volume: dict[str, np.ndarray] = {}
    swap_quote_volume: dict[str, np.ndarray] = {}
    mark_close: dict[str, np.ndarray] = {}

    for instrument in SPOT_INSTRUMENTS:
        current, arrays = _rows_by_timestamp(
            spot[instrument],
            label=f"spot:{instrument}",
            fields=("open", "high", "low", "close", "quote_volume"),
        )
        timestamps = current if timestamps is None else timestamps
        if current != timestamps:
            raise C5AReferenceError(f"spot alignment mismatch: {instrument}")
        if (
            np.any(arrays["open"] <= 0)
            or np.any(arrays["high"] <= 0)
            or np.any(arrays["low"] <= 0)
            or np.any(arrays["close"] <= 0)
            or np.any(arrays["quote_volume"] < 0)
        ):
            raise C5AReferenceError(f"non-positive price or negative volume: {instrument}")
        invalid = (
            (arrays["low"] > arrays["high"])
            | (arrays["open"] < arrays["low"])
            | (arrays["open"] > arrays["high"])
            | (arrays["close"] < arrays["low"])
            | (arrays["close"] > arrays["high"])
        )
        if np.any(invalid):
            raise C5AReferenceError(f"invalid spot OHLC geometry: {instrument}")
        spot_open[instrument] = arrays["open"]
        spot_high[instrument] = arrays["high"]
        spot_low[instrument] = arrays["low"]
        spot_close[instrument] = arrays["close"]
        spot_quote_volume[instrument] = arrays["quote_volume"]

    for instrument in SWAP_INSTRUMENTS:
        current, arrays = _rows_by_timestamp(
            swap[instrument],
            label=f"swap:{instrument}",
            fields=("quote_volume",),
        )
        if current != timestamps:
            raise C5AReferenceError(f"swap alignment mismatch: {instrument}")
        if np.any(arrays["quote_volume"] < 0):
            raise C5AReferenceError(f"negative swap quote volume: {instrument}")
        swap_quote_volume[instrument] = arrays["quote_volume"]

        current, arrays = _rows_by_timestamp(
            mark[instrument],
            label=f"mark:{instrument}",
            fields=("close",),
        )
        if current != timestamps:
            raise C5AReferenceError(f"mark alignment mismatch: {instrument}")
        if np.any(arrays["close"] <= 0):
            raise C5AReferenceError(f"non-positive mark close: {instrument}")
        mark_close[instrument] = arrays["close"]

    if timestamps is None:
        raise C5AReferenceError("empty C5A market")
    return C5AMarket(
        timestamps=timestamps,
        spot_open=spot_open,
        spot_high=spot_high,
        spot_low=spot_low,
        spot_close=spot_close,
        spot_quote_volume=spot_quote_volume,
        swap_quote_volume=swap_quote_volume,
        mark_close=mark_close,
    )


def _index_of(market: C5AMarket, timestamp: datetime) -> int:
    try:
        return market.timestamps.index(timestamp)
    except ValueError as exc:
        raise C5AReferenceError(f"timestamp absent from market: {timestamp.isoformat()}") from exc


def calibration_decision_times(config: Mapping[str, Any]) -> tuple[datetime, ...]:
    start = _timestamp(config["calibration_start"])
    end = _timestamp(config["calibration_end_inclusive"])
    values: list[datetime] = []
    current = start
    while current <= end:
        if current.weekday() != 0 or current.hour != 0:
            raise C5AReferenceError("calibration boundary is not Monday 00 UTC")
        values.append(current)
        current += timedelta(days=7)
    if len(values) != 39:
        raise C5AReferenceError(f"calibration observation count mismatch: {len(values)}")
    return tuple(values)


def window_decision_times(window: Mapping[str, Any]) -> tuple[datetime, ...]:
    start, end = _timestamp(window["start"]), _timestamp(window["end"])
    values: list[datetime] = []
    current = start
    while current < end:
        if current.weekday() != 0 or current.hour != 0:
            raise C5AReferenceError("screen boundary is not Monday 00 UTC")
        values.append(current)
        current += timedelta(days=7)
    if len(values) != 13:
        raise C5AReferenceError(f"half-window decision count mismatch: {len(values)}")
    return tuple(values)


def _raw_features(
    market: C5AMarket,
    *,
    execution_index: int,
    config: Mapping[str, Any],
) -> dict[str, dict[str, float]]:
    signal_index = execution_index - 1
    if signal_index < 0:
        raise C5AReferenceError("missing completed signal bar")
    signal_time = market.timestamps[signal_index]
    if signal_time.weekday() != 6 or signal_time.hour != 20:
        raise C5AReferenceError("C5A signal must use Sunday 20 UTC")
    trend_intervals = int(config["trend_intervals"])
    vol_count = int(config["volatility_return_count"])
    crowding_bars = int(config["crowding_bars"])
    if signal_index - trend_intervals < 0 or signal_index - vol_count < 0:
        raise C5AReferenceError("insufficient C5A warm-up")

    output: dict[str, dict[str, float]] = {}
    for spot in SPOT_INSTRUMENTS:
        swap = SPOT_TO_SWAP[spot]
        close = market.spot_close[spot]
        trend = float(close[signal_index] / close[signal_index - trend_intervals] - 1.0)
        price_slice = close[signal_index - vol_count : signal_index + 1]
        if len(price_slice) != vol_count + 1:
            raise C5AReferenceError("realized-volatility price count mismatch")
        log_returns = np.diff(np.log(price_slice))
        if len(log_returns) != vol_count or not np.isfinite(log_returns).all():
            raise C5AReferenceError("realized-volatility return count mismatch")
        volatility = float(np.std(log_returns, ddof=1) * math.sqrt(ANNUAL_4H_BARS))
        if not math.isfinite(volatility) or volatility <= 0:
            raise C5AReferenceError(f"invalid realized volatility: {spot}")

        start = signal_index - crowding_bars + 1
        stop = signal_index + 1
        spot_closes = close[start:stop]
        mark_closes = market.mark_close[swap][start:stop]
        spot_volume = market.spot_quote_volume[spot][start:stop]
        swap_volume = market.swap_quote_volume[swap][start:stop]
        if not all(len(values) == crowding_bars for values in (spot_closes, mark_closes, spot_volume, swap_volume)):
            raise C5AReferenceError("crowding-window count mismatch")
        basis_values = mark_closes / spot_closes - 1.0
        basis = float(np.median(basis_values))
        denominator = float(np.sum(spot_volume))
        if denominator <= 0:
            raise C5AReferenceError(f"zero spot quote-volume denominator: {spot}")
        participation = float(np.sum(swap_volume) / denominator)
        if not math.isfinite(basis) or not math.isfinite(participation) or participation < 0:
            raise C5AReferenceError(f"invalid crowding feature: {spot}")
        output[spot] = {
            "trend_28d": trend,
            "rv_28d": volatility,
            "basis_7d": basis,
            "participation_7d": participation,
        }
    return output


def build_calibration(
    market: C5AMarket,
    config: Mapping[str, Any],
) -> dict[str, Any]:
    validate_config(config)
    observations = {
        spot: {"basis_7d": [], "participation_7d": []}
        for spot in SPOT_INSTRUMENTS
    }
    rows: list[dict[str, Any]] = []
    for execution_time in calibration_decision_times(config):
        index = _index_of(market, execution_time)
        features = _raw_features(market, execution_index=index, config=config)
        for spot in SPOT_INSTRUMENTS:
            observations[spot]["basis_7d"].append(features[spot]["basis_7d"])
            observations[spot]["participation_7d"].append(features[spot]["participation_7d"])
            rows.append(
                {
                    "execution_time": execution_time.isoformat(),
                    "instrument": spot,
                    "basis_7d": features[spot]["basis_7d"],
                    "participation_7d": features[spot]["participation_7d"],
                }
            )
    if len(rows) != 117:
        raise C5AReferenceError("calibration row count mismatch")
    for spot in SPOT_INSTRUMENTS:
        if any(len(observations[spot][field]) != 39 for field in observations[spot]):
            raise C5AReferenceError("calibration vector count mismatch")
    hashes = {
        spot: {
            field: canonical_sha256(values)
            for field, values in observations[spot].items()
        }
        for spot in SPOT_INSTRUMENTS
    }
    return {
        "schema_version": 1,
        "stage": "C5A",
        "status": "PASS",
        "observations": observations,
        "rows": rows,
        "hashes": hashes,
        "observation_count_per_asset_field": 39,
        "confirmation_opened": False,
        "holdout_state": "HOLDOUT_CLOSED",
        "live": "FORBIDDEN",
    }


def _ecdf_percentile(values: Sequence[float], x: float) -> float:
    if len(values) != 39:
        raise C5AReferenceError("ECDF calibration count mismatch")
    return sum(float(value) <= x for value in values) / 39.0
