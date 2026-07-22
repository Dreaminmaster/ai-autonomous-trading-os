from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts import c6a_authoritative_source_inventory_v3 as v3


def source_plan() -> dict:
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
            is_candle = kind.endswith("candles")
            url = (
                "https://www.okx.com/api/v5/market/history-mark-price-candles"
                if kind == "swap_mark_candles"
                else "https://www.okx.com/api/v5/market/history-candles"
                if is_candle
                else f"https://www.okx.com/historical-data/{kind}-{instrument}.json"
            )
            rows.append(
                {
                    "source_id": f"{kind}-{instrument}",
                    "kind": kind,
                    "instrument": instrument,
                    "url": url,
                    "coverage_start": "2023-06-05T00:00:00Z",
                    "coverage_end_exclusive": "2025-12-29T00:00:00Z",
                    "content_type": "application/x-ndjson" if is_candle else "application/json",
                    "request_mode": "PAGINATED_PUBLIC_API" if is_candle else "SINGLE_OBJECT",
                    "bar": "1H" if is_candle else None,
                    "limit": 100 if is_candle else None,
                }
            )
    return {
        "schema_version": 1,
        "stage": "C6A",
        "authenticated": False,
        "economic_boundary_exclusive": "2025-12-29T00:00:00Z",
        "sources": rows,
    }


def execution_contract() -> dict:
    return {
        "schema_version": 2,
        "stage": "C6A",
        "status": "IMPLEMENTATION_PENDING",
        "required_design_main_sha": "071e45218e299367f3bef18832d931df7d278ace",
        "authoritative_entrypoints": dict(v3.validate_execution_contract_v2.__globals__["EXPECTED_ENTRYPOINTS"]),
        "non_authoritative_scaffolds": list(v3.validate_execution_contract_v2.__globals__["EXPECTED_SCAFFOLDS"]),
        "required_order": list(v3.validate_execution_contract_v2.__globals__["EXPECTED_ORDER"]),
        "economic_result_run": False,
        "confirmation_opened": False,
        "c6b_state": "C6B_CLOSED",
        "c5b_state": "C5B_CLOSED_AND_UNTOUCHED",
        "holdout_state": "HOLDOUT_CLOSED",
        "paper_state": "PAPER_CLOSED",
        "shadow_state": "SHADOW_CLOSED",
        "live": "FORBIDDEN",
    }


def repo_fixture(root: Path) -> tuple[str, Path, Path]:
    workflow = ".github/workflows/c6a-authoritative.yml"
    workflow_path = root / workflow
    workflow_path.parent.mkdir(parents=True)
    workflow_path.write_text("name: C6A\n", encoding="utf-8")
    for relative in v3.workflow_inventory.base.DESIGN_FILES:
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("design\n", encoding="utf-8")
    for relative in v3.workflow_inventory.base.EXACT_IMPLEMENTATION_FILES:
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("implementation\n", encoding="utf-8")
    for index in range(24):
        path = root / f"implementation/src/atos/c6a_fixture_{index:02d}.py"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"VALUE={index}\n", encoding="utf-8")
    plan_path = root / "implementation/config/c6a_public_source_plan.json"
    plan_path.parent.mkdir(parents=True, exist_ok=True)
    plan_path.write_text(json.dumps(source_plan()), encoding="utf-8")
    execution_path = root / "implementation/config/c6a_execution_contract_v2.json"
    execution_path.write_text(json.dumps(execution_contract()), encoding="utf-8")
    for relative in set(execution_contract()["authoritative_entrypoints"].values()) | set(
        execution_contract()["non_authoritative_scaffolds"]
    ):
        path = root / "implementation" / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("pass\n", encoding="utf-8")
    return workflow, plan_path, execution_path


def test_v3_inventory_binds_both_plans_and_excludes_workflow_from_economic_source(
    tmp_path: Path,
) -> None:
    workflow, plan_path, execution_path = repo_fixture(tmp_path)
    payload = v3.build_inventory_v3(
        root=tmp_path,
        source_sha="a" * 40,
        workflow_path=workflow,
        plan_path=plan_path,
        execution_contract_path=execution_path,
    )
    paths = {row["path"] for row in payload["files"]}
    assert "implementation/config/c6a_public_source_plan.json" in paths
    assert "implementation/config/c6a_execution_contract_v2.json" in paths
    assert payload["source_plan_in_economic_source_inventory"] is True
    assert payload["execution_contract_in_economic_source_inventory"] is True
    assert payload["source_plan"]["entry_count"] == 12
    assert len(payload["execution_contract"]["canonical_sha256"]) == 64
    assert payload["temporary_workflow"]["economic_source"] is False
    assert workflow not in paths


def test_v3_inventory_rejects_external_or_invalid_contract(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    workflow, plan_path, execution_path = repo_fixture(root)
    outside = tmp_path / "outside.json"
    outside.write_text(json.dumps(execution_contract()), encoding="utf-8")
    with pytest.raises(v3.C6AAuthoritativeInventoryV3Error, match="inside"):
        v3.build_inventory_v3(
            root=root,
            source_sha="b" * 40,
            workflow_path=workflow,
            plan_path=plan_path,
            execution_contract_path=outside,
        )

    payload = execution_contract()
    payload["live"] = "OPEN"
    execution_path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(Exception, match="safety-state"):
        v3.build_inventory_v3(
            root=root,
            source_sha="b" * 40,
            workflow_path=workflow,
            plan_path=plan_path,
            execution_contract_path=execution_path,
        )
