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


def load_policy(path: str) -> dict:
    return json.loads(Path(path).read_text(encoding='utf-8'))


def command_status(policy: dict) -> dict:
    return {'status': 'ok', 'mode': policy.get('mode', 'paper'), 'default_real_orders': False}


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


def main() -> None:
    parser = argparse.ArgumentParser(prog='atos')
    parser.add_argument('command', choices=['status', 'risk', 'cycle'])
    parser.add_argument('--policy', default='implementation/config/policy.json')
    args = parser.parse_args()
    policy = load_policy(args.policy)
    if args.command == 'status':
        output = command_status(policy)
    elif args.command == 'risk':
        output = command_risk(policy)
    else:
        output = command_cycle(policy)
    print(json.dumps(output, indent=2, ensure_ascii=False))


if __name__ == '__main__':
    main()
