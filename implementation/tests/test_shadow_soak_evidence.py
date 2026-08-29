from __future__ import annotations

import json
import sqlite3
import urllib.parse
from datetime import UTC, datetime
from pathlib import Path
from typing import Self

import pytest

from atos.domain import Candle, StrategyCandidate
from atos.ledger import Ledger
from atos.market import PublicMarketAdapter
from atos.runtime import AutonomousRuntime
from atos.shadow_soak_evidence import (
    ShadowSoakEvidenceError,
    build_shadow_soak_evidence,
    verify_shadow_soak_package,
)
from atos.shadow_supervisor import ShadowSupervisor
from atos.strategy_registry import StrategyRegistry

SHA = "a" * 40


class FakeResponse:
    def __init__(self, url: str, payload: dict):
        self.url = url
        self.raw = json.dumps(payload).encode()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def geturl(self) -> str:
        return self.url

    def read(self, _: int) -> bytes:
        return self.raw


class PublicFixtureOpener:
    def __call__(self, request: object, **_: object) -> FakeResponse:
        url = str(request.full_url)
        parsed = urllib.parse.urlparse(url)
        symbol = urllib.parse.parse_qs(parsed.query)["instId"][0]
        now_ms = int(datetime.now(tz=UTC).timestamp() * 1000)
        if parsed.path == "/api/v5/market/ticker":
            payload = {
                "code": "0",
                "data": [{"instId": symbol, "last": "101", "ts": str(now_ms)}],
            }
        elif parsed.path == "/api/v5/market/candles":
            payload = {
                "code": "0",
                "data": [
                    [
                        str(now_ms - index * 60_000),
                        "100",
                        "102",
                        "99",
                        "101",
                        "1000",
                        "0",
                        "0",
                        "1",
                    ]
                    for index in range(21)
                ],
            }
        elif parsed.path == "/api/v5/market/books":
            payload = {
                "code": "0",
                "data": [
                    {
                        "bids": [["100", "1", "0", "1"]],
                        "asks": [["102", "1", "0", "1"]],
                        "ts": str(now_ms),
                    }
                ],
            }
        else:  # pragma: no cover
            raise AssertionError(parsed.path)
        return FakeResponse(url, payload)


class AlwaysBuyStrategy:
    strategy_id = "always_buy_test"

    def generate(self, symbol: str, candles: list[Candle]) -> StrategyCandidate | None:
        return StrategyCandidate(
            strategy_id=self.strategy_id,
            symbol=symbol,
            side="BUY",
            signal_strength=0.9,
            confidence=0.9,
            entry_reason="deterministic evidence fixture",
            suggested_stop_loss_pct=1.0,
            suggested_take_profit_pct=2.0,
            max_holding_minutes=60,
        )


def _policy(tmp_path: Path, *, passing: bool = True) -> dict:
    return {
        "mode": "shadow",
        "live_enabled": False,
        "public_data_only": True,
        "allowed_symbols": ["BTC-USDT"],
        "position_limits": {"max_position_pct_per_trade": 1.0},
        "ai_output_limits": {"min_confidence_for_trade": 0.6},
        "trade_limits": {"max_trades_per_day": 20, "cooldown_seconds": 300},
        "risk_limits": {"max_drawdown_pct": 20.0},
        "portfolio_limits": {
            "max_gross_exposure_pct": 20.0,
            "max_symbol_exposure_pct": 5.0,
        },
        "data_freshness": {
            "max_candle_age_seconds": 300,
            "min_candles_required": 20,
            "max_gap_minutes": 15,
        },
        "paper": {"equity_usdt": 1000.0, "fee_bps": 10.0, "slippage_bps": 5.0},
        "persistence": {
            "enabled": True,
            "database_path": str(tmp_path / "runtime.sqlite"),
        },
        "shadow_evidence": {
            "minimum_duration_seconds": 0 if passing else 86_400,
            "minimum_cycles": 1 if passing else 100,
            "minimum_simulated_fills": 0 if passing else 30,
            "max_failure_rate": 0.0,
            "max_heartbeat_gap_seconds": 180.0,
            "max_equity_drawdown_pct": 100.0,
            "require_positive_net_pnl": not passing,
        },
    }


