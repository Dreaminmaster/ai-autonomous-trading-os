"""Frozen C14A cross-sectional Amihud liquidity-risk research contract."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from atos.c14a_research_program_guard import (
    EXPECTED_FAMILYWISE_TRIALS,
    verify_repository_authority,
)

CANDIDATE_POOL = (
    "BTC-USDT-SWAP",
    "ETH-USDT-SWAP",
    "SOL-USDT-SWAP",
    "BCH-USDT-SWAP",
    "DOGE-USDT-SWAP",
    "XRP-USDT-SWAP",
    "LTC-USDT-SWAP",
    "LINK-USDT-SWAP",
)
COMPARATORS = (
    "CashComparator",
    "MeanAbsoluteReturnRankComparator",
    "InverseQuoteVolumeRankComparator",
)
CANDIDATE_ID = "C14ACrossSectionalAmihudLiquidityRisk"
BTC_BETA_BENCHMARK = "BTC-USDT-SWAP"

HOUR = timedelta(hours=1)
WEEK = timedelta(days=7)
TRADE_CAPTURE_START = datetime(2023, 12, 3, tzinfo=UTC)
MARK_WARMUP_START = datetime(2023, 12, 31, 23, tzinfo=UTC)
SCORED_START = datetime(2024, 1, 1, tzinfo=UTC)
SCORED_END_EXCLUSIVE = datetime(2026, 6, 29, tzinfo=UTC)

SELECTED_UNIVERSE_SIZE = 8
SIGNAL_LOOKBACK_COMPLETE_DAYS = 28
SIGNAL_EXECUTION_LAG_HOURS = 24
LONG_COUNT = 2
SHORT_COUNT = 2
GROSS_NOTIONAL = Decimal("0.50")
LONG_GROSS_NOTIONAL = Decimal("0.25")
SHORT_GROSS_NOTIONAL = Decimal("0.25")
PER_POSITION_ABS_NOTIONAL = Decimal("0.125")
STARTING_EQUITY = Decimal(1000)
MINIMUM_EQUITY_TO_GROSS_NOTIONAL = Decimal("1.25")
RECONCILIATION_TOLERANCE = Decimal("1e-10")
COST_RATES = {
    "1.0x": Decimal("0.0015"),
    "1.5x": Decimal("0.00225"),
    "2.0x": Decimal("0.0030"),
}
EXPECTED_DECISIONS_PER_WINDOW = 26
EXPECTED_TOTAL_DECISIONS = 130
EXPECTED_NONFLAT_DIRECTIONS = 520


class C14AContractError(RuntimeError):
    """Raised when a frozen C14A identity or time boundary drifts."""


def iso(value: datetime) -> str:
    if value.tzinfo is None:
        raise C14AContractError("C14A timestamp must be timezone-aware")
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True)
class HistoricalWindow:
    window_id: str
    start: datetime
    end_exclusive: datetime

    def to_dict(self) -> dict[str, str]:
        row = asdict(self)
        return {
            "window_id": str(row["window_id"]),
            "start": iso(row["start"]),
            "end_exclusive": iso(row["end_exclusive"]),
        }


HISTORICAL_WINDOWS = (
    HistoricalWindow(
        "H1", datetime(2024, 1, 1, tzinfo=UTC), datetime(2024, 7, 1, tzinfo=UTC)
    ),
    HistoricalWindow(
        "H2", datetime(2024, 7, 1, tzinfo=UTC), datetime(2024, 12, 30, tzinfo=UTC)
    ),
    HistoricalWindow(
        "H3", datetime(2024, 12, 30, tzinfo=UTC), datetime(2025, 6, 30, tzinfo=UTC)
    ),
    HistoricalWindow(
        "H4", datetime(2025, 6, 30, tzinfo=UTC), datetime(2025, 12, 29, tzinfo=UTC)
    ),
    HistoricalWindow(
        "H5", datetime(2025, 12, 29, tzinfo=UTC), datetime(2026, 6, 29, tzinfo=UTC)
    ),
)


def window_by_id(window_id: str) -> HistoricalWindow:
    matches = [window for window in HISTORICAL_WINDOWS if window.window_id == window_id]
    if len(matches) != 1:
        raise C14AContractError(f"unknown C14A window: {window_id!r}")
    return matches[0]


def decision_times(window: HistoricalWindow | str) -> tuple[datetime, ...]:
    selected = window_by_id(window) if isinstance(window, str) else window
    output: list[datetime] = []
    current = selected.start
    while current < selected.end_exclusive:
        if current.weekday() != 0 or any(
            (current.hour, current.minute, current.second, current.microsecond)
        ):
            raise C14AContractError("C14A decision must be Monday 00:00 UTC")
        output.append(current)
        current += WEEK
    if len(output) != EXPECTED_DECISIONS_PER_WINDOW or current != selected.end_exclusive:
        raise C14AContractError("each C14A window must contain exactly 26 weeks")
    return tuple(output)


def capture_plan() -> dict[str, Any]:
    """Return the exact fixed-universe public-custody boundaries."""

    return {
        "window_ids": [window.window_id for window in HISTORICAL_WINDOWS],
        "instruments": list(CANDIDATE_POOL),
        "selected_universe_size": SELECTED_UNIVERSE_SIZE,
        "btc_beta_benchmark_instrument": BTC_BETA_BENCHMARK,
        "trade_start_inclusive": iso(TRADE_CAPTURE_START),
        "trade_end_exclusive": iso(SCORED_END_EXCLUSIVE + HOUR),
        "mark_start_inclusive": iso(MARK_WARMUP_START),
        "mark_end_exclusive": iso(SCORED_END_EXCLUSIVE),
        "funding_start_inclusive": iso(SCORED_START),
        "funding_end_exclusive": iso(SCORED_END_EXCLUSIVE),
        "scored_start_inclusive": iso(SCORED_START),
        "scored_end_exclusive": iso(SCORED_END_EXCLUSIVE),
    }


def safety_boundary() -> dict[str, Any]:
    return {
        "historical_data_status": "HISTORICAL_DEVELOPMENT_ONLY",
        "execution_feasibility_established": False,
        "authenticated": False,
        "contains_account_data": False,
        "contains_order_data": False,
        "paper_side_effect": False,
        "shadow_side_effect": False,
        "paper_state": "PAPER_CLOSED",
        "shadow_state": "SHADOW_CLOSED",
        "live_state": "LIVE_FORBIDDEN",
    }


def validate_contract() -> dict[str, Any]:
    report = verify_repository_authority()
    if report.get("familywise_trial_count") != EXPECTED_FAMILYWISE_TRIALS:
        raise C14AContractError("C14A program trial-count drift")
    previous = None
    decisions = 0
    for index, window in enumerate(HISTORICAL_WINDOWS, start=1):
        if window.window_id != f"H{index}" or (previous and window.start != previous):
            raise C14AContractError("C14A historical-window identity drift")
        decisions += len(decision_times(window))
        previous = window.end_exclusive
    if decisions != EXPECTED_TOTAL_DECISIONS:
        raise C14AContractError("C14A total decision-count drift")
    if (
        HISTORICAL_WINDOWS[0].start != SCORED_START
        or HISTORICAL_WINDOWS[-1].end_exclusive != SCORED_END_EXCLUSIVE
    ):
        raise C14AContractError("C14A scored boundary drift")
    return report


__all__ = [
    "BTC_BETA_BENCHMARK",
    "CANDIDATE_ID",
    "CANDIDATE_POOL",
    "COMPARATORS",
    "COST_RATES",
    "EXPECTED_DECISIONS_PER_WINDOW",
    "EXPECTED_NONFLAT_DIRECTIONS",
    "EXPECTED_TOTAL_DECISIONS",
    "GROSS_NOTIONAL",
    "HISTORICAL_WINDOWS",
    "HOUR",
    "LONG_COUNT",
    "LONG_GROSS_NOTIONAL",
    "MARK_WARMUP_START",
    "MINIMUM_EQUITY_TO_GROSS_NOTIONAL",
    "PER_POSITION_ABS_NOTIONAL",
    "RECONCILIATION_TOLERANCE",
    "SCORED_END_EXCLUSIVE",
    "SCORED_START",
    "SELECTED_UNIVERSE_SIZE",
    "SHORT_COUNT",
    "SHORT_GROSS_NOTIONAL",
    "SIGNAL_EXECUTION_LAG_HOURS",
    "SIGNAL_LOOKBACK_COMPLETE_DAYS",
    "STARTING_EQUITY",
    "TRADE_CAPTURE_START",
    "WEEK",
    "C14AContractError",
    "HistoricalWindow",
    "capture_plan",
    "decision_times",
    "iso",
    "safety_boundary",
    "validate_contract",
    "window_by_id",
]
