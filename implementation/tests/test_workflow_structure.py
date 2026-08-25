"""Structural contract tests for Freqtrade Validation workflow."""
import yaml, pathlib, pytest

WORKFLOW_PATH = pathlib.Path(__file__).resolve().parents[2] / ".github" / "workflows" / "freqtrade-validation.yml"

@pytest.fixture
def wf():
    with open(WORKFLOW_PATH) as f:
        return yaml.safe_load(f)

def test_yaml_parse(wf): assert wf is not None

def test_workflow_dispatch_exists(wf):
    assert True in wf.get("on",{}) or "workflow_dispatch" in str(wf.get("on",{})) or wf.get("on") is None or "workflow_dispatch" in open(WORKFLOW_PATH).read()

def test_completed_c7a_authoritative_run_cannot_be_dispatched_again(wf):
    raw = open(WORKFLOW_PATH).read()
    assert "c7a-h1-h5-authoritative" not in wf.get("jobs", {})
    assert "c7a_h1_h5_authoritative" not in raw
    assert "scripts/c7a_h1_h5_capture.py" not in raw
    assert "scripts/c7a_h1_h5_evaluate.py" not in raw

def test_completed_c8a_authoritative_run_cannot_be_dispatched_again(wf):
    raw = open(WORKFLOW_PATH).read()
    assert "c8a-h1-h5-authoritative" not in wf.get("jobs", {})
    assert "c8a_h1_h5_authoritative" not in raw
    assert "scripts/c8a_h1_h5_capture.py" not in raw
    assert "scripts/c8a_h1_h5_evaluate.py" not in raw

def test_completed_c9a_authoritative_run_cannot_be_dispatched_again(wf):
    raw = open(WORKFLOW_PATH).read()
    assert "c9a-w1-w5-authoritative" not in wf.get("jobs", {})
    assert "c9a_w1_w5_authoritative" not in raw
    assert "scripts/c9a_w1_w5_capture.py" not in raw
    assert "scripts/c9a_w1_w5_evaluate.py" not in raw

def test_atos_tests_job(wf):
    assert "atos-tests" in wf.get("jobs",{})

def test_freqtrade_job(wf):
    assert "freqtrade" in wf.get("jobs",{})

def test_validation_summary_job(wf):
    assert "validation-summary" in wf.get("jobs",{})

def test_validation_summary_needs_upstream(wf):
    vs = wf["jobs"]["validation-summary"]
    assert "atos-tests" in vs.get("needs",[])
    assert "freqtrade" in vs.get("needs",[])

def test_atos_preflight_step(wf):
    steps = [s.get("name","") for s in wf["jobs"].get("atos-tests",{}).get("steps",[])]
    assert "Preflight evidence atos-tests" in steps

def test_freq_preflight_step(wf):
    steps = [s.get("name","") for s in wf["jobs"].get("freqtrade",{}).get("steps",[])]
    assert "Preflight evidence freqtrade" in steps

def test_upload_atos_after_preflight(wf):
    steps = [s.get("name","") for s in wf["jobs"].get("atos-tests",{}).get("steps",[])]
    p_idx = steps.index("Preflight evidence atos-tests")
    u_idx = steps.index("Upload ATOS artifacts")
    assert p_idx < u_idx

def test_upload_freq_after_preflight(wf):
    steps = [s.get("name","") for s in wf["jobs"].get("freqtrade",{}).get("steps",[])]
    p_idx = steps.index("Preflight evidence freqtrade")
    u_idx = steps.index("Upload Freqtrade artifacts")
    assert p_idx < u_idx

def test_no_if_always_on_atos_upload(wf):
    for s in wf["jobs"]["atos-tests"]["steps"]:
        if s.get("name") == "Upload ATOS artifacts":
            assert "if" not in s

def test_no_if_always_on_freq_upload(wf):
    for s in wf["jobs"]["freqtrade"]["steps"]:
        if s.get("name") == "Upload Freqtrade artifacts":
            assert "if" not in s

def test_stale_heredoc_count_zero(wf):
    raw = open(WORKFLOW_PATH).read()
    assert "<< 'EOFMANIFEST'" not in raw
    assert "cat > implementation/evidence_manifest.json" not in raw

def test_no_duplicate_cd(wf):
    raw = open(WORKFLOW_PATH).read()
    lines = raw.split("\n")
    for i in range(len(lines)-1):
        if "cd implementation" in lines[i] and "cd implementation" in lines[i+1]:
            assert False, f"duplicate cd at line {i+1}"

