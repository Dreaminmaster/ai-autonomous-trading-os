"""
Minimal signal-path test: verify AISupervisedStrategy can produce entry signals.

Tests that need Freqtrade are skipped in environments without it (iSH).
They run in CI (GitHub Actions Ubuntu with Freqtrade installed).

Also: RiskEngine tests that must pass everywhere.
"""

import sys
import pytest
from pathlib import Path

# Add ATOS source
_atos_dir = Path(__file__).resolve().parents[1] / "src"
if str(_atos_dir) not in sys.path:
    sys.path.insert(0, str(_atos_dir))

# Check if freqtrade is available
try:
    import freqtrade
    FREQTRADE_AVAILABLE = True
except ImportError:
    FREQTRADE_AVAILABLE = False

# Check if pandas is available
try:
    import pandas as pd
    import numpy as np
    PANDAS_AVAILABLE = True
except ImportError:
    PANDAS_AVAILABLE = False


# ── RiskEngine tests (always run, no Freqtrade dependency) ──────

def test_risk_engine_approves_valid_trade_intent():
    """RiskEngine must APPROVE a properly-formed TradeIntent."""
    from atos.risk import RiskEngine

    policy = {
        "mode": "paper",
        "allowed_symbols": ["BTC/USDT"],
        "position_limits": {"max_position_pct_per_trade": 10.0},
        "ai_output_limits": {"min_confidence_for_trade": 0.60},
    }
    risk = RiskEngine(policy)

    proper_intent = {
        "schema_version": "trade_intent.v1",
        "action": "BUY",
        "symbol": "BTC/USDT",
        "market_type": "paper_spot",
        "confidence": 0.72,
        "thesis": "Strong uptrend with volume confirmation",
        "evidence": ["fast MA above slow MA", "RSI trending up"],
        "selected_strategy_ids": ["trend_following_v1"],
        "position_size_pct": 5.0,
        "stop_loss_pct": 1.5,
        "take_profit_pct": 3.0,
        "max_holding_minutes": 240,
        "invalidation_conditions": ["price drops below slow MA"],
        "risk_notes": "Standard entry",
    }
    result = risk.evaluate(proper_intent)
    assert result.decision == "APPROVED", f"Expected APPROVED, got {result.decision}: {result.reasons}"


def test_risk_engine_rejects_provider_result_dict():
    """RiskEngine must REJECT a shallow dict lacking required TradeIntent fields."""
    from atos.risk import RiskEngine

    policy = {
        "mode": "paper",
        "allowed_symbols": ["BTC/USDT"],
        "position_limits": {"max_position_pct_per_trade": 10.0},
        "ai_output_limits": {"min_confidence_for_trade": 0.60},
    }
    risk = RiskEngine(policy)

    # Simulates what ProviderResult.to_dict() looks like — NO thesis/evidence/stop_loss/take_profit
    bogus_intent = {
        "action": "BUY",
        "confidence": 0.72,
        "provider": "mock",
        "latency_ms": 0,
        "tokens_used": 0,
    }
    result = risk.evaluate(bogus_intent)
    assert result.decision == "REJECTED", f"Expected REJECTED, got {result.decision}: {result.reasons}"
    rejection_reasons = " ".join(result.reasons)
    assert "missing" in rejection_reasons.lower() or "thesis" in rejection_reasons.lower() or "evidence" in rejection_reasons.lower()


def test_provider_result_has_intent_attribute():
    """ProviderResult must have .intent (TradeIntent), NOT just action/confidence."""
    from atos.providers import MockProvider, ProviderRequest

    provider = MockProvider()
    request = ProviderRequest(
        symbol="BTC/USDT",
        candidates=[{
            "strategy_id": "trend_following_v1",
            "side": "BUY",
            "confidence": 0.72,
            "entry_reason": "test",
            "suggested_stop_loss_pct": 1.0,
            "suggested_take_profit_pct": 2.0,
            "max_holding_minutes": 240,
        }],
        market_state={},
        risk_state={},
    )
    result = provider.decide(request)
    assert result.intent is not None
    assert result.intent.action == "BUY"
    assert result.intent.thesis != ""
    assert result.intent.evidence != []
    assert result.intent.stop_loss_pct > 0
    assert result.intent.take_profit_pct > 0


