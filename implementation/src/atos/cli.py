from __future__ import annotations

import argparse
import json
import signal
import threading
from pathlib import Path

from atos.dashboard import run_dashboard
from atos.domain import Candle, make_hold
from atos.durable_recovery import DurableSimulatedRecoveryController
from atos.market import PublicMarketAdapter
from atos.risk import RiskEngine
from atos.runtime import AutonomousRuntime
from atos.scoring import ScoringEngine
from atos.shadow_operator import inspect_shadow_status
from atos.shadow_soak_evidence import build_shadow_soak_evidence
from atos.shadow_supervisor import build_shadow_supervisor


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


def supervise(
    policy: dict,
    *,
    symbols: list[str],
    max_loops: int | None,
    interval_seconds: float,
    bar: str,
    limit: int,
    failure_threshold: int,
    health_path: str,
    ledger_path: str,
) -> dict:
    """Run the interruptible public-only Shadow supervisor."""
    if max_loops is not None and (type(max_loops) is not int or max_loops < 1):
        raise ValueError("max_loops must be positive or None")
    operating_policy = {**policy, "mode": "shadow"}
    stop_event = threading.Event()
    supervisor = build_shadow_supervisor(
        operating_policy,
        symbols=symbols,
        health_path=health_path,
        ledger_path=ledger_path,
        bar=bar,
        limit=limit,
        interval_seconds=interval_seconds,
        failure_threshold=failure_threshold,
        sleep_fn=stop_event.wait,
    )
    previous_handlers: dict[signal.Signals, object] = {}

    def request_stop(_: int, __: object) -> None:
        stop_event.set()

    for signum in (signal.SIGINT, signal.SIGTERM):
        previous_handlers[signum] = signal.getsignal(signum)
        signal.signal(signum, request_stop)
    try:
        return supervisor.run(max_loops=max_loops, stop_requested=stop_event.is_set)
    finally:
        for signum, handler in previous_handlers.items():
            signal.signal(signum, handler)


def shadow_evidence(
    policy_path: str,
    *,
    health_path: str,
    ledger_path: str,
    database_path: str,
    output_path: str,
    implementation_sha: str,
) -> dict:
    """Build one read-only, no-overwrite Shadow soak evidence package."""
    report, manifest = build_shadow_soak_evidence(
        output_path,
        policy_path=policy_path,
        health_path=health_path,
        ledger_path=ledger_path,
        database_path=database_path,
        implementation_sha=implementation_sha,
    )
    return {
        "status": report["gate"]["status"],
        "session_id": report["session_id"],
        "output_path": output_path,
        "evidence_sha256": manifest["files"][0]["sha256"],
        "authorizes_live": False,
        "live": "FORBIDDEN",
    }