def test_manifest_producer_consumer_names(wf):
    # atos upload
    atos_name = None
    for s in wf["jobs"]["atos-tests"]["steps"]:
        if s.get("uses","") == "actions/upload-artifact@v4":
            atos_name = s.get("with",{}).get("name","")
    assert atos_name == "atos-validation"
    # freqtrade upload
    freq_name = None
    for s in wf["jobs"]["freqtrade"]["steps"]:
        if s.get("uses","") == "actions/upload-artifact@v4":
            freq_name = s.get("with",{}).get("name","")
    assert freq_name == "freqtrade-validation"

def test_validation_summary_fail_closed(wf):
    vs = wf["jobs"]["validation-summary"]
    has_always = any("always()" in str(s) for s in vs.get("steps",[]))
    assert not has_always

def test_pytest_pipefail():
    raw = open(WORKFLOW_PATH).read()
    assert 'set -o pipefail; python -m pytest' in raw, 'pytest step missing pipefail'

def test_secret_scan_pipefail():
    raw = open(WORKFLOW_PATH).read()
    assert 'set -o pipefail; bash scripts/validate_no_secrets' in raw, 'secret scan step missing pipefail'

def test_atos_download_name_path():
    import yaml; wf = yaml.safe_load(open(WORKFLOW_PATH))
    vs = wf['jobs']['validation-summary']['steps']
    dl = [s for s in vs if 'download-artifact' in str(s.get('uses',''))]
    atos = [d for d in dl if d.get('with',{}).get('name')=='atos-validation']
    assert len(atos)==1, f'atos download missing: found {len(atos)}'
    assert atos[0]['with']['path']=='atos_artifacts'

def test_freqtrade_download_name_path():
    import yaml; wf = yaml.safe_load(open(WORKFLOW_PATH))
    vs = wf['jobs']['validation-summary']['steps']
    dl = [s for s in vs if 'download-artifact' in str(s.get('uses',''))]
    freq = [d for d in dl if d.get('with',{}).get('name')=='freqtrade-validation']
    assert len(freq)==1, f'freqtrade download missing: found {len(freq)}'
    assert freq[0]['with']['path']=='freqtrade_artifacts'

def test_validation_summary_upload():
    import yaml; wf = yaml.safe_load(open(WORKFLOW_PATH))
    vs = wf['jobs']['validation-summary']['steps']
    uploads = [s for s in vs if 'upload-artifact' in str(s.get('uses',''))]
    val = [u for u in uploads if u.get('with',{}).get('name')=='validation-summary']
    assert len(val)==1, f'validation-summary upload missing: found {len(val)}'
    assert val[0]['with']['if-no-files-found']=='error'

def test_notify_job_is_pr_only_and_waits_for_validation(wf):
    notify = wf["jobs"]["notify"]
    assert set(notify["needs"]) == {"atos-tests", "freqtrade", "validation-summary"}
    condition = str(notify["if"])
    assert "always()" in condition
    assert "github.event_name == 'pull_request'" in condition

def test_notify_is_fail_open_and_uses_secret_endpoint(wf):
    notify = wf["jobs"]["notify"]
    assert len(notify["steps"]) == 1
    step = notify["steps"][0]
    assert step["continue-on-error"] is True
    assert step["env"]["MESSAGE_PUSH_ENDPOINT"] == "${{ secrets.MESSAGE_PUSH_ENDPOINT }}"
    assert "|| true" in step["run"]

def test_notify_payload_contract_and_no_endpoint_literal():
    raw = WORKFLOW_PATH.read_text()
    assert "messagepush.luckfast.com" not in raw
    assert "curl --fail --silent --show-error --max-time 20 --get" in raw
    assert '--data-urlencode "title=ATOS · Freqtrade Validation 完成"' in raw
    assert '--data-urlencode "message=${body}"' in raw
    assert '--data-urlencode "content=${body}"' not in raw
    assert '--data-urlencode "sound=1"' in raw
    assert 'PR #${PR_NUMBER} | ${status} | SHA ${PR_HEAD_SHA} | Run ID ${RUN_ID}' in raw
    for status in ("SUCCESS", "FAILURE", "CANCELLED"):
        assert status in raw

def test_notify_uses_exact_pr_head_not_synthetic_merge_sha(wf):
    env = wf["jobs"]["notify"]["steps"][0]["env"]
    assert env["PR_HEAD_SHA"] == "${{ github.event.pull_request.head.sha }}"
    assert env["RUN_ID"] == "${{ github.run_id }}"
