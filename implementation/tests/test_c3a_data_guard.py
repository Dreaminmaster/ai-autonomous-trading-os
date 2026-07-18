from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from scripts.c3a_data_guard import C3ADataGuardError, validate_rows


FIRST_REQUIRED = datetime(2024, 1, 1, tzinfo=UTC) - timedelta(hours=4) * 450
LAST_REQUIRED = datetime(2024, 10, 1, tzinfo=UTC) - timedelta(hours=4)


def rows(*, missing_index: int | None = None, duplicate_index: int | None = None) -> list[dict]:
    result: list[dict] = []
    current = datetime(2023, 9, 1, tzinfo=UTC)
    index = 0
    while current <= LAST_REQUIRED:
        if index != missing_index:
            result.append({"date": current.isoformat(), "open": 100.0, "close": 101.0})
        if index == duplicate_index:
            result.append({"date": current.isoformat(), "open": 100.0, "close": 101.0})
        current += timedelta(hours=4)
        index += 1
    return result


def test_validate_rows_proves_exact_four_hour_coverage() -> None:
    report = validate_rows(rows(), "BTC/USDT", 450)
    assert report["status"] == "PASS"
    assert report["required_earliest"] == FIRST_REQUIRED.isoformat()
    assert report["required_latest"] == LAST_REQUIRED.isoformat()
    assert report["duplicates"] == 0
    assert report["gaps"] == 0
    assert len(report["required_timestamp_sha256"]) == 64


def test_validate_rows_rejects_gap_inside_required_range() -> None:
    target = int((FIRST_REQUIRED - datetime(2023, 9, 1, tzinfo=UTC)) / timedelta(hours=4)) + 25
    with pytest.raises(C3ADataGuardError, match="coverage mismatch|gap"):
        validate_rows(rows(missing_index=target), "ETH/USDT", 450)


def test_validate_rows_rejects_duplicate() -> None:
    with pytest.raises(C3ADataGuardError, match="duplicate"):
        validate_rows(rows(duplicate_index=800), "SOL/USDT", 450)


def test_validate_rows_rejects_post_boundary_data() -> None:
    payload = rows()
    payload.append({"date": "2024-10-01T00:00:00+00:00", "open": 100.0, "close": 101.0})
    with pytest.raises(C3ADataGuardError, match="boundary"):
        validate_rows(payload, "BTC/USDT", 450)