def shadow_status(
    policy: dict,
    *,
    health_path: str,
    database_path: str,
    max_heartbeat_age_seconds: float,
) -> dict:
    """Inspect Shadow liveness without starting, stopping, or mutating it."""
    return inspect_shadow_status(
        policy,
        health_path=health_path,
        database_path=database_path,
        max_heartbeat_age_seconds=max_heartbeat_age_seconds,
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


def recover(
    policy: dict,
    *,
    mode: str,
    database_path: str | None,
    confirmation_token: str | None,
    reason: str | None,
) -> dict:
    configured = policy.get("persistence", {}).get(
        "database_path", "runtime/atos_runtime.sqlite"
    )
    controller = DurableSimulatedRecoveryController(
        mode=mode, database_path=database_path or str(configured)
    )
    if confirmation_token is None:
        return controller.inspect()
    if reason is None:
        raise ValueError("--reason is required with --confirm-recovery")
    return controller.resolve(confirmation_token=confirmation_token, reason=reason)


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
            "supervise",
            "shadow-status",
            "shadow-evidence",
            "market",
            "review",
            "recover",
            "dashboard",
        ],
    )
    parser.add_argument("--policy", default="config/policy.json")
    parser.add_argument("--symbol", default="BTC-USDT")
    parser.add_argument("--loops", type=int, default=3)
    parser.add_argument("--mode", choices=["paper", "shadow"], default="shadow")
    parser.add_argument("--symbols", default="BTC-USDT,ETH-USDT")
    parser.add_argument("--bar", default="1m")
    parser.add_argument("--interval-seconds", type=float)
    parser.add_argument("--max-loops", type=int, default=0)
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--failure-threshold", type=int)
    parser.add_argument("--health-path")
    parser.add_argument("--ledger-path")
    parser.add_argument("--database-path")
    parser.add_argument("--confirm-recovery")
    parser.add_argument("--reason")
    parser.add_argument("--evidence-output")
    parser.add_argument("--implementation-sha")
    parser.add_argument("--max-heartbeat-age-seconds", type=float)
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
            interval_seconds=args.interval_seconds or 0.0,
            bar=args.bar,
        )
    elif args.command == "supervise":
        symbols = [value.strip() for value in args.symbols.split(",") if value.strip()]
        supervisor_policy = policy.get("shadow_supervisor", {})
        output = supervise(
            policy,
            symbols=symbols,
            max_loops=None if args.max_loops == 0 else args.max_loops,
            interval_seconds=(
                args.interval_seconds
                if args.interval_seconds is not None
                else float(supervisor_policy.get("interval_seconds", 60.0))
            ),
            bar=args.bar,
            limit=args.limit,
            failure_threshold=(
                args.failure_threshold
                if args.failure_threshold is not None
                else int(supervisor_policy.get("failure_threshold", 3))
            ),
            health_path=(
                args.health_path
                or str(
                    supervisor_policy.get("health_path", "runtime/shadow_health.json")
                )
            ),
            ledger_path=(
                args.ledger_path
                or str(
                    supervisor_policy.get("ledger_path", "runtime/shadow_events.sqlite")
                )
            ),
        )
    elif args.command in {"shadow-status", "shadow-evidence"}:
        supervisor_policy = policy.get("shadow_supervisor", {})
        if not isinstance(supervisor_policy, dict):
            raise ValueError("shadow_supervisor policy must be an object")
        health_path = args.health_path or str(
            supervisor_policy.get("health_path", "runtime/shadow_health.json")
        )
        database_path = args.database_path or str(
            policy.get("persistence", {}).get(
                "database_path", "runtime/atos_runtime.sqlite"
            )
        )
        if args.command == "shadow-status":
            evidence_policy = policy.get("shadow_evidence", {})
            if not isinstance(evidence_policy, dict):
                raise ValueError("shadow_evidence policy must be an object")
            output = shadow_status(
                policy,
                health_path=health_path,
                database_path=database_path,
                max_heartbeat_age_seconds=(
                    args.max_heartbeat_age_seconds
                    if args.max_heartbeat_age_seconds is not None
                    else float(evidence_policy.get("max_heartbeat_gap_seconds", 180.0))
                ),
            )
        else:
            if not args.evidence_output or not args.implementation_sha:
                raise ValueError(
                    "--evidence-output and --implementation-sha are required"
                )
            output = shadow_evidence(
                args.policy,
                health_path=health_path,
                ledger_path=(
                    args.ledger_path
                    or str(
                        supervisor_policy.get(
                            "ledger_path", "runtime/shadow_events.sqlite"
                        )
                    )
                ),
                database_path=database_path,
                output_path=args.evidence_output,
                implementation_sha=args.implementation_sha,
            )
    elif args.command == "market":
        output = market(args.symbol)
    elif args.command == "recover":
        output = recover(
            policy,
            mode=args.mode,
            database_path=args.database_path,
            confirmation_token=args.confirm_recovery,
            reason=args.reason,
        )
    else:
        output = review()
    print(json.dumps(output, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
