from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
IMPL = ROOT / "implementation"
ACTIVE_WORKFLOW = ROOT / ".github/workflows/c2a-low-turnover-allocation.yml"
ARCHIVED_WORKFLOW = (
    ROOT
    / "docs/architecture/phase-c/c2a-low-turnover-allocation/archive/C2A_AUTHORITATIVE_WORKFLOW_V1.yml"
)
CONFIG = IMPL / "config/c2a_low_turnover_allocation.json"
PUBLIC_DATA_CONFIG = IMPL / "config/c2a_public_data.json"
EVIDENCE = IMPL / "scripts/c2a_evidence.py"
FINALIZER = IMPL / "scripts/finalize_c2a_evidence.py"
INVENTORY = IMPL / "scripts/c2a_source_inventory.py"
RUNTIME = IMPL / "src/atos/c2a_allocation_runtime.py"


def load_inventory_module():
    spec = importlib.util.spec_from_file_location("c2a_source_inventory_test", INVENTORY)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_authoritative_workflow_is_archived_and_no_longer_active() -> None:
    assert not ACTIVE_WORKFLOW.exists()
    text = ARCHIVED_WORKFLOW.read_text(encoding="utf-8")
    assert "types: [ready_for_review]" in text
    assert "workflow_dispatch" not in text
    assert "schedule:" not in text
    assert "ref: ${{ env.C2A_SOURCE_SHA }}" in text
    assert "Verify exact source and merge-ref binding" in text
    assert "Run preregistered C2A allocation screen" in text
    assert "include-hidden-files: true" in text
    assert "implementation/freqtrade_data/c2a_runtime/**" in text
    assert "C2A_DOWNLOAD_TIMERANGE: '20230501-20241001'" in text
    assert "'.[dev,freqtrade]'" in text
    assert "scripts/setup_freqtrade.sh" not in text
    assert "--config config/c2a_public_data.json" in text


def test_archived_workflow_orders_guard_evidence_inventory_and_finalizer() -> None:
    text = ARCHIVED_WORKFLOW.read_text(encoding="utf-8")
    ordered = [
        "Verify public-data runtime config",
        "Seal API overshoot below C2A boundary",
        "Verify three-cell startup coverage and boundary",
        "Run preregistered C2A allocation screen",
        "Capture exact C2A source inventory",
        "Finalize exact-source C2A evidence",
        "Verify retained C2A source inventory",
        "Verify final safety state",
        "Secret leakage scan",
        "Upload C2A allocation evidence",
    ]
    positions = [text.index(item) for item in ordered]
    assert positions == sorted(positions)


def test_config_keeps_confirmation_holdout_and_live_closed() -> None:
    payload = json.loads(CONFIG.read_text(encoding="utf-8"))
    assert payload["required_base_sha"] == "995dc9aac3c934c01e196270fc2d41d50278063b"
    assert payload["confirmation_opened"] is False
    assert payload["holdout_state"] == "HOLDOUT_CLOSED"
    assert payload["live"] == "FORBIDDEN"
    assert payload["download_timerange"] == "20230501-20241001"
    assert payload["economic_boundary_exclusive"] == "2024-10-01T00:00:00Z"
    assert len(payload["policies"]) == 3
    assert len(payload["screen_windows"]) == 3
    assert len(payload["cost_rates"]) == 3
    assert payload["reserved_confirmation_windows"] == [
        {"id": "C1", "start": "2024-10-01", "end": "2025-01-01"},
        {"id": "C2", "start": "2025-01-01", "end": "2025-04-01"},
        {"id": "C3", "start": "2025-04-01", "end": "2025-07-01"},
    ]


def test_public_data_config_is_spot_public_and_non_executable() -> None:
    payload = json.loads(PUBLIC_DATA_CONFIG.read_text(encoding="utf-8"))
    exchange = payload["exchange"]
    assert payload["dry_run"] is True
    assert payload["trading_mode"] == "spot"
    assert payload["margin_mode"] == ""
    assert payload["api_server"]["enabled"] is False
    assert payload["initial_state"] == "stopped"
    assert payload["force_entry_enable"] is False
    assert exchange["name"] == "okx"
    assert exchange["key"] == exchange["secret"] == exchange["password"] == ""
    assert exchange["pair_whitelist"] == ["BTC/USDT", "ETH/USDT", "SOL/USDT"]


def test_evidence_requires_exact_27_rows_and_54_hidden_pointers() -> None:
    evidence = EVIDENCE.read_text(encoding="utf-8")
    finalizer = FINALIZER.read_text(encoding="utf-8")
    assert "len(policy_rows) != 27" in evidence
    assert "C2A must retain exactly 27 unique economic rows" in evidence
    assert 'directory / ".last_result.json"' in evidence
    assert "len(pointers) != 54" in finalizer
    assert "expected 54 retained pointers" in finalizer
    assert "economic_rows:independent_recompute" in finalizer
    assert "decision:independent_recompute" in finalizer


def test_runtime_patch_is_explicit_source_bound_and_narrow() -> None:
    text = RUNTIME.read_text(encoding="utf-8")
    assert "_normalized_targets" in text
    assert "_base._execute_target = _execute_target" in text
    assert "simulate_window = _base.simulate_window" in text
    assert "decide = _base.decide" in text
    assert "turnover_cap" in text
    assert "normalized targets exceed one" in text


def test_effective_source_inventory_is_complete_and_unique() -> None:
    module = load_inventory_module()
    paths = list(module.SOURCE_PATHS)
    expected = {
        Path(
            "docs/architecture/phase-c/c2a-low-turnover-allocation/archive/"
            "C2A_AUTHORITATIVE_WORKFLOW_V1.yml"
        ),
        Path("docs/architecture/phase-c/c2a-low-turnover-allocation/C2A_LOW_TURNOVER_ALLOCATION_CONTRACT_V1.md"),
        Path("docs/architecture/phase-c/c2a-low-turnover-allocation/C2A_WINDOW_ACCOUNTING_ADDENDUM_V1.md"),
        Path("docs/architecture/phase-c/c1a-family-screen/C1A_STRATEGY_FAMILY_SCREEN_RESULT_V1.md"),
        Path("implementation/config/c2a_low_turnover_allocation.json"),
        Path("implementation/config/c2a_public_data.json"),
        Path("implementation/src/atos/c2a_allocation.py"),
        Path("implementation/src/atos/c2a_allocation_runtime.py"),
        Path("implementation/scripts/c2a_data_guard.py"),
        Path("implementation/scripts/c2a_evidence.py"),
        Path("implementation/scripts/c2a_source_inventory.py"),
        Path("implementation/scripts/finalize_c2a_evidence.py"),
        Path("implementation/tests/conftest.py"),
        Path("implementation/tests/test_c2a_allocation.py"),
        Path("implementation/tests/test_c2a_data_guard.py"),
        Path("implementation/tests/test_c2a_evidence_contract.py"),
        Path("implementation/pyproject.toml"),
    }
    assert len(paths) == len(set(paths))
    assert expected == set(paths)
    module.validate_source_paths()


def test_executable_c2a_code_does_not_read_closed_periods_or_enable_execution() -> None:
    executable_text = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (
            EVIDENCE,
            FINALIZER,
            RUNTIME,
            IMPL / "scripts/c2a_data_guard.py",
            IMPL / "src/atos/c2a_allocation.py",
        )
    )
    assert '"confirmation_opened": true' not in executable_text.lower()
    assert '"live": "allowed"' not in executable_text.lower()
    assert "2025-07-01" not in executable_text
    assert "2026-07-01" not in executable_text
