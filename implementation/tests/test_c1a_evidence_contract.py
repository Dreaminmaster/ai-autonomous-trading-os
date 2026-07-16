from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "c1a-strategy-family-screen.yml"
EVIDENCE = ROOT / "implementation" / "scripts" / "c1a_evidence.py"
FINALIZER = ROOT / "implementation" / "scripts" / "finalize_c1a_evidence.py"
INVENTORY = ROOT / "implementation" / "scripts" / "c1a_source_inventory.py"
DATA_GUARD = ROOT / "implementation" / "scripts" / "c1a_data_guard.py"


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_workflow_is_ready_only_exact_sha_and_screen_bound() -> None:
    workflow = _text(WORKFLOW)
    assert "types: [ready_for_review]" in workflow
    assert "workflow_dispatch" not in workflow
    assert "C1A_SOURCE_SHA: ${{ github.event.pull_request.head.sha }}" in workflow
    assert "ref: ${{ env.C1A_SOURCE_SHA }}" in workflow
    assert "C1A_DOWNLOAD_TIMERANGE: '20230701-20241001'" in workflow
    assert "--timeframes 1h 1d" in workflow
    assert "--timerange \"$C1A_DOWNLOAD_TIMERANGE\"" in workflow
    assert "2025-07-01" not in workflow
    assert "2026-07-01" not in workflow
    assert "workflow success" not in workflow.lower()


def test_workflow_orders_sanitizer_before_any_research_read() -> None:
    workflow = _text(WORKFLOW)
    ordered = [
        "Download screen data only",
        "Seal API overshoot below C1A boundary",
        "Verify six-cell startup coverage and boundary",
        "Run preregistered fixed-family screen",
        "Capture exact C1A source inventory",
        "Finalize exact-source evidence",
        "Verify retained C1A source inventory",
        "Secret leakage scan",
        "Upload C1A family-screen evidence",
    ]
    positions = [workflow.index(item) for item in ordered]
    assert positions == sorted(positions)
    assert "if: always()" in workflow
    assert "retention-days: 90" in workflow


def test_evidence_runner_executes_exact_cartesian_screen_without_search() -> None:
    source = _text(EVIDENCE)
    tree = ast.parse(source)
    assert "hyperopt" not in source.lower()
    assert "C1A_SOURCE_SHA" in source
    assert "len(source_sha) != 40" in source
    assert "for strategy in config[\"strategies\"]" in source
    assert "for window in config[\"screen_windows\"]" in source
    assert "for multiplier in config[\"fee_multipliers\"]" in source
    assert "len(rows) != 27" in source
    for argument in (
        '"--fee"',
        '"--cache"',
        '"none"',
        '"--export"',
        '"trades"',
        '"--backtest-directory"',
    ):
        assert argument in source
    assert "confirmation_opened=false" in source
    assert '"holdout_state": "HOLDOUT_CLOSED"' in source
    assert '"live": "FORBIDDEN"' in source
    assert "2025-07-01" not in source
    assert "2026-07-01" not in source
    assert any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "evaluate_screen"
        for node in ast.walk(tree)
    )


def test_finalizer_recomputes_gate_and_binds_every_retained_cell() -> None:
    source = _text(FINALIZER)
    assert "evaluate_screen(rows, config)" in source
    assert "len(rows) != 27" in source
    assert "len(cells) != 9" in source
    assert 'command.get("returncode") != 0' in source
    assert 'manifest.get("source_head_sha") != source_sha' in source
    assert 'report.get("source_head_sha") != source_sha' in source
    assert "independent gate recomputation mismatch" in source
    assert '"confirmation_opened": False' in source
    assert '"holdout_state": "HOLDOUT_CLOSED"' in source
    assert '"live": "FORBIDDEN"' in source


def test_source_inventory_snapshots_workflow_runner_finalizer_and_tests() -> None:
    source = _text(INVENTORY)
    required = (
        ".github/workflows/c1a-strategy-family-screen.yml",
        "implementation/scripts/c1a_data_guard.py",
        "implementation/scripts/c1a_evidence.py",
        "implementation/scripts/c1a_source_inventory.py",
        "implementation/scripts/finalize_c1a_evidence.py",
        "implementation/src/atos/c1a_family_screen.py",
        "implementation/tests/test_c1a_data_guard.py",
        "implementation/tests/test_c1a_evidence_contract.py",
        "implementation/tests/test_c1a_family_screen.py",
        "implementation/tests/test_c1a_strategy_contract.py",
    )
    for path in required:
        assert path in source
    assert "shutil.copy2(source, snapshot)" in source
    assert "source_digest != snapshot_digest" in source
    assert "source inventory commit binding mismatch" in source


def test_data_guard_is_fail_closed_at_screen_boundary() -> None:
    source = _text(DATA_GUARD)
    assert "datetime(2024, 10, 1, tzinfo=UTC)" in source
    assert "BEFORE_ANY_RESEARCH_READ" in source
    assert "post-boundary candle" in source
    assert 'config.get("coverage_history_candles") != {"1h": 1499, "1d": 120}' in source
    assert '"holdout_state": "HOLDOUT_CLOSED"' in source
    assert '"live": "FORBIDDEN"' in source
