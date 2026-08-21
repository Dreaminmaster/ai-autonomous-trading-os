from __future__ import annotations

import json
from pathlib import Path
from typing import ClassVar
from urllib.error import HTTPError

import pytest
from atos.c7a_historical_capture import (
    C7AHistoricalCaptureError,
    CapturePackage,
    CaptureRecord,
)
from atos.c7a_okx_public_data import PublicRequest
from atos.c9a_contract import (
    ALL_TRADE_INSTRUMENTS,
    SOLVER_ITERATIONS,
    load_frozen_config,
)
from atos.c9a_historical_capture import (
    C9ACapturePackage,
    C9AHistoricalCaptureError,
    build_trade_candle_request,
    capture_trade_range,
    fetch_raw_c9a,
    normalize_trade_candle_payload,
    validate_c9a_public_request,
)
from atos.c9a_historical_schedule import (
    HISTORICAL_WINDOWS,
    decision_times,
    w1_w5_capture_plan,
)

SHA = "1" * 40


def _root() -> Path:
    return Path(__file__).resolve().parents[2]


def _payload(stamps: list[int], *, confirm: str = "1") -> bytes:
    return json.dumps(
        {
            "code": "0",
            "data": [
                [str(stamp), "100", "101", "99", "100", "1", "1", "100", confirm]
                for stamp in stamps
            ],
        }
    ).encode()


def _record(request: PublicRequest, raw: bytes) -> CaptureRecord:
    import hashlib

    return CaptureRecord(
        request_id=request.request_id,
        source_family=request.source_family,
        requested_url=request.url,
        final_url=request.url,
        collected_at="2026-08-21T00:00:00Z",
        media_type="application/json",
        size=len(raw),
        sha256=hashlib.sha256(raw).hexdigest(),
        relative_path="",
    )


def test_frozen_config_and_schedule_are_exact() -> None:
    config = load_frozen_config(_root())
    plan = w1_w5_capture_plan()
    assert SOLVER_ITERATIONS == 160
    assert plan["funding_start_inclusive"] == "2023-06-05T00:00:00Z"
    assert plan["trade_start_inclusive"] == "2023-07-02T22:00:00Z"
    assert plan["trade_end_exclusive"] == "2025-12-29T01:00:00Z"
    assert config["execution_feasibility_established"] is False
    assert sum(len(decision_times(window)) for window in HISTORICAL_WINDOWS) == 130


def test_c9a_allows_only_frozen_spot_trade_surface() -> None:
    request = build_trade_candle_request("BTC-USDT", after_ms=1_700_000_000_000)
    validate_c9a_public_request(request)
    with pytest.raises(Exception, match="drift|forbidden|unsupported"):
        validate_c9a_public_request(
            PublicRequest(
                "bad",
                "OKX_HISTORY_CANDLES_API",
                request.url.replace("/market/history-candles", "/trade/order"),
            )
        )
    with pytest.raises(Exception, match="drift|credential|authentication"):
        validate_c9a_public_request(
            PublicRequest(
                "bad-auth",
                "OKX_HISTORY_CANDLES_API",
                request.url,
                headers=(("OK-ACCESS-KEY", "forbidden"),),
            )
        )


def test_spot_normalization_rejects_unconfirmed_and_bad_geometry() -> None:
    stamp = 1_704_067_200_000
    with pytest.raises(C9AHistoricalCaptureError, match="unconfirmed"):
        normalize_trade_candle_payload(
            json.loads(_payload([stamp], confirm="0")), instrument="BTC-USDT"
        )
    payload = json.loads(_payload([stamp]))
    payload["data"][0][2] = "98"
    with pytest.raises(C9AHistoricalCaptureError, match="geometry"):
        normalize_trade_candle_payload(payload, instrument="BTC-USDT")


def test_trade_capture_persists_raw_before_failing_on_cross_page_duplicate(
    tmp_path: Path,
) -> None:
    package = C9ACapturePackage(tmp_path / "capture")
    pages = iter(
        (
            _payload([1_704_067_200_000, 1_704_063_600_000]),
            _payload([1_704_063_600_000, 1_704_060_000_000]),
        )
    )

    def fetch(request: PublicRequest) -> tuple[bytes, CaptureRecord]:
        raw = next(pages)
        return raw, _record(request, raw)

    with pytest.raises(C9AHistoricalCaptureError, match="duplicate|strictly older"):
        capture_trade_range(
            package,
            instrument="BTC-USDT",
            start_inclusive="2023-12-31T22:00:00Z",
            end_exclusive="2024-01-01T01:00:00Z",
            fetch_page=fetch,
            page_pause_seconds=0,
        )
    assert len(package.records) == 2
    assert len(list((tmp_path / "capture" / "raw").rglob("*.bin"))) == 2


def test_capture_package_path_and_overwrite_guards_cover_spot(tmp_path: Path) -> None:
    package = C9ACapturePackage(tmp_path / "capture")
    request = build_trade_candle_request("ETH-USDT", after_ms=1_704_067_200_000)
    raw = _payload([1_704_063_600_000])
    package.retain_raw(raw, _record(request, raw))
    with pytest.raises(C7AHistoricalCaptureError, match="duplicate"):
        package.retain_raw(raw, _record(request, raw))
    with pytest.raises(C7AHistoricalCaptureError, match="inside"):
        package.write_json("../escape.json", {})
    with pytest.raises(C7AHistoricalCaptureError, match="policy"):
        CapturePackage(
            tmp_path / "invalid-policy",
            allowed_instruments=("UNREVIEWED-USDT",),
            public_trade_instruments=("UNREVIEWED-USDT",),
        )
    assert not (tmp_path / "invalid-policy").exists()


def test_redirect_semantics_and_retry_remain_fail_closed() -> None:
    request = build_trade_candle_request("BTC-USDT", after_ms=1_704_067_200_000)

    class Response:
        status = 200
        headers: ClassVar[dict[str, str]] = {"Content-Type": "application/json"}

        def geturl(self) -> str:
            return request.url.replace("after=1704067200000", "after=1")

        def read(self, _limit: int) -> bytes:
            return _payload([1_704_063_600_000])

        def close(self) -> None:
            return None

    with pytest.raises(C7AHistoricalCaptureError, match="redirect changed"):
        fetch_raw_c9a(request, opener=lambda *_args, **_kwargs: Response())

    attempts = 0

    def rejected(*_args: object, **_kwargs: object) -> object:
        nonlocal attempts
        attempts += 1
        raise HTTPError(request.url, 403, "forbidden", {}, None)

    with pytest.raises(C7AHistoricalCaptureError, match="HTTP Error 403"):
        fetch_raw_c9a(request, opener=rejected)
    assert attempts == 1


def test_all_trade_instrument_inventory_is_fixed() -> None:
    assert ALL_TRADE_INSTRUMENTS == (
        "BTC-USDT",
        "ETH-USDT",
        "BTC-USDT-SWAP",
        "ETH-USDT-SWAP",
    )
