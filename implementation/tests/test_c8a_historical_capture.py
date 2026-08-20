from __future__ import annotations

import hashlib
import inspect
from pathlib import Path

import pytest

from atos.c7a_historical_capture import C7AHistoricalCaptureError, CaptureRecord
from atos.c7a_okx_public_data import build_mark_price_request
from atos.c8a_contract import INSTRUMENTS
from atos.c8a_historical_capture import (
    FUNDING_REQUEST_PAUSE_SECONDS,
    C8ACapturePackage,
    C8AHistoricalCaptureError,
    _assert_complete_funding_interval,
    capture_funding_downloads,
    capture_historical_funding_range,
)
from atos.c8a_historical_evidence import (
    C8AEvidencePackage,
    C8AHistoricalEvidenceError,
    verify_capture_package,
)
from atos.c8a_historical_run_guard import (
    C8AHistoricalRunGuardError,
    validate_checkout_binding,
    verify_checkout_binding,
)
from atos.c8a_historical_schedule import h1_h5_capture_plan

SHA = "c" * 40


def _record(raw: bytes) -> CaptureRecord:
    request = build_mark_price_request(INSTRUMENTS[0], after_ms=1_704_067_200_000)
    return CaptureRecord(
        request_id=request.request_id,
        source_family=request.source_family,
        requested_url=request.url,
        final_url=request.url,
        collected_at="2026-07-29T00:00:00Z",
        media_type="application/json",
        size=len(raw),
        sha256=hashlib.sha256(raw).hexdigest(),
        relative_path="",
    )


def test_c8a_capture_plan_locks_corrected_warmup_and_terminal_events() -> None:
    assert h1_h5_capture_plan() == {
        "window_ids": ["H1", "H2", "H3", "H4", "H5"],
        "instruments": list(INSTRUMENTS),
        "mark_start_inclusive": "2023-12-24T22:00:00Z",
        "mark_end_exclusive": "2026-06-29T00:00:00Z",
        "trade_start_inclusive": "2024-01-01T00:00:00Z",
        "trade_end_exclusive": "2026-06-29T01:00:00Z",
        "funding_start_inclusive": "2024-01-01T00:00:00Z",
        "funding_end_exclusive": "2026-06-29T01:00:00Z",
        "scored_start_inclusive": "2024-01-01T00:00:00Z",
        "scored_end_exclusive": "2026-06-29T00:00:00Z",
    }


def test_c8a_capture_package_has_stage_specific_immutable_manifest(
    tmp_path: Path,
) -> None:
    package = C8ACapturePackage(tmp_path / "capture")
    raw = b'{"code":"0","data":[]}'
    package.retain_raw(raw, _record(raw))
    plan = h1_h5_capture_plan()
    package.write_json(
        "checkout_binding.json",
        {
            "schema_version": 1,
            "stage": "C8A_HISTORICAL_CHECKOUT_BINDING",
            "implementation_sha": SHA,
            "observed_head_sha": SHA,
            "tracked_worktree_clean": True,
        },
    )
    for instrument in INSTRUMENTS:
        package.retain_normalized_series(
            series_type="marks",
            instrument=instrument,
            start_inclusive=str(plan["mark_start_inclusive"]),
            end_exclusive=str(plan["mark_end_exclusive"]),
            rows=({"timestamp": plan["mark_start_inclusive"], "close": "1"},),
        )
        package.retain_normalized_series(
            series_type="trades",
            instrument=instrument,
            start_inclusive=str(plan["trade_start_inclusive"]),
            end_exclusive=str(plan["trade_end_exclusive"]),
            rows=({"timestamp": plan["trade_start_inclusive"], "open": "1"},),
        )
        package.retain_normalized_series(
            series_type="funding",
            instrument=instrument,
            start_inclusive=str(plan["funding_start_inclusive"]),
            end_exclusive=str(plan["funding_end_exclusive"]),
            rows=(
                {"funding_time": plan["funding_start_inclusive"], "realized_rate": "0"},
            ),
        )
    manifest = package.finalize(implementation_sha=SHA, capture_plan=plan)
    assert manifest["stage"] == "C8A_HISTORICAL_CAPTURE_PACKAGE"
    assert manifest["authenticated"] is False
    assert manifest["live_state"] == "LIVE_FORBIDDEN"
    verified = verify_capture_package(tmp_path / "capture", implementation_sha=SHA)
    assert verified["capture_file_count"] == manifest["file_count"]
    with pytest.raises(C7AHistoricalCaptureError, match="finalized"):
        package.write_json("late.json", {})


