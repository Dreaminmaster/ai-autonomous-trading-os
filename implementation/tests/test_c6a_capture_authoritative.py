from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from atos.c6a_source_plan import PublicSourcePlanEntry
from scripts import c6a_capture_authoritative as capture


def entries() -> tuple[PublicSourcePlanEntry, ...]:
    start = datetime(2023, 6, 5, tzinfo=UTC)
    end = datetime(2025, 12, 29, tzinfo=UTC)
    return (
        PublicSourcePlanEntry(
            source_id="spot-api",
            kind="spot_trade_candles",
            instrument="BTC-USDT",
            url=capture.api_schema.TRADE_ENDPOINT,
            coverage_start=start,
            coverage_end_exclusive=end,
            content_type="application/x-ndjson",
        ),
        PublicSourcePlanEntry(
            source_id="funding-object",
            kind="funding_history",
            instrument="BTC-USDT-SWAP",
            url="https://www.okx.com/historical-data/funding.zip",
            coverage_start=start,
            coverage_end_exclusive=end,
            content_type="application/zip",
            archive_member="funding.csv",
        ),
    )


def plan() -> dict:
    return {
        "schema_version": 1,
        "stage": "C6A",
        "authenticated": False,
        "economic_boundary_exclusive": "2025-12-29T00:00:00Z",
        "sources": [
            {
                "source_id": "spot-api",
                "kind": "spot_trade_candles",
                "instrument": "BTC-USDT",
                "url": capture.api_schema.TRADE_ENDPOINT,
                "coverage_start": "2023-06-05T00:00:00Z",
                "coverage_end_exclusive": "2025-12-29T00:00:00Z",
                "content_type": "application/x-ndjson",
                "request_mode": "PAGINATED_PUBLIC_API",
                "bar": "1H",
                "limit": 100,
            },
            {
                "source_id": "funding-object",
                "kind": "funding_history",
                "instrument": "BTC-USDT-SWAP",
                "url": "https://www.okx.com/historical-data/funding.zip",
                "coverage_start": "2023-06-05T00:00:00Z",
                "coverage_end_exclusive": "2025-12-29T00:00:00Z",
                "content_type": "application/zip",
                "archive_member": "funding.csv",
                "request_mode": "SINGLE_OBJECT",
            },
        ],
    }


def patch_guards(monkeypatch) -> None:
    monkeypatch.setattr(capture.object_capture, "_assert_public_environment", lambda: None)
    monkeypatch.setattr(
        capture.object_capture,
        "_verify_program_authority",
        lambda source_sha=None: {
            "status": "PASS",
            "source_head_sha": source_sha,
            "verified_before_market_access": True,
        },
    )
    monkeypatch.setattr(capture, "validate_source_plan", lambda payload: entries())
    monkeypatch.setattr(capture, "validate_source_manifest", lambda payload: tuple())


def test_final_capture_retains_api_transcript_and_single_object(
    tmp_path: Path, monkeypatch
) -> None:
    patch_guards(monkeypatch)

    def api_capture(plan, *, destination, transcript_path, network_opener, sleep):
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text("{}\n", encoding="utf-8")
        transcript_path.parent.mkdir(parents=True, exist_ok=True)
        transcript_path.write_text("{}\n", encoding="utf-8")
        return {
            "source_id": plan.source_id,
            "kind": plan.kind,
            "instrument": plan.instrument,
            "url": plan.endpoint,
            "path": str(destination),
            "size": destination.stat().st_size,
            "sha256": "a" * 64,
            "status": "PASS",
            "raw_transcript_path": str(transcript_path),
            "raw_transcript_size": transcript_path.stat().st_size,
            "raw_transcript_sha256": "c" * 64,
            "raw_transcript_page_count": 1,
            "raw_response_bytes_retained": True,
        }

    def object_capture(entry, *, staging_dir, opener):
        path = staging_dir / "funding.zip"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"funding")
        return entry.manifest_fields(sha256="b" * 64), {
            "source_id": entry.source_id,
            "kind": entry.kind,
            "instrument": entry.instrument,
            "url": entry.url,
            "path": str(path),
            "size": path.stat().st_size,
            "sha256": "b" * 64,
            "status": "PASS",
        }

    monkeypatch.setattr(
        capture.api_capture, "capture_series_with_raw_transcript", api_capture
    )
    monkeypatch.setattr(capture.object_capture, "capture_entry", object_capture)
    raw = tmp_path / "raw"
    report = capture.capture(
        plan=plan(),
        raw_dir=raw,
        manifest_path=tmp_path / "manifest.json",
        report_path=tmp_path / "report.json",
        source_sha="a" * 40,
        api_sleep=lambda _: None,
    )
    assert report["status"] == "PASS"
    assert report["api_raw_response_transcripts_retained"] is True
    api_row = next(row for row in report["sources"] if row["kind"] == "spot_trade_candles")
    assert Path(api_row["path"]).is_file()
    assert Path(api_row["raw_transcript_path"]).is_file()


def test_final_capture_rolls_back_raw_transcript_on_failure(
    tmp_path: Path, monkeypatch
) -> None:
    patch_guards(monkeypatch)

    def api_capture(plan, *, destination, transcript_path, network_opener, sleep):
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text("{}\n", encoding="utf-8")
        transcript_path.parent.mkdir(parents=True, exist_ok=True)
        transcript_path.write_text("{}\n", encoding="utf-8")
        return {
            "source_id": plan.source_id,
            "kind": plan.kind,
            "instrument": plan.instrument,
            "url": plan.endpoint,
            "path": str(destination),
            "size": destination.stat().st_size,
            "sha256": "a" * 64,
            "status": "PASS",
            "raw_transcript_path": str(transcript_path),
            "raw_response_bytes_retained": True,
        }

    monkeypatch.setattr(
        capture.api_capture, "capture_series_with_raw_transcript", api_capture
    )
    monkeypatch.setattr(
        capture.object_capture,
        "capture_entry",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("object failure")),
    )
    raw = tmp_path / "raw"
    with pytest.raises(RuntimeError, match="object failure"):
        capture.capture(
            plan=plan(),
            raw_dir=raw,
            manifest_path=tmp_path / "manifest.json",
            report_path=tmp_path / "report.json",
            source_sha="b" * 40,
            api_sleep=lambda _: None,
        )
    assert not raw.exists()
    assert not raw.with_name("raw.staging").exists()
