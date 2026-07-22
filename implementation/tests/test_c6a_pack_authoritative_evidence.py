from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from scripts import c6a_pack_authoritative_evidence as authoritative


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
                    "archive_member": None,
                }
            )
    return {
        "schema_version": 1,
        "stage": "C6A",
        "authenticated": False,
        "economic_boundary_exclusive": "2025-12-29T00:00:00Z",
        "sources": rows,
    }


def manifest_and_report(source_plan: dict) -> tuple[dict, dict]:
    manifest_rows = []
    report_rows = []
    for index, row in enumerate(source_plan["sources"]):
        digest = f"{index + 1:064x}"[-64:]
        manifest_rows.append({**row, "sha256": digest})
        report_rows.append(
            {
                "source_id": row["source_id"],
                "kind": row["kind"],
                "instrument": row["instrument"],
                "url": row["url"],
                "sha256": digest,
                "status": "PASS",
            }
        )
    immutable = {
        "schema_version": 1,
        "stage": "C6A",
        "authenticated": False,
        "economic_boundary_exclusive": "2025-12-29T00:00:00Z",
        "sources": manifest_rows,
    }
    plan_hash = hashlib.sha256(
        json.dumps(
            source_plan, sort_keys=True, separators=(",", ":"), ensure_ascii=True
        ).encode("utf-8")
    ).hexdigest()
    report = {
        "status": "PASS",
        "source_plan_sha256": plan_hash,
        "sources": report_rows,
    }
    return immutable, report


def test_acquisition_evidence_requires_exact_three_way_binding() -> None:
    source_plan = plan()
    immutable, report = manifest_and_report(source_plan)
    result = authoritative.verify_acquisition_evidence(
        plan=source_plan,
        source_manifest=immutable,
        download_report=report,
    )
    assert result["status"] == "PASS"
    assert result["source_count"] == 12
    assert result["id_sets_equal"] is True
    assert result["immutable_manifest_matches_plan"] is True
    assert result["download_report_matches_manifest"] is True
    assert result["authenticated"] is False


def test_acquisition_evidence_rejects_plan_hash_or_manifest_drift() -> None:
    source_plan = plan()
    immutable, report = manifest_and_report(source_plan)
    report["source_plan_sha256"] = "0" * 64
    with pytest.raises(
        authoritative.C6AAuthoritativePackError, match="source-plan"
    ):
        authoritative.verify_acquisition_evidence(
            plan=source_plan,
            source_manifest=immutable,
            download_report=report,
        )

    immutable, report = manifest_and_report(source_plan)
    immutable["sources"][0]["url"] = "https://www.okx.com/public/drift.json"
    with pytest.raises(
        authoritative.C6AAuthoritativePackError, match="drift from plan"
    ):
        authoritative.verify_acquisition_evidence(
            plan=source_plan,
            source_manifest=immutable,
            download_report=report,
        )


def test_acquisition_evidence_rejects_download_hash_or_id_drift() -> None:
    source_plan = plan()
    immutable, report = manifest_and_report(source_plan)
    report["sources"][0]["sha256"] = "f" * 64
    with pytest.raises(
        authoritative.C6AAuthoritativePackError,
        match="download report drift",
    ):
        authoritative.verify_acquisition_evidence(
            plan=source_plan,
            source_manifest=immutable,
            download_report=report,
        )

    immutable, report = manifest_and_report(source_plan)
    report["sources"].pop()
    with pytest.raises(
        authoritative.C6AAuthoritativePackError, match="ID sets differ"
    ):
        authoritative.verify_acquisition_evidence(
            plan=source_plan,
            source_manifest=immutable,
            download_report=report,
        )
