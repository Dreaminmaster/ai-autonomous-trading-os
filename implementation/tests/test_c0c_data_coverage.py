from __future__ import annotations

import importlib.util
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "implementation" / "scripts" / "verify_c0c_data_coverage.py"
SPEC = importlib.util.spec_from_file_location("verify_c0c_data_coverage", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
coverage = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(coverage)


def _rows(start: datetime, end: datetime, step: timedelta) -> list[dict[str, str]]:
    result: list[dict[str, str]] = []
    current = start
    while current <= end:
        result.append({"date": current.isoformat()})
        current += step
    return result


def _contract_rows() -> tuple[list[dict[str, str]], datetime, datetime]:
    first_fold = datetime(2024, 1, 1, tzinfo=UTC)
    holdout = datetime(2024, 1, 3, tzinfo=UTC)
    rows = _rows(
        first_fold - timedelta(hours=2),
        holdout - timedelta(hours=1),
        timedelta(hours=1),
    )
    return rows, first_fold, holdout


def test_contiguous_pre_holdout_coverage_passes() -> None:
    rows, first_fold, holdout = _contract_rows()
    result = coverage.validate_rows(
        rows,
        pair="BTC/USDT",
        timeframe="1h",
        first_fold_start=first_fold,
        holdout_start=holdout,
        startup_candles=2,
    )
    assert result["status"] == "PASS"
    assert result["duplicates"] == 0
    assert result["gaps"] == 0
    assert result["required_rows"] == len(rows)
    assert result["latest"] == "2024-01-02T23:00:00+00:00"


def test_gap_fails_closed() -> None:
    rows, first_fold, holdout = _contract_rows()
    rows.pop(3)
    with pytest.raises(coverage.C0CDataCoverageError, match="required rows|candle gap"):
        coverage.validate_rows(
            rows,
            pair="ETH/USDT",
            timeframe="1h",
            first_fold_start=first_fold,
            holdout_start=holdout,
            startup_candles=2,
        )


def test_duplicate_fails_closed() -> None:
    rows, first_fold, holdout = _contract_rows()
    rows.append(dict(rows[0]))
    with pytest.raises(coverage.C0CDataCoverageError, match="duplicate candles"):
        coverage.validate_rows(
            rows,
            pair="SOL/USDT",
            timeframe="1h",
            first_fold_start=first_fold,
            holdout_start=holdout,
            startup_candles=2,
        )


def test_holdout_overlap_fails_closed() -> None:
    rows, first_fold, holdout = _contract_rows()
    rows.append({"date": holdout.isoformat()})
    with pytest.raises(coverage.C0CDataCoverageError, match="contains holdout candle"):
        coverage.validate_rows(
            rows,
            pair="BTC/USDT",
            timeframe="1h",
            first_fold_start=first_fold,
            holdout_start=holdout,
            startup_candles=2,
        )
