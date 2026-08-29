from __future__ import annotations

import argparse
import json
from pathlib import Path

from atos.dashboard import run_dashboard
from atos.domain import Candle, make_hold
from atos.market import PublicMarketAdapter
from atos.risk import RiskEngine
from atos.runtime import AutonomousRuntime
from atos.scoring import ScoringEngine


def load_policy(path: str) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def sample_candles() -> list[Candle]:
    return [Candle(100 + i, 102 + i, 99 + i, 101 + i, 1000 + i * 10) for i in range(40)]


def status(policy: dict) -> dict:
    return {
        "status": "ok",
        "mode": policy.get("mode", "paper"),
        "package": "atos",
        "components": [
            "market",
            "strategies",
            "providers",
            "risk",
            "execution",
            "ledger",
            "history",
            "scoring",
            "runtime",
            "dashboard",
        ],
    }


def cycle(policy: dict) -> dict:
    runtime = AutonomousRuntime(policy)
    return runtime.run_once("BTC-USDT", sample_candles(), mark_price=140.0)


def loop(policy: dict, loops: int) -> dict:
    runtime = AutonomousRuntime(policy)
    return runtime.run_loop("BTC-USDT", sample_candles, loops=loops).to_dict()


def operate(
    policy: dict,
    *,
    mode: str,
    symbols: list[str],
    loops: int,
    interval_seconds: float,
    bar: str,
) -> dict:
    operating_policy = {**policy, "mode": mode}
    runtime = AutonomousRuntime(operating_policy)
    return runtime.run_public_loop(
        symbols,
        loops=loops,
        interval_seconds=interval_seconds,
        bar=bar,
    )


def market(symbol: str) -> dict:
    snap = PublicMarketAdapter().snapshot(symbol)
    return {
        "symbol": snap.symbol,
        "ticker": snap.ticker,
        "candles_count": len(snap.candles),
        "orderbook": snap.orderbook,
    }


def review() -> dict:
    return ScoringEngine().daily_scores(
        {"trend_following_v1": [0.2, -0.1, 0.3, 0.0, 0.1, -0.05, 0.2, 0.1, 0.05, 0.3]}
    )


def risk(policy: dict) -> dict:
    return (
        RiskEngine(policy)
        .evaluate(
            make_hold("self check").to_dict(), {"mode": policy.get("mode", "paper")}
        )
        .to_dict()
    )


def main() -> None:
    parser = argparse.ArgumentParser(prog="atos")
    parser.add_argument(
        "command",
        choices=[
            "status",
            "risk",
            "cycle",
            "loop",
            "operate",
            "market",
            "review",
            "dashboard",
        ],
    )
    parser.add_argument("--policy", default="config/policy.json")
    parser.add_argument("--symbol", default="BTC-USDT")
    parser.add_argument("--loops", type=int, default=3)
    parser.add_argument("--mode", choices=["paper", "shadow"], default="shadow")
    parser.add_argument("--symbols", default="BTC-USDT,ETH-USDT")
    parser.add_argument("--bar", default="1m")
    parser.add_argument("--interval-seconds", type=float, default=0.0)
    parser.add_argument("--port", type=int, default=28787)
    args = parser.parse_args()
    policy = load_policy(args.policy)
    if args.command == "dashboard":
        run_dashboard(port=args.port)
        return
    if args.command == "status":
        output = status(policy)
    elif args.command == "risk":
        output = risk(policy)
    elif args.command == "cycle":
        output = cycle(policy)
    elif args.command == "loop":
        output = loop(policy, args.loops)
    elif args.command == "operate":
        symbols = [value.strip() for value in args.symbols.split(",") if value.strip()]
        output = operate(
            policy,
            mode=args.mode,
            symbols=symbols,
            loops=args.loops,
            interval_seconds=args.interval_seconds,
            bar=args.bar,
        )
    elif args.command == "market":
        output = market(args.symbol)
    else:
        output = review()
    print(json.dumps(output, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
