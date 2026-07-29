from pathlib import Path

import yaml

from atos.freqtrade_timeout_policy import (
    BACKTEST_TIMEOUT_SECONDS,
    LOOKAHEAD_TIMEOUT_SECONDS,
    LOOKAHEAD_WRAPPER_TIMEOUT_SECONDS,
)

ROOT = Path(__file__).resolve().parents[2]
IMPLEMENTATION = ROOT / "implementation"
WORKFLOW = ROOT / ".github" / "workflows" / "freqtrade-validation.yml"


def test_lookahead_budget_exceeds_observed_2100_second_timeout() -> None:
    assert BACKTEST_TIMEOUT_SECONDS == 900
    assert LOOKAHEAD_TIMEOUT_SECONDS >= 3000
    assert LOOKAHEAD_WRAPPER_TIMEOUT_SECONDS > LOOKAHEAD_TIMEOUT_SECONDS


def test_existing_runners_consume_the_shared_timeout_policy() -> None:
    canonical = (IMPLEMENTATION / "scripts" / "run_canonical_backtest.py").read_text()
    round_one = (IMPLEMENTATION / "scripts" / "ci_strategy_fix_round1.py").read_text()
    assert "timeout=BACKTEST_TIMEOUT_SECONDS" in canonical
    assert "timeout=LOOKAHEAD_TIMEOUT_SECONDS" in canonical
    assert "timeout=BACKTEST_TIMEOUT_SECONDS" in round_one
    assert "timeout=LOOKAHEAD_WRAPPER_TIMEOUT_SECONDS" in round_one
    assert "timeout=2100" not in canonical


def test_strategy_step_can_contain_two_complete_lookahead_wrappers() -> None:
    workflow = yaml.safe_load(WORKFLOW.read_text())
    steps = workflow["jobs"]["freqtrade"]["steps"]
    strategy = next(step for step in steps if step.get("name") == "Strategy Fix Round 1 (canonical)")
    budget_seconds = int(strategy["timeout-minutes"]) * 60
    assert strategy["timeout-minutes"] == 180
    assert budget_seconds >= 2 * LOOKAHEAD_WRAPPER_TIMEOUT_SECONDS