def _sources(
    tmp_path: Path, *, passing: bool = True, simulated_fill: bool = False
) -> dict[str, Path]:
    policy = _policy(tmp_path, passing=passing)
    policy_path = tmp_path / "policy.json"
    policy_path.write_text(json.dumps(policy), encoding="utf-8")
    health_path = tmp_path / "health.json"
    ledger_path = tmp_path / "ledger.sqlite"
    registry = StrategyRegistry()
    if simulated_fill:
        registry.register(AlwaysBuyStrategy())
    runtime = AutonomousRuntime(
        policy,
        Ledger(str(ledger_path)),
        registry=registry,
        market_adapter=PublicMarketAdapter(opener=PublicFixtureOpener()),
    )
    supervisor = ShadowSupervisor(
        runtime,
        symbols=["BTC-USDT"],
        health_path=health_path,
        interval_seconds=0,
    )
    result = supervisor.run(max_loops=1)
    assert result["reason"] == "BOUNDED_COMPLETE"
    runtime.executor.database.close()
    runtime.ledger.conn.close()
    return {
        "policy": policy_path,
        "health": health_path,
        "ledger": ledger_path,
        "database": tmp_path / "runtime.sqlite",
    }


def _build(tmp_path: Path, sources: dict[str, Path], name: str = "evidence"):
    return build_shadow_soak_evidence(
        tmp_path / name,
        policy_path=sources["policy"],
        health_path=sources["health"],
        ledger_path=sources["ledger"],
        database_path=sources["database"],
        implementation_sha=SHA,
    )


def test_completed_public_shadow_can_produce_non_authorizing_soak_pass(
    tmp_path: Path,
) -> None:
    report, manifest = _build(tmp_path, _sources(tmp_path))

    assert report["gate"] == {
        "status": "SOAK_PASS",
        "failures": [],
        "next_action": "INDEPENDENT_REVIEW",
        "authorizes_live": False,
        "live": "FORBIDDEN",
    }
    assert report["ledger_recompute"]["cycle_count"] == 1
    assert report["ledger_recompute"]["simulated_fill_count"] == 0
    assert report["runtime_cross_check"]["trade_intent_count"] == 1
    assert report["runtime_cross_check"]["risk_decision_count"] == 1
    assert report["runtime_cross_check"]["simulated_order_count"] == 0
    assert report["safety"]["account_access"] is False
    assert report["safety"]["external_execution"] is False
    assert report["safety"]["authorizes_live"] is False
    assert manifest["implementation_sha"] == SHA
    assert verify_shadow_soak_package(tmp_path / "evidence") == manifest


def test_production_thresholds_fail_closed_with_specific_reasons(
    tmp_path: Path,
) -> None:
    report, _ = _build(tmp_path, _sources(tmp_path, passing=False))

    assert report["gate"]["status"] == "SOAK_FAIL"
    assert report["gate"]["next_action"] == "HOLD"
    assert report["gate"]["authorizes_live"] is False
    assert set(report["gate"]["failures"]) >= {
        "minimum Shadow duration not reached",
        "minimum completed cycle count not reached",
        "minimum simulated fill count not reached",
        "net simulated PnL is not positive after costs",
    }


def test_simulated_fill_economics_are_recomputed_from_public_mark(
    tmp_path: Path,
) -> None:
    report, _ = _build(tmp_path, _sources(tmp_path, simulated_fill=True))

    recompute = report["ledger_recompute"]
    assert recompute["simulated_fill_count"] == 1
    assert recompute["fees_usdt"] == "0.01000499989995"
    assert recompute["net_pnl_usdt"] == "-0.01500499984995"
    assert report["runtime_cross_check"]["execution_intent_count"] == 1
    assert report["runtime_cross_check"]["simulated_order_count"] == 1
    assert report["runtime_cross_check"]["simulated_fill_count"] == 1
    assert report["gate"]["status"] == "SOAK_PASS"
    assert report["gate"]["authorizes_live"] is False


