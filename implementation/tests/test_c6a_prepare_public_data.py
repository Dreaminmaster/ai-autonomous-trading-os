from __future__ import annotations

import csv
import hashlib
import io
import json
import zipfile
from datetime import UTC, datetime

import pytest

from atos.c6a_sources import PublicSourceEntry
from scripts import c6a_prepare_public_data as prepare


def entry(
    *,
    source_id: str = "btc-candles",
    archive_member: str | None = None,
    kind: str = "spot_trade_candles",
    instrument: str = "BTC-USDT",
) -> PublicSourceEntry:
    return PublicSourceEntry(
        source_id=source_id,
        kind=kind,
        instrument=instrument,
        url="https://www.okx.com/historical-data/object.zip",
        sha256="a" * 64,
        coverage_start=datetime(2023, 6, 5, tzinfo=UTC),
        coverage_end_exclusive=datetime(2025, 12, 29, tzinfo=UTC),
        content_type="application/zip",
        archive_member=archive_member,
    )


def test_documented_okx_candle_array_normalizes_without_guessing() -> None:
    row = [
        "1597026383085",
        "3.721",
        "3.743",
        "3.677",
        "3.708",
        "8422410",
        "22698348",
        "12698348",
        "1",
    ]
    normalized = prepare.normalize_candle(row)
    assert normalized == {
        "timestamp": "1597026383085",
        "open": "3.721",
        "high": "3.743",
        "low": "3.677",
        "close": "3.708",
        "quote_volume": "12698348",
    }


def test_unconfirmed_or_incomplete_candle_fails_closed() -> None:
    with pytest.raises(prepare.C6APrepareError, match="unconfirmed"):
        prepare.normalize_candle(["1", "1", "1", "1", "1", "0", "0", "0", "0"])
    with pytest.raises(prepare.C6APrepareError, match="fewer"):
        prepare.normalize_candle(["1", "1"])


def test_csv_json_and_jsonl_decoders_require_records() -> None:
    csv_bytes = b"ts,o,h,l,c,volCcyQuote\n1,2,3,1,2,10\n"
    assert prepare._decode_records(csv_bytes, name="rows.csv")[0]["c"] == "2"
    assert prepare._decode_records(b'[{"x":1}]', name="rows.json") == [{"x": 1}]
    assert prepare._decode_records(b'{"x":1}\n{"x":2}\n', name="rows.jsonl") == [
        {"x": 1},
        {"x": 2},
    ]
    with pytest.raises(prepare.C6APrepareError, match="empty"):
        prepare._decode_records(b"[]", name="rows.json")


def test_zip_requires_exact_reviewed_member_and_blocks_traversal(tmp_path) -> None:
    archive = tmp_path / "source.zip"
    with zipfile.ZipFile(archive, "w") as handle:
        handle.writestr("reviewed/rows.csv", "ts,o,h,l,c,volCcyQuote\n1,2,3,1,2,10\n")
        handle.writestr("other.csv", "ts,o,h,l,c,volCcyQuote\n1,9,9,9,9,9\n")
    exact = entry(archive_member="reviewed/rows.csv")
    rows = prepare.load_records(archive, exact)
    assert rows[0]["o"] == "2"

    with pytest.raises(prepare.C6APrepareError, match="exact ZIP member"):
        prepare.load_records(archive, entry(archive_member="missing.csv"))
    with pytest.raises(prepare.C6APrepareError, match="unsafe archive member"):
        prepare.load_records(archive, entry(archive_member="../rows.csv"))
    with pytest.raises(prepare.C6APrepareError, match="requires exact archive_member"):
        prepare.load_records(archive, entry())


def test_funding_and_metadata_require_explicit_authority() -> None:
    funding = prepare.normalize_funding(
        {"fundingTime": "1", "realizedRate": "0.001"},
        instrument="BTC-USDT-SWAP",
    )
    assert funding["instrument"] == "BTC-USDT-SWAP"
    assert funding["realized_rate"] == "0.001"
    with pytest.raises(prepare.C6APrepareError, match="instrument mismatch"):
        prepare.normalize_funding(
            {"instId": "ETH-USDT-SWAP", "fundingTime": "1", "realizedRate": "0"},
            instrument="BTC-USDT-SWAP",
        )

    with pytest.raises(prepare.C6APrepareError, match="authority fields"):
        prepare.normalize_metadata(
            {"instId": "BTC-USDT", "effective_from": "2023-01-01T00:00:00Z"},
            instrument="BTC-USDT",
        )
    metadata = prepare.normalize_metadata(
        {
            "instId": "BTC-USDT",
            "effective_from": "2023-01-01T00:00:00Z",
            "source": "public changelog",
            "source_sha256": "a" * 64,
        },
        instrument="BTC-USDT",
    )
    assert metadata["instrument"] == "BTC-USDT"
