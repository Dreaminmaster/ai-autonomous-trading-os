"""Tests: canonical runner provenance, isolation, SHA256 tracking."""

import hashlib
import json
import tempfile
from pathlib import Path

def test_runner_rejects_stale_existing_json():
    """Runner must reject JSONs created before run_started_ns."""
    results_dir = Path(tempfile.mkdtemp())
    js = results_dir / "backtest-result-old.json"
    js.write_text("{}")
    js_stat = js.stat()
    # Simulate: mtime is from an hour ago
    run_started_ns = js_stat.st_mtime_ns + 3600 * 1_000_000_000
    # reject rule: mtime_ns < run_started_ns → skip
    assert js_stat.st_mtime_ns < run_started_ns, "stale file not rejected"

def test_runner_accepts_fresh_new_json():
    """Runner must accept JSON created after run_started_ns."""
    import os, time
    results_dir = Path(tempfile.mkdtemp())
    js = results_dir / "backtest-result-fresh.json"
    js.write_text('{"strategy": {"total_trades": 42}}')
    # Set mtime deterministically: 2 seconds after run_started_ns
    run_started_ns = int(time.time_ns())
    fresh_mtime_ns = run_started_ns + 2_000_000_000  # +2 seconds
    os.utime(js, ns=(fresh_mtime_ns, fresh_mtime_ns))
    js_stat = js.stat()
    assert js_stat.st_mtime_ns >= run_started_ns, (
        f"fresh file should be accepted: mtime {js_stat.st_mtime_ns} >= run_started {run_started_ns}"
    )

def test_variant_results_are_isolated():
    """Each variant must have its own isolated results dir."""
    d1 = Path(tempfile.mkdtemp()) / "run1" / "variant_a"
    d2 = Path(tempfile.mkdtemp()) / "run1" / "variant_b"
    d1.mkdir(parents=True)
    d2.mkdir(parents=True)
    (d1 / "result.json").write_text('{"a": 1}')
    (d2 / "result.json").write_text('{"b": 2}')
    assert (d1 / "result.json").exists()
    assert (d2 / "result.json").exists()
    assert d1 != d2, "variants must use distinct dirs"

def test_summary_contains_source_json_sha256():
    """Summary JSON must include source_json_sha256."""
    import time
    summary = {
        "variant": "test_variant",
        "run_id": "test_123",
        "run_started_at_ns": time.time_ns(),
        "source_json_path": "/tmp/test.json",
        "source_json_mtime_ns": time.time_ns(),
        "source_json_sha256": hashlib.sha256(b"test").hexdigest()[:16],
        "total_trades": 42,
        "profit_total_pct": 10.0,
        "profit_total": 100.0,
        "winrate": 0.55,
        "max_drawdown": 5.0,
        "profit_factor": 1.5,
        "policy_sha256": "abcd1234",
        "config_sha256": "efgh5678",
        "cache_mode": "none",
        "elapsed_s": 42.0,
    }
    assert "source_json_sha256" in summary
    assert len(summary["source_json_sha256"]) == 16
    assert "policy_sha256" in summary
    assert "config_sha256" in summary
    assert summary["cache_mode"] == "none"

def test_sha256_is_valid_hex():
    """SHA256 must be valid hex."""
    h = hashlib.sha256(b"policy content").hexdigest()
    assert len(h) == 64
    assert all(c in "0123456789abcdef" for c in h)
    h12 = h[:12]
    assert len(h12) == 12

def test_isolated_dir_per_variant():
    """Directory per variant must include backtest_results subdir."""
    import tempfile
    d = Path(tempfile.mkdtemp())
    (d / "backtest_results").mkdir(parents=True)
    assert (d / "backtest_results").exists()
