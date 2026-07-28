from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from atos.c7a_historical_schedule import (
    C7AHistoricalScheduleError,
    HISTORICAL_WINDOWS,
    HistoricalWindow,
    assert_official_public_metadata,
    decision_times,
    required_source_bounds,
    validate_historical_windows,
    window_by_id,
)


PUBLIC_METADATA = {
    "stage": "C7A_HISTORICAL_VALIDATION",
    "source_kind": "OFFICIAL_PUBLIC_OKX",
    "source_family": "OKX_FUNDING_RATE_HISTORY_API",
    "authenticated": False,
    "contains_account_data": False,
    "contains_order_data": False,
    "private_api": False,
    "paper_side_effect": False,
    "live_state": "LIVE_FORBIDDEN",
    "collected_at": "2026-07-28T00:00:00Z",
}


def test_five_fixed_windows_are_contiguous_non_overlapping_and_26_weeks() -> None:
    validate_historical_windows()
    assert [window.window_id for window in HISTORICAL_WINDOWS] == [
        "H1",
        "H2",
        "H3",
        "H4",
        "H5",
    ]
    for index, window in enumerate(HISTORICAL_WINDOWS):
        values = decision_times(window)
        assert len(values) == 26
        assert all(value.weekday() == 0 for value in values)
        assert all(value.hour == 0 and value.minute == 0 for value in values)
        assert values[-1] + timedelta(days=7) == window.end_exclusive
        if index:
            assert window.first_scored_decision == HISTORICAL_WINDOWS[index - 1].end_exclusive


def test_required_source_bounds_include_exact_first_lookbacks() -> None:
    bounds = required_source_bounds("H1")
    assert bounds == {
        "window_id": "H1",
        "funding_start_inclusive": "2023-12-04T00:00:00Z",
        "mark_start_inclusive": "2023-12-03T23:00:00Z",
        "scored_start_inclusive": "2024-01-01T00:00:00Z",
        "scored_end_exclusive": "2024-07-01T00:00:00Z",
    }


def test_last_historical_window_ends_before_prospective_confirmation() -> None:
    assert HISTORICAL_WINDOWS[-1].end_exclusive == datetime(2026, 6, 29, tzinfo=UTC)
    assert HISTORICAL_WINDOWS[-1].end_exclusive < datetime(2026, 8, 24, tzinfo=UTC)


def test_window_lookup_is_exact_and_fail_closed() -> None:
    assert window_by_id("H3") == HISTORICAL_WINDOWS[2]
    with pytest.raises(C7AHistoricalScheduleError, match="unknown historical window"):
        window_by_id("h3")


def test_malformed_window_grid_is_rejected() -> None:
    malformed = HistoricalWindow(
        "BAD",
        datetime(2024, 1, 2, tzinfo=UTC),
        datetime(2024, 7, 2, tzinfo=UTC),
    )
    with pytest.raises(C7AHistoricalScheduleError, match="Monday"):
        decision_times(malformed)


def test_official_public_metadata_is_accepted() -> None:
    assert_official_public_metadata(PUBLIC_METADATA)


@pytest.mark.parametrize(
    "field,value",
    [
        ("authenticated", True),
        ("contains_account_data", True),
        ("contains_order_data", True),
        ("private_api", True),
        ("paper_side_effect", True),
        ("live_state", "LIVE"),
        ("source_kind", "USER_ACCOUNT"),
    ],
)
def test_private_or_side_effect_metadata_is_rejected(field: str, value: object) -> None:
    metadata = dict(PUBLIC_METADATA)
    metadata[field] = value
    with pytest.raises(C7AHistoricalScheduleError, match="boundary violation"):
        assert_official_public_metadata(metadata)


def test_unapproved_source_family_is_rejected() -> None:
    metadata = dict(PUBLIC_METADATA)
    metadata["source_family"] = "THIRD_PARTY_MIRROR"
    with pytest.raises(C7AHistoricalScheduleError, match="unapproved"):
        assert_official_public_metadata(metadata)


def test_naive_collection_timestamp_is_rejected() -> None:
    metadata = dict(PUBLIC_METADATA)
    metadata["collected_at"] = "2026-07-28T00:00:00"
    with pytest.raises(C7AHistoricalScheduleError, match="timezone-aware"):
        assert_official_public_metadata(metadata)
