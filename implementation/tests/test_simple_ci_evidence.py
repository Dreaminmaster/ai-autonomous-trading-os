"""Simple CI evidence tests."""
import json, pytest
from unittest.mock import patch

def _fake_api(runs, exc=None):
    class Resp:
        def read(self): return json.dumps({"workflow_runs": runs}).encode()
        def __enter__(self): return self
        def __exit__(self,*a): pass
    def fake(url, *args, **kw):
        if exc: raise exc
        return Resp()
    return fake

def test_success():
    runs = [{"name":"CI","status":"completed","conclusion":"success","id":123,"head_sha":"abc123def","created_at":"2026-01-01"}]
    with patch('atos.simple_ci_evidence.urllib.request.urlopen', _fake_api(runs)):
        from atos.simple_ci_evidence import verify_simple_ci_for_sha
        r = verify_simple_ci_for_sha("abc123def", token="x")
        assert r["verified"]

def test_missing(): _check_raises([])
def test_no_ci(): _check_raises([{"name":"X","status":"completed","conclusion":"success","id":1,"head_sha":"abc123def","created_at":"2026-01-01"}])
def test_wrong_sha(): _check_raises([{"name":"CI","status":"completed","conclusion":"success","id":1,"head_sha":"DIFF","created_at":"2026-01-01"}])
def test_pending(): _check_raises([{"name":"CI","status":"in_progress","conclusion":None,"id":1,"head_sha":"abc123def","created_at":"2026-01-01"}])
def test_failure(): _check_raises([{"name":"CI","status":"completed","conclusion":"failure","id":1,"head_sha":"abc123def","created_at":"2026-01-01"}])
def test_cancelled(): _check_raises([{"name":"CI","status":"completed","conclusion":"cancelled","id":1,"head_sha":"abc123def","created_at":"2026-01-01"}])
def test_api_error(): _check_raises([{"name":"CI","status":"completed","conclusion":"success","id":1,"head_sha":"abc123def","created_at":"2026-01-01"}], exc=RuntimeError("API down"))
def test_invalid_sha():
    with patch('atos.simple_ci_evidence.urllib.request.urlopen', _fake_api([])):
        from atos.simple_ci_evidence import verify_simple_ci_for_sha
        with pytest.raises(RuntimeError):
            verify_simple_ci_for_sha("short", token="x")

def _check_raises(runs, exc=None):
    with patch('atos.simple_ci_evidence.urllib.request.urlopen', _fake_api(runs, exc)):
        from atos.simple_ci_evidence import verify_simple_ci_for_sha
        with pytest.raises(RuntimeError):
            verify_simple_ci_for_sha("abc123def", token="x")
