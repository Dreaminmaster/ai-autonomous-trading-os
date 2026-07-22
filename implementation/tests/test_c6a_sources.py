from __future__ import annotations

import copy

import pytest

from atos.c6a_contract import C6AError
from atos.c6a_sources import (
    coverage_intervals,
    require_complete_coverage,
    validate_source_manifest,
)


def manifest() -> dict:
    sources = []
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
            sources.append(
                {
                    "source_id": f"{kind}-{instrument}",
                    "kind": kind,
                    "instrument": instrument,
                    "url": f"https://www.okx.com/historical-data/{kind}/{instrument}.zip",
                    "sha256": "a" * 64,
                    "coverage_start": "2023-06-05T00:00:00Z",
                    "coverage_end_exclusive": "2025-12-29T00:00:00Z",
                    "content_type": "application/zip",
                }
            )
    return {
        "schema_version": 1,
        "stage": "C6A",
        "authenticated": False,
        "economic_boundary_exclusive": "2025-12-29T00:00:00Z",
        "sources": sources,
    }


def test_manifest_requires_every_complete_public_primitive_pair() -> None:
    entries = validate_source_manifest(manifest())
    assert len(entries) == 12
    assert all(entry.url.startswith("https://www.okx.com/") for entry in entries)
    coverage = require_complete_coverage(entries)
    assert coverage["status"] == "PASS"
    assert coverage["pair_count"] == 12


def test_non_okx_auth_or_boundary_source_fails_closed() -> None:
    payload = manifest()
    payload["sources"][0]["url"] = "https://example.com/data.zip"
    with pytest.raises(C6AError, match="OKX domain"):
        validate_source_manifest(payload)

    payload = manifest()
    payload["authenticated"] = True
    with pytest.raises(C6AError, match="forbid authentication"):
        validate_source_manifest(payload)

    payload = manifest()
    payload["sources"][0]["coverage_end_exclusive"] = "2025-12-29T01:00:00Z"
    with pytest.raises(C6AError, match="closed economic boundary"):
        validate_source_manifest(payload)


def test_missing_pair_bad_hash_or_partial_coverage_fails_closed() -> None:
    payload = manifest()
    payload["sources"] = payload["sources"][:-1]
    with pytest.raises(C6AError, match="missing primitive pairs"):
        validate_source_manifest(payload)

    payload = manifest()
    payload["sources"][0]["sha256"] = "bad"
    with pytest.raises(C6AError, match="SHA-256"):
        validate_source_manifest(payload)

    payload = manifest()
    payload["sources"][0]["coverage_start"] = "2023-06-06T00:00:00Z"
    with pytest.raises(C6AError, match="incomplete source coverage"):
        validate_source_manifest(payload)


def test_adjacent_archive_parts_are_accepted_but_gap_or_overlap_fails() -> None:
    payload = manifest()
    original = payload["sources"][0]
    original["coverage_end_exclusive"] = "2024-01-01T00:00:00Z"
    second = copy.deepcopy(original)
    second["source_id"] += "-part2"
    second["coverage_start"] = "2024-01-01T00:00:00Z"
    second["coverage_end_exclusive"] = "2025-12-29T00:00:00Z"
    payload["sources"].append(second)
    entries = validate_source_manifest(payload)
    intervals = coverage_intervals(
        entries, kind="spot_trade_candles", instrument="BTC-USDT"
    )
    assert len(intervals) == 2

    gapped = copy.deepcopy(payload)
    gapped["sources"][-1]["coverage_start"] = "2024-01-02T00:00:00Z"
    with pytest.raises(C6AError, match="gap in source coverage"):
        validate_source_manifest(gapped)

    overlapping = copy.deepcopy(payload)
    overlapping["sources"][-1]["coverage_start"] = "2023-12-31T00:00:00Z"
    with pytest.raises(C6AError, match="overlapping source coverage"):
        validate_source_manifest(overlapping)
