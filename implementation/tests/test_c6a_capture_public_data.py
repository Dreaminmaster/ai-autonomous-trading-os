from __future__ import annotations

import io
import json
from pathlib import Path

import pytest

from atos.c6a_source_plan import validate_source_plan
from atos.c6a_sources import validate_source_manifest
from scripts import c6a_capture_public_data as capture


def plan() -> dict:
    rows = []
    mapping = {
        "spot_trade_candles": ("BTC-USDT", "ETH-USDT"),
        "swap_trade_candles": ("BTC-USDT-SWAP", "ETH-USDT-SWAP"),
        "swap_mark_candles": ("BTC-USDT-SWAP", "ETH-USDT-SWAP"),
        "funding_history": ("BTC-USDT-SWAP", "ETH-USDT-SWAP"),
        "instrument_metadata": (
            "BTC-USDT",
            "ETH-USDT",
            "BTC-USDT-SWAP",
            "ETH-USDT-SWAP",
        ),
    }
    for kind, instruments in mapping.items():
        for instrument in instruments:
            rows.append(
                {
                    "source_id": f"{kind}-{instrument}",
                    "kind": kind,
                    "instrument": instrument,
                    "url": f"https://www.okx.com/public/{kind}/{instrument}.json",
                    "coverage_start": "2023-06-05T00:00:00Z",
                    "coverage_end_exclusive": "2025-12-29T00:00:00Z",
                    "content_type": "application/json",
                }
            )
    return {
        "schema_version": 1,
        "stage": "C6A",
        "authenticated": False,
        "economic_boundary_exclusive": "2025-12-29T00:00:00Z",
        "sources": rows,
    }


def test_source_plan_is_complete_public_and_hash_free() -> None:
    entries = validate_source_plan(plan())
    assert len(entries) == 12
    assert all(entry.url.startswith("https://www.okx.com/") for entry in entries)
    assert all("sha256" not in row for row in plan()["sources"])


def test_first_capture_emits_hash_manifest_and_compatible_report(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(
        capture,
        "_verify_program_authority",
        lambda source_sha=None: {
            "status": "PASS",
            "source_head_sha": source_sha or "a" * 40,
            "verified_before_market_access": True,
        },
    )
    raw = tmp_path / "raw"
    manifest_path = tmp_path / "source-manifest.json"
    report_path = tmp_path / "download-report.json"

    def opener(entry):
        return io.BytesIO(f"public:{entry.source_id}".encode())

    report = capture.capture(
        plan=plan(),
        raw_dir=raw,
        manifest_path=manifest_path,
        report_path=report_path,
        source_sha="a" * 40,
        opener=opener,
    )
    assert report["status"] == "PASS"
    assert report["source_count"] == 12
    assert report["economic_result_run"] is False
    assert report["c5b_state"] == "C5B_CLOSED_AND_UNTOUCHED"
    assert report["live"] == "FORBIDDEN"
    immutable = json.loads(manifest_path.read_text(encoding="utf-8"))
    entries = validate_source_manifest(immutable)
    assert len(entries) == 12
    assert all(len(entry.sha256) == 64 for entry in entries)
    assert all(Path(row["path"]).is_file() for row in report["sources"])
    assert not (tmp_path / "raw.staging").exists()


def test_capture_is_atomic_and_refuses_overwrite_or_empty_object(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(
        capture,
        "_verify_program_authority",
        lambda source_sha=None: {
            "status": "PASS",
            "source_head_sha": source_sha or "b" * 40,
            "verified_before_market_access": True,
        },
    )
    raw = tmp_path / "raw"
    manifest_path = tmp_path / "manifest.json"
    report_path = tmp_path / "report.json"
    with pytest.raises(capture.C6ACaptureError, match="empty"):
        capture.capture(
            plan=plan(),
            raw_dir=raw,
            manifest_path=manifest_path,
            report_path=report_path,
            source_sha="b" * 40,
            opener=lambda _: io.BytesIO(b""),
        )
    assert not raw.exists()
    assert not manifest_path.exists()
    assert not report_path.exists()

    raw.mkdir()
    with pytest.raises(capture.C6ACaptureError, match="overwrite"):
        capture.capture(
            plan=plan(),
            raw_dir=raw,
            manifest_path=manifest_path,
            report_path=report_path,
            source_sha="b" * 40,
            opener=lambda _: io.BytesIO(b"x"),
        )


def test_source_plan_rejects_credentials_gap_and_non_okx_url() -> None:
    payload = plan()
    payload["sources"][0]["url"] = "https://www.okx.com/data?apiKey=secret"
    with pytest.raises(Exception, match="credential query"):
        validate_source_plan(payload)

    payload = plan()
    payload["sources"][0]["coverage_start"] = "2023-06-06T00:00:00Z"
    with pytest.raises(Exception, match="incomplete"):
        validate_source_plan(payload)

    payload = plan()
    payload["sources"][0]["url"] = "https://example.com/data.json"
    with pytest.raises(Exception, match="OKX domain"):
        validate_source_plan(payload)
