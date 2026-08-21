"""Frozen C9A continuous-notional historical research contract."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation, localcontext
from pathlib import Path
from typing import Any

SPOT_INSTRUMENTS = ("BTC-USDT", "ETH-USDT")
SWAP_INSTRUMENTS = ("BTC-USDT-SWAP", "ETH-USDT-SWAP")
SPOT_TO_SWAP = dict(zip(SPOT_INSTRUMENTS, SWAP_INSTRUMENTS, strict=True))
ALL_TRADE_INSTRUMENTS = (*SPOT_INSTRUMENTS, *SWAP_INSTRUMENTS)
CANDIDATE_ID = "C9AContinuousNotionalFundingCarry"
POLICIES = ("candidate", "always_on", "cash", "spot_buy_and_hold")
COST_RATES = {
    "1.0x": Decimal("0.0015"),
    "1.5x": Decimal("0.00225"),
    "2.0x": Decimal("0.0030"),
}
STARTING_EQUITY = Decimal(1000)
FUNDING_LOOKBACK = timedelta(days=28)
MINIMUM_FUNDING_SUM = Decimal("0.009")
MINIMUM_POSITIVE_SHARE = Decimal("0.6666666666666666666666666667")
MAXIMUM_ENTRY_ABS_BASIS = Decimal("0.02")
MAXIMUM_RISK_ABS_BASIS = Decimal("0.05")
MINIMUM_COLLATERAL_BUFFER = Decimal("1.25")
SPOT_CAPITAL_FRACTION = Decimal("0.3333333333333333333333333333")
COLLATERAL_CAPITAL_FRACTION = Decimal("0.6666666666666666666666666667")
RESIZING_BAND = Decimal("0.10")
RECONCILIATION_TOLERANCE = Decimal("1e-10")
SOLVER_ITERATIONS = 160
EXPECTED_DECISIONS_PER_WINDOW = 26
EXPECTED_TOTAL_DECISIONS = 130
HOUR = timedelta(hours=1)
WEEK = timedelta(days=7)
HISTORICAL_DATA_STATUS = "HISTORICAL_DEVELOPMENT_ONLY"
LIVE_STATE = "LIVE_FORBIDDEN"
PAPER_STATE = "PAPER_CLOSED"
SHADOW_STATE = "SHADOW_CLOSED"
FROZEN_GATES = {
    "minimum_annualized_weekly_sharpe": "1.00",
    "minimum_weekly_psr": "0.95",
    "maximum_drawdown": "0.10",
    "maximum_annualized_one_way_turnover": "6.0",
    "minimum_funding_cost_coverage": "2.0",
    "minimum_active_weeks_total": 52,
    "minimum_active_weeks_per_window": 6,
    "minimum_active_funding_settlements": 100,
    "maximum_positive_asset_pnl_share": "0.70",
    "maximum_positive_window_pnl_share": "0.40",
    "maximum_positive_week_pnl_share": "0.15",
    "maximum_top_three_positive_week_pnl_share": "0.35",
    "minimum_sharpe_delta_vs_always_on": "0.10",
}


class C9AError(RuntimeError):
    """Raised whenever a frozen C9A invariant cannot be proven."""


def decimal_value(value: Any, label: str, *, positive: bool = False) -> Decimal:
    if value is None or isinstance(value, bool):
        raise C9AError(f"{label} must be a finite decimal")
    try:
        with localcontext() as context:
            context.prec = 60
            result = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise C9AError(f"{label} must be a finite decimal") from exc
    if not result.is_finite() or (positive and result <= 0):
        raise C9AError(f"{label} must be {'positive' if positive else 'finite'}")
    return result


def parse_time(value: Any) -> datetime:
    if isinstance(value, datetime):
        result = value
    elif isinstance(value, str):
        try:
            result = datetime.fromisoformat(value)
        except ValueError as exc:
            raise C9AError(f"invalid timestamp: {value!r}") from exc
    else:
        raise C9AError(f"invalid timestamp: {value!r}")
    if result.tzinfo is None:
        raise C9AError("timestamp must be timezone-aware")
    return result.astimezone(UTC)


def iso(value: datetime) -> str:
    return parse_time(value).isoformat().replace("+00:00", "Z")


def load_frozen_config(repository_root: Path) -> dict[str, Any]:
    path = (
        Path(repository_root)
        / "implementation"
        / "config"
        / "c9a_continuous_notional_funding_carry.json"
    )
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise C9AError("unable to read frozen C9A configuration") from exc
    if not isinstance(value, dict):
        raise C9AError("frozen C9A configuration must be an object")
    validate_config(value)
    return value


def validate_config(value: dict[str, Any]) -> None:
    expected = {
        "schema_version": 1,
        "stage": "C9A",
        "candidate_id": CANDIDATE_ID,
        "spot_instruments": list(SPOT_INSTRUMENTS),
        "swap_instruments": list(SWAP_INSTRUMENTS),
        "funding_warmup_start": "2023-06-05T00:00:00Z",
        "price_custody_start": "2023-07-02T22:00:00Z",
        "scored_start": "2023-07-03T00:00:00Z",
        "scored_end_exclusive": "2025-12-29T00:00:00Z",
        "funding_lookback_days": 28,
        "minimum_funding_sum_28d_exclusive": str(MINIMUM_FUNDING_SUM),
        "minimum_positive_funding_share": str(MINIMUM_POSITIVE_SHARE),
        "maximum_entry_abs_basis": str(MAXIMUM_ENTRY_ABS_BASIS),
        "maximum_risk_abs_basis": str(MAXIMUM_RISK_ABS_BASIS),
        "minimum_collateral_buffer_ratio": str(MINIMUM_COLLATERAL_BUFFER),
        "starting_equity": str(STARTING_EQUITY),
        "spot_capital_fraction": str(SPOT_CAPITAL_FRACTION),
        "collateral_capital_fraction": str(COLLATERAL_CAPITAL_FRACTION),
        "resizing_band": str(RESIZING_BAND),
        "solver_iterations": SOLVER_ITERATIONS,
        "historical_data_status": HISTORICAL_DATA_STATUS,
        "execution_feasibility_established": False,
        "paper_state": PAPER_STATE,
        "shadow_state": SHADOW_STATE,
        "live_state": LIVE_STATE,
    }
    if set(value) != {
        *expected,
        "comparators",
        "reconciliation_tolerance",
        "cost_rates",
        "gates",
    }:
        raise C9AError("frozen C9A configuration key-set drift")
    for key, expected_value in expected.items():
        if value.get(key) != expected_value:
            raise C9AError(f"frozen C9A configuration drift: {key}")
    if (
        decimal_value(value.get("reconciliation_tolerance"), "reconciliation tolerance")
        != RECONCILIATION_TOLERANCE
    ):
        raise C9AError("frozen C9A configuration drift: reconciliation_tolerance")
    if value.get("cost_rates") != {key: str(raw) for key, raw in COST_RATES.items()}:
        raise C9AError("frozen C9A cost-rate drift")
    if value.get("gates") != FROZEN_GATES:
        raise C9AError("frozen C9A gate drift")
    if value.get("comparators") != [
        "CashComparator",
        "AlwaysOnContinuousDeltaNeutralComparator",
        "SpotBuyAndHoldComparator",
    ]:
        raise C9AError("frozen C9A comparator drift")


def safety_boundary() -> dict[str, Any]:
    return {
        "authenticated": False,
        "contains_account_data": False,
        "contains_order_data": False,
        "private_api": False,
        "paper_side_effect": False,
        "shadow_side_effect": False,
        "execution_feasibility_established": False,
        "paper_state": PAPER_STATE,
        "shadow_state": SHADOW_STATE,
        "live_state": LIVE_STATE,
    }
