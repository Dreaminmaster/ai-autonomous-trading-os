from __future__ import annotations

import json
from pathlib import Path

import pytest

from atos.c6a_contract import C6AError
from atos.c6a_execution_contract_v2 import (
    EXPECTED_ENTRYPOINTS,
    EXPECTED_ORDER,
    EXPECTED_SCAFFOLDS,
    validate_execution_contract_v2,
)
from scripts import c6a_execution_guard_v2

IMPL = Path(__file__).resolve().parents[1]
CONFIG = IMPL / "config/c6a_execution_contract_v2.json"


def payload() -> dict:
    return json.loads(CONFIG.read_text(encoding="utf-8"))


def test_repository_final_execution_contract_is_exact_and_complete() -> None:
    current = payload()
    digest = validate_execution_contract_v2(current, implementation_root=IMPL)
    assert len(digest) == 64
    assert current["authoritative_entrypoints"] == EXPECTED_ENTRYPOINTS
    assert tuple(current["required_order"]) == EXPECTED_ORDER
    assert tuple(current["non_authoritative_scaffolds"]) == EXPECTED_SCAFFOLDS
    report = c6a_execution_guard_v2.verify(CONFIG)
    assert report["status"] == "PASS"
    assert report["schema_version"] == 2
    assert report["authoritative_entrypoint_count"] == 11
    assert report["c6b_state"] == "C6B_CLOSED"
    assert report["live"] == "FORBIDDEN"


def test_final_execution_contract_rejects_role_order_and_safety_drift() -> None:
    current = payload()
    current["authoritative_entrypoints"]["source_inventory"] = (
        "scripts/c6a_authoritative_source_inventory_v2.py"
    )
    with pytest.raises(C6AError, match="entrypoint map"):
        validate_execution_contract_v2(current)

    current = payload()
    current["required_order"].reverse()
    with pytest.raises(C6AError, match="order drift"):
        validate_execution_contract_v2(current)

    current = payload()
    current["confirmation_opened"] = True
    with pytest.raises(C6AError, match="safety-state"):
        validate_execution_contract_v2(current)


def test_final_execution_contract_rejects_missing_file(tmp_path: Path) -> None:
    current = payload()
    required = set(EXPECTED_ENTRYPOINTS.values()) | set(EXPECTED_SCAFFOLDS)
    for relative in required:
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("pass\n", encoding="utf-8")
    (tmp_path / EXPECTED_ENTRYPOINTS["source_inventory"]).unlink()
    with pytest.raises(C6AError, match="missing or unsafe"):
        validate_execution_contract_v2(current, implementation_root=tmp_path)
