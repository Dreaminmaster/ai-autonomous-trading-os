from __future__ import annotations

import importlib.util
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "implementation" / "scripts" / "c1a_data_guard.py"
SPEC = importlib.util.spec_from_file_location("c1a_data_guard_test_module", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def _rows(start: datetime, end: datetime, step: timedelta) -> list[dict[str, object]]:
    result = []
    current = start
    value = 100.0
    while current <= end:
        result.append(
            {
                "date": current,
                "open": value,
                "high": value + 1,
                "low": value - 1,
                "close": value,
                "volume": 1.0,
            }
        )
        current += step
        value += 0.01
    return result


def test_config_and_frozen_boundary_are_exact() -> None:
    config = MODULE._load_config()
    assert config["download_timerange"] == "20230701-20241001"
    assert config["coverage_history_candles"] == {"1h": 1499, "1d": 120}
    assert MODULE.BOUNDARY == datetime(2024, 10, 1, tzinfo=UTC)
    assert "BEFORE_ANY_RESEARCH_READ" in MODULE.POLICY


def test_hourly_and_daily_required_ranges_pass_without_gaps() -> None:
    first = datetime(2024, 1, 1, tzinfo=UTC)
    hourly_step = timedelta(hours=1)
    hourly = _rows(
        first - hourly_step * 1499,
        MODULE.BOUNDARY - hourly_step,
        hourly_step,
    )
    hourly_report = MODULE.validate_rows(
        hourly,
        pair="BTC/USDT",
        timeframe="1h",
        history_candles=1499,
    )
    assert hourly_report["status"] == "PASS"
    assert hourly_report["duplicates"] == 0
    assert hourly_report["gaps"] == 0

    daily_step = timedelta(days=1)
    daily = _rows(first - daily_step * 120, MODULE.BOUNDARY - daily_step, daily_step)
    daily_report = MODULE.validate_rows(
        daily,
        pair="BTC/USDT",
        timeframe="1d",
        history_candles=120,
    )
    assert daily_report["status"] == "PASS"
    assert daily_report["required_latest"] == "2024-09-30T00:00:00+00:00"


def test_duplicate_gap_and_post_boundary_data_fail_closed() -> None:
    first = datetime(2024, 1, 1, tzinfo=UTC)
    step = timedelta(days=1)
    rows = _rows(first - step * 120, MODULE.BOUNDARY - step, step)

    duplicate = rows + [dict(rows[-1])]
    with pytest.raises(MODULE.C1ADataGuardError, match="duplicate"):
        MODULE.validate_rows(
            duplicate,
            pair="ETH/USDT",
            timeframe="1d",
            history_candles=120,
        )

    missing = rows[:20] + rows[21:]
    with pytest.raises(MODULE.C1ADataGuardError, match="required rows|gap"):
        MODULE.validate_rows(
            missing,
            pair="ETH/USDT",
            timeframe="1d",
            history_candles=120,
        )

    future = rows + [
        {
            "date": MODULE.BOUNDARY,
            "open": 1.0,
            "high": 1.0,
            "low": 1.0,
            "close": 1.0,
            "volume": 1.0,
        }
    ]
    with pytest.raises(MODULE.C1ADataGuardError, match="post-boundary"):
        MODULE.validate_rows(
            future,
            pair="ETH/USDT",
            timeframe="1d",
            history_candles=120,
        )


def test_boundary_report_requires_exact_source_and_six_sealed_cells() -> None:
    source = "a" * 40
    cells = [
        {
            "pair": pair,
            "timeframe": timeframe,
            "status": "PASS",
            "post_boundary_rows": 0,
            "retained_latest": (
                "2024-09-30T23:00:00+00:00" if timeframe == "1h" else "2024-09-30T00:00:00+00:00"
            ),
        }
        for pair in ("BTC/USDT", "ETH/USDT", "SOL/USDT")
        for timeframe in ("1h", "1d")
    ]
    payload = {
        "status": "PASS",
        "source_head_sha": source,
        "economic_boundary_exclusive": "2024-10-01T00:00:00+00:00",
        "holdout_state": "HOLDOUT_CLOSED",
        "live": "FORBIDDEN",
        "policy": MODULE.POLICY,
        "cells": cells,
    }
    MODULE.validate_boundary_report(payload, source)
    payload["source_head_sha"] = "b" * 40
    with pytest.raises(MODULE.C1ADataGuardError, match="source SHA"):
        MODULE.validate_boundary_report(payload, source)
