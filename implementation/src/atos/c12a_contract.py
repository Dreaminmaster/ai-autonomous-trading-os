"""Frozen C12A fixed-maturity basis-carry research contract."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from atos.c12a_research_program_guard import (
    C12A_CONFIG_PATH,
    verify_repository_authority,
)

CANDIDATE_ID = "C12AFixedMaturityBasisCarry"
ASSETS = ("BTC", "ETH")
SPOT_INSTRUMENTS = ("BTC-USDT", "ETH-USDT")
EXPECTED_COST = Decimal("0.00225")
COST_RATES = {
    "1.0x": Decimal("0.0015"),
    "1.5x": EXPECTED_COST,
    "2.0x": Decimal("0.0030"),
}
ENTRY_THRESHOLD = Decimal("0.0120")
TOLERANCE = Decimal("1e-10")
STARTING_EQUITY = Decimal(1000)
WEEK = timedelta(days=7)
HOUR = timedelta(hours=1)
EXECUTION_MAX_DELAY = timedelta(minutes=5)


class C12AError(RuntimeError):
    """Raised whenever a frozen C12A invariant cannot be proven."""


def decimal_value(value: Any, label: str, *, positive: bool = False) -> Decimal:
    if isinstance(value, bool):
        raise C12AError(f"{label} must be a finite decimal")
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise C12AError(f"{label} must be a finite decimal") from exc
    if not parsed.is_finite() or (positive and parsed <= 0):
        qualifier = "positive" if positive else "finite"
        raise C12AError(f"{label} must be {qualifier}")
    return parsed


def utc_timestamp(value: Any) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value))
    except ValueError as exc:
        raise C12AError(f"invalid timestamp: {value!r}") from exc
    if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
        raise C12AError("timestamp must be UTC")
    return parsed.astimezone(UTC)


def iso_z(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise C12AError("timestamp must be UTC")
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True)
class Window:
    window_id: str
    start: datetime
    end: datetime

    def __post_init__(self) -> None:
        if self.window_id not in {"H1", "H2", "H3", "H4", "H5"}:
            raise C12AError("unknown C12A window")
        if self.start >= self.end or self.start.weekday() != 0:
            raise C12AError("invalid C12A window bounds")
        if (self.end - self.start) != 26 * WEEK:
            raise C12AError("each C12A window must contain exactly 26 weeks")


@dataclass(frozen=True)
class ContractDecision:
    window_id: str
    asset: str
    spot_instrument: str
    futures_instrument: str
    expiry: datetime
    signal_cutoff: datetime
    entry_timestamp: datetime
    exit_timestamp: datetime

    def __post_init__(self) -> None:
        if self.asset not in ASSETS:
            raise C12AError("C12A asset drift")
        if self.spot_instrument != f"{self.asset}-USDT":
            raise C12AError("C12A spot identity drift")
        if not self.futures_instrument.startswith(f"{self.asset}-USDT-"):
            raise C12AError("C12A futures identity drift")
        if self.entry_timestamp != self.expiry - timedelta(days=28):
            raise C12AError("C12A entry clock drift")
        if self.signal_cutoff != self.entry_timestamp - HOUR:
            raise C12AError("C12A signal clock drift")
        if self.exit_timestamp != self.expiry - HOUR:
            raise C12AError("C12A exit clock drift")
        if any(
            stamp.minute or stamp.second or stamp.microsecond
            for stamp in (
                self.expiry,
                self.signal_cutoff,
                self.entry_timestamp,
                self.exit_timestamp,
            )
        ):
            raise C12AError("C12A clock is not hour-aligned")


WINDOWS = (
    Window("H1", utc_timestamp("2024-01-01T00:00:00Z"), utc_timestamp("2024-07-01T00:00:00Z")),
    Window("H2", utc_timestamp("2024-07-01T00:00:00Z"), utc_timestamp("2024-12-30T00:00:00Z")),
    Window("H3", utc_timestamp("2024-12-30T00:00:00Z"), utc_timestamp("2025-06-30T00:00:00Z")),
    Window("H4", utc_timestamp("2025-06-30T00:00:00Z"), utc_timestamp("2025-12-29T00:00:00Z")),
    Window("H5", utc_timestamp("2025-12-29T00:00:00Z"), utc_timestamp("2026-06-29T00:00:00Z")),
)


def _load_config(path: Path = C12A_CONFIG_PATH) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise C12AError("unable to read frozen C12A configuration") from exc
    if not isinstance(payload, dict):
        raise C12AError("frozen C12A configuration must be an object")
    return payload


def load_frozen_config(*, verify_authority: bool = True) -> dict[str, Any]:
    """Load C12A only after the repository design authorities pass."""

    if verify_authority:
        try:
            verify_repository_authority()
        except RuntimeError as exc:
            raise C12AError(str(exc)) from exc
    config = _load_config()
    if config.get("candidate_id") != CANDIDATE_ID:
        raise C12AError("frozen C12A candidate identity drift")
    return config


def contract_decisions(config: dict[str, Any] | None = None) -> tuple[ContractDecision, ...]:
    """Return the exact twenty decisions in chronological/asset order."""

    payload = config if config is not None else load_frozen_config()
    rows = payload.get("quarterly_contracts")
    if not isinstance(rows, list) or len(rows) != 10:
        raise C12AError("C12A requires exactly ten quarterly expiries")
    windows = {window.window_id: window for window in WINDOWS}
    output: list[ContractDecision] = []
    for row in rows:
        if not isinstance(row, dict):
            raise C12AError("C12A quarterly-contract row must be an object")
        expiry = utc_timestamp(row.get("expiry"))
        entry = expiry - timedelta(days=28)
        matches = [
            window for window in windows.values() if window.start <= entry < window.end
        ]
        if len(matches) != 1 or not (matches[0].start <= expiry < matches[0].end):
            raise C12AError("C12A contract is outside one frozen window")
        for asset, key in (("BTC", "btc"), ("ETH", "eth")):
            output.append(
                ContractDecision(
                    window_id=matches[0].window_id,
                    asset=asset,
                    spot_instrument=f"{asset}-USDT",
                    futures_instrument=str(row.get(key)),
                    expiry=expiry,
                    signal_cutoff=entry - HOUR,
                    entry_timestamp=entry,
                    exit_timestamp=expiry - HOUR,
                )
            )
    output.sort(key=lambda item: (item.entry_timestamp, item.asset))
    if len(output) != 20 or len({item.futures_instrument for item in output}) != 20:
        raise C12AError("C12A decision inventory drift")
    counts = {window.window_id: 0 for window in WINDOWS}
    for item in output:
        counts[item.window_id] += 1
    if set(counts.values()) != {4}:
        raise C12AError("each C12A window must contain four asset-contract decisions")
    return tuple(output)


def normalized_basis(*, futures_price: Any, spot_price: Any) -> Decimal:
    future = decimal_value(futures_price, "futures price", positive=True)
    spot = decimal_value(spot_price, "spot price", positive=True)
    value = (future - spot) / (future + spot)
    if not value.is_finite():
        raise C12AError("normalized basis is non-finite")
    return value


def should_enter(*, futures_price: Any, spot_price: Any) -> bool:
    return normalized_basis(futures_price=futures_price, spot_price=spot_price) > ENTRY_THRESHOLD


def base_quantity(
    *, sleeve_equity: Any, spot_entry: Any, futures_entry: Any, cost_rate: Any
) -> Decimal:
    sleeve = decimal_value(sleeve_equity, "sleeve equity", positive=True)
    spot = decimal_value(spot_entry, "spot entry", positive=True)
    future = decimal_value(futures_entry, "futures entry", positive=True)
    cost = decimal_value(cost_rate, "cost rate")
    if cost < 0:
        raise C12AError("cost rate must be non-negative")
    quantity = sleeve / ((spot + future) * (Decimal(1) + cost))
    if not quantity.is_finite() or quantity <= 0:
        raise C12AError("C12A base quantity is invalid")
    return quantity


def safety_boundary() -> dict[str, Any]:
    return {
        "authenticated": False,
        "contains_account_data": False,
        "contains_order_data": False,
        "paper_side_effect": False,
        "shadow_side_effect": False,
        "paper_state": "PAPER_CLOSED",
        "shadow_state": "SHADOW_CLOSED",
        "live_state": "LIVE_FORBIDDEN",
    }


def finite_float(value: Decimal, label: str) -> float:
    result = float(value)
    if not math.isfinite(result):
        raise C12AError(f"{label} is non-finite")
    return result


__all__ = [
    "ASSETS",
    "CANDIDATE_ID",
    "COST_RATES",
    "ENTRY_THRESHOLD",
    "EXECUTION_MAX_DELAY",
    "EXPECTED_COST",
    "SPOT_INSTRUMENTS",
    "STARTING_EQUITY",
    "TOLERANCE",
    "WINDOWS",
    "C12AError",
    "ContractDecision",
    "Window",
    "base_quantity",
    "contract_decisions",
    "decimal_value",
    "finite_float",
    "iso_z",
    "load_frozen_config",
    "normalized_basis",
    "safety_boundary",
    "should_enter",
    "utc_timestamp",
]