def test_unsafe_health_is_reported_as_failure_not_authority(tmp_path: Path) -> None:
    sources = _sources(tmp_path)
    health = json.loads(sources["health"].read_text())
    health["private_api"] = True
    sources["health"].write_text(json.dumps(health), encoding="utf-8")

    report, _ = _build(tmp_path, sources)

    assert report["gate"]["status"] == "SOAK_FAIL"
    assert "health.private_api safety invariant failed" in report["gate"]["failures"]
    assert report["gate"]["authorizes_live"] is False


def test_ledger_fill_drift_is_rejected_by_runtime_cross_check(tmp_path: Path) -> None:
    sources = _sources(tmp_path, simulated_fill=True)
    connection = sqlite3.connect(sources["ledger"])
    try:
        row_id, raw = connection.execute(
            "SELECT id,payload_json FROM events WHERE kind='execution'"
        ).fetchone()
        payload = json.loads(raw)
        payload["fee"] = 99.0
        connection.execute(
            "UPDATE events SET payload_json=? WHERE id=?",
            (json.dumps(payload, sort_keys=True), row_id),
        )
        connection.commit()
    finally:
        connection.close()

    report, _ = _build(tmp_path, sources)

    assert report["gate"]["status"] == "SOAK_FAIL"
    assert (
        "ledger/runtime simulated fill payload mismatch" in report["gate"]["failures"]
    )
    assert report["gate"]["authorizes_live"] is False


def test_evaluator_does_not_mutate_source_databases(tmp_path: Path) -> None:
    sources = _sources(tmp_path)

    def counts(path: Path, tables: tuple[str, ...]) -> tuple[int, ...]:
        connection = sqlite3.connect(path)
        try:
            return tuple(
                connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                for table in tables
            )
        finally:
            connection.close()

    ledger_before = counts(
        sources["ledger"], ("events", "strategy_scores", "positions")
    )
    runtime_before = counts(
        sources["database"],
        ("runtime_sessions", "runtime_cycles", "trade_intents", "risk_decisions"),
    )

    _build(tmp_path, sources)

    assert (
        counts(sources["ledger"], ("events", "strategy_scores", "positions"))
        == ledger_before
    )
    assert (
        counts(
            sources["database"],
            ("runtime_sessions", "runtime_cycles", "trade_intents", "risk_decisions"),
        )
        == runtime_before
    )


def test_output_is_exclusive_and_manifest_detects_tampering(tmp_path: Path) -> None:
    sources = _sources(tmp_path)
    _build(tmp_path, sources)

    with pytest.raises(ShadowSoakEvidenceError, match="already exists"):
        _build(tmp_path, sources)

    evidence = tmp_path / "evidence" / "shadow_soak_evidence.json"
    evidence.write_bytes(evidence.read_bytes() + b" ")
    with pytest.raises(ShadowSoakEvidenceError, match="hash mismatch"):
        verify_shadow_soak_package(tmp_path / "evidence")


def test_verifier_rejects_manifest_identity_drift(tmp_path: Path) -> None:
    sources = _sources(tmp_path)
    _build(tmp_path, sources)
    manifest_path = tmp_path / "evidence" / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["stage"] = "UNREVIEWED"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(ShadowSoakEvidenceError, match="identity drift"):
        verify_shadow_soak_package(tmp_path / "evidence")


def test_symlink_source_and_inexact_sha_are_rejected(tmp_path: Path) -> None:
    sources = _sources(tmp_path)
    link = tmp_path / "health-link.json"
    link.symlink_to(sources["health"])
    with pytest.raises(ShadowSoakEvidenceError, match="symbolic link"):
        build_shadow_soak_evidence(
            tmp_path / "bad-link",
            policy_path=sources["policy"],
            health_path=link,
            ledger_path=sources["ledger"],
            database_path=sources["database"],
            implementation_sha=SHA,
        )
    with pytest.raises(ShadowSoakEvidenceError, match="exact lowercase SHA"):
        build_shadow_soak_evidence(
            tmp_path / "bad-sha",
            policy_path=sources["policy"],
            health_path=sources["health"],
            ledger_path=sources["ledger"],
            database_path=sources["database"],
            implementation_sha="abc",
        )