def test_c8a_capture_rejects_plan_drift(tmp_path: Path) -> None:
    package = C8ACapturePackage(tmp_path / "capture")
    raw = b'{"code":"0","data":[]}'
    package.retain_raw(raw, _record(raw))
    plan = h1_h5_capture_plan()
    plan["mark_start_inclusive"] = "2023-12-25T00:00:00Z"
    with pytest.raises(C8AHistoricalCaptureError, match="frozen"):
        package.finalize(implementation_sha=SHA, capture_plan=plan)


def test_c8a_funding_coverage_allows_real_nonboundary_settlement_times() -> None:
    _assert_complete_funding_interval(
        (
            {"funding_time": "2024-01-01T01:00:00Z"},
            {"funding_time": "2024-01-01T09:00:00Z"},
        ),
        instrument=INSTRUMENTS[0],
        start_inclusive="2024-01-01T00:00:00Z",
        end_exclusive="2024-01-01T10:00:00Z",
    )


def test_c8a_funding_requests_use_rate_limit_headroom() -> None:
    assert FUNDING_REQUEST_PAUSE_SECONDS == 0.5
    assert (
        inspect.signature(capture_historical_funding_range)
        .parameters["request_pause_seconds"]
        .default
        == FUNDING_REQUEST_PAUSE_SECONDS
    )
    assert (
        inspect.signature(capture_funding_downloads)
        .parameters["download_pause_seconds"]
        .default
        == FUNDING_REQUEST_PAUSE_SECONDS
    )


def test_c8a_checkout_binding_requires_exact_clean_sha(tmp_path: Path) -> None:
    expected = {
        "schema_version": 1,
        "stage": "C8A_HISTORICAL_CHECKOUT_BINDING",
        "implementation_sha": SHA,
        "observed_head_sha": SHA,
        "tracked_worktree_clean": True,
    }
    assert validate_checkout_binding(expected, implementation_sha=SHA) == expected

    class Result:
        def __init__(self, stdout: str):
            self.stdout = stdout

    outputs = iter((Result(SHA + "\n"), Result("")))
    assert (
        verify_checkout_binding(
            SHA,
            repository_root=tmp_path,
            runner=lambda *_args, **_kwargs: next(outputs),
        )
        == expected
    )
    with pytest.raises(C8AHistoricalRunGuardError):
        validate_checkout_binding(
            {**expected, "tracked_worktree_clean": False}, implementation_sha=SHA
        )


def test_c8a_evidence_writer_is_atomic_manifested_and_no_overwrite(
    tmp_path: Path,
) -> None:
    package = C8AEvidencePackage(tmp_path / "evidence")
    package.write_json(
        "result.json", {"status": "FAIL", "live_state": "LIVE_FORBIDDEN"}
    )
    with pytest.raises(C8AHistoricalEvidenceError, match="already exists"):
        package.write_json("result.json", {})
    manifest = package.finalize(implementation_sha=SHA)
    assert manifest["stage"] == "C8A_H1_H5_HISTORICAL_EVIDENCE_PACKAGE"
    assert manifest["file_count"] == 1
    with pytest.raises(C8AHistoricalEvidenceError, match="finalized"):
        package.write_json("late.json", {})
