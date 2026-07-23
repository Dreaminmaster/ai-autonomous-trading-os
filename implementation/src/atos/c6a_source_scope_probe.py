"""Bounded public Help Center probe for reproducible GLOBAL source scope.

The probe is deliberately narrower than the source-authority gate.  It requests
only page 1 of the public OKX announcement catalog with a frozen transparent
header matrix, retains raw bytes/headers/redirects, and never accesses articles,
Wayback, instruments, candles, funding, accounts, trading, paper, shadow, or
live endpoints.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from email.message import Message
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener

from atos.c6a_source_authority import SourceAuthorityError
from atos.c6a_source_authority_scope import SCOPE_FAILURE, global_scope_proof


PROBE_STAGE = "C6A_GLOBAL_SOURCE_SCOPE_PROBE"
PROBE_URL = "https://www.okx.com/help/section/announcements-latest-announcements/page/1"
PROBE_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)
_ATOS_USER_AGENT = "atos-c6a-source-scope-probe/1.0"
_ALLOWED_HELP_PATH_RE = re.compile(
    r"^/(?:[a-z]{2,3}(?:-[a-z]{2,4})?/)?help/(?:"
    r"section/announcements-latest-announcements(?:/page/1)?|"
    r"category/announcements"
    r")/?$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class ProbeCandidate:
    candidate_id: str
    profile_id: str
    replicate: str
    user_agent: str
    accept_language: str | None

    def headers(self) -> dict[str, str]:
        result = {
            "User-Agent": self.user_agent,
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Encoding": "identity",
        }
        if self.accept_language is not None:
            result["Accept-Language"] = self.accept_language
        return result


def _pair(profile_id: str, user_agent: str, accept_language: str | None) -> tuple[ProbeCandidate, ...]:
    return tuple(
        ProbeCandidate(
            candidate_id=f"{profile_id}-{replicate.lower()}",
            profile_id=profile_id,
            replicate=replicate,
            user_agent=user_agent,
            accept_language=accept_language,
        )
        for replicate in ("A", "B")
    )


CANDIDATES = (
    *_pair("control-atos-minimal", _ATOS_USER_AGENT, None),
    *_pair("browser-neutral-en", PROBE_USER_AGENT, "en;q=1.0"),
    *_pair("browser-en-us", PROBE_USER_AGENT, "en-US,en;q=0.9"),
    *_pair("browser-en-gb", PROBE_USER_AGENT, "en-GB,en;q=0.9"),
)


def canonical_json_bytes(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n").encode(
        "utf-8"
    )


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def atomic_write_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".tmp-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except BaseException:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def atomic_write_json(path: Path, value: Any) -> None:
    atomic_write_bytes(path, canonical_json_bytes(value))


def validate_probe_target(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme != "https" or (parsed.hostname or "").lower() != "www.okx.com":
        raise SourceAuthorityError(f"probe target escaped www.okx.com: {url}")
    if parsed.username or parsed.password or parsed.fragment:
        raise SourceAuthorityError(f"probe target contains credentials or fragment: {url}")
    if parsed.query:
        raise SourceAuthorityError(f"probe target contains an unapproved query: {url}")
    if _ALLOWED_HELP_PATH_RE.fullmatch(parsed.path) is None:
        raise SourceAuthorityError(f"probe target escaped the frozen Help Center page: {url}")


class _ProbeRedirectHandler(HTTPRedirectHandler):
    def __init__(self, chain: list[dict[str, Any]]) -> None:
        super().__init__()
        self._chain = chain

    def redirect_request(
        self,
        req: Request,
        fp: Any,
        code: int,
        msg: str,
        headers: Any,
        newurl: str,
    ) -> Request | None:
        resolved = urljoin(req.full_url, newurl)
        validate_probe_target(resolved)
        self._chain.append(
            {
                "status_code": int(code),
                "from_url": req.full_url,
                "to_url": resolved,
            }
        )
        return super().redirect_request(req, fp, code, msg, headers, resolved)


def _header_mapping(headers: Message | Mapping[str, Any]) -> dict[str, str]:
    return {str(key).lower(): str(value) for key, value in headers.items()}


def network_fetch_candidate(
    candidate: ProbeCandidate,
    *,
    timeout_seconds: int = 45,
    max_attempts: int = 2,
    retry_delay_seconds: int = 2,
) -> dict[str, Any]:
    """Fetch exactly the frozen public page for one predeclared candidate."""

    validate_probe_target(PROBE_URL)
    started = datetime.now(timezone.utc).isoformat()
    last_error: BaseException | None = None
    for attempt_number in range(1, max_attempts + 1):
        chain: list[dict[str, Any]] = []
        try:
            opener = build_opener(_ProbeRedirectHandler(chain))
            request = Request(PROBE_URL, method="GET", headers=candidate.headers())
            with opener.open(request, timeout=timeout_seconds) as response:
                data = response.read()
                status = int(getattr(response, "status", 200))
                final_url = str(response.geturl())
                headers = _header_mapping(response.headers)
            validate_probe_target(final_url)
            if status != 200 or not data:
                raise SourceAuthorityError(
                    f"probe source returned status={status} size={len(data)}"
                )
            return {
                "retrieval_started_at": started,
                "retrieval_completed_at": datetime.now(timezone.utc).isoformat(),
                "attempt_number": attempt_number,
                "status_code": status,
                "final_url": final_url,
                "headers": headers,
                "redirect_chain": chain,
                "raw_bytes": data,
            }
        except (HTTPError, URLError, TimeoutError, SourceAuthorityError) as exc:
            last_error = exc
            if attempt_number < max_attempts:
                time.sleep(retry_delay_seconds)
    raise SourceAuthorityError(
        f"probe candidate failed after {max_attempts} attempts: {last_error}"
    )


def _scope_verdict(final_url: str, data: bytes) -> tuple[str, dict[str, Any] | None, str | None]:
    try:
        return "PASS", global_scope_proof(final_url, data), None
    except SourceAuthorityError as exc:
        return "FAIL", None, str(exc)


def _profile_passes(rows: Sequence[Mapping[str, Any]], profile_id: str) -> bool:
    selected = [row for row in rows if row.get("profile_id") == profile_id]
    return bool(
        len(selected) == 2
        and {row.get("replicate") for row in selected} == {"A", "B"}
        and all(row.get("scope_status") == "PASS" for row in selected)
        and len({row.get("final_url") for row in selected}) == 1
    )


def run_probe(
    output_root: Path,
    *,
    fetch_candidate: Callable[[ProbeCandidate], Mapping[str, Any]] = network_fetch_candidate,
    candidates: Sequence[ProbeCandidate] = CANDIDATES,
) -> dict[str, Any]:
    """Run the bounded matrix and retain a non-authorizing result package."""

    output_root.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, Any]] = []
    for index, candidate in enumerate(candidates):
        if index:
            time.sleep(1)
        base = {
            "candidate_id": candidate.candidate_id,
            "profile_id": candidate.profile_id,
            "replicate": candidate.replicate,
            "request_url": PROBE_URL,
            "request_headers": candidate.headers(),
        }
        try:
            fetched = dict(fetch_candidate(candidate))
            raw = fetched.pop("raw_bytes")
            if not isinstance(raw, bytes):
                raise SourceAuthorityError("probe fetcher did not return raw bytes")
            raw_path = Path("raw") / f"{candidate.candidate_id}.bin"
            atomic_write_bytes(output_root / raw_path, raw)
            final_url = str(fetched.get("final_url", ""))
            scope_status, scope_proof, scope_error = _scope_verdict(final_url, raw)
            rows.append(
                {
                    **base,
                    **fetched,
                    "raw_path": raw_path.as_posix(),
                    "raw_size": len(raw),
                    "raw_sha256": sha256_bytes(raw),
                    "scope_status": scope_status,
                    "scope_proof": scope_proof,
                    "failure_code": None if scope_status == "PASS" else SCOPE_FAILURE,
                    "scope_error": scope_error,
                }
            )
        except (OSError, ValueError, SourceAuthorityError) as exc:
            rows.append(
                {
                    **base,
                    "scope_status": "FAIL",
                    "failure_code": SCOPE_FAILURE,
                    "error_type": type(exc).__name__,
                    "scope_error": str(exc),
                }
            )

    profile_ids = tuple(dict.fromkeys(candidate.profile_id for candidate in candidates))
    passing_profiles = [profile_id for profile_id in profile_ids if _profile_passes(rows, profile_id)]
    payload = {
        "schema_version": 1,
        "stage": PROBE_STAGE,
        "status": "PASS" if passing_profiles else "FAIL",
        "result": "PASS" if passing_profiles else SCOPE_FAILURE,
        "probe_url": PROBE_URL,
        "candidate_count": len(candidates),
        "candidate_results": rows,
        "reproducible_passing_profiles": passing_profiles,
        "implementation_authorized": False,
        "economic_data_access_authorized": False,
        "third_full_capture_authorized": False,
        "paper_state": "PAPER_CLOSED",
        "shadow_state": "SHADOW_CLOSED",
        "live_state": "LIVE_FORBIDDEN",
    }
    atomic_write_json(output_root / "probe_result.json", payload)
    return payload


def build_manifest(output_root: Path) -> dict[str, Any]:
    files = []
    for path in sorted(item for item in output_root.rglob("*") if item.is_file()):
        relative = path.relative_to(output_root).as_posix()
        if relative == "manifest.json":
            continue
        data = path.read_bytes()
        files.append({"path": relative, "size": len(data), "sha256": sha256_bytes(data)})
    payload = {
        "schema_version": 1,
        "stage": f"{PROBE_STAGE}_MANIFEST",
        "files": files,
        "file_count": len(files),
        "implementation_authorized": False,
        "economic_data_access_authorized": False,
        "third_full_capture_authorized": False,
        "live_state": "LIVE_FORBIDDEN",
    }
    atomic_write_json(output_root / "manifest.json", payload)
    return payload
