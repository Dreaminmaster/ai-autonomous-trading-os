"""Physically separate reviewer for the bounded C6A GLOBAL scope probe.

No production probe, scope, transport, parser, gate, or package code is
imported.  Candidate identity, safety headers, retained bytes, redirect targets,
GLOBAL page evidence, profile replication, and the final probe verdict are
recomputed from the artifact directory.
"""
from __future__ import annotations

import hashlib
import json
import re
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Mapping, Sequence
from urllib.parse import urlparse


SCOPE_FAILURE = "FAIL_SOURCE_AUTHORITY_SCOPE_DRIFT"
PROBE_STAGE = "C6A_GLOBAL_SOURCE_SCOPE_PROBE"
PROBE_URL = "https://www.okx.com/help/section/announcements-latest-announcements/page/1"
_BROWSER_UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)
_ATOS_UA = "atos-c6a-source-scope-probe/1.0"
_ALLOWED_PATH_RE = re.compile(
    r"^/(?:[a-z]{2,3}(?:-[a-z]{2,4})?/)?help/(?:"
    r"section/announcements-latest-announcements(?:/page/1)?|"
    r"category/announcements"
    r")/?$",
    re.IGNORECASE,
)
_GLOBAL_PATH_RE = re.compile(
    r"^/help/(?:section/announcements-latest-announcements(?:/page/1)?|category/announcements)/?$",
    re.IGNORECASE,
)
_REQUIRED_MARKERS = (
    "latest events",
    "deposit/withdrawal suspension",
    "p2p trading",
    "web3",
    "earn and loan",
    "jumpstart",
    "okb burn",
    "others",
)
_FORBIDDEN_MARKERS = ("okx united states", "okx europe", "okx tr")


def _headers(user_agent: str, accept_language: str | None) -> dict[str, str]:
    result = {
        "User-Agent": user_agent,
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Encoding": "identity",
    }
    if accept_language is not None:
        result["Accept-Language"] = accept_language
    return result


def _expected_candidates() -> dict[str, dict[str, Any]]:
    profiles = (
        ("control-atos-minimal", _ATOS_UA, None),
        ("browser-neutral-en", _BROWSER_UA, "en;q=1.0"),
        ("browser-en-us", _BROWSER_UA, "en-US,en;q=0.9"),
        ("browser-en-gb", _BROWSER_UA, "en-GB,en;q=0.9"),
    )
    result: dict[str, dict[str, Any]] = {}
    for profile_id, user_agent, accept_language in profiles:
        for replicate in ("A", "B"):
            candidate_id = f"{profile_id}-{replicate.lower()}"
            result[candidate_id] = {
                "profile_id": profile_id,
                "replicate": replicate,
                "request_headers": _headers(user_agent, accept_language),
            }
    return result


class _VisibleTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        text = " ".join(data.split())
        if text:
            self.parts.append(text)


def _allowed_target(url: str) -> bool:
    parsed = urlparse(url)
    return bool(
        parsed.scheme == "https"
        and (parsed.hostname or "").lower() == "www.okx.com"
        and not parsed.username
        and not parsed.password
        and not parsed.fragment
        and not parsed.query
        and _ALLOWED_PATH_RE.fullmatch(parsed.path)
    )


def _global_target(url: str) -> bool:
    parsed = urlparse(url)
    return bool(_allowed_target(url) and _GLOBAL_PATH_RE.fullmatch(parsed.path))


def _safe_file(root: Path, relative: Any) -> Path | None:
    if not isinstance(relative, str) or not relative:
        return None
    path = (root / relative).resolve()
    if not path.is_relative_to(root.resolve()) or not path.is_file():
        return None
    return path


def _recompute_scope(final_url: str, raw: bytes) -> tuple[bool, list[str]]:
    diagnostics: list[str] = []
    if not _global_target(final_url):
        diagnostics.append("final URL is not the locale-neutral GLOBAL Help Center")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        return False, diagnostics + ["raw page is not UTF-8"]
    parser = _VisibleTextParser()
    parser.feed(text)
    folded = " ".join(parser.parts).casefold()
    forbidden = [marker for marker in _FORBIDDEN_MARKERS if marker in folded]
    missing = [marker for marker in _REQUIRED_MARKERS if marker not in folded]
    if forbidden:
        diagnostics.append(f"regional identity markers present: {forbidden}")
    if missing:
        diagnostics.append(f"GLOBAL category evidence missing: {missing}")
    return not diagnostics, diagnostics


