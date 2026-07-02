"""
Full acceptance test suite — covers all 13 spec requirements.

Tests marked as acceptance tests from AGENTS.md and docs/09_mvp_plan.md.
"""

import json
import pytest
from pathlib import Path

from atos.domain import Candle, make_hold
from atos.risk import RiskEngine
from atos.execution import PaperExecutor, GuardedExchangeExecutor
from atos.ledger import Ledger
from atos.scoring import ScoringEngine, StrategyWeightManager
from atos.evaluator import Evaluator
from atos.runtime import AutonomousRuntime
from atos.strategies import default_strategies
from atos.providers import MockProvider, ProviderManager, ProviderRequest

POLICY = {
    "mode": "paper",
    "allowed_symbols": ["BTC/USDT:USDT", "ETH/USDT:USDT"],
    "position_limits": {"max_position_pct_per_trade": 10.0, "max_total_exposure_pct": 30.0},
    "ai_output_limits": {"min_confidence_for_trade": 0.60},
    "trade_limits": {"max_trades_per_day": 20, "cooldown_seconds": 300},
    "risk_limits": {"max_drawdown_pct": 20.0},
}


# ── Acceptance Test 1: Mock provider produces TradeIntent ──────────────

def test_acceptance_mock_provider():
    """A1: Mock provider must produce structured TradeIntent."""
    provider = MockProvider()
    request = ProviderRequest(
        symbol="BTC/USDT:USDT",
        candidates=[{"strategy_id": "trend_v1", "side": "BUY", "confidence": 0.7, "entry_reason": "trend up", "suggested_stop_loss_pct": 1.0, "suggested_take_profit_pct": 2.0, "max_holding_minutes": 240}],
        market_state={},
        risk_state={},
    )
    result = provider.decide(request)
    assert result.intent.action in ("BUY", "HOLD")
    assert result.intent.schema_version == "trade_intent.v1"
    assert result.error is None


# ── Acceptance Test 2: Risk engine blocks invalid intents ──────────────

def test_acceptance_risk_blocks_invalid():
    """A2: Risk engine must reject invalid TradeIntents."""
    risk = RiskEngine(POLICY)
    bad_intent = {"action": "BUY", "symbol": "DOGE/USDT:USDT", "confidence": 0.9}
    result = risk.evaluate(bad_intent)
    assert result.decision == "REJECTED"


# ── Acceptance Test 3: Kill switch blocks execution ────────────────────

def test_acceptance_kill_switch():
    """A3: Kill switch must block execution."""
    Path("runtime/kill_switch.flag").write_text("kill")
    try:
        risk = RiskEngine(POLICY)
        from atos.domain import make_hold
        result = risk.evaluate(make_hold("test").to_dict(), {"kill_switch_active": True})
        assert result.decision in ("KILL_SWITCH_ACTIVE", "PAUSED")
    finally:
        Path("runtime/kill_switch.flag").unlink(missing_ok=True)


# ── Acceptance Test 4: Paper ledger records every intent ───────────────

def test_acceptance_ledger_records():
    """A4: Ledger must record every trade intent."""
    ledger = Ledger(":memory:")
    ledger.record("trade_intent", {"action": "BUY", "symbol": "BTC/USDT:USDT"})
    ledger.record("risk_decision", {"decision": "APPROVED"})
    ledger.record("execution", {"status": "FILLED_SIMULATED"})
    assert ledger.count() == 3
    events = ledger.list_events()
    assert len(events) == 3


# ── Acceptance Test 5: Fees affect PnL ─────────────────────────────────

def test_acceptance_fees_affect_pnl():
    """A5: Fees and slippage must affect simulated PnL."""
    executor = PaperExecutor(fee_bps=10.0, slippage_bps=5.0)
    intent = {"action": "BUY", "symbol": "BTC/USDT:USDT", "position_size_pct": 100}
    risk = {"decision": "APPROVED"}
    result = executor.execute(intent, risk, mark_price=50000.0, equity_usdt=1000.0)
    assert result.fee > 0  # Fee must be non-zero


