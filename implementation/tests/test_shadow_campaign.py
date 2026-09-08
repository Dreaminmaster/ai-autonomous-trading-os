from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

from atos.shadow_campaign import ShadowCampaignManager
from atos.shadow_service import LAUNCH_SCHEMA_VERSION

SHA = "a" * 40
RUN_ID = "shadow_service_abcdefabcdefabcdefabcdefabcdefab"
SESSION_ID = "session_abcdefabcdefabcd"


def _policy() -> dict:
    return {
        "mode": "paper",
        "live_enabled": False,
        "public_data_only": True,
        "allowed_symbols": ["BTC-USDT", "ETH-USDT"],
        "paper": {"equity_usdt": 1000.0, "fee_bps": 10.0, "slippage_bps": 5.0},
        "persistence": {"enabled": True, "database_path": "runtime/atos_runtime.sqlite"},
        "shadow_supervisor": {
            "health_path": "runtime/shadow_health.json",
            "ledger_path": "runtime/shadow_events.sqlite",
            "interval_seconds": 60.0,
            "failure_threshold": 3,
            "automatic_restart": False,
        },
        "shadow_evidence": {
            "minimum_duration_seconds": 120,
            "minimum_cycles": 4,
            "minimum_simulated_fills": 2,
            "max_failure_rate": 0.1,
            "max_heartbeat_gap_seconds": 180.0,
            "max_equity_drawdown_pct": 10.0,
            "require_positive_net_pnl": True,
        },
    }


def _manager(tmp_path: Path) -> ShadowCampaignManager:
    repository = tmp_path / "repo"
    config = repository / "implementation" / "config"
    config.mkdir(parents=True)
    policy_path = config / "policy.json"
    policy_path.write_text(json.dumps(_policy()), encoding="utf-8")
    manager = ShadowCampaignManager(repository, policy_path=policy_path)
    manager._current_binding = lambda **_: {  # type: ignore[method-assign]
        "implementation_sha": SHA,
        "policy_sha256": hashlib.sha256(policy_path.read_bytes()).hexdigest(),
        "strategy_version": "test-strategy@v1",
    }
    return manager


def _service_segment(campaign_path: Path) -> dict:
    run_root = campaign_path.parent / "segments" / RUN_ID
    run_root.mkdir(parents=True)
    policy = _policy()
    database = run_root / "atos_runtime.sqlite"
    ledger = run_root / "shadow_events.sqlite"
    health = run_root / "shadow_health.json"
    deployed = run_root / "deployed_policy.json"
    stop = run_root / "stop_request.json"
    log = run_root / "supervisor.log"
    policy["persistence"]["database_path"] = str(database)
    policy["shadow_supervisor"]["health_path"] = str(health)
    policy["shadow_supervisor"]["ledger_path"] = str(ledger)
    deployed.write_text(json.dumps(policy), encoding="utf-8")
    log.write_text("", encoding="utf-8")
    base = datetime(2026, 9, 8, tzinfo=UTC)
    with sqlite3.connect(database) as connection:
        connection.execute(
            "CREATE TABLE runtime_sessions(session_id TEXT PRIMARY KEY,started_at TEXT,mode TEXT,status TEXT,stopped_at TEXT,stop_reason TEXT)"
        )
        connection.execute(
            "CREATE TABLE runtime_cycles(cycle_id TEXT PRIMARY KEY,session_id TEXT,symbol TEXT,started_at TEXT,completed_at TEXT,status TEXT,last_completed_stage TEXT,last_error TEXT)"
        )
        connection.execute(
            "INSERT INTO runtime_sessions VALUES (?,?,?,?,?,?)",
            (SESSION_ID, base.isoformat(), "shadow", "STOPPED", (base + timedelta(minutes=2)).isoformat(), "OPERATOR_STOP"),
        )
        for index in range(1, 4):
            connection.execute(
                "INSERT INTO runtime_cycles VALUES (?,?,?,?,?,?,?,?)",
                (
                    f"cycle-{index}",
                    SESSION_ID,
                    "BTC-USDT",
                    (base + timedelta(minutes=index - 1)).isoformat(),
                    (base + timedelta(minutes=index - 1, seconds=3)).isoformat(),
                    "COMPLETED",
                    "COMPLETED",
                    None,
                ),
            )
        connection.commit()
    safety = {
        "session_id": SESSION_ID,
        "mode": "shadow",
        "public_data_only": True,
        "account_access": False,
        "private_api": False,
        "external_execution": False,
        "automatic_restart": False,
        "single_process_lock": True,
        "live": "FORBIDDEN",
    }
    events: list[tuple[str, str, dict]] = []
    for index in range(1, 3):
        at = base + timedelta(minutes=index - 1)
        events.extend(
            [
                (at.isoformat(), "market_snapshot", {**safety, "cycle_id": f"cycle-{index}", "symbol": "BTC-USDT", "source": "OKX_OFFICIAL_PUBLIC", "public_only": True, "mark_price": "100"}),
                (at.isoformat(), "execution", {**safety, "cycle_id": f"cycle-{index}", "symbol": "BTC-USDT", "status": "SHADOW_SIMULATED" if index == 1 else "NOOP_HOLD", "action": "BUY" if index == 1 else "HOLD", "notional": "10", "price": "100.15", "fee": "0.01"}),
                (at.isoformat(), "runtime_cycle_completed", {**safety, "cycle_id": f"cycle-{index}"}),
                (at.isoformat(), "shadow_supervisor_heartbeat", {**safety, "updated_at": at.isoformat(), "heartbeat_sequence": index}),
            ]
        )
    events.extend(
        [
            ((base + timedelta(minutes=2)).isoformat(), "execution", {**safety, "cycle_id": "cycle-3", "symbol": "BTC-USDT", "status": "NOOP_HOLD", "action": "HOLD"}),
            ((base + timedelta(minutes=2)).isoformat(), "runtime_cycle_completed", {**safety, "cycle_id": "cycle-3"}),
            ((base + timedelta(minutes=2)).isoformat(), "shadow_supervisor_heartbeat", {**safety, "updated_at": (base + timedelta(minutes=2)).isoformat(), "heartbeat_sequence": 3}),
            ((base + timedelta(minutes=2)).isoformat(), "shadow_supervisor_failure", safety),
        ]
    )
    with sqlite3.connect(ledger) as connection:
        connection.execute("CREATE TABLE events(id INTEGER PRIMARY KEY AUTOINCREMENT,created_at TEXT NOT NULL,kind TEXT NOT NULL,payload_json TEXT NOT NULL)")
        connection.executemany(
            "INSERT INTO events(created_at,kind,payload_json) VALUES (?,?,?)",
            [(at, kind, json.dumps(payload)) for at, kind, payload in events],
        )
        connection.commit()
    health.write_text(json.dumps({**safety, "schema_version": "shadow_supervisor.v1"}), encoding="utf-8")
    receipt = {
        "schema_version": LAUNCH_SCHEMA_VERSION,
        "run_id": RUN_ID,
        "launched_at": base.isoformat(),
        "implementation_sha": SHA,
        "source_policy_sha256": "b" * 64,
        "deployed_policy_sha256": hashlib.sha256(deployed.read_bytes()).hexdigest(),
        "source_policy_path": str(deployed),
        "deployed_policy_path": str(deployed),
        "python_executable": "/safe/python",
        "pid_observation_only": 99999999,
        "symbols": ["BTC-USDT", "ETH-USDT"],
        "bar": "1m",
        "limit": 100,
        "interval_seconds": 60.0,
        "failure_threshold": 3,
        "health_path": str(health),
        "ledger_path": str(ledger),
        "database_path": str(database),
        "stop_request_path": str(stop),
        "log_path": str(log),
        "mode": "shadow",
        "public_data_only": True,
        "account_access": False,
        "private_api": False,
        "external_execution": False,
        "automatic_restart": False,
        "uses_pid_signal_for_stop": False,
        "authorizes_live": False,
        "live": "FORBIDDEN",
    }
    receipt_path = run_root / "launch_receipt.json"
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
    return {
        "sequence": 1,
        "segment_id": RUN_ID,
        "receipt_path": str(receipt_path),
        "state": "PAUSED_CLEAN",
        "started_at": base.isoformat(),
        "ended_at": (base + timedelta(minutes=2)).isoformat(),
        "session_id": SESSION_ID,
        "last_valid_heartbeat": (base + timedelta(minutes=1)).isoformat(),
        "valid_duration_seconds": 60.0,
        "valid_cycles": 2,
        "failures": 1,
        "simulated_fills": 1,
        "seeded_from_previous_segment": False,
        "unclean_recovery": None,
    }


