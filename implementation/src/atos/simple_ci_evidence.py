"""Verify Simple CI workflow via GitHub Actions API. Fail-closed."""
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
    if not head_sha or len(head_sha) < 7:
        raise RuntimeError(f"Invalid head_sha: {head_sha!r}")
    token = token or os.environ.get("GITHUB_TOKEN", "")
    if not token:
        raise RuntimeError("GITHUB_TOKEN not set")

    # Step 1: Resolve workflow ID by path
    wf_url = f"https://api.github.com/repos/{repo}/actions/workflows"
    wf_data = _api(wf_url, token)
    target_path = ".github/workflows/ci.yml"
    target_name = "CI"
    workflow_id = None
    for w in wf_data.get("workflows", []):
        if w.get("path") == target_path and w.get("name") == target_name and w.get("state") == "active":
            workflow_id = w.get("id")
            break
    if workflow_id is None:
        raise RuntimeError(f"Workflow not found: {target_path} ({target_name})")

    # Step 2: Get runs for exact workflow_id + head_sha
    runs_url = f"https://api.github.com/repos/{repo}/actions/workflows/{workflow_id}/runs?head_sha={head_sha}&per_page=20"
    runs_data = _api(runs_url, token)
    runs = runs_data.get("workflow_runs", [])
    if not runs:
        raise RuntimeError(f"No Simple CI runs for SHA {head_sha[:8]}")
    if len(runs) > 1:
        raise RuntimeError(f"Ambiguous: {len(runs)} Simple CI runs for SHA {head_sha[:8]}")
    r = runs[0]
    run_id = r.get("id")
    run_sha = r.get("head_sha")
    status = r.get("status")
    conclusion = r.get("conclusion")

    if run_sha != head_sha:
        raise RuntimeError(f"Simple CI head_sha mismatch: {run_sha[:8]} != {head_sha[:8]}")
    if status != "completed":
        raise RuntimeError(f"Simple CI not completed: {status}")
    if conclusion != "success":
        raise RuntimeError(f"Simple CI not success: {conclusion}")

    return {
        "schema_version": 1,
        "workflow_id": workflow_id,
        "workflow_name": target_name,
        "workflow_path": target_path,
        "run_id": run_id,
        "head_sha": head_sha,
        "status": status,
        "conclusion": conclusion,
        "verified": True,
    }
