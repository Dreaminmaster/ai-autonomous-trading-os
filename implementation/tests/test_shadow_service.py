from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import pytest
from atos.cli import supervise
from atos.shadow_service import (
    LAUNCH_SCHEMA_VERSION,
    STOP_SCHEMA_VERSION,
    ShadowServiceError,
    StopRequestWatcher,
    request_shadow_service_stop,
    shadow_service_status_context,
    start_shadow_service,
)

SHA = "a" * 40
RUN_ID = "shadow_service_0123456789abcdef0123456789abcdef"


def _policy() -> dict:
    return {
        "mode": "paper",
        "live_enabled": False,
        "public_data_only": True,
        "allowed_symbols": ["BTC-USDT", "ETH-USDT"],
        "persistence": {
            "enabled": True,
            "database_path": "runtime/atos_runtime.sqlite",
        },
        "shadow_supervisor": {
            "health_path": "runtime/shadow_health.json",
            "ledger_path": "runtime/shadow_events.sqlite",
            "interval_seconds": 60.0,
            "failure_threshold": 3,
            "automatic_restart": False,
        },
    }


class GitRunner:
    def __init__(self, *, dirty: bool = False, head: str = SHA) -> None:
        self.dirty = dirty
        self.head = head
        self.calls: list[list[str]] = []

    def __call__(self, args: list[str], **_: Any) -> subprocess.CompletedProcess[str]:
        self.calls.append(args)
        if args[-2:] == ["rev-parse", "HEAD"]:
            output = self.head + "\n"
        elif "status" in args:
            output = " M implementation/src/atos/runtime.py\n" if self.dirty else ""
        else:  # pragma: no cover - a new git call is a contract change
            raise AssertionError(args)
        return subprocess.CompletedProcess(args, 0, stdout=output, stderr="")


class FakeProcess:
    pid = 4242


class PopenRecorder:
    def __init__(self) -> None:
        self.args: list[str] | None = None
        self.kwargs: dict[str, Any] = {}

    def __call__(self, args: list[str], **kwargs: Any) -> FakeProcess:
        self.args = args
        self.kwargs = kwargs
        return FakeProcess()


def _repository(tmp_path: Path) -> tuple[Path, Path, dict]:
    repository = tmp_path / "repository"
    implementation = repository / "implementation"
    (implementation / "config").mkdir(parents=True)
    policy = _policy()
    policy_path = implementation / "config" / "policy.json"
    policy_path.write_text(json.dumps(policy), encoding="utf-8")
    return repository, policy_path, policy


def _start(tmp_path: Path, **overrides: Any) -> tuple[dict, PopenRecorder, Path]:
    repository, policy_path, policy = _repository(tmp_path)
    popen = PopenRecorder()
    arguments = {
        "policy_path": policy_path,
        "repository_root": repository,
        "implementation_sha": SHA,
        "service_root": "runtime/shadow_service",
        "symbols": ["BTC-USDT", "ETH-USDT"],
        "bar": "1m",
        "limit": 100,
        "interval_seconds": 60.0,
        "failure_threshold": 3,
        "python_executable": "/safe/python3.11",
        "run_id": RUN_ID,
        "git_runner": GitRunner(),
        "popen_factory": popen,
    }
    arguments.update(overrides)
    result = start_shadow_service(policy, **arguments)
    return result, popen, repository


