from __future__ import annotations

import pytest

from scripts import c6a_source_plan_preflight as preflight


def valid_plan() -> dict:
    rows = []
    candle_mapping = {
        "spot_trade_candles": ("BTC-USDT", "ETH-USDT"),
        "swap_trade_candles": ("BTC-USDT-SWAP", "ETH-USDT-SWAP"),
        "swap_mark_candles": ("BTC-USDT-SWAP", "ETH-USDT-SWAP"),
    }
    for kind, instruments in candle_mapping.items():
        endpoint = (
            preflight.MARK_ENDPOINT
            if kind == "swap_mark_candles"
            else preflight.TRADE_ENDPOINT
        )
        for instrument in instruments:
            rows.append(
                {
                    "source_id": f"{kind}-{instrument}",
                    "kind": kind,
                    "instrument": instrument,
                    "url": endpoint,
                    "coverage_start": "2023-06-05T00:00:00Z",
                    "coverage_end_exclusive": "2025-12-29T00:00:00Z",
                    "content_type": "application/x-ndjson",
                    "request_mode": "PAGINATED_PUBLIC_API",
                    "bar": "1H",
                    "limit": 100,
                }
            )
    for instrument in ("BTC-USDT-SWAP", "ETH-USDT-SWAP"):
        rows.append(
            {
                "source_id": f"funding-{instrument}",
                "kind": "funding_history",
                "instrument": instrument,
                "url": f"https://www.okx.com/historical-data/funding-{instrument}.zip",
                "coverage_start": "2023-06-05T00:00:00Z",
                "coverage_end_exclusive": "2025-12-29T00:00:00Z",
                "content_type": "application/zip",
                "archive_member": f"funding-{instrument}.csv",
                "request_mode": "SINGLE_OBJECT",
            }
        )
    for instrument in (
        "BTC-USDT",
        "ETH-USDT",
        "BTC-USDT-SWAP",
        "ETH-USDT-SWAP",
    ):
        rows.append(
            {
                "source_id": f"metadata-{instrument}",
                "kind": "instrument_metadata",
                "instrument": instrument,
                "url": f"https://www.okx.com/historical-data/instrument-metadata-{instrument}.json",
                "coverage_start": "2023-06-05T00:00:00Z",
                "coverage_end_exclusive": "2025-12-29T00:00:00Z",
                "content_type": "application/json",
                "request_mode": "SINGLE_OBJECT",
            }
        )
    return {
        "schema_version": 1,
        "stage": "C6A",
        "authenticated": False,
        "economic_boundary_exclusive": "2025-12-29T00:00:00Z",
        "sources": rows,
    }


def test_preflight_accepts_exact_shape_without_placeholders() -> None:
    report = preflight.preflight(valid_plan())
    assert report["status"] == "PASS"
    assert report["source_count"] == 12
    assert report["paginated_candle_source_count"] == 6
    assert report["exact_object_source_count"] == 6
    assert report["placeholder_count"] == 0
    assert len(report["source_plan_sha256"]) == 64


def test_preflight_rejects_placeholder_wrong_mode_or_missing_archive_member() -> None:
    payload = valid_plan()
    payload["sources"][6]["url"] = "https://www.okx.com/placeholder/funding.zip"
    with pytest.raises(preflight.C6ASourcePlanPreflightError, match="placeholder"):
        preflight.preflight(payload)

    payload = valid_plan()
    payload["sources"][0]["request_mode"] = "SINGLE_OBJECT"
    with pytest.raises(preflight.C6ASourcePlanPreflightError, match="mode/endpoint"):
        preflight.preflight(payload)

    payload = valid_plan()
    payload["sources"][6]["archive_member"] = None
    with pytest.raises(preflight.C6ASourcePlanPreflightError, match="archive source"):
        preflight.preflight(payload)


def test_preflight_rejects_metadata_or_funding_identity_drift() -> None:
    payload = valid_plan()
    payload["sources"][6]["url"] = "https://www.okx.com/historical-data/object.zip"
    with pytest.raises(preflight.C6ASourcePlanPreflightError, match="funding identity"):
        preflight.preflight(payload)

    payload = valid_plan()
    payload["sources"][8]["url"] = "https://www.okx.com/historical-data/object.json"
    with pytest.raises(preflight.C6ASourcePlanPreflightError, match="instrument identity"):
        preflight.preflight(payload)
