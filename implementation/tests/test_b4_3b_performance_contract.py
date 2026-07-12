"""B4.3B3 lifecycle performance contract and evidence tests."""
from __future__ import annotations

import ast
import copy
import importlib.util
import json
import sys
from pathlib import Path

import pytest

_SCRIPT_PATH = (
    Path(__file__).resolve().parents[1]
    / "scripts"
    / "benchmark_b4_3b_lifecycle.py"
)
_SPEC = importlib.util.spec_from_file_location(
    "atos_b4_3b_lifecycle_benchmark",
    _SCRIPT_PATH,
)
assert _SPEC is not None and _SPEC.loader is not None
benchmark = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = benchmark
_SPEC.loader.exec_module(benchmark)


@pytest.fixture(scope="module")
def performance_report(tmp_path_factory):
    workdir = tmp_path_factory.mktemp("b4-3b3-performance")
    return benchmark.run_benchmark(
        workdir=workdir,
        sample_count=benchmark.MIN_SAMPLE_COUNT,
        warmup_count=benchmark.MIN_WARMUP_COUNT,
        head_sha="a" * 40,
        run_id="123456789",
    )


def test_real_relative_performance_gate_passes(performance_report):
    assert performance_report["gate_status"] == "PASS"
    assert performance_report["errors"] == []
    assert performance_report["connection_reuse"] is True
    assert performance_report["live"] == "FORBIDDEN"


def test_evidence_metadata_is_exact_and_complete(performance_report):
    assert performance_report["schema_version"] == benchmark.SCHEMA_VERSION
    assert performance_report["head_sha"] == "a" * 40
    assert performance_report["run_id"] == "123456789"
    assert performance_report["python_version"].startswith("3.11")
    assert performance_report["platform"]
    assert performance_report["clock"] == "time.perf_counter_ns"
    assert performance_report["sample_count"] == benchmark.MIN_SAMPLE_COUNT
    assert performance_report["warmup_count"] == benchmark.MIN_WARMUP_COUNT
    assert performance_report["replicate_count"] == benchmark.REPLICATE_COUNT
    assert performance_report["total_sample_count"] == (
        benchmark.MIN_SAMPLE_COUNT * benchmark.REPLICATE_COUNT
    )
    assert performance_report["aggregation"] == benchmark.AGGREGATION
    assert performance_report["crossover"] == benchmark.CROSSOVER
    assert performance_report["calls_per_sample_per_path"] == (
        benchmark.CALLS_PER_SAMPLE_PER_PATH
    )
    assert performance_report["total_call_count_per_path"] == (
        benchmark.MIN_SAMPLE_COUNT
        * benchmark.REPLICATE_COUNT
        * benchmark.CALLS_PER_SAMPLE_PER_PATH
    )
    assert performance_report["max_p95_ratio"] == pytest.approx(1.10)


def test_all_required_operations_are_present_once(performance_report):
    records = performance_report["operations"]
    names = [record["operation"] for record in records]
    assert tuple(names) == benchmark.REQUIRED_OPERATIONS
    assert len(names) == len(set(names))


@pytest.mark.parametrize("operation", benchmark.REQUIRED_OPERATIONS)
def test_each_operation_meets_latency_and_statement_gate(
    performance_report,
    operation,
):
    record = next(
        item for item in performance_report["operations"]
        if item["operation"] == operation
    )
    assert record["gate_status"] == "PASS"
    assert record["connection_reuse"] is True
    assert record["aggregation"] == benchmark.AGGREGATION
    assert record["replicate_count"] == benchmark.REPLICATE_COUNT
    assert record["sample_count_per_replicate"] == benchmark.MIN_SAMPLE_COUNT
    assert record["total_sample_count"] == (
        benchmark.MIN_SAMPLE_COUNT * benchmark.REPLICATE_COUNT
    )
    assert record["crossover"] == benchmark.CROSSOVER
    assert record["calls_per_sample_per_path"] == (
        benchmark.CALLS_PER_SAMPLE_PER_PATH
    )
    assert record["total_call_count_per_path"] == (
        benchmark.MIN_SAMPLE_COUNT
        * benchmark.REPLICATE_COUNT
        * benchmark.CALLS_PER_SAMPLE_PER_PATH
    )
    assert len(record["replicates"]) == benchmark.REPLICATE_COUNT
    assert [item["replicate_index"] for item in record["replicates"]] == list(
        range(1, benchmark.REPLICATE_COUNT + 1)
    )
    for replicate in record["replicates"]:
        assert replicate["crossover"] == benchmark.CROSSOVER
        assert replicate["calls_per_sample_per_path"] == (
            benchmark.CALLS_PER_SAMPLE_PER_PATH
        )
        assert replicate["p50_ratio"] > 0
        assert replicate["p95_ratio"] > 0
    assert 0 < record["p95_ratio"] <= benchmark.MAX_P95_RATIO
    assert record["p50_ratio"] > 0
    for field in (
        "baseline_p50_ns",
        "baseline_p95_ns",
        "modular_p50_ns",
        "modular_p95_ns",
        "pooled_baseline_p50_ns",
        "pooled_baseline_p95_ns",
        "pooled_modular_p50_ns",
        "pooled_modular_p95_ns",
    ):
        assert type(record[field]) is int
        assert record[field] > 0
    expected = dict(benchmark._EXPECTED_COUNTS[operation])
    assert record["baseline_statement_counts"] == expected
    assert record["modular_statement_counts"] == expected


def test_baseline_equivalence_proof_is_fail_closed(performance_report):
    proof = performance_report["baseline_equivalence"]
    assert proof == {
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
        "database_role_crossover": True,
        "calls_per_sample_per_path": benchmark.CALLS_PER_SAMPLE_PER_PATH,
        "internal_json_transport": False,
    }