def test_start_seals_exact_provenance_and_safe_detached_command(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OKX_API_KEY", "must-not-reach-child")
    result, popen, repository = _start(tmp_path)

    assert result["status"] == "LAUNCHED"
    assert result["run_id"] == RUN_ID
    assert result["pid_observation_only"] == 4242
    assert result["automatic_restart"] is False
    assert result["authorizes_live"] is False
    assert result["live"] == "FORBIDDEN"
    assert popen.args is not None
    assert popen.args[:4] == ["/safe/python3.11", "-m", "atos.cli", "supervise"]
    assert popen.args[popen.args.index("--max-loops") + 1] == "0"
    assert popen.args[popen.args.index("--service-run-id") + 1] == RUN_ID
    assert "--stop-request-path" in popen.args
    assert popen.kwargs["cwd"] == repository / "implementation"
    assert popen.kwargs["start_new_session"] is True
    assert popen.kwargs["close_fds"] is True
    assert "OKX_API_KEY" not in popen.kwargs["env"]
    assert popen.kwargs["env"]["PYTHONPATH"] == str(
        repository / "implementation" / "src"
    )

    receipt_path = Path(result["receipt_path"])
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert receipt["schema_version"] == LAUNCH_SCHEMA_VERSION
    assert receipt["implementation_sha"] == SHA
    assert len(receipt["source_policy_sha256"]) == 64
    assert len(receipt["deployed_policy_sha256"]) == 64
    deployed_policy = Path(receipt["deployed_policy_path"])
    deployed = json.loads(deployed_policy.read_text(encoding="utf-8"))
    run_root = Path(result["receipt_path"]).parent
    assert deployed["persistence"]["database_path"] == str(
        run_root / "atos_runtime.sqlite"
    )
    assert deployed["shadow_supervisor"]["health_path"] == str(
        run_root / "shadow_health.json"
    )
    assert deployed["shadow_supervisor"]["ledger_path"] == str(
        run_root / "shadow_events.sqlite"
    )
    assert popen.args[popen.args.index("--policy") + 1] == str(deployed_policy)
    assert receipt["uses_pid_signal_for_stop"] is False
    assert receipt["account_access"] is False
    assert receipt["private_api"] is False
    assert receipt["external_execution"] is False
    assert receipt_path.stat().st_mode & 0o777 == 0o600
    assert Path(result["log_path"]).stat().st_mode & 0o777 == 0o600


def test_dirty_or_wrong_checkout_rejected_before_process_or_runtime_files(
    tmp_path: Path,
) -> None:
    repository, policy_path, policy = _repository(tmp_path)
    popen = PopenRecorder()
    common = {
        "policy_path": policy_path,
        "repository_root": repository,
        "implementation_sha": SHA,
        "service_root": "runtime/shadow_service",
        "symbols": ["BTC-USDT"],
        "bar": "1m",
        "limit": 100,
        "interval_seconds": 60.0,
        "failure_threshold": 3,
        "run_id": RUN_ID,
        "popen_factory": popen,
    }
    with pytest.raises(ShadowServiceError, match="clean checkout"):
        start_shadow_service(policy, git_runner=GitRunner(dirty=True), **common)
    with pytest.raises(ShadowServiceError, match="does not match"):
        start_shadow_service(policy, git_runner=GitRunner(head="b" * 40), **common)

    assert popen.args is None
    assert not (repository / "implementation" / "runtime").exists()


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("live_enabled", True),
        ("public_data_only", False),
    ],
)
def test_unsafe_policy_rejected_before_launch(
    tmp_path: Path, field: str, value: object
) -> None:
    repository, policy_path, policy = _repository(tmp_path)
    policy[field] = value
    policy_path.write_text(json.dumps(policy), encoding="utf-8")

    with pytest.raises(ShadowServiceError, match="policy safety"):
        start_shadow_service(
            policy,
            policy_path=policy_path,
            repository_root=repository,
            implementation_sha=SHA,
            service_root="runtime/shadow_service",
            symbols=["BTC-USDT"],
            bar="1m",
            limit=100,
            interval_seconds=60.0,
            failure_threshold=3,
            run_id=RUN_ID,
            git_runner=GitRunner(),
            popen_factory=PopenRecorder(),
        )


def test_service_and_runtime_paths_cannot_escape_repository_runtime(
    tmp_path: Path,
) -> None:
    repository, policy_path, policy = _repository(tmp_path)
    policy["persistence"]["database_path"] = "../../outside.sqlite"
    policy_path.write_text(json.dumps(policy), encoding="utf-8")
    with pytest.raises(ShadowServiceError, match="database must stay inside"):
        start_shadow_service(
            policy,
            policy_path=policy_path,
            repository_root=repository,
            implementation_sha=SHA,
            service_root="runtime/shadow_service",
            symbols=["BTC-USDT"],
            bar="1m",
            limit=100,
            interval_seconds=60.0,
            failure_threshold=3,
            run_id=RUN_ID,
            git_runner=GitRunner(),
            popen_factory=PopenRecorder(),
        )


def test_receipt_driven_stop_is_idempotent_and_never_signals_pid(
    tmp_path: Path,
) -> None:
    launched, _, _ = _start(tmp_path)

    first = request_shadow_service_stop(launched["receipt_path"])
    second = request_shadow_service_stop(launched["receipt_path"])

    assert first["status"] == second["status"] == "STOP_REQUESTED"
    assert first["uses_pid_signal"] is False
    stop_path = Path(first["stop_request_path"])
    payload = json.loads(stop_path.read_text(encoding="utf-8"))
    assert payload["schema_version"] == STOP_SCHEMA_VERSION
    assert payload["run_id"] == RUN_ID
    assert payload["action"] == "STOP"
    assert payload["account_access"] is False
    assert payload["private_api"] is False
    assert payload["external_execution"] is False
    assert payload["live"] == "FORBIDDEN"
    assert stop_path.stat().st_mode & 0o777 == 0o600
    assert StopRequestWatcher(stop_path, RUN_ID).requested() is True


