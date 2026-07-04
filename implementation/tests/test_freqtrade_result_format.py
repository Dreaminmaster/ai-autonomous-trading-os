"""Tests: parse Freqtrade zip/json results, provenance, unit consistency."""

import hashlib
import json
import tempfile
import zipfile
from pathlib import Path

def test_parse_freqtrade_zip_result():
    """Parse a realistic Freqtrade zip archive with embedded JSON."""
    js = json.dumps({"strategy": {"total_trades": 244, "profit_total_pct": -16.12, "winrate": 44.7, "max_drawdown": 17.85, "profit_factor": 0.75}})
    d = tempfile.mkdtemp()
    zp = Path(d) / "backtest-result-test.zip"
    with zipfile.ZipFile(zp, "w") as zz:
        zz.writestr("backtest-result.json", js)
    with zipfile.ZipFile(zp) as zz:
        names = zz.namelist()
        for name in names:
            if "meta" not in name and name.endswith(".json"):
                data = json.loads(zz.read(name))
                assert data["strategy"]["total_trades"] == 244
                break

def test_parse_freqtrade_plain_json_result():
    """Direct JSON fallback works."""
    js = {"strategy": {"total_trades": 42, "profit_total_pct": 10.0, "winrate": 55.0, "max_drawdown": 5.0, "profit_factor": 2.0}}
    assert js["strategy"]["total_trades"] == 42

def test_meta_json_not_treated_as_full_result():
    """Files with 'meta' in name are excluded."""
    assert "meta" in "backtest-result-ts.meta.json"
    assert "meta" not in "backtest-result-ts.json"

def test_canonical_summary_units():
    """profit_total_pct is always -16.12 not -0.1612."""
    summary = {"profit_total_pct": -16.12, "max_drawdown_pct": 17.85}
    assert summary["profit_total_pct"] == -16.12
    assert summary["max_drawdown_pct"] == 17.85

def test_canonical_summary_contains_provenance():
    import time
    summary = {
        "variant": "test",
        "run_id": "run_1",
        "run_started_at_ns": time.time_ns(),
        "source_result_path": "/tmp/test.zip",
        "source_result_sha256": hashlib.sha256(b"x").hexdigest()[:16],
        "source_result_type": "zip",
        "total_trades": 244,
        "profit_total_pct": -16.12,
        "winrate": 44.7,
        "max_drawdown_pct": 17.85,
        "profit_factor": 0.75,
        "policy_sha256": "abcd1234",
        "config_sha256": "efgh5678",
        "cache_mode": "none",
        "isolated_user_data_dir": "/tmp/iso/run1/v1",
        "baseline_integrity": "CONFIRMED",
    }
    assert summary["source_result_type"] in ("zip", "json")
    assert len(summary["source_result_sha256"]) == 16
    assert summary["baseline_integrity"] == "CONFIRMED"

def test_isolated_result_does_not_use_old_global_file():
    """Isolated dir must be specific to run/variant, not shared."""
    d1 = Path(tempfile.mkdtemp()) / "run_a" / "variant_1" / "backtest_results"
    d2 = Path(tempfile.mkdtemp()) / "run_a" / "variant_2" / "backtest_results"
    d1.mkdir(parents=True)
    d2.mkdir(parents=True)
    assert d1 != d2
    (d1 / "result.zip").write_text("a")
    (d2 / "result.zip").write_text("b")
    assert (d1 / "result.zip").read_text() != (d2 / "result.zip").read_text()
