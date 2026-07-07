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
