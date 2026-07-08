"""Real producer→consumer integration: verify_simple_ci_for_sha → generate_summary."""
import json, tempfile, pathlib
from unittest.mock import patch

SHA = "abc1234567890123456789012345678901234567"

def test_real_producer_output_passes_consumer():
    cnt = [0]
    class FResp:
        def __init__(s, data): s.data = data
        def read(s): return json.dumps(s.data).encode()
        def __enter__(s): return s
        def __exit__(s,*_): pass
    def fake(url, *a, **kw):
        cnt[0] += 1
        if cnt[0] == 1:
            return FResp({"workflows":[{"id":305746223,"path":".github/workflows/ci.yml","name":"CI","state":"active"}]})
        return FResp({"workflow_runs":[{"name":"CI","status":"completed","conclusion":"success","id":789,"head_sha":SHA,"created_at":"2026-01-01"}]})

    with patch('atos.simple_ci_evidence.urllib.request.urlopen', fake):
        from atos.simple_ci_evidence import verify_simple_ci_for_sha
        sci = verify_simple_ci_for_sha(SHA, token="x")

    assert sci["workflow_id"] == 305746223
    assert sci["verified"] is True

    from atos.evidence_summary import generate_summary, summary_pass, write_json_atomic

    ad=tempfile.mkdtemp(); fd=tempfile.mkdtemp()
    ab=pathlib.Path(ad); fb=pathlib.Path(fd)

    write_json_atomic(str(ab/"evidence_manifest.json"),{"schema_version":1,"run_id":"run1","head_sha":SHA,"job":"atos-tests"})
    write_json_atomic(str(fb/"evidence_manifest.json"),{"schema_version":1,"run_id":"run1","head_sha":SHA,"job":"freqtrade"})
    (fb/"freqtrade_data/backtest_results").mkdir(parents=True)
    write_json_atomic(str(fb/"freqtrade_data/backtest_results/canonical_baseline_summary.json"),{"total_trades":244,"profit_total_pct":-16.12,"winrate":44.67,"max_drawdown_pct":17.85,"profit_factor":0.75,"baseline_integrity":"CONFIRMED","pair_universe_integrity":"PASS","cache_mode":"none","run_id":"run1"})
    write_json_atomic(str(fb/"freqtrade_data/backtest_results/canonical_baseline_la_lookahead_status.json"),{"schema_version":1,"parser_status":"PASS","has_bias":False,"fatal_markers_found":[],"final_status":"PASS","freqtrade_returncode":0,"explicit_no_bias_evidence":False,"variant":"v1_la","output_base":"v1_la"})
    (fb/"validation_reports").mkdir(parents=True)
    write_json_atomic(str(fb/"validation_reports/strategy_fix_round1.json"),{"schema_version":1,"run_id":"run1","head_sha":SHA,"baseline_integrity":"PASS","baseline_metrics":{k:"PASS" for k in["total_trades","profit_total_pct","winrate","max_drawdown_pct","profit_factor"]},"selected_variants":[{"variant":"v1","lookahead_variant":"v1_la","lookahead_status_file":"freqtrade_data/backtest_results/v1_la_lookahead_status.json","lookahead_final_status":"PASS"}]})
    write_json_atomic(str(fb/"freqtrade_data/backtest_results/v1_la_lookahead_status.json"),{"schema_version":1,"parser_status":"PASS","has_bias":False,"fatal_markers_found":[],"final_status":"PASS","freqtrade_returncode":0,"explicit_no_bias_evidence":False,"variant":"v1_la","output_base":"v1_la"})

    s,err=generate_summary(SHA,"run1","success","success",ad,fd,simple_ci_evidence=sci)
    assert summary_pass(s,err), f"Integration failed: {err}"
    assert s["simple_ci"]["workflow_id"] == 305746223
    assert s["simple_ci"]["verified"] is True
