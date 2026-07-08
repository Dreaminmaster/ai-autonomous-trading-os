"""Simple CI evidence tests."""
import json, pytest
from unittest.mock import patch
from atos.simple_ci_evidence import verify_simple_ci_for_sha

def _mock(wf_runs):
    wfs = {"workflows": [{"id":99,"path":".github/workflows/ci.yml","name":"CI","state":"active"}]}
    cnt = [0]
    def fake(url, *a, **kw):
        cnt[0] += 1
        class R:
            def read(self): return json.dumps(wfs if cnt[0]==1 else wf_runs).encode()
            def __enter__(s): return s
            def __exit__(s,*_): pass
        return R()
    return fake

def test_success():
    runs = {"workflow_runs": [{"name":"CI","status":"completed","conclusion":"success","id":123,"head_sha":"abc123def","created_at":"2026-01-01"}]}
    with patch('atos.simple_ci_evidence.urllib.request.urlopen', _mock(runs)):
        r = verify_simple_ci_for_sha("abc123def", token="x")
        assert r["verified"] is True and r["workflow_id"] == 99

def test_missing(): _chk({"workflow_runs": []})
def test_wrong_sha(): _chk({"workflow_runs": [{"name":"CI","status":"completed","conclusion":"success","id":1,"head_sha":"DIFF"}]})
def test_pending(): _chk({"workflow_runs": [{"name":"CI","status":"in_progress","conclusion":None,"id":1,"head_sha":"abc123def"}]})
def test_failure(): _chk({"workflow_runs": [{"name":"CI","status":"completed","conclusion":"failure","id":1,"head_sha":"abc123def"}]})
def test_cancelled(): _chk({"workflow_runs": [{"name":"CI","status":"completed","conclusion":"cancelled","id":1,"head_sha":"abc123def"}]})
def test_ambiguous(): _chk({"workflow_runs": [{"name":"CI","status":"completed","conclusion":"success","id":1,"head_sha":"abc123def"},{"name":"CI","status":"completed","conclusion":"success","id":2,"head_sha":"abc123def"}]})

def _chk(runs):
    with patch('atos.simple_ci_evidence.urllib.request.urlopen', _mock(runs)):
        with pytest.raises(RuntimeError):
            verify_simple_ci_for_sha("abc123def", token="x")

def test_api_error():
    exc = RuntimeError("API down")
    def _err(*a,**kw): raise exc
    with patch('atos.simple_ci_evidence.urllib.request.urlopen', _err):
        with pytest.raises(RuntimeError):
            verify_simple_ci_for_sha("abc123def", token="x")

def test_invalid_sha():
    with pytest.raises(RuntimeError):
        verify_simple_ci_for_sha("short", token="x")