def test_campaign_accumulates_only_durable_public_cycles_with_heartbeats(tmp_path: Path) -> None:
    manager = _manager(tmp_path)
    manager.create(start=False)
    campaign_path = manager._current_path()
    assert campaign_path is not None
    campaign = json.loads(campaign_path.read_text(encoding="utf-8"))
    campaign["segments"] = [_service_segment(campaign_path)]
    campaign_path.write_text(json.dumps(campaign), encoding="utf-8")

    status = manager.status()

    assert status["state"] == "PAUSED"
    assert status["metrics"]["valid_cycles"] == 2
    assert status["metrics"]["valid_duration_seconds"] == 60.0
    assert status["metrics"]["simulated_fills"] == 1
    assert status["metrics"]["failures"] == 1
    assert status["metrics"]["failure_rate"] == 1 / 3
    assert status["metrics"]["latest_public_market_at"] is not None
    assert status["safe_to_power_off"] is True
    assert status["live"] == "FORBIDDEN"


def test_new_campaign_freezes_provenance_and_is_resumable(tmp_path: Path) -> None:
    manager = _manager(tmp_path)
    status = manager.create(start=False)

    assert status["state"] == "PAUSED"
    assert status["resume_available"] is True
    assert status["implementation_sha"] == SHA
    assert status["strategy_version"] == "test-strategy@v1"
    assert Path(manager._current_path().parent / "frozen_policy.json").exists()  # type: ignore[union-attr]
    assert status["account_access"] is False
    assert status["private_api"] is False
    assert status["external_execution"] is False
    assert status["live"] == "FORBIDDEN"


def test_interrupted_segment_is_aborted_but_keeps_prior_valid_work(tmp_path: Path) -> None:
    manager = _manager(tmp_path)
    manager.create(start=False)
    campaign_path = manager._current_path()
    assert campaign_path is not None
    campaign = json.loads(campaign_path.read_text(encoding="utf-8"))
    segment = _service_segment(campaign_path)
    segment["state"] = "RUNNING"
    segment["ended_at"] = None
    campaign["segments"] = [segment]
    campaign["active_segment_id"] = RUN_ID
    campaign["state"] = "RUNNING"
    campaign["safe_to_power_off"] = False
    campaign_path.write_text(json.dumps(campaign), encoding="utf-8")

    status = manager.status()

    assert status["state"] == "PAUSED"
    assert status["segments"][0]["state"] == "ABORTED_UNCLEAN"
    assert status["metrics"]["valid_cycles"] == 2
    assert status["metrics"]["valid_duration_seconds"] == 60.0
    assert status["safe_to_power_off"] is True
