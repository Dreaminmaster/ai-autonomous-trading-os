"""Frozen C6A contract and public-input guards.

This module contains no exchange-account, private-API, order, paper, shadow, or
live path.  It validates only preregistered configuration and primitive public
research inputs.
"""
from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping, Sequence

SPOT_INSTRUMENTS = ("BTC-USDT", "ETH-USDT")
SWAP_INSTRUMENTS = ("BTC-USDT-SWAP", "ETH-USDT-SWAP")
SPOT_TO_SWAP = dict(zip(SPOT_INSTRUMENTS, SWAP_INSTRUMENTS, strict=True))
CANDIDATE_ID = "C6AMarketNeutralFundingCarry"
COMPARATORS = (
    "CashComparator",
    "AlwaysOnDeltaNeutralComparator",
    "SpotBuyAndHoldComparator",
)
EXPECTED_CONFIG_CANONICAL_SHA256 = (
    "06187fc36110dd7bf867bcd6928f7fff3826204dd6ee9de8e848542452a8f852"
)
REQUIRED_DESIGN_MAIN_SHA = "071e45218e299367f3bef18832d931df7d278ace"
ECONOMIC_BOUNDARY = datetime(2025, 12, 29, tzinfo=UTC)
LOOKBACK = timedelta(days=28)
ONE_HOUR = timedelta(hours=1)


class C6AError(RuntimeError):
    """Raised when a frozen C6A invariant fails closed."""


def canonical_sha256(payload: Any) -> str:
    encoded = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _epoch_timestamp(raw: float, original: Any) -> datetime:
    if not math.isfinite(raw):
        raise C6AError(f"invalid timestamp: {original!r}")
    try:
        return datetime.fromtimestamp(
            raw / (1000 if abs(raw) > 10_000_000_000 else 1), tz=UTC
        )
    except (OverflowError, OSError, ValueError) as exc:
        raise C6AError(f"invalid timestamp: {original!r}") from exc


def parse_timestamp(value: Any) -> datetime:
    if isinstance(value, datetime):
        result = value
    elif isinstance(value, str) and value.strip():
        text = value.strip()
        try:
            numeric = float(text)
        except ValueError:
            try:
                result = datetime.fromisoformat(text.replace("Z", "+00:00"))
            except ValueError as exc:
                raise C6AError(f"invalid timestamp: {value!r}") from exc
        else:
            result = _epoch_timestamp(numeric, value)
    elif isinstance(value, (int, float)) and not isinstance(value, bool):
        result = _epoch_timestamp(float(value), value)
    else:
        raise C6AError(f"invalid timestamp: {value!r}")
    return result.replace(tzinfo=UTC) if result.tzinfo is None else result.astimezone(UTC)


def decimal_value(value: Any, label: str) -> Decimal:
    if value is None or isinstance(value, bool):
        raise C6AError(f"{label} must be decimal")
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise C6AError(f"{label} must be decimal") from exc
    if not result.is_finite():
        raise C6AError(f"{label} must be finite")
    return result


def validate_config(config: Mapping[str, Any]) -> None:
    if canonical_sha256(config) != EXPECTED_CONFIG_CANONICAL_SHA256:
        raise C6AError("C6A semantic configuration drift")
    if config.get("schema_version") != 1 or config.get("stage") != "C6A":
        raise C6AError("C6A identity drift")
    if config.get("status") != "IMPLEMENTATION_PENDING":
        raise C6AError("C6A implementation-state drift")
    if config.get("required_design_main_sha") != REQUIRED_DESIGN_MAIN_SHA:
        raise C6AError("C6A design-main drift")
    if tuple(config.get("spot_instruments", ())) != SPOT_INSTRUMENTS:
        raise C6AError("C6A spot-instrument drift")
    if tuple(config.get("swap_instruments", ())) != SWAP_INSTRUMENTS:
        raise C6AError("C6A swap-instrument drift")
    if config.get("candidate_id") != CANDIDATE_ID:
        raise C6AError("C6A candidate identity drift")
    if tuple(config.get("comparators", ())) != COMPARATORS:
        raise C6AError("C6A comparator drift")
    if config.get("timeframe") != "1H":
        raise C6AError("C6A timeframe drift")
    if parse_timestamp(config.get("economic_boundary_exclusive")) != ECONOMIC_BOUNDARY:
        raise C6AError("C6A economic boundary drift")
    windows = config.get("windows")
    if not isinstance(windows, list) or len(windows) != 5:
        raise C6AError("C6A must contain five windows")
    previous_end: datetime | None = None
    for index, window in enumerate(windows, start=1):
        if not isinstance(window, Mapping) or window.get("id") != f"W{index}":
            raise C6AError("C6A window identity drift")
        start = parse_timestamp(window.get("start"))
        end = parse_timestamp(window.get("end"))
        if start.weekday() != 0 or start.hour != 0 or start.minute != 0:
            raise C6AError("C6A window start must be Monday 00:00 UTC")
        if end.weekday() != 0 or end.hour != 0 or end.minute != 0:
            raise C6AError("C6A window end must be Monday 00:00 UTC")
        if end - start != timedelta(weeks=26):
            raise C6AError("C6A window must contain exactly 26 weeks")
        if previous_end is not None and start != previous_end:
            raise C6AError("C6A windows must be contiguous without state carry")
        previous_end = end
    if previous_end != ECONOMIC_BOUNDARY:
        raise C6AError("C6A final window boundary drift")
    if config.get("confirmation_opened") is not False:
        raise C6AError("C6B must remain closed")
    if (
        config.get("c5b_state") != "C5B_CLOSED_AND_UNTOUCHED"
        or config.get("holdout_state") != "HOLDOUT_CLOSED"
        or config.get("paper_state") != "PAPER_CLOSED"
        or config.get("shadow_state") != "SHADOW_CLOSED"
        or config.get("live") != "FORBIDDEN"
    ):
        raise C6AError("C6A safety-state drift")