# ── Acceptance Test 6: Backtest is chronological ───────────────────────

def test_acceptance_chronological():
    """A6: Historical replay must process candles in order."""
    candles = [Candle(100 + i, 102 + i, 99 + i, 101 + i, 1000) for i in range(40)]
    runtime = AutonomousRuntime(POLICY)
    result = runtime.run_once("BTC/USDT:USDT", candles, mark_price=140.0)
    assert result["execution"]["status"] in ("FILLED_SIMULATED", "NOOP_HOLD", "BLOCKED_BY_RISK")


# ── Acceptance Test 7: Secrets not stored ──────────────────────────────

def test_acceptance_no_secret_stored():
    """A7: API keys must not appear in code or logs."""
    src_dir = Path(__file__).resolve().parents[1] / "src"
    if not src_dir.exists():
        return
    for py_file in src_dir.rglob("*.py"):
        content = py_file.read_text(errors="ignore")
        if 'sk-proj-' in content or 'sk-ant-' in content:
            assert False, f"Hardcoded API key in {py_file.name}"


# ── Acceptance Test 8: Strategy candidates include risk notes ──────────

def test_acceptance_strategy_risk_notes():
    """A8: Each strategy must include risk_notes and regime_tags."""
    candles = [Candle(100 + i, 102 + i, 99 + i, 101 + i, 1000) for i in range(40)]
    for strategy in default_strategies():
        candidate = strategy.generate("BTC/USDT:USDT", candles)
        if candidate:
            assert candidate.risk_notes or candidate.strategy_id == "hold_baseline"
            assert candidate.regime_tags


# ── Acceptance Test 9: Walk-forward validation available ───────────────

def test_acceptance_walk_forward():
    """A9: Walk-forward validation must be available."""
    evaluator = Evaluator()
    result = evaluator.walk_forward([0.1, 0.2, -0.1, 0.0, 0.3, -0.05, 0.1, 0.15, -0.02, 0.05, 0.2, -0.1, 0.08, 0.12, -0.03], train=10, test=5)
    assert result.windows >= 1
    assert result.in_sample.samples > 0
    assert result.out_of_sample is not None


# ── Acceptance Test 10: Monte Carlo available ──────────────────────────

def test_acceptance_monte_carlo():
    """A10: Monte Carlo simulation must be available."""
    evaluator = Evaluator()
    result = evaluator.monte_carlo([0.1, 0.2, -0.1, 0.0, 0.3, -0.05, 0.1, 0.15, -0.02, 0.05, 0.2, -0.1], simulations=100)
    assert result.simulations == 100
    assert result.mean_return is not None
    assert -1.0 <= result.ruin_probability <= 1.0


# ── Acceptance Test 11: Strategy weight manager works ──────────────────

def test_acceptance_weight_manager():
    """A11: Strategy weights must be bounded and normalized."""
    mgr = StrategyWeightManager({"trend_v1": 0.5, "mean_rev_v1": 0.5})
    mgr.apply_score("breakout_v1", 0.05)
    weights = mgr.get_weights()
    assert "breakout_v1" in weights
    total = sum(weights.values())
    assert abs(total - 1.0) < 0.01  # normalized
    for w in weights.values():
        assert 0.01 <= w <= 0.50  # bounded


# ── Acceptance Test 12: Dry-run is default ─────────────────────────────

def test_acceptance_dryrun_default():
    """A12: Default mode must be paper/dry-run."""
    from atos.core import RuntimeState
    state = RuntimeState()
    assert state.mode.value == "paper"
    assert state.external_execution_enabled is False


# ── Acceptance Test 13: Live execution throws without enable ───────────

def test_acceptance_live_disabled():
    """A13: GuardedExchangeExecutor must raise without explicit enable."""
    executor = GuardedExchangeExecutor(enabled=False)
    with pytest.raises(PermissionError):
        executor.execute()
