from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "implementation" / "scripts" / "c1a_contract_completion.py"
WORKFLOW = ROOT / ".github" / "workflows" / "c1a-strategy-family-screen.yml"
C0C_RESULT = (
    ROOT
    / "docs"
    / "architecture"
    / "phase-c"
    / "c0c"
    / "C0C_COST_AWARE_EMA_RESULT_V1.md"
)


def _module():
    spec = importlib.util.spec_from_file_location("c1a_contract_completion", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _runtime_payload() -> dict:
    return {
        "dry_run": True,
        "trading_mode": "spot",
        "max_open_trades": 3,
        "stake_currency": "USDT",
        "stake_amount": 300.0,
        "dry_run_wallet": 1000.0,
        "tradable_balance_ratio": 1.0,
        "force_entry_enable": False,
        "initial_state": "stopped",
        "exchange": {
            "name": "okx",
            "key": "",
            "secret": "",
            "password": "",
            "pair_whitelist": ["BTC/USDT", "ETH/USDT", "SOL/USDT"],
        },
        "api_server": {"enabled": False},
    }


def test_frozen_c0c_context_is_non_selectable_and_document_bound() -> None:
    module = _module()
    context = module.frozen_c0c_context()
    assert context["status"] == "REJECTED"
    assert context["selectable"] is False
    assert context["development_test_opened"] is False
    assert context["candidate_source_sha"] == "c93c548ed7d22c90fbc729dbb3022ee9e7c579c1"
    assert context["workflow_run"] == "29472584256"
    assert context["artifact_id"] == "8365664976"
    assert context["result_document_sha256"] == module.sha256_file(C0C_RESULT)
    assert context["basis"] == "FROZEN_RESULT_DOCUMENT_NO_RERUN"
    assert context["holdout_state"] == "HOLDOUT_CLOSED"
    assert context["live"] == "FORBIDDEN"


def test_effective_runtime_config_is_fail_closed() -> None:
    module = _module()
    payload = _runtime_payload()
    module.validate_runtime_config_payload(payload)
    payload["dry_run"] = False
    with pytest.raises(module.C1AContractCompletionError, match="spot dry-run"):
        module.validate_runtime_config_payload(payload)


def test_effective_source_set_includes_comparator_runtime_and_verifier() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    for required in (
        "C0C_COST_AWARE_EMA_RESULT_V1.md",
        "freqtrade_data/c1a_runtime/config.c1a.json",
        "scripts/c1a_contract_completion.py",
        "tests/test_c1a_contract_completion.py",
        "contract:frozen_c0c_comparator_bound",
        "contract:source_inventory_snapshot_verified",
    ):
        assert required in source


def test_workflow_applies_and_verifies_completion_around_finalizer() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    ordered = [
        "Run preregistered fixed-family screen",
        "Apply frozen comparator and effective-source bindings",
        "Capture exact C1A source inventory",
        "Finalize exact-source evidence",
        "Verify retained C1A source inventory",
        "Verify frozen comparator and effective-source bindings",
        "Secret leakage scan",
    ]
    positions = [workflow.index(item) for item in ordered]
    assert positions == sorted(positions)
    assert "python scripts/c1a_contract_completion.py apply" in workflow
    assert "python scripts/c1a_contract_completion.py verify" in workflow
    assert "tests/test_c1a_contract_completion.py" in workflow
