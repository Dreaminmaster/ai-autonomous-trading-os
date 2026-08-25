from __future__ import annotations

import copy
import csv
import io
import json
import zipfile
from datetime import timedelta
from decimal import Decimal
from urllib.parse import parse_qsl, urlparse

import pytest

from atos.c7a_okx_public_data import PublicRequest
from atos.c12a_contract import contract_decisions, iso_z, load_frozen_config
from atos.c12a_historical_capture import (
    C12A_MAX_EXTRACTED_DOWNLOAD_BYTES,
    FUTURES_HEADER,
    C12ACapturePackage,
    C12AHistoricalCaptureError,
    build_futures_manifest_request,
    capture_plan,
    contracts_by_family_month,
    normalize_futures_archive,
    normalize_futures_manifest,
    validate_c12a_public_request,
    validate_contract_trade_coverage,
)


def _manifest(*, family: str, month: str, url: str | None = None) -> dict[str, object]:
    filename = f"{family}-futureschain-trades-{month}.zip"
    return {
        "code": "0",
        "data": [
            {
                "dateAggrType": "monthly",
                "details": [
                    {
                        "instId": "",
                        "instFamily": family,
                        "instType": "FUTURES",
                        "groupDetails": [
                            {
                                "filename": filename,
                                "url": url
                                or f"https://static.okx.com/cdn/okex/traderecords/{filename}",
                            }
                        ],
                    }
                ],
            }
        ],
    }


def _archive(
    *,
    family: str,
    month: str,
    rows: list[dict[str, str]],
    member: str | None = None,
    header: tuple[str, ...] = FUTURES_HEADER,
) -> bytes:
    csv_stream = io.StringIO(newline="")
    writer = csv.DictWriter(csv_stream, fieldnames=header)
    writer.writeheader()
    writer.writerows(rows)
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            member or f"{family}-futureschain-trades-{month}.csv",
            csv_stream.getvalue(),
        )
    return output.getvalue()


def _row(
    *,
    instrument: str = "BTC-USDT-240329",
    trade_id: str = "1",
    timestamp_ms: str = "1709251200000",
) -> dict[str, str]:
    return {
        "instrument_name": instrument,
        "trade_id": trade_id,
        "side": "buy",
        "price": "62000.125",
        "size": "3",
        "created_time": timestamp_ms,
    }


def test_manifest_request_is_one_official_public_month() -> None:
    request = build_futures_manifest_request(family="BTC-USDT", month="2024-03")
    validate_c12a_public_request(request)
    query = dict(parse_qsl(urlparse(request.url).query))
    assert query["module"] == "1"
    assert query["instType"] == "FUTURES"
    assert query["instFamilyList"] == "BTC-USDT"
    assert query["dateAggrType"] == "monthly"
    assert int(query["begin"]) < int(query["end"])
    assert C12A_MAX_EXTRACTED_DOWNLOAD_BYTES == 256 * 1024 * 1024


def test_request_rejects_auth_private_or_query_drift() -> None:
    request = build_futures_manifest_request(family="BTC-USDT", month="2024-03")
    with pytest.raises(C12AHistoricalCaptureError):
        validate_c12a_public_request(
            PublicRequest(
                request_id=request.request_id,
                source_family=request.source_family,
                url=request.url + "&apiKey=secret",
            )
        )
    with pytest.raises(C12AHistoricalCaptureError):
        validate_c12a_public_request(
            PublicRequest(
                request_id="private",
                source_family="OKX_HISTORICAL_FUTURES_CHAIN_DOWNLOAD",
                url="https://www.okx.com/api/v5/account/balance",
            )
        )


def test_manifest_selects_exact_archive_and_rejects_duplicate() -> None:
    payload = _manifest(family="BTC-USDT", month="2024-03")
    spec = normalize_futures_manifest(
        payload,
        family="BTC-USDT",
        month="2024-03",
        instrument="BTC-USDT-240329",
    )
    assert spec.request_id == "c12a-futures-BTC-USDT-2024-03"
    validate_c12a_public_request(spec.request())

    duplicate = copy.deepcopy(payload)
    groups = duplicate["data"][0]["details"][0]["groupDetails"]  # type: ignore[index]
    groups.append(copy.deepcopy(groups[0]))
    with pytest.raises(C12AHistoricalCaptureError, match="missing or duplicated"):
        normalize_futures_manifest(
            duplicate,
            family="BTC-USDT",
            month="2024-03",
            instrument="BTC-USDT-240329",
        )