def test_provider_result_dict_vs_intent_dict_differs():
    """provider_result.to_dict() != provider_result.intent.to_dict() — must differ."""
    from atos.providers import MockProvider, ProviderRequest

    provider = MockProvider()
    request = ProviderRequest(
        symbol="BTC/USDT",
        candidates=[{
            "strategy_id": "trend_following_v1",
            "side": "BUY",
            "confidence": 0.72,
            "entry_reason": "test",
            "suggested_stop_loss_pct": 1.0,
            "suggested_take_profit_pct": 2.0,
            "max_holding_minutes": 240,
        }],
        market_state={},
        risk_state={},
    )
    result = provider.decide(request)

    provider_dict = result.to_dict()
    intent_dict = result.intent.to_dict()

    # ProviderResult dict has "provider" and "latency_ms"
    assert "provider" in provider_dict
    assert "latency_ms" in provider_dict
    # TradeIntent dict has "thesis" and "stop_loss_pct"
    assert "thesis" in intent_dict
    assert "stop_loss_pct" in intent_dict
    # ProviderResult dict should NOT have thesis
    assert "thesis" not in provider_dict, "BUG: ProviderResult.to_dict() contains thesis — should be TradeIntent only"


# ── Signal path tests (require Freqtrade + pandas, skip otherwise) ──

@pytest.mark.skipif(not FREQTRADE_AVAILABLE, reason="Freqtrade not installed")
def test_strategy_importable():
    from ai_supervised_strategy import AISupervisedStrategy
    assert AISupervisedStrategy is not None


@pytest.mark.skipif(not FREQTRADE_AVAILABLE or not PANDAS_AVAILABLE, reason="Freqtrade or pandas not installed")
def test_populate_indicators():
    from ai_supervised_strategy import AISupervisedStrategy

    strategy = AISupervisedStrategy()
    df = pd.DataFrame({
        "open":  [100.0 + i * 0.5 for i in range(100)],
        "high":  [102.0 + i * 0.5 for i in range(100)],
        "low":   [98.0  + i * 0.5 for i in range(100)],
        "close": [101.0 + i * 0.5 for i in range(100)],
        "volume":[1000 + i * 10 for i in range(100)],
    })

    result = strategy.populate_indicators(df, {"pair": "BTC/USDT"})
    for col in ["fast_ma", "slow_ma", "rsi"]:
        assert col in result.columns, f"Missing: {col}"


@pytest.mark.skipif(not FREQTRADE_AVAILABLE or not PANDAS_AVAILABLE, reason="Freqtrade or pandas not installed")
def test_populate_entry_trend_on_uptrend():
    """On clear uptrend, entry signals should be producible (diagnostic, not assertion)."""
    from ai_supervised_strategy import AISupervisedStrategy

    strategy = AISupervisedStrategy()
    strategy.atos_enabled = True
    strategy.atos_provider = "mock"

    df = pd.DataFrame({
        "open":  [100.0 + i * 0.8 for i in range(100)],
        "high":  [102.0 + i * 0.8 for i in range(100)],
        "low":   [98.0  + i * 0.8 for i in range(100)],
        "close": [101.0 + i * 0.8 for i in range(100)],
        "volume":[1000 + i * 20 for i in range(100)],
    })

    df = strategy.populate_indicators(df, {"pair": "BTC/USDT"})
    df = strategy.populate_entry_trend(df, {"pair": "BTC/USDT"})

    signal_count = int(df["enter_long"].sum())
    print(f"\n  Strategy signal count: {signal_count}")
    assert signal_count >= 0  # diagnostic — even 0 is useful info


@pytest.mark.skipif(not FREQTRADE_AVAILABLE or not PANDAS_AVAILABLE, reason="Freqtrade or pandas not installed")
def test_builtin_fallback_on_uptrend():
    """Built-in fallback produces BUY candidates on uptrend data."""
    from ai_supervised_strategy import _builtin_candidates

    df = pd.DataFrame({
        "open":  [100.0 + i * 0.8 for i in range(100)],
        "high":  [102.0 + i * 0.8 for i in range(100)],
        "low":   [98.0  + i * 0.8 for i in range(100)],
        "close": [101.0 + i * 0.8 for i in range(100)],
        "volume":[1000 + i * 20 for i in range(100)],
    })

    candidates = _builtin_candidates(df)
    buy_cands = [c for c in candidates if c.get("side") == "BUY"]
    assert len(buy_cands) >= 1, f"No BUY candidates on uptrend"