def test_report_evaluator_rejects_latency_regression(performance_report):
    altered = copy.deepcopy(performance_report)
    altered["operations"][0]["p95_ratio"] = 1.100001
    altered["operations"][0]["gate_status"] = "FAIL"
    gate, errors = benchmark.evaluate_report(altered)
    assert gate == "FAIL"
    assert any("p95 ratio exceeds" in error for error in errors)


def test_report_evaluator_rejects_missing_replicate_evidence(performance_report):
    altered = copy.deepcopy(performance_report)
    altered["operations"][0]["replicates"].pop()
    gate, errors = benchmark.evaluate_report(altered)
    assert gate == "FAIL"
    assert any("replicate evidence mismatch" in error for error in errors)


def test_report_evaluator_rejects_aggregation_drift(performance_report):
    altered = copy.deepcopy(performance_report)
    altered["aggregation"] = "pooled_percentiles"
    gate, errors = benchmark.evaluate_report(altered)
    assert gate == "FAIL"
    assert "aggregation mismatch" in errors


def test_report_evaluator_rejects_crossover_drift(performance_report):
    altered = copy.deepcopy(performance_report)
    altered["crossover"] = "fixed_database_roles"
    gate, errors = benchmark.evaluate_report(altered)
    assert gate == "FAIL"
    assert "crossover mismatch" in errors


def test_report_evaluator_rejects_call_count_drift(performance_report):
    altered = copy.deepcopy(performance_report)
    altered["operations"][0]["calls_per_sample_per_path"] = 1
    gate, errors = benchmark.evaluate_report(altered)
    assert gate == "FAIL"
    assert any("calls_per_sample_per_path mismatch" in error for error in errors)


def test_report_evaluator_rejects_missing_operation(performance_report):
    altered = copy.deepcopy(performance_report)
    altered["operations"].pop()
    gate, errors = benchmark.evaluate_report(altered)
    assert gate == "FAIL"
    assert "required operation set mismatch" in errors


def test_report_evaluator_rejects_statement_drift(performance_report):
    altered = copy.deepcopy(performance_report)
    altered["operations"][1]["modular_statement_counts"][
        "committed_mutations"
    ] += 1
    gate, errors = benchmark.evaluate_report(altered)
    assert gate == "FAIL"
    assert any("modular statement counts mismatch" in error for error in errors)


def test_minimum_samples_and_warmups_are_enforced(tmp_path):
    with pytest.raises(ValueError, match="sample_count"):
        benchmark.run_benchmark(
            workdir=tmp_path / "samples",
            sample_count=benchmark.MIN_SAMPLE_COUNT - 1,
            warmup_count=benchmark.MIN_WARMUP_COUNT,
            head_sha="b" * 40,
            run_id="1",
        )
    with pytest.raises(ValueError, match="warmup_count"):
        benchmark.run_benchmark(
            workdir=tmp_path / "warmups",
            sample_count=benchmark.MIN_SAMPLE_COUNT,
            warmup_count=benchmark.MIN_WARMUP_COUNT - 1,
            head_sha="b" * 40,
            run_id="1",
        )


@pytest.mark.parametrize(
    ("head_sha", "run_id", "message"),
    [
        ("A" * 40, "1", "head_sha"),
        ("a" * 39, "1", "head_sha"),
        ("a" * 40, "local", "run_id"),
        ("a" * 40, "", "run_id"),
    ],
)
def test_exact_sha_and_run_binding_is_required(
    tmp_path,
    head_sha,
    run_id,
    message,
):
    with pytest.raises(ValueError, match=message):
        benchmark.run_benchmark(
            workdir=tmp_path / f"invalid-{message}-{len(run_id)}",
            sample_count=benchmark.MIN_SAMPLE_COUNT,
            warmup_count=benchmark.MIN_WARMUP_COUNT,
            head_sha=head_sha,
            run_id=run_id,
        )


def test_percentile_interpolation_is_deterministic():
    values = [10, 20, 30, 40, 50]
    assert benchmark._percentile_ns(values, 0.50) == 30
    assert benchmark._percentile_ns(values, 0.95) == 48
    with pytest.raises(ValueError):
        benchmark._percentile_ns([], 0.95)


def test_atomic_report_writer_leaves_no_partial_file(tmp_path, performance_report):
    output = tmp_path / "evidence" / "performance.json"
    benchmark.write_report_atomic(output, performance_report)
    assert json.loads(output.read_text(encoding="utf-8")) == performance_report
    assert not output.with_name(output.name + ".tmp").exists()


def test_benchmark_has_no_network_orm_or_sleep_dependency():
    source = _SCRIPT_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported_roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_roots.update(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_roots.add(node.module.split(".", 1)[0])
    assert imported_roots.isdisjoint(
        {
            "requests",
            "httpx",
            "aiohttp",
            "urllib3",
            "sqlalchemy",
            "socket",
        }
    )
    assert "time.sleep" not in source
    assert "sqlite3.connect" not in source
    assert "http://" not in source
    assert "https://" not in source


def test_topology_proves_two_files_persistent_connections_and_alternation(
    performance_report,
):
    assert performance_report["benchmark_topology"] == {
        "database_files": 2,
        "persistent_connections": 2,
        "sample_order": "paired AB/BA crossover with alternating call order",
        "warmups_excluded": True,
        "same_process": True,
        "database_role_crossover": True,
        "calls_per_sample_per_path": benchmark.CALLS_PER_SAMPLE_PER_PATH,
        "replicate_aggregation": benchmark.AGGREGATION,
    }
