import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / 'python'
sys.path.insert(0, str(ROOT))

from models import hold_intent
from risk_engine import RiskEngine


def test_hold_intent_ok():
    policy = {'mode': 'paper', 'allowed_symbols': ['BTC-USDT'], 'position_limits': {'max_position_pct_per_trade': 1.0}, 'ai_output_limits': {'min_confidence_for_trade': 0.6}}
    decision = RiskEngine(policy).evaluate(hold_intent('test').to_dict())
    assert decision.decision == 'APPROVED'
