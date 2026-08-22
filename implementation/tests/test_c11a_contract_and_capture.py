from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from atos.c7a_historical_capture import C7AHistoricalCaptureError, CaptureRecord
from atos.c7a_okx_public_data import (
    FUNDING_ARCHIVE_COLUMNS,
    C7APublicDataError,
    PublicRequest,
    build_mark_price_request,
    build_trade_candle_request,
    normalize_trade_candle_payload,
    validate_public_request,
)
from atos.c11a_contract import (
    BTC_BETA_BENCHMARK,
    CANDIDATE_POOL,
    EXPECTED_TOTAL_DECISIONS,
    FORMATION_END_EXCLUSIVE,
    FORMATION_START,
    HISTORICAL_WINDOWS,
    HOUR,
    capture_plan,
    decision_times,
    safety_boundary,
    validate_contract,
)
from atos.c11a_historical_capture import (
    C11ACapturePackage,
    C11AFundingDownloadSpec,
    C11AHistoricalCaptureError,
    capture_funding_downloads,
    capture_trade_range,
    select_formation_universe,
    validate_c11a_public_request,
)
from atos.c11a_historical_independent import (
    C11AHistoricalIndependentError,
    review_formation_universe,
)


def _ms(value: datetime) -> int:
    return int(value.timestamp() * 1000)


def _raw_payload(rows: list[list[str]]) -> bytes:
    return json.dumps({"code": "0", "msg": "", "data": rows}).encode()


def _trade_row(timestamp_ms: int, quote_volume: str = "100") -> list[str]:
    return [
        str(timestamp_ms),
        "100",
        "102",
        "99",
        "101",
        "999999",
        "888888",
        quote_volume,
        "1",
    ]


def _record(request: PublicRequest, raw: bytes, media_type: str = "application/json") -> CaptureRecord:
    return CaptureRecord(
        request_id=request.request_id,
        source_family=request.source_family,
        requested_url=request.url,
        final_url=request.url,
        collected_at="2026-08-21T00:00:00Z",
        media_type=media_type,
        size=len(raw),
        sha256=hashlib.sha256(raw).hexdigest(),
        relative_path="",
    )


def _formation() -> dict[str, tuple[dict[str, str], ...]]:
    timestamp = "2023-07-03T00:00:00Z"
    return {
        instrument: (
            {
                "timestamp": timestamp,
                "open": "1",
                "high": "1",
                "low": "1",
                "close": "1",
                "volume_contract": str(1000 - index),
                "volume_base": str(2000 - index),
                "volume_quote": str(index + 1),
                "confirm": "1",
            },
        )
        for index, instrument in enumerate(CANDIDATE_POOL)
    }


