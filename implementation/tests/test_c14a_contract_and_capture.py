from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from atos.c7a_historical_capture import C7AHistoricalCaptureError, CaptureRecord
from atos.c7a_okx_public_data import (
    C7APublicDataError,
    PublicRequest,
    build_trade_candle_request,
)
from atos.c14a_contract import (
    CANDIDATE_POOL,
    COMPARATORS,
    EXPECTED_TOTAL_DECISIONS,
    HISTORICAL_WINDOWS,
    capture_plan,
    decision_times,
    safety_boundary,
    validate_contract,
)
from atos.c14a_historical_capture import (
    C14ACapturePackage,
    C14AHistoricalCaptureError,
    capture_trade_range,
    validate_c14a_public_request,
)

SHA = "a" * 40


def _record(request: PublicRequest, raw: bytes) -> CaptureRecord:
    return CaptureRecord(
        request_id=request.request_id,
        source_family=request.source_family,
        requested_url=request.url,
        final_url=request.url,
        collected_at="2026-08-26T00:00:00Z",
        media_type="application/json",
        size=len(raw),
        sha256=hashlib.sha256(raw).hexdigest(),
        relative_path="",
    )


def _complete_package(root: Path) -> C14ACapturePackage:
    package = C14ACapturePackage(root)
    package.write_json(
        "checkout_binding.json",
        {
            "schema_version": 1,
            "stage": "C14A_HISTORICAL_CHECKOUT_BINDING",
            "implementation_sha": SHA,
            "observed_head_sha": SHA,
            "tracked_worktree_clean": True,
        },
    )
    request = build_trade_candle_request(
        CANDIDATE_POOL[0], after_ms=1_704_067_200_000, allowed_instruments=CANDIDATE_POOL
    )
    raw = b'{"code":"0","data":[]}'
    package.retain_raw(raw, _record(request, raw))
    plan = capture_plan()
    for instrument in CANDIDATE_POOL:
        package.retain_c14a_series(
            series_type="trades",
            instrument=instrument,
            start_inclusive=str(plan["trade_start_inclusive"]),
            end_exclusive=str(plan["trade_end_exclusive"]),
            rows=({"timestamp": plan["trade_start_inclusive"], "open": "1"},),
        )
        package.retain_c14a_series(
            series_type="marks",
            instrument=instrument,
            start_inclusive=str(plan["mark_start_inclusive"]),
            end_exclusive=str(plan["mark_end_exclusive"]),
            rows=({"timestamp": plan["mark_start_inclusive"], "close": "1"},),
        )
        package.retain_c14a_series(
            series_type="funding",
            instrument=instrument,
            start_inclusive=str(plan["funding_start_inclusive"]),
            end_exclusive=str(plan["funding_end_exclusive"]),
            rows=(
                {"funding_time": plan["funding_start_inclusive"], "realized_rate": "0"},
            ),
        )
    return package


def test_contract_freezes_exact_universe_clocks_comparators_and_safety() -> None:
    report = validate_contract()
    plan = capture_plan()
    assert report["familywise_trial_count"] == 629
    assert CANDIDATE_POOL == (
        "BTC-USDT-SWAP",
        "ETH-USDT-SWAP",
        "SOL-USDT-SWAP",
        "BCH-USDT-SWAP",
        "DOGE-USDT-SWAP",
        "XRP-USDT-SWAP",
        "LTC-USDT-SWAP",
        "LINK-USDT-SWAP",
    )
    assert COMPARATORS == (
        "CashComparator",
        "MeanAbsoluteReturnRankComparator",
        "InverseQuoteVolumeRankComparator",
    )
    assert plan["trade_start_inclusive"] == "2023-12-03T00:00:00Z"
    assert plan["trade_end_exclusive"] == "2026-06-29T01:00:00Z"
    assert plan["mark_start_inclusive"] == "2023-12-31T23:00:00Z"
    assert sum(len(decision_times(window)) for window in HISTORICAL_WINDOWS) == (
        EXPECTED_TOTAL_DECISIONS
    )
    assert safety_boundary()["authenticated"] is False
    assert safety_boundary()["paper_state"] == "PAPER_CLOSED"
    assert safety_boundary()["shadow_state"] == "SHADOW_CLOSED"
    assert safety_boundary()["live_state"] == "LIVE_FORBIDDEN"


def test_public_request_policy_rejects_credentials_private_paths_and_other_assets() -> None:
    request = build_trade_candle_request(
        "SOL-USDT-SWAP",
        after_ms=1_704_067_200_000,
        allowed_instruments=CANDIDATE_POOL,
    )
    validate_c14a_public_request(request)
    with pytest.raises(C7APublicDataError):
        validate_c14a_public_request(
            PublicRequest(
                "credential",
                "OKX_HISTORY_CANDLES_API",
                request.url + "&apiKey=forbidden",
            )
        )
    with pytest.raises(C7APublicDataError):
        validate_c14a_public_request(
            PublicRequest(
                "private",
                "OKX_HISTORY_CANDLES_API",
                "https://www.okx.com/api/v5/account/balance?instId=SOL-USDT-SWAP",
            )
        )
    with pytest.raises(C7APublicDataError):
        validate_c14a_public_request(
            PublicRequest(
                "other",
                "OKX_HISTORY_CANDLES_API",
                request.url.replace("SOL-USDT-SWAP", "ADA-USDT-SWAP"),
            )
        )