def test_archive_normalizes_target_and_validates_other_family_rows() -> None:
    raw = _archive(
        family="BTC-USDT",
        month="2024-03",
        rows=[
            _row(trade_id="2"),
            _row(instrument="BTC-USDT-240628", trade_id="3"),
            _row(trade_id="1", timestamp_ms="1709251199000"),
        ],
    )
    rows = normalize_futures_archive(
        raw,
        family="BTC-USDT",
        month="2024-03",
        instrument="BTC-USDT-240329",
    )
    assert [row["trade_id"] for row in rows] == ["1", "2"]
    assert all(row["instrument"] == "BTC-USDT-240329" for row in rows)
    assert Decimal(rows[0]["price"]) == Decimal("62000.125")


def test_archive_orders_exact_second_before_fractional_trade() -> None:
    raw = _archive(
        family="BTC-USDT",
        month="2024-03",
        rows=[
            _row(trade_id="2", timestamp_ms="1709251200123"),
            _row(trade_id="1", timestamp_ms="1709251200000"),
        ],
    )
    rows = normalize_futures_archive(
        raw,
        family="BTC-USDT",
        month="2024-03",
        instrument="BTC-USDT-240329",
    )
    assert [row["trade_id"] for row in rows] == ["1", "2"]
    assert rows[0]["timestamp"].endswith("00Z")
    assert rows[1]["timestamp"].endswith("00.123000Z")


@pytest.mark.parametrize(
    ("raw", "message"),
    [
        (
            _archive(
                family="BTC-USDT",
                month="2024-03",
                rows=[_row(), _row()],
            ),
            "duplicate futures trade ID",
        ),
        (
            _archive(
                family="BTC-USDT",
                month="2024-03",
                rows=[_row()],
                member="../escape.csv",
            ),
            "member identity is unsafe",
        ),
        (
            _archive(
                family="BTC-USDT",
                month="2024-03",
                rows=[_row()],
                header=(
                    "trade_id",
                    "instrument_name",
                    "side",
                    "price",
                    "size",
                    "created_time",
                ),
            ),
            "header drift",
        ),
        (
            _archive(
                family="BTC-USDT",
                month="2024-03",
                rows=[_row(instrument="ETH-USDT-240329")],
            ),
            "escaped its frozen family",
        ),
    ],
)
def test_archive_rejects_duplicates_unsafe_members_headers_or_family(
    raw: bytes, message: str
) -> None:
    with pytest.raises(C12AHistoricalCaptureError, match=message):
        normalize_futures_archive(
            raw,
            family="BTC-USDT",
            month="2024-03",
            instrument="BTC-USDT-240329",
        )


def test_contract_family_month_inventory_is_exact() -> None:
    config = load_frozen_config(verify_authority=False)
    inventory = contracts_by_family_month(config)
    assert len(inventory) == 38
    assert {family for family, _ in inventory} == {"BTC-USDT", "ETH-USDT"}
    assert {month for _, month in inventory} == set(config["required_archive_months"])
    assert capture_plan(config)["archive_calendar_timezone"] == "UTC+08:00"


def test_trade_coverage_requires_every_hour_and_bounded_execution() -> None:
    decision = contract_decisions(load_frozen_config(verify_authority=False))[0]
    timestamps = [decision.signal_cutoff - timedelta(hours=1)]
    current = decision.entry_timestamp
    while current <= decision.exit_timestamp:
        timestamps.append(current)
        current += timedelta(hours=1)
    rows = [
        {
            "instrument": decision.futures_instrument,
            "trade_id": str(index),
            "side": "buy",
            "price": "60000",
            "size": "1",
            "timestamp": iso_z(stamp),
        }
        for index, stamp in enumerate(timestamps, start=1)
    ]
    assert len(validate_contract_trade_coverage(rows, decision=decision)) == len(rows)
    missing = [
        row for row in rows if row["timestamp"] != iso_z(decision.entry_timestamp)
    ]
    with pytest.raises(C12AHistoricalCaptureError, match="carried hour"):
        validate_contract_trade_coverage(missing, decision=decision)

    unordered = list(rows)
    unordered[0], unordered[1] = unordered[1], unordered[0]
    with pytest.raises(C12AHistoricalCaptureError, match="unordered"):
        validate_contract_trade_coverage(unordered, decision=decision)


def test_capture_package_accepts_only_new_empty_directory(tmp_path) -> None:
    package = C12ACapturePackage(tmp_path / "capture")
    assert package.records == ()
    with pytest.raises(C12AHistoricalCaptureError, match="implementation SHA"):
        package.finalize(
            implementation_sha="not-a-sha",
            frozen_capture_plan=capture_plan(
                load_frozen_config(verify_authority=False)
            ),
        )


def test_manifest_payload_is_json_roundtrippable() -> None:
    payload = _manifest(family="ETH-USDT", month="2025-12")
    decoded = json.loads(json.dumps(payload))
    spec = normalize_futures_manifest(
        decoded,
        family="ETH-USDT",
        month="2025-12",
        instrument="ETH-USDT-251226",
    )
    assert spec.instrument == "ETH-USDT-251226"
