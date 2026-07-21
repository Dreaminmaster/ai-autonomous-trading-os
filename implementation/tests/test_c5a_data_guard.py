from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

from atos.c5a_derivatives_crowding import expected_timestamps

IMPL = Path(__file__).resolve().parents[1]


def _module(name: str, relative: str):
    path = IMPL / relative
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


guard = _module("c5a_data_guard_test", "scripts/c5a_data_guard.py")
download = _module("c5a_download_test", "scripts/c5a_download_public_data.py")


def _spot_rows():
    return [
        {
            "date": stamp.isoformat(),
            "open": 100.0,
            "high": 101.0,
            "low": 99.0,
            "close": 100.5,
            "quote_volume": 1000.0,
        }
        for stamp in expected_timestamps()
    ]


def test_guard_verifies_exact_spot_grid(tmp_path: Path) -> None:
    path = tmp_path / "BTC-USDT.json"
    path.write_text(json.dumps(_spot_rows()), encoding="utf-8")
    report = guard.verify_file(
        path,
        fields=("open", "high", "low", "close", "quote_volume"),
        label="spot:BTC-USDT",
    )
    assert report["rows"] == 2940
    assert report["gaps"] == 0
    assert report["duplicates"] == 0


def test_guard_rejects_missing_and_post_boundary_rows(tmp_path: Path) -> None:
    missing = tmp_path / "missing.json"
    missing.write_text(json.dumps(_spot_rows()[:-1]), encoding="utf-8")
    with pytest.raises(guard.C5ADataGuardError, match="coverage mismatch"):
        guard.verify_file(
            missing,
            fields=("open", "high", "low", "close", "quote_volume"),
            label="spot:BTC-USDT",
        )

    raw = tmp_path / "raw.json"
    rows = _spot_rows() + [
        {
            "date": "2026-01-05T00:00:00+00:00",
            "open": 100.0,
            "high": 101.0,
            "low": 99.0,
            "close": 100.5,
            "quote_volume": 1000.0,
        }
    ]
    raw.write_text(json.dumps(rows), encoding="utf-8")
    sealed = tmp_path / "sealed.json"
    report = guard.seal_file(
        raw,
        sealed,
        fields=("open", "high", "low", "close", "quote_volume"),
        label="spot:BTC-USDT",
    )
    assert report["removed_post_boundary_rows"] == 1
    assert len(json.loads(sealed.read_text(encoding="utf-8"))) == 2940


def test_downloader_normalizes_only_completed_public_rows() -> None:
    trade = download._normalize_trade(
        ["1735689600000", "100", "101", "99", "100.5", "10", "1000", "1005", "1"],
        include_ohlc=True,
    )
    assert trade["close"] == 100.5
    assert trade["quote_volume"] == 1005.0
    mark = download._normalize_mark(
        ["1735689600000", "100", "101", "99", "100.25", "1"]
    )
    assert mark["close"] == 100.25
    with pytest.raises(download.C5ADownloadError, match="incomplete"):
        download._normalize_mark(
            ["1735689600000", "100", "101", "99", "100.25", "0"]
        )