def test_c11a_contract_binds_program_history_clocks_and_safety() -> None:
    report = validate_contract()
    assert report["status"] == "PASS"
    assert report["familywise_trial_count"] == 627
    assert sum(len(decision_times(window)) for window in HISTORICAL_WINDOWS) == (
        EXPECTED_TOTAL_DECISIONS
    )
    assert capture_plan()["selected_universe_size"] == 8
    assert capture_plan()["mark_start_inclusive"] == "2023-12-03T22:00:00Z"
    assert capture_plan()["selected_trade_end_exclusive"] == "2026-06-29T01:00:00Z"
    assert safety_boundary() == {
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


def test_c11a_public_request_policy_is_explicit_and_account_free() -> None:
    request = build_trade_candle_request(
        "SOL-USDT-SWAP",
        after_ms=1_704_067_200_000,
        allowed_instruments=CANDIDATE_POOL,
    )
    validate_c11a_public_request(request)
    mark = build_mark_price_request(
        "TRX-USDT-SWAP",
        after_ms=1_704_067_200_000,
        allowed_instruments=CANDIDATE_POOL,
    )
    validate_c11a_public_request(mark)

    with pytest.raises(C7APublicDataError, match="unsupported public instrument"):
        build_trade_candle_request("SOL-USDT-SWAP", after_ms=1_704_067_200_000)
    with pytest.raises(C7APublicDataError, match="credential"):
        validate_c11a_public_request(
            PublicRequest(
                "bad",
                "OKX_HISTORY_CANDLES_API",
                "https://www.okx.com/api/v5/market/history-candles?"
                "instId=SOL-USDT-SWAP&bar=1H&limit=300&apikey=x",
            )
        )
    with pytest.raises(C7APublicDataError, match="private or account"):
        validate_c11a_public_request(
            PublicRequest(
                "private",
                "OKX_HISTORY_CANDLES_API",
                "https://www.okx.com/api/v5/account/balance?"
                "instId=SOL-USDT-SWAP&bar=1H&limit=300",
            )
        )
    with pytest.raises(C7APublicDataError, match="instrument policy"):
        validate_public_request(request, instruments=("SOL-USDT-SWAP",))


def test_derivative_liquidity_uses_official_quote_volume_field() -> None:
    payload = {
        "code": "0",
        "msg": "",
        "data": [_trade_row(1_704_067_200_000, "7.5")],
    }
    rows = normalize_trade_candle_payload(
        payload,
        instrument="SOL-USDT-SWAP",
        allowed_instruments=CANDIDATE_POOL,
    )
    assert rows[0]["volume_contract"] == "999999"
    assert rows[0]["volume_base"] == "888888"
    assert rows[0]["volume_quote"] == "7.5"

    formation = _formation()
    evidence = select_formation_universe(formation)
    expected = list(reversed(CANDIDATE_POOL[-8:]))
    assert evidence["liquidity_field"] == "volCcyQuote"
    assert evidence["selected_universe"] == expected
    assert [row["instrument"] for row in evidence["scores"][:8]] == expected


def test_formation_rejects_missing_misaligned_or_nonfinite_volume() -> None:
    missing = _formation()
    missing.pop(CANDIDATE_POOL[0])
    with pytest.raises(C11AHistoricalCaptureError, match="candidate-pool"):
        select_formation_universe(missing)

    misaligned = _formation()
    row = dict(misaligned[CANDIDATE_POOL[1]][0])
    row["timestamp"] = "2023-07-03T01:00:00Z"
    misaligned[CANDIDATE_POOL[1]] = (row,)
    with pytest.raises(C11AHistoricalCaptureError, match="misaligned"):
        select_formation_universe(misaligned)

    invalid = _formation()
    row = dict(invalid[CANDIDATE_POOL[2]][0])
    row["volume_quote"] = "NaN"
    invalid[CANDIDATE_POOL[2]] = (row,)
    with pytest.raises(C11AHistoricalCaptureError, match="finite"):
        select_formation_universe(invalid)


def test_independent_formation_recompute_requires_complete_fixed_clock() -> None:
    formation = {}
    for index, instrument in enumerate(CANDIDATE_POOL):
        rows = []
        current = FORMATION_START
        while current < FORMATION_END_EXCLUSIVE:
            rows.append(
                {
                    "timestamp": current.isoformat(),
                    "volume_quote": str(index + 1),
                }
            )
            current += HOUR
        formation[instrument] = rows
    retained = select_formation_universe(formation)
    review = review_formation_universe(retained, formation)
    assert review["status"] == "PASS"
    formation[CANDIDATE_POOL[0]].pop()
    with pytest.raises(C11AHistoricalIndependentError, match="formation clock"):
        review_formation_universe(retained, formation)


def test_trade_capture_persists_raw_before_exact_normalization(tmp_path: Path) -> None:
    package = C11ACapturePackage(tmp_path / "capture")
    start = datetime(2024, 1, 1, tzinfo=UTC)
    end = start + timedelta(hours=3)
    raw = _raw_payload(
        [_trade_row(_ms(start + timedelta(hours=offset))) for offset in (2, 1, 0)]
    )

    def fetch(request: PublicRequest) -> tuple[bytes, CaptureRecord]:
        return raw, _record(request, raw)

    rows = capture_trade_range(
        package,
        series_type="formation_trades",
        instrument="BTC-USDT-SWAP",
        start_inclusive=start.isoformat(),
        end_exclusive=end.isoformat(),
        fetch_page=fetch,
        page_pause_seconds=0,
    )
    assert len(rows) == 3
    assert len(package.records) == 1
    assert len(list((tmp_path / "capture/raw").rglob("*.bin"))) == 1
    assert (
        tmp_path
        / "capture/normalized/formation_trades/BTC-USDT-SWAP.json"
    ).is_file()


def test_capture_rejects_cross_page_duplicate_before_overwrite(tmp_path: Path) -> None:
    package = C11ACapturePackage(tmp_path / "capture")
    start = datetime(2024, 1, 1, tzinfo=UTC)
    end = start + timedelta(hours=4)
    pages = iter(
        (
            _raw_payload([_trade_row(_ms(start + timedelta(hours=3)))]),
            _raw_payload([_trade_row(_ms(start + timedelta(hours=3)))]),
        )
    )

    def fetch(request: PublicRequest) -> tuple[bytes, CaptureRecord]:
        raw = next(pages)
        return raw, _record(request, raw)

    with pytest.raises(C11AHistoricalCaptureError, match="strictly older|duplicate"):
        capture_trade_range(
            package,
            series_type="formation_trades",
            instrument="BTC-USDT-SWAP",
            start_inclusive=start.isoformat(),
            end_exclusive=end.isoformat(),
            fetch_page=fetch,
            page_pause_seconds=0,
        )
    assert len(package.records) == 2


def test_package_freezes_ranked_universe_and_rejects_forgery(tmp_path: Path) -> None:
    evidence = select_formation_universe(_formation())
    package = C11ACapturePackage(tmp_path / "good")
    assert package.freeze_universe(evidence) == tuple(evidence["selected_universe"])
    assert BTC_BETA_BENCHMARK not in evidence["selected_universe"]
    package.retain_c11a_series(
        series_type="marks",
        instrument=BTC_BETA_BENCHMARK,
        start_inclusive="2023-12-31T23:00:00Z",
        end_exclusive="2024-01-01T00:00:00Z",
        rows=({"timestamp": "2023-12-31T23:00:00Z", "close": "1"},),
    )
    with pytest.raises(C11AHistoricalCaptureError, match="already frozen"):
        package.freeze_universe(evidence)
    with pytest.raises(C11AHistoricalCaptureError, match="outside frozen phase"):
        package.retain_c11a_series(
            series_type="marks",
            instrument=CANDIDATE_POOL[0],
            start_inclusive="2024-01-01T00:00:00Z",
            end_exclusive="2024-01-01T01:00:00Z",
            rows=({"timestamp": "2024-01-01T00:00:00Z", "close": "1"},),
        )

    forged = json.loads(json.dumps(evidence))
    forged["selected_universe"] = list(reversed(forged["selected_universe"]))
    other = C11ACapturePackage(tmp_path / "forged")
    with pytest.raises(C11AHistoricalCaptureError, match="rank/selection"):
        other.freeze_universe(forged)
    with pytest.raises(C7APublicDataError, match="official"):
        validate_c11a_public_request(
            PublicRequest(
                "outside",
                "OKX_HISTORICAL_DOWNLOAD",
                "https://example.com/data.csv",
            )
        )


def test_funding_downloads_are_cross_file_unique_and_bound_to_top_eight(
    tmp_path: Path,
) -> None:
    package = C11ACapturePackage(tmp_path / "capture")
    evidence = select_formation_universe(_formation())
    selected = package.freeze_universe(evidence)
    start = datetime(2024, 1, 1, tzinfo=UTC)
    end = start + timedelta(hours=8)
    specs = tuple(
        C11AFundingDownloadSpec(
            request_id=f"funding-{instrument}",
            instrument=instrument,
            url=f"https://www.okx.com/data/{instrument}.csv",
            column_map=FUNDING_ARCHIVE_COLUMNS,
        )
        for instrument in selected
    )

    def fetch(request: PublicRequest) -> tuple[bytes, CaptureRecord]:
        instrument = request.request_id.removeprefix("funding-")
        raw = (
            "instrument_name,funding_time,funding_rate\n"
            f"{instrument},{_ms(start)},0.0001\n"
        ).encode()
        return raw, _record(request, raw, "text/csv")

    rows = capture_funding_downloads(
        package,
        selected_universe=selected,
        specs=specs,
        start_inclusive=start.isoformat(),
        end_exclusive=end.isoformat(),
        fetch_object=fetch,
        download_pause_seconds=0,
    )
    assert set(rows) == set(selected)
    assert all(len(values) == 1 for values in rows.values())
    assert len(package.records) == 8

    duplicate = (specs[0], specs[0], *specs[1:])
    other = C11ACapturePackage(tmp_path / "duplicate")
    other.freeze_universe(evidence)
    with pytest.raises(C11AHistoricalCaptureError, match="request IDs"):
        capture_funding_downloads(
            other,
            selected_universe=selected,
            specs=duplicate,
            start_inclusive=start.isoformat(),
            end_exclusive=end.isoformat(),
            fetch_object=fetch,
            download_pause_seconds=0,
        )


def test_package_finalize_fails_until_every_frozen_series_exists(tmp_path: Path) -> None:
    package = C11ACapturePackage(tmp_path / "capture")
    package.freeze_universe(select_formation_universe(_formation()))
    request = build_trade_candle_request(
        "BTC-USDT-SWAP",
        after_ms=1_704_067_200_000,
        allowed_instruments=CANDIDATE_POOL,
    )
    raw = _raw_payload([_trade_row(1_704_063_600_000)])
    package.retain_raw(raw, _record(request, raw))
    with pytest.raises(C11AHistoricalCaptureError, match="inventory"):
        package.finalize(
            implementation_sha="a" * 40,
            capture_plan_value=capture_plan(),
        )


def test_package_path_and_overwrite_guards_remain_fail_closed(tmp_path: Path) -> None:
    package = C11ACapturePackage(tmp_path / "capture")
    with pytest.raises(C7APublicDataError):
        normalize_trade_candle_payload(
            {"code": "0", "msg": "", "data": [_trade_row(1_704_067_200_000)]},
            instrument="UNREVIEWED-USDT-SWAP",
            allowed_instruments=CANDIDATE_POOL,
        )
    with pytest.raises(C7AHistoricalCaptureError, match="inside"):
        package.write_json("../escape.json", {})
    assert not (tmp_path / "escape.json").exists()
