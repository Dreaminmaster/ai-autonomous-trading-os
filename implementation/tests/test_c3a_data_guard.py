from __future__ import annotations

from datetime import UTC, datetime, timedelta
import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/c3a_data_guard.py"


def load_module():
    spec = importlib.util.spec_from_file_location("c3a_data_guard_test", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def complete_rows() -> list[dict[str, object]]:
    start = datetime(2023, 9, 1, tzinfo=UTC)
    end = datetime(2024, 9, 30, 20, tzinfo=UTC)
    rows = []
    current = start
    value = 100.0
    while current <= end:
        rows.append({"date": current, "open": value, "high": value, "low": value, "close": value, "volume": 1.0})
        current += timedelta(hours=4)
        value += 0.01
    return rows


def test_complete_four_hour_coverage_passes_and_has_startup() -> None:
    module = load_module()
    result = module.validate_rows(complete_rows(), "BTC/USDT", 450)
    assert result["status"] == "PASS"
    assert result["timeframe"] == "4h"
    assert result["startup_bars"] >= 450
    assert result["latest"] == "2024-09-30T20:00:00+00:00"
    assert result["duplicates"] == 0
    assert result["gaps"] == 0


def test_duplicate_timestamp_fails_closed() -> None:
    module = load_module()
    rows = complete_rows()
    rows.insert(10, dict(rows[10]))
    with pytest.raises(module.C3ADataGuardError, match="duplicate"):
        module.validate_rows(rows, "ETH/USDT", 450)


def test_missing_timestamp_fails_closed() -> None:
    module = load_module()
    rows = complete_rows()
    del rows[500]
    with pytest.raises(module.C3ADataGuardError, match="coverage|gap"):
        module.validate_rows(rows, "SOL/USDT", 450)


def test_post_boundary_latest_fails_closed() -> None:
    module = load_module()
    rows = complete_rows()
    rows.append(
        {
            "date": datetime(2024, 10, 1, tzinfo=UTC),
            "open": 100.0,
            "high": 100.0,
            "low": 100.0,
            "close": 100.0,
            "volume": 1.0,
        }
    )
    with pytest.raises(module.C3ADataGuardError, match="latest"):
        module.validate_rows(rows, "BTC/USDT", 450)


def test_misaligned_timestamp_lists_are_not_equal() -> None:
    module = load_module()
    left = module.validate_rows(complete_rows(), "BTC/USDT", 450)["timestamps"]
    rows = complete_rows()
    rows[100]["date"] = rows[100]["date"] + timedelta(hours=1)
    with pytest.raises(module.C3ADataGuardError):
        module.validate_rows(rows, "ETH/USDT", 450)
    assert len(left) > 0