def test_status_context_resolves_exact_isolated_runtime(tmp_path: Path) -> None:
    launched, _, _ = _start(tmp_path)

    context = shadow_service_status_context(launched["receipt_path"])

    run_root = Path(launched["receipt_path"]).parent
    assert context["implementation_sha"] == SHA
    assert context["run_id"] == RUN_ID
    assert context["health_path"] == str(run_root / "shadow_health.json")
    assert context["database_path"] == str(run_root / "atos_runtime.sqlite")
    assert context["policy"]["persistence"]["database_path"] == context["database_path"]


def test_status_context_rejects_deployed_policy_tamper(tmp_path: Path) -> None:
    launched, _, _ = _start(tmp_path)
    receipt = json.loads(Path(launched["receipt_path"]).read_text(encoding="utf-8"))
    Path(receipt["deployed_policy_path"]).write_text("{}", encoding="utf-8")

    with pytest.raises(ShadowServiceError, match="hash does not match"):
        shadow_service_status_context(launched["receipt_path"])


def test_stop_rejects_tampered_receipt_and_escaping_request_path(
    tmp_path: Path,
) -> None:
    launched, _, _ = _start(tmp_path)
    receipt_path = Path(launched["receipt_path"])
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt["external_execution"] = True
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
    with pytest.raises(ShadowServiceError, match="safety boundary"):
        request_shadow_service_stop(receipt_path)

    receipt["external_execution"] = False
    receipt["stop_request_path"] = str(tmp_path / "escaped-stop.json")
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
    with pytest.raises(ShadowServiceError, match="escapes"):
        request_shadow_service_stop(receipt_path)


def test_stop_watcher_missing_is_false_but_any_present_tamper_stops(
    tmp_path: Path,
) -> None:
    stop_path = tmp_path / "stop.json"
    watcher = StopRequestWatcher(stop_path, RUN_ID)
    assert watcher.requested() is False

    stop_path.write_text("not-json", encoding="utf-8")
    assert watcher.requested() is True

    stop_path.unlink()
    target = tmp_path / "target.json"
    target.write_text("{}", encoding="utf-8")
    stop_path.symlink_to(target)
    assert watcher.requested() is True


def test_supervisor_consumes_service_stop_before_any_public_request(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    policy = _policy()
    policy["persistence"]["database_path"] = str(tmp_path / "runtime.sqlite")
    stop_path = tmp_path / "stop.json"
    stop_path.write_text("{}", encoding="utf-8")

    def forbidden_snapshot(*_: object, **__: object) -> object:
        raise AssertionError("public adapter must not run after a pre-existing stop")

    monkeypatch.setattr("atos.market.PublicMarketAdapter.snapshot", forbidden_snapshot)
    result = supervise(
        policy,
        symbols=["BTC-USDT"],
        max_loops=None,
        interval_seconds=0,
        bar="1m",
        limit=100,
        failure_threshold=3,
        health_path=str(tmp_path / "health.json"),
        ledger_path=str(tmp_path / "ledger.sqlite"),
        service_run_id=RUN_ID,
        stop_request_path=str(stop_path),
    )

    assert result["state"] == "STOPPED"
    assert result["reason"] == "OPERATOR_STOP"
    assert result["cycles_completed"] == 0
    assert result["durable_session_status"] == "NOT_PERSISTED"
    assert result["external_execution"] is False
    assert result["live"] == "FORBIDDEN"


def test_duplicate_service_run_directory_fails_without_second_process(
    tmp_path: Path,
) -> None:
    _start(tmp_path)
    repository = tmp_path / "repository"
    policy_path = repository / "implementation" / "config" / "policy.json"
    popen = PopenRecorder()
    with pytest.raises(ShadowServiceError, match="already exists"):
        start_shadow_service(
            _policy(),
            policy_path=policy_path,
            repository_root=repository,
            implementation_sha=SHA,
            service_root="runtime/shadow_service",
            symbols=["BTC-USDT"],
            bar="1m",
            limit=100,
            interval_seconds=60.0,
            failure_threshold=3,
            run_id=RUN_ID,
            git_runner=GitRunner(),
            popen_factory=popen,
        )
    assert popen.args is None