def review_probe(root: Path) -> dict[str, Any]:
    errors: list[str] = []
    path = root / "probe_result.json"
    if not path.is_file():
        return {
            "schema_version": 1,
            "stage": f"{PROBE_STAGE}_INDEPENDENT_REVIEW",
            "status": "FAIL",
            "probe_status_recomputed": "FAIL",
            "probe_result_recomputed": SCOPE_FAILURE,
            "errors": ["probe_result.json missing"],
            "implementation_authorized": False,
            "economic_data_access_authorized": False,
            "third_full_capture_authorized": False,
            "live_state": "LIVE_FORBIDDEN",
        }
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        return {
            "schema_version": 1,
            "stage": f"{PROBE_STAGE}_INDEPENDENT_REVIEW",
            "status": "FAIL",
            "probe_status_recomputed": "FAIL",
            "probe_result_recomputed": SCOPE_FAILURE,
            "errors": [f"probe result unreadable: {exc}"],
            "implementation_authorized": False,
            "economic_data_access_authorized": False,
            "third_full_capture_authorized": False,
            "live_state": "LIVE_FORBIDDEN",
        }

    if payload.get("stage") != PROBE_STAGE or payload.get("probe_url") != PROBE_URL:
        errors.append("probe identity or URL drift")
    if payload.get("implementation_authorized") is not False:
        errors.append("probe improperly authorizes implementation")
    if payload.get("economic_data_access_authorized") is not False:
        errors.append("probe improperly authorizes economic data access")
    if payload.get("third_full_capture_authorized") is not False:
        errors.append("probe improperly authorizes a third full capture")
    if payload.get("live_state") != "LIVE_FORBIDDEN":
        errors.append("probe live-state boundary drift")

    expected = _expected_candidates()
    rows = payload.get("candidate_results")
    if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes)):
        rows = []
        errors.append("candidate results missing")
    observed_ids = [str(row.get("candidate_id", "")) for row in rows if isinstance(row, Mapping)]
    if set(observed_ids) != set(expected) or len(observed_ids) != len(expected):
        errors.append("candidate identity coverage mismatch")

    recomputed_rows: list[dict[str, Any]] = []
    for index, row in enumerate(rows):
        if not isinstance(row, Mapping):
            errors.append(f"candidate row {index} is not an object")
            continue
        candidate_id = str(row.get("candidate_id", ""))
        contract = expected.get(candidate_id)
        if contract is None:
            continue
        if row.get("profile_id") != contract["profile_id"] or row.get("replicate") != contract["replicate"]:
            errors.append(f"candidate {candidate_id} profile identity drift")
        headers = row.get("request_headers")
        if headers != contract["request_headers"]:
            errors.append(f"candidate {candidate_id} request header drift")
        if isinstance(headers, Mapping) and any(
            str(key).casefold() in {"cookie", "authorization", "proxy-authorization"}
            for key in headers
        ):
            errors.append(f"candidate {candidate_id} contains prohibited request state")
        if row.get("request_url") != PROBE_URL:
            errors.append(f"candidate {candidate_id} request URL drift")
        chain = row.get("redirect_chain", [])
        if isinstance(chain, Sequence) and not isinstance(chain, (str, bytes)):
            for redirect in chain:
                if not isinstance(redirect, Mapping) or not _allowed_target(
                    str(redirect.get("to_url", ""))
                ):
                    errors.append(f"candidate {candidate_id} redirect escaped probe scope")
        else:
            errors.append(f"candidate {candidate_id} redirect chain invalid")

        raw_path = _safe_file(root, row.get("raw_path"))
        if raw_path is None:
            recomputed_rows.append(
                {
                    "candidate_id": candidate_id,
                    "profile_id": contract["profile_id"],
                    "replicate": contract["replicate"],
                    "scope_status": "FAIL",
                    "final_url": row.get("final_url"),
                }
            )
            continue
        raw = raw_path.read_bytes()
        if row.get("raw_size") != len(raw) or row.get("raw_sha256") != hashlib.sha256(raw).hexdigest():
            errors.append(f"candidate {candidate_id} raw size/hash mismatch")
        passed, diagnostics = _recompute_scope(str(row.get("final_url", "")), raw)
        recomputed_status = "PASS" if passed else "FAIL"
        if row.get("scope_status") != recomputed_status:
            errors.append(f"candidate {candidate_id} production/reviewer scope mismatch")
        if passed and row.get("failure_code") not in (None, ""):
            errors.append(f"candidate {candidate_id} records failure on reviewer PASS")
        if not passed and row.get("failure_code") != SCOPE_FAILURE:
            errors.append(f"candidate {candidate_id} lacks scope-drift failure code")
        recomputed_rows.append(
            {
                "candidate_id": candidate_id,
                "profile_id": contract["profile_id"],
                "replicate": contract["replicate"],
                "scope_status": recomputed_status,
                "final_url": row.get("final_url"),
                "diagnostics": diagnostics,
            }
        )

    passing_profiles: list[str] = []
    for profile_id in dict.fromkeys(contract["profile_id"] for contract in expected.values()):
        selected = [row for row in recomputed_rows if row["profile_id"] == profile_id]
        if (
            len(selected) == 2
            and {row["replicate"] for row in selected} == {"A", "B"}
            and all(row["scope_status"] == "PASS" for row in selected)
            and len({row["final_url"] for row in selected}) == 1
        ):
            passing_profiles.append(profile_id)

    probe_status = "PASS" if passing_profiles else "FAIL"
    probe_result = "PASS" if passing_profiles else SCOPE_FAILURE
    if payload.get("status") != probe_status or payload.get("result") != probe_result:
        errors.append("production/reviewer probe verdict mismatch")
    if payload.get("reproducible_passing_profiles") != passing_profiles:
        errors.append("production/reviewer passing-profile mismatch")

    return {
        "schema_version": 1,
        "stage": f"{PROBE_STAGE}_INDEPENDENT_REVIEW",
        "status": "PASS" if not errors else "FAIL",
        "probe_status_recomputed": probe_status,
        "probe_result_recomputed": probe_result,
        "reproducible_passing_profiles": passing_profiles,
        "candidate_results_recomputed": recomputed_rows,
        "errors": errors,
        "implementation_authorized": False,
        "economic_data_access_authorized": False,
        "third_full_capture_authorized": False,
        "live_state": "LIVE_FORBIDDEN",
    }
