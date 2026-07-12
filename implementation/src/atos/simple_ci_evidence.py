"""Verify Simple CI workflow via GitHub Actions API. Fail-closed."""
import json
import os
import urllib.error
import urllib.request


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


def _valid_sha(value, label):
    if not isinstance(value, str) or len(value) < 7:
        raise RuntimeError(f"Invalid {label}: {value!r}")


def _run_matches_pr(run, pr_number):
    for pr in run.get("pull_requests", []):
        if pr.get("number") == pr_number:
            return True
    return False


def verify_simple_ci_for_sha(
    head_sha,
    repo="Dreaminmaster/ai-autonomous-trading-os",
    token=None,
    run_head_sha=None,
    pr_number=None,
    run_event=None,
):
    """Verify the authoritative Simple CI run for one evidence SHA.

    For push/workflow_dispatch validation, ``head_sha`` and ``run_head_sha`` are
    the same exact commit. For pull_request validation, GitHub's Actions API
    indexes the CI run by the PR source head while the checked-out commit is the
    synthetic merge ref in ``GITHUB_SHA``. In that mode this function verifies
    the PR source head, PR number, event type and current ``merge_commit_sha``
    before binding the successful CI run to the merge-ref evidence SHA.
    """
    _valid_sha(head_sha, "head_sha")
    run_head_sha = run_head_sha or head_sha
    _valid_sha(run_head_sha, "run_head_sha")

    if pr_number is not None and (type(pr_number) is not int or pr_number <= 0):
        raise RuntimeError(f"Invalid pr_number: {pr_number!r}")
    if run_head_sha != head_sha and pr_number is None:
        raise RuntimeError("pr_number required when run_head_sha differs from head_sha")
    if run_head_sha != head_sha and run_event != "pull_request":
        raise RuntimeError("pull_request event required for merge-ref provenance")

    token = token or os.environ.get("GITHUB_TOKEN", "")
    if not token:
        raise RuntimeError("GITHUB_TOKEN not set")

    # Step 1: Resolve workflow ID by exact path + name.
    wf_url = f"https://api.github.com/repos/{repo}/actions/workflows"
    wf_data = _api(wf_url, token)
    target_path = ".github/workflows/ci.yml"
    target_name = "CI"
    workflow_id = None
    for workflow in wf_data.get("workflows", []):
        if (
            workflow.get("path") == target_path
            and workflow.get("name") == target_name
            and workflow.get("state") == "active"
        ):
            workflow_id = workflow.get("id")
            break
    if workflow_id is None:
        raise RuntimeError(f"Workflow not found: {target_path} ({target_name})")

    # Step 2: Get CI runs indexed by the API's authoritative run head SHA.
    runs_url = (
        f"https://api.github.com/repos/{repo}/actions/workflows/{workflow_id}/runs"
        f"?head_sha={run_head_sha}&per_page=20"
    )
    runs_data = _api(runs_url, token)
    candidates = runs_data.get("workflow_runs", [])
    if run_event:
        candidates = [run for run in candidates if run.get("event") == run_event]
    if pr_number is not None:
        candidates = [run for run in candidates if _run_matches_pr(run, pr_number)]

    if not candidates:
        details = f" event={run_event}" if run_event else ""
        if pr_number is not None:
            details += f" pr={pr_number}"
        raise RuntimeError(f"No Simple CI runs for SHA {run_head_sha[:8]}{details}")
    if len(candidates) > 1:
        raise RuntimeError(
            f"Ambiguous: {len(candidates)} Simple CI runs for SHA {run_head_sha[:8]}"
        )

    run = candidates[0]
    run_id = run.get("id")
    api_run_sha = run.get("head_sha")
    status = run.get("status")
    conclusion = run.get("conclusion")
    event = run.get("event")

    if api_run_sha != run_head_sha:
        raise RuntimeError(
            f"Simple CI head_sha mismatch: {str(api_run_sha)[:8]} != {run_head_sha[:8]}"
        )
    if run_event and event != run_event:
        raise RuntimeError(f"Simple CI event mismatch: {event} != {run_event}")
    if status != "completed":
        raise RuntimeError(f"Simple CI not completed: {status}")
    if conclusion != "success":
        raise RuntimeError(f"Simple CI not success: {conclusion}")

    provenance_mode = "exact_sha"
    merge_commit_verified = False

    # Step 3: For pull_request merge refs, independently verify the mapping.
    if run_head_sha != head_sha:
        pr_url = f"https://api.github.com/repos/{repo}/pulls/{pr_number}"
        pr_data = _api(pr_url, token)
        pr_head_sha = ((pr_data.get("head") or {}).get("sha"))
        merge_commit_sha = pr_data.get("merge_commit_sha")
        if pr_head_sha != run_head_sha:
            raise RuntimeError(
                f"PR head_sha mismatch: {str(pr_head_sha)[:8]} != {run_head_sha[:8]}"
            )
        if merge_commit_sha != head_sha:
            raise RuntimeError(
                f"PR merge_commit_sha mismatch: {str(merge_commit_sha)[:8]} != {head_sha[:8]}"
            )
        provenance_mode = "pull_request_merge_ref"
        merge_commit_verified = True

    return {
        "schema_version": 1,
        "workflow_id": workflow_id,
        "workflow_name": target_name,
        "workflow_path": target_path,
        "run_id": run_id,
        "head_sha": head_sha,
        "run_head_sha": run_head_sha,
        "event": event,
        "pr_number": pr_number,
        "provenance_mode": provenance_mode,
        "merge_commit_verified": merge_commit_verified,
        "status": status,
        "conclusion": conclusion,
        "verified": True,
    }
