"""Verify Simple CI workflow status for an exact head SHA via GitHub Actions API.

Fail-closed: only exact-SHA + completed + success → PASS.
"""
import json, os, urllib.request, urllib.error

def _api(url, token):
    req = urllib.request.Request(url)
    req.add_header("Authorization", "Bearer " + token)
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("X-GitHub-Api-Version", "2022-11-28")
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"GitHub API HTTP {e.code}: {e.reason}")
    except (OSError, ValueError) as e:
        raise RuntimeError(f"GitHub API error: {e}")

def verify_simple_ci_for_sha(head_sha, repo="Dreaminmaster/ai-autonomous-trading-os", token=None):
    """Fail-closed: any issue → RuntimeError. Returns evidence dict on success."""
    if not head_sha or len(head_sha) < 7:
        raise RuntimeError(f"Invalid head_sha: {head_sha!r}")
    token = token or os.environ.get("GITHUB_TOKEN", "")
    if not token:
        raise RuntimeError("GITHUB_TOKEN not set")
    
    url = f"https://api.github.com/repos/{repo}/actions/runs?head_sha={head_sha}&per_page=50"
    data = _api(url, token)
    
    runs = data.get("workflow_runs", [])
    if not runs:
        raise RuntimeError(f"No CI runs found for SHA {head_sha[:8]}")
    
    simple_ci_runs = [r for r in runs if r.get("name") == "CI"]
    if not simple_ci_runs:
        raise RuntimeError(f"No Simple CI run found for SHA {head_sha[:8]}")
    
    # Pick most recent matching run
    best = simple_ci_runs[0]
    for r in simple_ci_runs[1:]:
        if r.get("created_at", "") > best.get("created_at", ""):
            best = r
    
    status = best.get("status")
    conclusion = best.get("conclusion")
    run_id = best.get("id")
    run_sha = best.get("head_sha")
    
    if run_sha != head_sha:
        raise RuntimeError(f"Simple CI head_sha mismatch: {run_sha[:8]} != {head_sha[:8]}")
    if status != "completed":
        raise RuntimeError(f"Simple CI run {run_id} status={status}, expected completed")
    if conclusion != "success":
        raise RuntimeError(f"Simple CI run {run_id} conclusion={conclusion}, expected success")
    
    return {
        "schema_version": 1,
        "workflow": "CI",
        "run_id": run_id,
        "head_sha": head_sha,
        "status": "completed",
        "conclusion": "success",
        "verified": True,
    }
