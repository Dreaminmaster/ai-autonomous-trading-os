"""B4.3B3 relative performance gate for the lifecycle persistence hot path.

The benchmark measures only the modular boundary overhead.  Both paths execute
exactly the frozen public persistence implementation, validation, SQLite SQL,
BEGIN IMMEDIATE transaction mode, durability pragmas, and accounting policy.
The direct baseline invokes the concrete public method as an unbound function;
the modular path invokes the same object through the frozen Protocol contract.
This avoids a second hand-written SQL implementation drifting from production.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import sys
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from atos.lifecycle_persistence import SqliteLifecyclePersistence
from atos.lifecycle_types import (
    FillApplicationCommand,
    FillApplicationResult,
    FillSequenceWriter,
    OperationStats,
    OrderAcknowledgementCommand,
    OrderAcknowledgementResult,
    OrderAcknowledgementWriter,
    OrderSide,
    OrderStatus,
    OrderType,
    PersistenceOutcome,
)
from atos.position_accounting import NettingPositionAccountingV1
from atos.runtime_db import RuntimeDatabase
from atos.runtime_migrations import MIGRATION_PLAN, MigrationManager

SCHEMA_VERSION = "b4.3b3.lifecycle-performance.v1"
LIVE = "FORBIDDEN"
MAX_P95_RATIO = 1.10
MIN_SAMPLE_COUNT = 60
MIN_WARMUP_COUNT = 10
DEFAULT_SAMPLE_COUNT = 80
DEFAULT_WARMUP_COUNT = 12

OP_NEW_ORDER_ACK = "new_order_acknowledgement"
OP_NEW_ONE_EVENT_FILL = "new_one_event_fill"
OP_NEW_ZERO_CROSSING = "new_two_event_zero_crossing"
OP_EXACT_ORDER_REPLAY = "exact_order_replay"
OP_EXACT_FILL_REPLAY = "exact_fill_replay"
REQUIRED_OPERATIONS = (
    OP_NEW_ORDER_ACK,
    OP_NEW_ONE_EVENT_FILL,
    OP_NEW_ZERO_CROSSING,
    OP_EXACT_ORDER_REPLAY,
    OP_EXACT_FILL_REPLAY,
)

_EXPECTED_COUNTS: Mapping[str, Mapping[str, int]] = {
    OP_NEW_ORDER_ACK: {
        "read_statements": 1,
        "attempted_mutations": 3,
        "committed_mutations": 3,
        "transaction_count": 1,
    },
    OP_NEW_ONE_EVENT_FILL: {
        "read_statements": 3,
        "attempted_mutations": 4,
        "committed_mutations": 4,
        "transaction_count": 1,
    },
    OP_NEW_ZERO_CROSSING: {
        "read_statements": 3,
        "attempted_mutations": 6,
        "committed_mutations": 6,
        "transaction_count": 1,
    },
    OP_EXACT_ORDER_REPLAY: {
        "read_statements": 1,
        "attempted_mutations": 0,
        "committed_mutations": 0,
        "transaction_count": 1,
    },
    OP_EXACT_FILL_REPLAY: {
        "read_statements": 2,
        "attempted_mutations": 0,
        "committed_mutations": 0,
        "transaction_count": 1,
    },
}

_BASE_TIME = datetime(2026, 1, 1, tzinfo=timezone.utc)


class BenchmarkContractError(RuntimeError):
    """Raised when benchmark equivalence or evidence invariants fail."""


@dataclass(slots=True)
class _Environment:
    db: RuntimeDatabase
    adapter: SqliteLifecyclePersistence
    connection_identity: int

    def close(self) -> None:
        self.db.close()


class _DirectRunner:
    """Concrete unbound-method path used as the direct equivalent baseline."""

    def __init__(self, adapter: SqliteLifecyclePersistence) -> None:
        self._adapter = adapter
        self._ack = SqliteLifecyclePersistence.register_order_acknowledgement
        self._fill = SqliteLifecyclePersistence.apply_fill

    def acknowledge(
        self, command: OrderAcknowledgementCommand
    ) -> OrderAcknowledgementResult:
        return self._ack(self._adapter, command)

    def apply_fill(self, command: FillApplicationCommand) -> FillApplicationResult:
        return self._fill(self._adapter, command)


class _ModularRunner:
    """Production modular-monolith path through the frozen typed Protocols."""

    def __init__(self, adapter: SqliteLifecyclePersistence) -> None:
        self._order_writer: OrderAcknowledgementWriter = adapter
        self._fill_writer: FillSequenceWriter = adapter

    def acknowledge(
        self, command: OrderAcknowledgementCommand
    ) -> OrderAcknowledgementResult:
        return self._order_writer.register_order_acknowledgement(command)

    def apply_fill(self, command: FillApplicationCommand) -> FillApplicationResult:
        return self._fill_writer.apply_fill(command)


@dataclass(frozen=True, slots=True)
class _PreparedCall:
    invoke: Callable[[], OrderAcknowledgementResult | FillApplicationResult]
    connection_identity: int


@dataclass(frozen=True, slots=True)
class _Scenario:
    name: str
    prepare: Callable[[
        _Environment,
        _DirectRunner | _ModularRunner,
        str,
        int,
    ], _PreparedCall]


def _new_environment(path: Path) -> _Environment:
    db = RuntimeDatabase(path)
    connection = db.connect()
    MigrationManager(db, MIGRATION_PLAN).migrate()
    adapter = SqliteLifecyclePersistence(db, NettingPositionAccountingV1())
    return _Environment(db, adapter, id(connection))


def _scenario_time(ordinal: int, offset_seconds: int) -> datetime:
    return _BASE_TIME + timedelta(seconds=(ordinal * 20) + offset_seconds)


def _seed_execution_graph(
    db: RuntimeDatabase,
    suffix: str,
    *,
    action: str,
    account_scope: str,
    symbol: str = "BTC/USDT",
) -> dict[str, str]:
    graph = {
        "session_id": f"session-{suffix}",
        "cycle_id": f"cycle-{suffix}",
        "trade_intent_id": f"trade-{suffix}",
        "risk_decision_id": f"risk-{suffix}",
        "execution_intent_id": f"execution-{suffix}",
        "attempt_id": f"attempt-{suffix}",
        "client_order_id": f"client-{suffix}",
        "order_id": f"order-{suffix}",
        "symbol": symbol,
        "action": action,
        "venue": "okx_paper",
        "account_scope": account_scope,
    }
    connection = db.connection
    connection.execute(
        "INSERT INTO runtime_sessions VALUES (?,?,?,?,NULL,NULL)",
        (graph["session_id"], "2026-01-01T00:00:00Z", "paper", "RUNNING"),
    )
    connection.execute(
        "INSERT INTO runtime_cycles "
        "(cycle_id,session_id,symbol,started_at,status) VALUES (?,?,?,?,?)",
        (
            graph["cycle_id"],
            graph["session_id"],
            symbol,
            "2026-01-01T00:00:00Z",
            "CREATED",
        ),
    )
    connection.execute(
        "INSERT INTO trade_intents VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            graph["trade_intent_id"],
            symbol,
            action,
            "0.9",
            "benchmark",
            "{}",
            "0.1",
            "0.02",
            "0.04",
            "[]",
            "[]",
            "2026-01-01T00:00:00Z",
        ),
    )
    connection.execute(
        "INSERT INTO risk_decisions VALUES (?,?,?,?,?,?,?)",
        (
            graph["risk_decision_id"],
            graph["trade_intent_id"],
            "APPROVED",
            "[]",
            "0.1",
            "{}",
            "2026-01-01T00:00:00Z",
        ),
    )
    connection.execute(
        "INSERT INTO execution_intents VALUES (?,?,?,?,?,?,?,?,?)",
        (
            graph["execution_intent_id"],
            graph["trade_intent_id"],
            graph["risk_decision_id"],
            graph["cycle_id"],
            symbol,
            action,
            "100",
            hashlib.sha256(suffix.encode("utf-8")).hexdigest(),
            "2026-01-01T00:00:00Z",
        ),
    )
    connection.execute(
        "INSERT INTO dispatch_attempts VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (
            graph["attempt_id"],
            graph["execution_intent_id"],
            graph["client_order_id"],
            graph["venue"],
            account_scope,
            "SUBMITTED",
            1,
            "2026-01-01T00:00:00Z",
            "2026-01-01T00:00:00Z",
            None,
            None,
        ),
    )
    connection.execute(
        "INSERT INTO execution_states VALUES (?,?,?,?,?,?)",
        (
            graph["execution_intent_id"],
            "DISPATCHED",
            graph["attempt_id"],
            0,
            "2026-01-01T00:00:00Z",
            "2026-01-01T00:00:00Z",
        ),
    )
    connection.commit()
    return graph


def _order_command(
    graph: Mapping[str, str],
    ordinal: int,
    *,
    quantity: Decimal = Decimal("2"),
) -> OrderAcknowledgementCommand:
    return OrderAcknowledgementCommand(
        venue=graph["venue"],
        account_scope=graph["account_scope"],
        order_id=graph["order_id"],
        execution_intent_id=graph["execution_intent_id"],
        attempt_id=graph["attempt_id"],
        client_order_id=graph["client_order_id"],
        symbol=graph["symbol"],
        side=OrderSide(graph["action"]),
        quantity=quantity,
        price=Decimal("100"),
        order_type=OrderType.LIMIT,
        acknowledged_at=_scenario_time(ordinal, 0),
    )


def _fill_command(
    graph: Mapping[str, str],
    ordinal: int,
    fill_id: str,
    *,
    quantity: Decimal = Decimal("1"),
    price: Decimal = Decimal("100"),
    status: OrderStatus = OrderStatus.PARTIALLY_FILLED,
    occurred_offset: int = 1,
    recorded_offset: int = 2,
) -> FillApplicationCommand:
    return FillApplicationCommand(
        venue=graph["venue"],
        account_scope=graph["account_scope"],
        fill_id=fill_id,
        order_id=graph["order_id"],
        symbol=graph["symbol"],
        quantity=quantity,
        price=price,
        fee=Decimal("0.1"),
        fee_currency="USDT",
        occurred_at=_scenario_time(ordinal, occurred_offset),
        recorded_at=_scenario_time(ordinal, recorded_offset),
        order_status_after=status,
    )


def _setup_ack(
    adapter: SqliteLifecyclePersistence,
    command: OrderAcknowledgementCommand,
) -> None:
    result = SqliteLifecyclePersistence.register_order_acknowledgement(
        adapter, command
    )
    if result.outcome is not PersistenceOutcome.APPLIED:
        raise BenchmarkContractError("setup acknowledgement was not APPLIED")


def _setup_fill(
    adapter: SqliteLifecyclePersistence,
    command: FillApplicationCommand,
) -> None:
    result = SqliteLifecyclePersistence.apply_fill(adapter, command)
    if result.outcome is not PersistenceOutcome.APPLIED:
        raise BenchmarkContractError("setup fill was not APPLIED")


def _prepare_new_order(
    environment: _Environment,
    runner: _DirectRunner | _ModularRunner,
    label: str,
    ordinal: int,
) -> _PreparedCall:
    suffix = f"{label}-ack-{ordinal}"
    graph = _seed_execution_graph(
        environment.db,
        suffix,
        action="BUY",
        account_scope=f"scope-{suffix}",
    )
    command = _order_command(graph, ordinal)
    return _PreparedCall(lambda: runner.acknowledge(command), environment.connection_identity)


def _prepare_new_one_event_fill(
    environment: _Environment,
    runner: _DirectRunner | _ModularRunner,
    label: str,
    ordinal: int,
) -> _PreparedCall:
    suffix = f"{label}-one-fill-{ordinal}"
    graph = _seed_execution_graph(
        environment.db,
        suffix,
        action="BUY",
        account_scope=f"scope-{suffix}",
    )
    _setup_ack(environment.adapter, _order_command(graph, ordinal))
    command = _fill_command(graph, ordinal, f"fill-{suffix}")
    return _PreparedCall(lambda: runner.apply_fill(command), environment.connection_identity)


def _prepare_zero_crossing(
    environment: _Environment,
    runner: _DirectRunner | _ModularRunner,
    label: str,
    ordinal: int,
) -> _PreparedCall:
    scope = f"scope-{label}-cross-{ordinal}"
    buy_suffix = f"{label}-cross-buy-{ordinal}"
    buy = _seed_execution_graph(
        environment.db,
        buy_suffix,
        action="BUY",
        account_scope=scope,
    )
    _setup_ack(environment.adapter, _order_command(buy, ordinal, quantity=Decimal("1")))
    _setup_fill(
        environment.adapter,
        _fill_command(
            buy,
            ordinal,
            f"fill-{buy_suffix}",
            quantity=Decimal("1"),
            status=OrderStatus.FILLED,
        ),
    )

    sell_suffix = f"{label}-cross-sell-{ordinal}"
    sell = _seed_execution_graph(
        environment.db,
        sell_suffix,
        action="SELL",
        account_scope=scope,
    )
    _setup_ack(
        environment.adapter,
        _order_command(sell, ordinal, quantity=Decimal("1.5")),
    )
    command = _fill_command(
        sell,
        ordinal,
        f"fill-{sell_suffix}",
        quantity=Decimal("1.5"),
        price=Decimal("110"),
        status=OrderStatus.FILLED,
        occurred_offset=3,
        recorded_offset=4,
    )
    return _PreparedCall(lambda: runner.apply_fill(command), environment.connection_identity)


def _prepare_order_replay(
    environment: _Environment,
    runner: _DirectRunner | _ModularRunner,
    label: str,
    ordinal: int,
) -> _PreparedCall:
    suffix = f"{label}-ack-replay-{ordinal}"
    graph = _seed_execution_graph(
        environment.db,
        suffix,
        action="BUY",
        account_scope=f"scope-{suffix}",
    )
    command = _order_command(graph, ordinal)
    _setup_ack(environment.adapter, command)
    return _PreparedCall(lambda: runner.acknowledge(command), environment.connection_identity)


def _prepare_fill_replay(
    environment: _Environment,
    runner: _DirectRunner | _ModularRunner,
    label: str,
    ordinal: int,
) -> _PreparedCall:
    suffix = f"{label}-fill-replay-{ordinal}"
    graph = _seed_execution_graph(
        environment.db,
        suffix,
        action="BUY",
        account_scope=f"scope-{suffix}",
    )
    _setup_ack(environment.adapter, _order_command(graph, ordinal))
    command = _fill_command(graph, ordinal, f"fill-{suffix}")
    _setup_fill(environment.adapter, command)
    return _PreparedCall(lambda: runner.apply_fill(command), environment.connection_identity)


_SCENARIOS = (
    _Scenario(OP_NEW_ORDER_ACK, _prepare_new_order),
    _Scenario(OP_NEW_ONE_EVENT_FILL, _prepare_new_one_event_fill),
    _Scenario(OP_NEW_ZERO_CROSSING, _prepare_zero_crossing),
    _Scenario(OP_EXACT_ORDER_REPLAY, _prepare_order_replay),
    _Scenario(OP_EXACT_FILL_REPLAY, _prepare_fill_replay),
)


def _percentile_ns(values: Sequence[int], percentile: float) -> int:
    if not values:
        raise ValueError("values must not be empty")
    if not 0 <= percentile <= 1:
        raise ValueError("percentile must be between 0 and 1")
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * percentile
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = position - lower
    interpolated = ordered[lower] + (ordered[upper] - ordered[lower]) * fraction
    return int(round(interpolated))


def _stats_payload(stats: OperationStats) -> dict[str, int]:
    return {
        "read_statements": stats.read_statements,
        "attempted_mutations": stats.attempted_mutations,
        "committed_mutations": stats.committed_mutations,
        "transaction_count": stats.transaction_count,
    }


def _assert_result_contract(
    operation: str,
    result: OrderAcknowledgementResult | FillApplicationResult,
    expected_connection_identity: int,
) -> None:
    expected = _EXPECTED_COUNTS[operation]
    actual = _stats_payload(result.stats)
    if actual != expected:
        raise BenchmarkContractError(
            f"{operation} statement counts differ: expected={expected}, actual={actual}"
        )
    if result.stats.db_connection_identity != expected_connection_identity:
        raise BenchmarkContractError(f"{operation} changed database connection")
    if operation in (OP_EXACT_ORDER_REPLAY, OP_EXACT_FILL_REPLAY):
        expected_outcome = PersistenceOutcome.REPLAY_NOOP
    else:
        expected_outcome = PersistenceOutcome.APPLIED
    if result.outcome is not expected_outcome:
        raise BenchmarkContractError(
            f"{operation} outcome is {result.outcome}, expected {expected_outcome}"
        )


def _time_call(
    operation: str,
    prepared: _PreparedCall,
) -> tuple[int, OrderAcknowledgementResult | FillApplicationResult]:
    started = time.perf_counter_ns()
    result = prepared.invoke()
    elapsed = time.perf_counter_ns() - started
    if elapsed <= 0:
        raise BenchmarkContractError("perf_counter_ns returned non-positive elapsed time")
    _assert_result_contract(operation, result, prepared.connection_identity)
    return elapsed, result


def _benchmark_operation(
    scenario: _Scenario,
    baseline_environment: _Environment,
    modular_environment: _Environment,
    *,
    sample_count: int,
    warmup_count: int,
) -> dict[str, Any]:
    baseline_runner = _DirectRunner(baseline_environment.adapter)
    modular_runner = _ModularRunner(modular_environment.adapter)
    baseline_samples: list[int] = []
    modular_samples: list[int] = []

    total_iterations = warmup_count + sample_count
    for ordinal in range(total_iterations):
        baseline_prepared = scenario.prepare(
            baseline_environment,
            baseline_runner,
            "baseline",
            ordinal,
        )
        modular_prepared = scenario.prepare(
            modular_environment,
            modular_runner,
            "modular",
            ordinal,
        )

        ordered_calls = (
            (("baseline", baseline_prepared), ("modular", modular_prepared))
            if ordinal % 2 == 0
            else (("modular", modular_prepared), ("baseline", baseline_prepared))
        )
        measured: dict[str, int] = {}
        for label, prepared in ordered_calls:
            elapsed, _ = _time_call(scenario.name, prepared)
            measured[label] = elapsed

        if ordinal >= warmup_count:
            baseline_samples.append(measured["baseline"])
            modular_samples.append(measured["modular"])

    if len(baseline_samples) != sample_count or len(modular_samples) != sample_count:
        raise BenchmarkContractError("sample collection count mismatch")

    baseline_p50 = _percentile_ns(baseline_samples, 0.50)
    baseline_p95 = _percentile_ns(baseline_samples, 0.95)
    modular_p50 = _percentile_ns(modular_samples, 0.50)
    modular_p95 = _percentile_ns(modular_samples, 0.95)
    p50_ratio = modular_p50 / baseline_p50
    p95_ratio = modular_p95 / baseline_p95

    connection_reuse = (
        id(baseline_environment.db.connection)
        == baseline_environment.connection_identity
        and id(modular_environment.db.connection)
        == modular_environment.connection_identity
    )

    return {
        "operation": scenario.name,
        "baseline_p50_ns": baseline_p50,
        "baseline_p95_ns": baseline_p95,
        "modular_p50_ns": modular_p50,
        "modular_p95_ns": modular_p95,
        "p50_ratio": p50_ratio,
        "p95_ratio": p95_ratio,
        "baseline_statement_counts": dict(_EXPECTED_COUNTS[scenario.name]),
        "modular_statement_counts": dict(_EXPECTED_COUNTS[scenario.name]),
        "connection_reuse": connection_reuse,
        "gate_status": "PASS" if connection_reuse and p95_ratio <= MAX_P95_RATIO else "FAIL",
    }


def _baseline_equivalence() -> dict[str, Any]:
    return {
        "baseline_call": "unbound concrete public method",
        "modular_call": "typed Protocol direct in-process call",
        "same_public_implementation": True,
        "same_input_validation": True,
        "same_decimal_and_utc_normalization": True,
        "same_sql_statements": True,
        "same_transaction_mode": "BEGIN IMMEDIATE",
        "same_schema_and_migrations": True,
        "same_durability_pragmas": {
            "foreign_keys": "ON",
            "journal_mode": "WAL",
            "synchronous": "FULL",
            "busy_timeout_ms": 5000,
        },
        "same_accounting_policy": "NettingPositionAccountingV1",
        "policy_indirection_bypassed": False,
        "network_calls": 0,
        "reconnects_per_operation": 0,
        "internal_json_transport": False,
    }


def evaluate_report(report: Mapping[str, Any]) -> tuple[str, list[str]]:
    errors: list[str] = []
    if report.get("schema_version") != SCHEMA_VERSION:
        errors.append("schema_version mismatch")
    if report.get("live") != LIVE:
        errors.append("LIVE must be FORBIDDEN")
    head_sha = report.get("head_sha")
    if (
        not isinstance(head_sha, str)
        or len(head_sha) != 40
        or any(character not in "0123456789abcdef" for character in head_sha)
    ):
        errors.append("head_sha is not exact lowercase SHA-1 text")
    run_id = report.get("run_id")
    if not isinstance(run_id, str) or not run_id.isdigit():
        errors.append("run_id is not decimal text")
    if not str(report.get("python_version", "")).startswith("3.11"):
        errors.append("python_version must be 3.11")
    if report.get("clock") != "time.perf_counter_ns":
        errors.append("clock mismatch")
    if report.get("max_p95_ratio") != MAX_P95_RATIO:
        errors.append("max_p95_ratio mismatch")
    if report.get("sample_count", 0) < MIN_SAMPLE_COUNT:
        errors.append("sample_count below minimum")
    if report.get("warmup_count", 0) < MIN_WARMUP_COUNT:
        errors.append("warmup_count below minimum")
    if report.get("baseline_equivalence") != _baseline_equivalence():
        errors.append("baseline equivalence proof mismatch")
    expected_topology = {
        "database_files": 2,
        "persistent_connections": 2,
        "sample_order": "alternating baseline/modular",
        "warmups_excluded": True,
        "same_process": True,
    }
    if report.get("benchmark_topology") != expected_topology:
        errors.append("benchmark topology mismatch")
    if report.get("connection_reuse") is not True:
        errors.append("top-level connection reuse failed")

    operation_records = report.get("operations")
    if not isinstance(operation_records, list):
        errors.append("operations must be a list")
        return "FAIL", errors
    by_name = {
        record.get("operation"): record
        for record in operation_records
        if isinstance(record, Mapping)
    }
    if (
        len(operation_records) != len(REQUIRED_OPERATIONS)
        or len(by_name) != len(REQUIRED_OPERATIONS)
        or set(by_name) != set(REQUIRED_OPERATIONS)
    ):
        errors.append("required operation set mismatch")

    for name in REQUIRED_OPERATIONS:
        record = by_name.get(name)
        if record is None:
            continue
        if record.get("baseline_statement_counts") != dict(_EXPECTED_COUNTS[name]):
            errors.append(f"{name}: baseline statement counts mismatch")
        if record.get("modular_statement_counts") != dict(_EXPECTED_COUNTS[name]):
            errors.append(f"{name}: modular statement counts mismatch")
        if record.get("connection_reuse") is not True:
            errors.append(f"{name}: connection was not reused")
        p50_ratio = record.get("p50_ratio")
        if not isinstance(p50_ratio, (int, float)) or p50_ratio <= 0:
            errors.append(f"{name}: p50 ratio must be positive")
        ratio = record.get("p95_ratio")
        if (
            not isinstance(ratio, (int, float))
            or ratio <= 0
            or ratio > MAX_P95_RATIO
        ):
            errors.append(f"{name}: p95 ratio exceeds {MAX_P95_RATIO:.2f}")
        for field in (
            "baseline_p50_ns",
            "baseline_p95_ns",
            "modular_p50_ns",
            "modular_p95_ns",
        ):
            value = record.get(field)
            if type(value) is not int or value <= 0:
                errors.append(f"{name}: {field} must be positive int")
        expected_gate = "PASS" if (
            record.get("connection_reuse") is True
            and isinstance(ratio, (int, float))
            and ratio <= MAX_P95_RATIO
        ) else "FAIL"
        if record.get("gate_status") != expected_gate:
            errors.append(f"{name}: gate_status inconsistent with evidence")

    return ("PASS" if not errors else "FAIL"), errors


def run_benchmark(
    *,
    workdir: Path,
    sample_count: int = DEFAULT_SAMPLE_COUNT,
    warmup_count: int = DEFAULT_WARMUP_COUNT,
    head_sha: str,
    run_id: str,
) -> dict[str, Any]:
    if type(sample_count) is not int or sample_count < MIN_SAMPLE_COUNT:
        raise ValueError(f"sample_count must be int >= {MIN_SAMPLE_COUNT}")
    if type(warmup_count) is not int or warmup_count < MIN_WARMUP_COUNT:
        raise ValueError(f"warmup_count must be int >= {MIN_WARMUP_COUNT}")
    if (
        not isinstance(head_sha, str)
        or len(head_sha) != 40
        or any(character not in "0123456789abcdef" for character in head_sha)
    ):
        raise ValueError("head_sha must be exactly 40 lowercase hexadecimal characters")
    if not isinstance(run_id, str) or not run_id.isdigit():
        raise ValueError("run_id must contain decimal digits only")

    workdir.mkdir(parents=True, exist_ok=True)
    baseline_environment = _new_environment(workdir / "baseline.sqlite")
    modular_environment = _new_environment(workdir / "modular.sqlite")
    try:
        operations = [
            _benchmark_operation(
                scenario,
                baseline_environment,
                modular_environment,
                sample_count=sample_count,
                warmup_count=warmup_count,
            )
            for scenario in _SCENARIOS
        ]
        report: dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "head_sha": head_sha,
            "run_id": run_id,
            "python_version": platform.python_version(),
            "platform": platform.platform(),
            "sample_count": sample_count,
            "warmup_count": warmup_count,
            "clock": "time.perf_counter_ns",
            "max_p95_ratio": MAX_P95_RATIO,
            "benchmark_topology": {
                "database_files": 2,
                "persistent_connections": 2,
                "sample_order": "alternating baseline/modular",
                "warmups_excluded": True,
                "same_process": True,
            },
            "baseline_equivalence": _baseline_equivalence(),
            "operations": operations,
            "connection_reuse": all(
                record["connection_reuse"] for record in operations
            ),
            "live": LIVE,
        }
        gate_status, errors = evaluate_report(report)
        report["gate_status"] = gate_status
        report["errors"] = errors
        return report
    finally:
        baseline_environment.close()
        modular_environment.close()


def write_report_atomic(path: Path, report: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    payload = json.dumps(report, indent=2, sort_keys=True) + "\n"
    temporary.write_text(payload, encoding="utf-8")
    os.replace(temporary, path)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the B4.3B3 lifecycle modular-overhead performance gate."
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("b4_3b_performance_report.json"),
    )
    parser.add_argument("--sample-count", type=int, default=DEFAULT_SAMPLE_COUNT)
    parser.add_argument("--warmup-count", type=int, default=DEFAULT_WARMUP_COUNT)
    parser.add_argument(
        "--head-sha",
        default=os.environ.get("GITHUB_SHA"),
    )
    parser.add_argument(
        "--run-id",
        default=os.environ.get("GITHUB_RUN_ID"),
    )
    parser.add_argument("--workdir", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    if args.workdir is None:
        with tempfile.TemporaryDirectory(prefix="b4-3b3-benchmark-") as temporary:
            report = run_benchmark(
                workdir=Path(temporary),
                sample_count=args.sample_count,
                warmup_count=args.warmup_count,
                head_sha=args.head_sha,
                run_id=args.run_id,
            )
    else:
        report = run_benchmark(
            workdir=args.workdir,
            sample_count=args.sample_count,
            warmup_count=args.warmup_count,
            head_sha=args.head_sha,
            run_id=args.run_id,
        )
    write_report_atomic(args.output, report)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["gate_status"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