def decision_times(window: Mapping[str, Any]) -> tuple[datetime, ...]:
    start = parse_timestamp(window["start"])
    end = parse_timestamp(window["end"])
    values = tuple(start + timedelta(weeks=index) for index in range(26))
    if len(values) != 26 or values[-1] != end - timedelta(weeks=1):
        raise C6AError("C6A decision-grid mismatch")
    return values


def terminal_time(window: Mapping[str, Any]) -> datetime:
    result = parse_timestamp(window["end"]) - ONE_HOUR
    if result.weekday() != 6 or result.hour != 23 or result.minute != 0:
        raise C6AError("C6A terminal timestamp must be Sunday 23:00 UTC")
    return result


@dataclass(frozen=True)
class FundingRecord:
    instrument: str
    funding_time: datetime
    realized_rate: Decimal

    @classmethod
    def from_mapping(cls, row: Mapping[str, Any]) -> "FundingRecord":
        instrument = str(row.get("instrument", row.get("instId", "")))
        if instrument not in SWAP_INSTRUMENTS:
            raise C6AError(f"unexpected funding instrument: {instrument!r}")
        return cls(
            instrument=instrument,
            funding_time=parse_timestamp(row.get("funding_time", row.get("fundingTime"))),
            realized_rate=decimal_value(
                row.get("realized_rate", row.get("realizedRate")), "realized funding rate"
            ),
        )


def validate_funding_records(
    rows: Sequence[Mapping[str, Any] | FundingRecord],
    *,
    boundary_exclusive: datetime = ECONOMIC_BOUNDARY,
) -> tuple[FundingRecord, ...]:
    records = tuple(
        row if isinstance(row, FundingRecord) else FundingRecord.from_mapping(row)
        for row in rows
    )
    if not records:
        raise C6AError("empty funding history")
    keys = tuple((row.instrument, row.funding_time) for row in records)
    if keys != tuple(sorted(keys)) or len(set(keys)) != len(keys):
        raise C6AError("funding history must be ordered and unique by instrument/time")
    for row in records:
        if row.funding_time >= boundary_exclusive:
            raise C6AError("funding record reaches closed economic boundary")
    for instrument in SWAP_INSTRUMENTS:
        times = [row.funding_time for row in records if row.instrument == instrument]
        if not times:
            raise C6AError(f"missing funding instrument: {instrument}")
        if any(new <= old for old, new in zip(times, times[1:])):
            raise C6AError(f"non-increasing funding timestamps: {instrument}")
    return records


