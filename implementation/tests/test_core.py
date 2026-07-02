"""Test core domain and risk engine via standard atos package."""
from atos.domain import make_hold
from atos.risk import RiskEngine


def test_hold_intent_ok():
    policy = {
        "mode": "paper",
        "allowed_symbols": ["BTC-USDT"],
        "position_limits": {"max_position_pct_per_trade": 1.0},
        "ai_output_limits": {"min_confidence_for_trade": 0.6},
    }
    decision = RiskEngine(policy).evaluate(make_hold("test").to_dict())
    assert decision.decision == "APPROVED"
