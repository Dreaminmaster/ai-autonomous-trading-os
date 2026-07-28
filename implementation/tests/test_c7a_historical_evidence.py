from __future__ import annotations

import hashlib
import math
from datetime import UTC, datetime, timedelta

import pytest

from atos.c7a_contract import INSTRUMENTS
from atos.c7a_historical_capture import (
    CapturePackage,
    CaptureRecord,
    h1_h5_capture_plan,
)
from atos.c7a_historical_evidence import (
    C7AHistoricalEvidenceError,
    build_h1_h5_evidence_package,
)
from atos.c7a_okx_public_data import build_mark_price_request

BTC, ETH = INSTRUMENTS
SHA = "b" * 40
HOUR = timedelta(hours=1)


def _binding() -> dict:
    return {
        "schema_version": 1,
        "stage": "C7A_HISTORICAL_CHECKOUT_BINDING",
        "implementation_sha": SHA,
        "observed_head_sha": SHA,
        "tracked_worktree_clean": True,
    }


def _stamp(value: str) -> datetime:
    return datetime.fromisoformat(value)


def _capture(tmp_path):
    plan = h1_h5_capture_plan()
    package = CapturePackage(tmp_path / "capture")
    package.write_json("checkout_binding.json", _binding())
    request = build_mark_price_request(BTC, after_ms=1_704_067_200_000)
    raw = b'{"code":"0","data":[]}'
    package.retain_raw(
        raw,
        CaptureRecord(
            request_id=request.request_id,
            source_family=request.source_family,
            requested_url=request.url,
            final_url=request.url,
            collected_at="2026-07-29T00:00:00Z",
            media_type="application/json",
            size=len(raw),
            sha256=hashlib.sha256(raw).hexdigest(),
            relative_path="",
        ),
    )

    mark_start = _stamp(plan["mark_start_inclusive"])
    scored_end = _stamp(plan["scored_end_exclusive"])
    trade_start = _stamp(plan["trade_start_inclusive"])
    trade_end = _stamp(plan["trade_end_exclusive"])
    marks = {instrument: [] for instrument in INSTRUMENTS}
    prices = {BTC: 40_000.0, ETH: 2_000.0}
    current = mark_start
    index = 0
    while current < scored_end:
        common_return = 0.0002 * math.sin(index / 19) + 0.0001 * math.cos(index / 13)
        for instrument in INSTRUMENTS:
            prices[instrument] *= math.exp(common_return)
            marks[instrument].append(
                {"timestamp": current.isoformat(), "close": prices[instrument]}
            )
        current += HOUR
        index += 1

    mark_lookup = {
        instrument: {row["timestamp"]: row["close"] for row in marks[instrument]}
        for instrument in INSTRUMENTS
    }
    trades = {instrument: [] for instrument in INSTRUMENTS}
    current = trade_start
    while current < trade_end:
        source = min(current, scored_end - HOUR).isoformat()
        for instrument in INSTRUMENTS:
            value = mark_lookup[instrument][source]
            trades[instrument].append(
                {"timestamp": current.isoformat(), "open": value, "close": value}
            )
        current += HOUR

    funding = {instrument: [] for instrument in INSTRUMENTS}
    current = _stamp(plan["funding_start_inclusive"])
    while current < scored_end:
        funding[BTC].append(
            {"funding_time": current.isoformat(), "realized_rate": "0.0004"}
        )
        funding[ETH].append(
            {"funding_time": current.isoformat(), "realized_rate": "0.00005"}
        )
        current += timedelta(hours=8)

    for instrument in INSTRUMENTS:
        package.retain_normalized_series(
            series_type="marks",
            instrument=instrument,
            start_inclusive=plan["mark_start_inclusive"],
            end_exclusive=plan["scored_end_exclusive"],
            rows=marks[instrument],
        )
        package.retain_normalized_series(
            series_type="trades",
            instrument=instrument,
            start_inclusive=plan["trade_start_inclusive"],
            end_exclusive=plan["trade_end_exclusive"],
            rows=trades[instrument],
        )
        package.retain_normalized_series(
            series_type="funding",
            instrument=instrument,
            start_inclusive=plan["funding_start_inclusive"],
            end_exclusive=plan["scored_end_exclusive"],
            rows=funding[instrument],
        )
    package.finalize(implementation_sha=SHA, capture_plan=plan)
    return package.root


def test_h1_h5_evidence_package_is_immutable_independent_and_classified(
    tmp_path,
) -> None:
    capture_root = _capture(tmp_path)
    final, manifest = build_h1_h5_evidence_package(
        tmp_path / "evidence",
        capture_root=capture_root,
        implementation_sha=SHA,
        authoritative_run_id="fixture-h1-h5-v1",
        evaluation_checkout_binding=_binding(),
        evaluated_at=datetime(2026, 7, 29, tzinfo=UTC),
    )
    assert final["classification"] == "ECONOMIC_FAIL"
    assert final["independent_recompute_passed"] is True
    assert final["shadow_eligible"] is False
    assert manifest["file_count"] == 14
    assert (tmp_path / "evidence" / "pooled_summary.json").is_file()
    assert (tmp_path / "evidence" / "manifest.json").is_file()

    with pytest.raises(C7AHistoricalEvidenceError, match="already exists"):
        build_h1_h5_evidence_package(
            tmp_path / "evidence",
            capture_root=capture_root,
            implementation_sha=SHA,
            authoritative_run_id="fixture-h1-h5-v1",
            evaluation_checkout_binding=_binding(),
        )


def test_capture_hash_tamper_fails_before_economics(tmp_path) -> None:
    capture_root = _capture(tmp_path)
    path = capture_root / "normalized" / "funding" / f"{BTC}.json"
    path.write_bytes(path.read_bytes() + b" ")
    with pytest.raises(C7AHistoricalEvidenceError, match="capture hash mismatch"):
        build_h1_h5_evidence_package(
            tmp_path / "tampered-evidence",
            capture_root=capture_root,
            implementation_sha=SHA,
            authoritative_run_id="tamper-must-fail",
            evaluation_checkout_binding=_binding(),
        )


def test_capture_symlink_fails_before_any_research_read(tmp_path) -> None:
    capture_root = _capture(tmp_path)
    (capture_root / "unexpected-link").symlink_to(capture_root / "capture_index.json")
    with pytest.raises(C7AHistoricalEvidenceError, match="symbolic link"):
        build_h1_h5_evidence_package(
            tmp_path / "symlink-evidence",
            capture_root=capture_root,
            implementation_sha=SHA,
            authoritative_run_id="symlink-must-fail",
            evaluation_checkout_binding=_binding(),
        )