@dataclass(frozen=True)
class MetadataRecord:
    instrument: str
    instrument_type: str
    base_currency: str
    quote_currency: str
    settlement_currency: str
    contract_value: Decimal | None
    contract_value_currency: str | None
    lot_size: Decimal
    minimum_size: Decimal
    tick_size: Decimal
    effective_from: datetime
    effective_to: datetime | None
    source: str
    source_sha256: str

    @classmethod
    def from_mapping(cls, row: Mapping[str, Any]) -> "MetadataRecord":
        instrument = str(row.get("instrument", row.get("instId", "")))
        if instrument not in (*SPOT_INSTRUMENTS, *SWAP_INSTRUMENTS):
            raise C6AError(f"unexpected metadata instrument: {instrument!r}")
        instrument_type = str(row.get("instrument_type", row.get("instType", ""))).upper()
        if instrument_type not in {"SPOT", "SWAP"}:
            raise C6AError("metadata instrument type must be SPOT or SWAP")
        contract_raw = row.get("contract_value", row.get("ctVal"))
        contract_value = (
            None if contract_raw in (None, "") else decimal_value(contract_raw, "contract value")
        )
        effective_to_raw = row.get("effective_to")
        effective_to = None if effective_to_raw in (None, "") else parse_timestamp(effective_to_raw)
        result = cls(
            instrument=instrument,
            instrument_type=instrument_type,
            base_currency=str(row.get("base_currency", row.get("baseCcy", ""))),
            quote_currency=str(row.get("quote_currency", row.get("quoteCcy", ""))),
            settlement_currency=str(row.get("settlement_currency", row.get("settleCcy", ""))),
            contract_value=contract_value,
            contract_value_currency=(
                None
                if row.get("contract_value_currency", row.get("ctValCcy")) in (None, "")
                else str(row.get("contract_value_currency", row.get("ctValCcy")))
            ),
            lot_size=decimal_value(row.get("lot_size", row.get("lotSz")), "lot size"),
            minimum_size=decimal_value(row.get("minimum_size", row.get("minSz")), "minimum size"),
            tick_size=decimal_value(row.get("tick_size", row.get("tickSz")), "tick size"),
            effective_from=parse_timestamp(row.get("effective_from")),
            effective_to=effective_to,
            source=str(row.get("source", "")),
            source_sha256=str(row.get("source_sha256", "")),
        )
        result.validate()
        return result

    def validate(self) -> None:
        if self.lot_size <= 0 or self.minimum_size <= 0 or self.tick_size <= 0:
            raise C6AError("metadata sizes must be positive")
        if self.effective_to is not None and self.effective_to <= self.effective_from:
            raise C6AError("metadata effective interval must be positive")
        if len(self.source_sha256) != 64 or any(
            character not in "0123456789abcdef" for character in self.source_sha256
        ):
            raise C6AError("metadata source SHA-256 is invalid")
        if not self.source:
            raise C6AError("metadata public source is required")
        if self.instrument_type == "SWAP":
            base = self.instrument.split("-")[0]
            if (
                self.contract_value is None
                or self.contract_value <= 0
                or self.contract_value_currency != base
                or self.settlement_currency != "USDT"
            ):
                raise C6AError("swap metadata must provide base-denominated linear contract value")
        elif self.contract_value is not None:
            raise C6AError("spot metadata must not define a contract value")

    def covers(self, timestamp: datetime) -> bool:
        value = parse_timestamp(timestamp)
        return self.effective_from <= value and (
            self.effective_to is None or value < self.effective_to
        )


def metadata_at(
    records: Sequence[MetadataRecord], instrument: str, timestamp: datetime
) -> MetadataRecord:
    matches = [row for row in records if row.instrument == instrument and row.covers(timestamp)]
    if len(matches) != 1:
        raise C6AError(
            f"expected exactly one effective metadata record for {instrument} at "
            f"{parse_timestamp(timestamp).isoformat()}, found {len(matches)}"
        )
    return matches[0]


def funding_signal(
    records: Sequence[FundingRecord],
    *,
    instrument: str,
    decision_time: datetime,
) -> dict[str, Decimal | int]:
    decision = parse_timestamp(decision_time)
    start = decision - LOOKBACK
    selected = [
        row
        for row in records
        if row.instrument == instrument and start <= row.funding_time < decision
    ]
    if not selected:
        raise C6AError(f"no actual funding settlements in lookback: {instrument}")
    total = sum((row.realized_rate for row in selected), Decimal("0"))
    positive = sum(row.realized_rate > 0 for row in selected)
    share = Decimal(positive) / Decimal(len(selected))
    return {
        "settlement_count": len(selected),
        "positive_settlement_count": positive,
        "funding_sum_28d": total,
        "positive_funding_share_28d": share,
    }


def candidate_eligible(
    signal: Mapping[str, Any], *, basis: Any, config: Mapping[str, Any]
) -> bool:
    return (
        decimal_value(signal["funding_sum_28d"], "funding sum")
        > decimal_value(config["minimum_funding_sum_28d_exclusive"], "funding threshold")
        and decimal_value(signal["positive_funding_share_28d"], "positive funding share")
        >= decimal_value(config["minimum_positive_funding_share"], "share threshold")
        and abs(decimal_value(basis, "basis"))
        <= decimal_value(config["maximum_entry_abs_basis"], "entry basis limit")
    )


def risk_exit_required(
    *, basis: Any, collateral_buffer_ratio: Any, config: Mapping[str, Any]
) -> bool:
    return (
        abs(decimal_value(basis, "basis"))
        > decimal_value(config["maximum_risk_abs_basis"], "risk basis limit")
        or decimal_value(collateral_buffer_ratio, "collateral buffer")
        < decimal_value(config["minimum_collateral_buffer_ratio"], "buffer limit")
    )
