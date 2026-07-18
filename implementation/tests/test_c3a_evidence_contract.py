from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
IMPL = ROOT / "implementation"
WORKFLOW = ROOT / ".github/workflows/c3a-residual-mean-reversion.yml"
CONFIG = IMPL / "config/c3a_residual_mean_reversion.json"
PUBLIC_DATA_CONFIG = IMPL / "config/c3a_public_data.json"
EVIDENCE = IMPL / "scripts/c3a_evidence.py"
FINALIZER = IMPL / "scripts/finalize_c3a_evidence.py"
INVENTORY = IMPL / "scripts/c3a_source_inventory.py"
ENGINE_FILES = (
    IMPL / "src/atos/c3a_residual.py",
    IMPL / "src/atos/c3a_residual_common.py",
    IMPL / "src/atos/c3a_residual_indicators.py",
    IMPL / "src/atos/c3a_residual_simulation.py",
    IMPL / "src/atos/c3a_residual_decision.py",
)


def load_inventory_module():
    spec = importlib.util.spec_from_file_location("c3a_source_inventory_test", INVENTORY)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_workflow_is_single_ready_trigger_and_retains_hidden_evidence() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "types: [ready_for_review]" in text
    assert "workflow_dispatch" not in text
    assert "schedule:" not in text
    assert "ref: ${{ env.C3A_SOURCE_SHA }}" in text
    assert "Verify exact source and merge-ref binding" in text
    assert "Run preregistered C3A residual screen" in text
    assert "include-hidden-files: true" in text
    assert "implementation/freqtrade_data/c3a_runtime/**" in text
    assert "C3A_DOWNLOAD_TIMERANGE: '20230901-20241001'" in text
    assert "'.[dev,freqtrade]'" in text
    assert "--config config/c3a_public_data.json" in text
    assert "--timeframes 4h" in text


def test_workflow_orders_guard_evidence_inventory_and_finalizer() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    ordered = [
        "Verify public-data runtime config",
        "Seal API overshoot below C3A boundary",
        "Verify aligned four-hour startup coverage and boundary",
        "Run preregistered C3A residual screen",
        "Capture exact C3A source inventory",
        "Finalize exact-source C3A evidence",
        "Verify retained C3A source inventory",
        "Verify final safety state",
        "Secret leakage scan",
        "Upload C3A residual evidence",
    ]
    positions = [text.index(item) for item in ordered]
    assert positions == sorted(positions)


def test_config_keeps_confirmation_holdout_and_live_closed() -> None:
    payload = json.loads(CONFIG.read_text(encoding="utf-8"))
    assert payload["required_base_sha"] == "f8bacea9785dc51783a51ba06948402dfed1a08f"
    assert payload["confirmation_opened"] is False
    assert payload["c3b_state"] == "CLOSED"
    assert payload["holdout_state"] == "HOLDOUT_CLOSED"
    assert payload["live"] == "FORBIDDEN"
    assert payload["download_timerange"] == "20230901-20241001"
    assert payload["economic_boundary_exclusive"] == "2024-10-01T00:00:00Z"
    assert payload["startup_history_candles"] == 450
    assert len(payload["policies"]) == 3
    assert len(payload["screen_windows"]) == 3
    assert len(payload["cost_rates"]) == 3
    assert payload["expected_policy_rows"] == 27
    assert payload["expected_comparator_rows"] == 36
    assert payload["expected_hidden_pointers"] == 63


def test_public_data_config_is_spot_public_and_non_executable() -> None:
    payload = json.loads(PUBLIC_DATA_CONFIG.read_text(encoding="utf-8"))
    exchange = payload["exchange"]
    assert payload["dry_run"] is True
    assert payload["trading_mode"] == "spot"
    assert payload["margin_mode"] == ""
    assert payload["api_server"]["enabled"] is False
    assert payload["initial_state"] == "stopped"
    assert payload["force_entry_enable"] is False
    assert payload["entry_pricing"]["use_order_book"] is False
    assert payload["exit_pricing"]["use_order_book"] is False
    assert exchange["name"] == "okx"
    assert exchange["key"] == exchange["secret"] == exchange["password"] == ""
    assert exchange["pair_whitelist"] == ["BTC/USDT", "ETH/USDT", "SOL/USDT"]


def test_evidence_requires_exact_frozen_counts() -> None:
    evidence = EVIDENCE.read_text(encoding="utf-8")
    finalizer = FINALIZER.read_text(encoding="utf-8")
    assert "len(policy_rows) != 27" in evidence
    assert "len(comparators) != 36" in evidence
    assert "len(pointers) != 63" in evidence
    assert "len(pointers) == 63" in finalizer
    assert "policy_rows:independent_recompute" in finalizer
    assert "comparator_rows:independent_recompute" in finalizer
    assert "decision:{key}:independent_recompute" in finalizer


def test_effective_source_inventory_is_complete_and_unique() -> None:
    module = load_inventory_module()
    paths = list(module.SOURCE_PATHS)
    assert len(paths) == len(set(paths)) == 20
    assert Path(".github/workflows/c3a-residual-mean-reversion.yml") in paths
    assert Path("implementation/src/atos/c3a_residual.py") in paths
    assert Path("implementation/scripts/finalize_c3a_evidence.py") in paths
    module.validate_source_paths()


def test_executable_c3a_code_does_not_open_closed_periods_or_execution() -> None:
    executable_text = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (
            *ENGINE_FILES,
            EVIDENCE,
            FINALIZER,
            IMPL / "scripts/c3a_data_guard.py",
        )
    ).lower()
    assert '"confirmation_opened": true' not in executable_text
    assert '"live": "allowed"' not in executable_text
    assert "2025-07-01t00:00:00z" not in executable_text
    assert "2026-07-01t00:00:00z" not in executable_text
    assert "create_order" not in executable_text
    assert "fetch_balance" not in executable_text