def test_trade_capture_retains_raw_before_strict_exact_normalization(tmp_path: Path) -> None:
    package = C14ACapturePackage(tmp_path / "capture")
    start = datetime(2024, 1, 1, tzinfo=UTC)

    def fetch(request: PublicRequest) -> tuple[bytes, CaptureRecord]:
        raw = json.dumps(
            {
                "code": "0",
                "msg": "",
                "data": [[str(int(start.timestamp() * 1000)), "100", "101", "99", "100.5", "1", "1", "100", "1"]],
            }
        ).encode()
        return raw, _record(request, raw)

    rows = capture_trade_range(
        package,
        series_type="trades",
        instrument="BTC-USDT-SWAP",
        start_inclusive="2024-01-01T00:00:00Z",
        end_exclusive="2024-01-01T01:00:00Z",
        fetch_page=fetch,
        page_pause_seconds=0,
    )
    assert rows[0]["confirm"] == "1"
    assert rows[0]["volume_quote"] == "100"
    raw_path = next((tmp_path / "capture/raw").rglob("*.bin"))
    assert package.records[0].sha256 == hashlib.sha256(raw_path.read_bytes()).hexdigest()


def test_trade_capture_rejects_zero_quote_volume_before_retention_as_series(
    tmp_path: Path,
) -> None:
    package = C14ACapturePackage(tmp_path / "capture")

    def fetch(request: PublicRequest) -> tuple[bytes, CaptureRecord]:
        raw = json.dumps(
            {
                "code": "0",
                "msg": "",
                "data": [
                    [
                        "1704067200000",
                        "100",
                        "101",
                        "99",
                        "100.5",
                        "1",
                        "1",
                        "0",
                        "1",
                    ]
                ],
            }
        ).encode()
        return raw, _record(request, raw)

    with pytest.raises(C14AHistoricalCaptureError, match="quote volume"):
        capture_trade_range(
            package,
            series_type="trades",
            instrument="BTC-USDT-SWAP",
            start_inclusive="2024-01-01T00:00:00Z",
            end_exclusive="2024-01-01T01:00:00Z",
            fetch_page=fetch,
            page_pause_seconds=0,
        )


def test_trade_capture_rejects_unconfirmed_candle(tmp_path: Path) -> None:
    package = C14ACapturePackage(tmp_path / "capture")

    def fetch(request: PublicRequest) -> tuple[bytes, CaptureRecord]:
        raw = json.dumps(
            {"code": "0", "msg": "", "data": [["1704067200000", "1", "1", "1", "1", "1", "1", "1", "0"]]}
        ).encode()
        return raw, _record(request, raw)

    with pytest.raises(C14AHistoricalCaptureError):
        capture_trade_range(
            package,
            series_type="trades",
            instrument="BTC-USDT-SWAP",
            start_inclusive="2024-01-01T00:00:00Z",
            end_exclusive="2024-01-01T01:00:00Z",
            fetch_page=fetch,
            page_pause_seconds=0,
        )


def test_capture_package_has_fixed_universe_and_recursive_hash_manifest(tmp_path: Path) -> None:
    package = _complete_package(tmp_path / "capture")
    assert package.selected_universe == CANDIDATE_POOL
    manifest = package.finalize(implementation_sha=SHA, capture_plan_value=capture_plan())
    assert manifest["stage"] == "C14A_HISTORICAL_CAPTURE_PACKAGE"
    assert manifest["real_public_data"] is True
    assert manifest["economic_result"] is False
    assert manifest["file_count"] == len(manifest["files"])
    for row in manifest["files"]:
        data = (tmp_path / "capture" / row["path"]).read_bytes()
        assert len(data) == row["size"]
        assert hashlib.sha256(data).hexdigest() == row["sha256"]


def test_capture_package_fails_closed_on_missing_series_overwrite_and_escape(tmp_path: Path) -> None:
    incomplete = C14ACapturePackage(tmp_path / "incomplete")
    with pytest.raises(C14AHistoricalCaptureError, match="records or fixed universe"):
        incomplete.finalize(implementation_sha=SHA, capture_plan_value=capture_plan())
    package = C14ACapturePackage(tmp_path / "guarded")
    package.write_json("safe.json", {"ok": True})
    with pytest.raises(C7AHistoricalCaptureError):
        package.write_json("safe.json", {"ok": False})
    with pytest.raises(C7AHistoricalCaptureError):
        package.write_json("../escape.json", {"bad": True})


def test_package_rejects_formation_series_and_nonfixed_instrument(tmp_path: Path) -> None:
    package = C14ACapturePackage(tmp_path / "capture")
    for series_type, instrument in (
        ("formation_trades", CANDIDATE_POOL[0]),
        ("trades", "ADA-USDT-SWAP"),
    ):
        with pytest.raises(C14AHistoricalCaptureError, match="outside frozen phase"):
            package.retain_c14a_series(
                series_type=series_type,
                instrument=instrument,
                start_inclusive="2024-01-01T00:00:00Z",
                end_exclusive="2024-01-01T01:00:00Z",
                rows=({"timestamp": "2024-01-01T00:00:00Z", "open": "1"},),
            )
