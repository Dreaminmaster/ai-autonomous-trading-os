from __future__ import annotations

import argparse
import json
from pathlib import Path

from models import hold_intent
from risk_engine import RiskEngine
from run_demo import make_candidates
from decision_layer import MockDecisionLayer
from paper_executor import PaperExecutor
from ledger_store import LedgerStore
from market_data import PublicMarketDataAdapter
from review_layer import ReviewLayer


def load_policy(path: str) -> dict:
    return json.loads(Path(path).read_text(encoding='utf-8'))


def command_status(policy: dict) -> dict:
    return {
        'status': 'ok',
        'mode': policy.get('mode', 'paper'),
        'default_real_orders': False,
        'components': ['strategy_pool', 'decision_layer', 'risk_engine', 'paper_executor', 'ledger', 'market_data', 'review_layer'],
    }


def command_risk(policy: dict) -> dict:
    intent = hold_intent('risk self-check').to_dict()
    return RiskEngine(policy).evaluate(intent, {'mode': policy.get('mode', 'paper')}).to_dict()


def command_cycle(policy: dict) -> dict:
    candidates = make_candidates()
    intent = MockDecisionLayer().decide('BTC-USDT', candidates)
    risk = RiskEngine(policy).evaluate(intent.to_dict(), {'mode': policy.get('mode', 'paper')})
    result = PaperExecutor().execute(intent.to_dict(), risk.to_dict(), mark_price=106.0, equity_usdt=1000.0)
    ledger = LedgerStore()
    ledger.record('candidates', {'items': candidates})
    ledger.record('intent', intent.to_dict())
    ledger.record('risk', risk.to_dict())
    ledger.record('result', result.to_dict())
    return {'candidates': candidates, 'intent': intent.to_dict(), 'risk': risk.to_dict(), 'result': result.to_dict(), 'ledger_events': ledger.count()}


def command_market(symbol: str) -> dict:
    adapter = PublicMarketDataAdapter()
    snap = adapter.snapshot(symbol)
    return {
        'symbol': snap.symbol,
        'ticker': snap.ticker,
        'candles_count': len(snap.candles),
        'orderbook': snap.orderbook,
    }


def command_review() -> dict:
    return ReviewLayer().daily_review({
        'trend_following_v1': [0.3, -0.1, 0.2, 0.1, -0.05, 0.4, 0.0, 0.1, -0.2, 0.25],
        'mean_reversion_v1': [-0.2, -0.1, 0.05, -0.05, -0.1, 0.0, -0.2, 0.1, -0.1, -0.05],
    })


def main() -> None:
    parser = argparse.ArgumentParser(prog='atos')
    parser.add_argument('command', choices=['status', 'risk', 'cycle', 'market', 'review'])
    parser.add_argument('--policy', default='implementation/config/policy.json')
    parser.add_argument('--symbol', default='BTC-USDT')
    args = parser.parse_args()
    policy = load_policy(args.policy)
    if args.command == 'status':
        output = command_status(policy)
    elif args.command == 'risk':
        output = command_risk(policy)
    elif args.command == 'cycle':
        output = command_cycle(policy)
    elif args.command == 'market':
        output = command_market(args.symbol)
    else:
        output = command_review()
    print(json.dumps(output, indent=2, ensure_ascii=False))


if __name__ == '__main__':
    main()
