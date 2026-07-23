"""One-shot, pre-economic C6A source-authority capture orchestrator.

The orchestrator executes only the committed query inventory, retains every
successful response before parsing, and deliberately emits no timestamp-
effective metadata interval unless a separate deterministic derivation can
prove both boundaries.  With the currently frozen snapshot/announcement plan,
that means the attempt may correctly close as an authority failure rather than
projecting point observations across time.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence
from urllib.parse import parse_qs, urlparse

from atos.c6a_source_authority import FAILURE_PRIORITY, SourceAuthorityError, SourceObject
from atos.c6a_source_authority_announcements import (
    html_visible_text,
    parse_known_transition_notice,
)
from atos.c6a_source_authority_capture import (
    CapturedResponse,
    FrozenRequest,
    archive_lookup_requests,
    atomic_write_json,
    canonical_json_bytes,
    capture_request,
    catalog_requests,
    inventory_sha256,
    load_frozen_inventory,
    memento_request,
    parse_announcement_catalog,
    parse_wayback_cdx,
    response_record,
    sha256_bytes,
)
from atos.c6a_source_authority_gate import GateSnapshot, evaluate_gate_snapshot
from atos.c6a_source_authority_inventory import (
    classify_catalog_article,
    direct_transition_article_requests,
    prove_catalog_terminal_page,
)
from atos.c6a_source_authority_metadata import decode_okx_instruments_response
from atos.c6a_source_authority_package import package_gate_artifact


AUTHORITY_GAP_FAILURES = (
    "FAIL_REQUIRED_FIELD_MISSING",
    "FAIL_UNCOVERED_INTERVAL",
    "FAIL_TRANSITION_WINDOW_UNPROVEN",
)


def _retry_kwargs(payload: Mapping[str, Any]) -> dict[str, int]:
    retry = payload["retry_policy"]
    return {
        "timeout_seconds": int(retry["timeout_seconds"]),
        "max_attempts": int(retry["max_attempts"]),
        "initial_backoff_seconds": int(retry["initial_backoff_seconds"]),
        "maximum_backoff_seconds": int(retry["maximum_backoff_seconds"]),
    }


def _decoded_record_path(request_id: str) -> Path:
    return Path("decoded") / f"{request_id}.json"


def _write_decoded(output_root: Path, request_id: str, payload: Any) -> tuple[str, int, str]:
    data = canonical_json_bytes(payload)
    relative = _decoded_record_path(request_id)
    path = output_root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return relative.as_posix(), len(data), sha256_bytes(data)


def _source_record(
    capture: CapturedResponse,
    *,
    authority_class: str,
    decoded_path: str,
    decoded_size: int,
    decoded_sha256: str,
    parser_version: str,
    publication_timestamp: str | None = None,
    archive_capture_timestamp: str | None = None,
) -> dict[str, Any]:
    canonical = capture.request.canonical_official_url or capture.request.url
    return {
        "source_id": capture.request.request_id,
        "authority_class": authority_class,
        "canonical_official_url": canonical,
        "retrieval_url": capture.final_url,
        "requested_url": capture.request.url,
        "publication_timestamp": publication_timestamp,
        "archive_capture_timestamp": archive_capture_timestamp,
        "retrieval_started_at": capture.retrieval_started_at,
        "retrieval_completed_at": capture.retrieval_completed_at,
        "status_code": capture.status_code,
        "headers": dict(capture.headers),
        "raw_path": capture.raw_path,
        "raw_size": capture.raw_size,
        "raw_sha256": capture.raw_sha256,
        "decoded_path": decoded_path,
        "decoded_size": decoded_size,
        "decoded_sha256": decoded_sha256,
        "parser_version": parser_version,
        "eligible": True,
        "rejection_reason": None,
    }


def _source_objects(rows: Sequence[Mapping[str, Any]]) -> tuple[SourceObject, ...]:
    return tuple(SourceObject.from_mapping(row) for row in rows)


def _failure_for_exception(exc: BaseException, *, request_kind: str) -> str:
    message = str(exc).lower()
    if "forbidden" in message or "credential" in message:
        return "FAIL_FORBIDDEN_DATA_ACCESS"
    if request_kind == "announcement_catalog":
        return "FAIL_ANNOUNCEMENT_CATALOG_INCOMPLETE"
    if request_kind == "archive_lookup":
        return "FAIL_ARCHIVE_DECODING_OR_PROVENANCE"
    if request_kind == "announcement_article":
        return "FAIL_TRANSITION_WINDOW_UNPROVEN"
    return "FAIL_REQUIRED_FIELD_MISSING"


def _record_error(
    log: list[dict[str, Any]],
    failures: set[str],
    *,
    stage: str,
    request: FrozenRequest | None,
    error: BaseException,
) -> None:
    request_kind = request.request_kind if request is not None else "unknown"
    failure = _failure_for_exception(error, request_kind=request_kind)
    failures.add(failure)
    log.append(
        {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "stage": stage,
            "request_id": request.request_id if request is not None else None,
            "request_kind": request_kind,
            "url": request.url if request is not None else None,
            "failure_code": failure,
            "error_type": type(error).__name__,
            "error": str(error),
        }
    )


def _instrument_from_canonical_url(url: str) -> str:
    values = parse_qs(urlparse(url).query).get("instId", [])
    if len(values) != 1 or not values[0]:
        raise SourceAuthorityError("archive canonical URL lacks one exact instId")
    return values[0]


def run_source_authority_attempt(
    *,
    inventory_path: Path,
    output_root: Path,
    source_commit_sha: str,
    pr_merge_ref: str | None,
) -> dict[str, Any]:
    """Execute the frozen public-source plan and package one immutable result."""

    output_root.mkdir(parents=True, exist_ok=True)
    payload = load_frozen_inventory(inventory_path)
    retry_kwargs = _retry_kwargs(payload)
    parser_versions = payload["parser_versions"]
    source_rows: list[dict[str, Any]] = []
    attempt_log: list[dict[str, Any]] = []
    failures: set[str] = set(AUTHORITY_GAP_FAILURES)
    forbidden_access_count = 0

    known_requests = direct_transition_article_requests(payload)
    known_urls = [request.url for request in known_requests]
    catalog_pages: list[dict[str, Any]] = []
    catalog_items: list[dict[str, Any]] = []
    catalog_complete = True
    terminal_proof: dict[str, Any] | None = None

    frozen_catalog_requests = catalog_requests(payload)
    for request in frozen_catalog_requests:
        try:
            capture = capture_request(request, output_root=output_root, **retry_kwargs)
            parsed = parse_announcement_catalog(request.url, (output_root / capture.raw_path).read_bytes())
            decoded_path, decoded_size, decoded_sha = _write_decoded(
                output_root, request.request_id, parsed
            )
            source_rows.append(
                _source_record(
                    capture,
                    authority_class="OFFICIAL_OKX_ANNOUNCEMENT",
                    decoded_path=decoded_path,
                    decoded_size=decoded_size,
                    decoded_sha256=decoded_sha,
                    parser_version=str(parser_versions["announcement_catalog"]),
                )
            )
            page_items: list[dict[str, Any]] = []
            for article in parsed["articles"]:
                classified = classify_catalog_article(
                    article,
                    aliases=payload["instrument_aliases"],
                    metadata_terms=payload["metadata_terms"],
                    known_urls=known_urls,
                )
                item = {**classified, "page_number": parsed["page_number"]}
                page_items.append(item)
                catalog_items.append(item)
            catalog_pages.append(
                {
                    **response_record(capture),
                    "retrieval_timestamp": capture.retrieval_completed_at,
                    "requested_url": request.url,
                    "page_number": parsed["page_number"],
                    "first_item": parsed["first_item"],
                    "last_item": parsed["last_item"],
                    "total_items": parsed["total_items"],
                    "declared_terminal_page": parsed["declared_terminal_page"],
                    "is_terminal_page": parsed["is_terminal_page"],
                    "next_page_state": (
                        "TERMINAL" if parsed["is_terminal_page"] else "NEXT_PAGE_REQUIRED"
                    ),
                    "decoded_path": decoded_path,
                    "decoded_size": decoded_size,
                    "decoded_sha256": decoded_sha,
                    "parsed_item_count": len(page_items),
                }
            )
            if parsed["is_terminal_page"]:
                terminal_proof = prove_catalog_terminal_page(
                    parsed, frozen_max_page=len(frozen_catalog_requests)
                )
                break
        except (SourceAuthorityError, OSError, ValueError) as exc:
            catalog_complete = False
            _record_error(
                attempt_log,
                failures,
                stage="announcement_catalog",
                request=request,
                error=exc,
            )
            if "forbidden" in str(exc).lower() or "credential" in str(exc).lower():
                forbidden_access_count += 1
            break
    if terminal_proof is None:
        catalog_complete = False
        failures.add("FAIL_ANNOUNCEMENT_CATALOG_INCOMPLETE")

    duplicate_urls = {
        url
        for url in {str(item.get("canonical_url", "")) for item in catalog_items}
        if sum(str(item.get("canonical_url", "")) == url for item in catalog_items) > 1
    }
    if duplicate_urls:
        catalog_complete = False
        failures.add("FAIL_ANNOUNCEMENT_CATALOG_INCOMPLETE")
        attempt_log.append(
            {
                "stage": "announcement_catalog_deduplication",
                "failure_code": "FAIL_ANNOUNCEMENT_CATALOG_INCOMPLETE",
                "duplicate_urls": sorted(duplicate_urls),
            }
        )

    notice_proofs: list[dict[str, Any]] = []
    captured_article_urls: set[str] = set()
    for request in known_requests:
        try:
            capture = capture_request(request, output_root=output_root, **retry_kwargs)
            raw = (output_root / capture.raw_path).read_bytes()
            proof = parse_known_transition_notice(
                raw, request_id=request.request_id, source_id=request.request_id
            )
            decoded_path, decoded_size, decoded_sha = _write_decoded(
                output_root, request.request_id, proof
            )
            source_rows.append(
                _source_record(
                    capture,
                    authority_class="OFFICIAL_OKX_ANNOUNCEMENT",
                    decoded_path=decoded_path,
                    decoded_size=decoded_size,
                    decoded_sha256=decoded_sha,
                    parser_version=str(parser_versions["announcement_article"]),
                    publication_timestamp=str(proof["publication_date"]),
                )
            )
            notice_proofs.append(proof)
            captured_article_urls.add(request.url)
        except (SourceAuthorityError, OSError, ValueError) as exc:
            _record_error(
                attempt_log,
                failures,
                stage="known_transition_notice",
                request=request,
                error=exc,
            )
            if "forbidden" in str(exc).lower() or "credential" in str(exc).lower():
                forbidden_access_count += 1

    selected_items = [
        item
        for item in catalog_items
        if item.get("selected_for_article_capture") is True
        and str(item.get("canonical_url", "")) not in captured_article_urls
    ]
    for index, item in enumerate(selected_items, start=1):
        request = FrozenRequest(
            request_id=f"catalog-selected-article-{index:04d}",
            request_kind="announcement_article",
            url=str(item["canonical_url"]),
            canonical_official_url=str(item["canonical_url"]),
            expected_content_type="text/html",
            parent_request_id="okx-announcement-catalog-global",
        )
        try:
            capture = capture_request(request, output_root=output_root, **retry_kwargs)
            visible = {
                "canonical_url": request.url,
                "visible_text": html_visible_text((output_root / capture.raw_path).read_bytes()),
            }
            decoded_path, decoded_size, decoded_sha = _write_decoded(
                output_root, request.request_id, visible
            )
            source_rows.append(
                _source_record(
                    capture,
                    authority_class="OFFICIAL_OKX_ANNOUNCEMENT",
                    decoded_path=decoded_path,
                    decoded_size=decoded_size,
                    decoded_sha256=decoded_sha,
                    parser_version=str(parser_versions["announcement_article"]),
                    publication_timestamp=str(item.get("published_at")),
                )
            )
        except (SourceAuthorityError, OSError, ValueError) as exc:
            _record_error(
                attempt_log,
                failures,
                stage="selected_announcement_article",
                request=request,
                error=exc,
            )
            if "forbidden" in str(exc).lower() or "credential" in str(exc).lower():
                forbidden_access_count += 1

    archive_indexes: list[dict[str, Any]] = []
    for request in archive_lookup_requests(payload):
        try:
            index_capture = capture_request(request, output_root=output_root, **retry_kwargs)
            captures = parse_wayback_cdx(
                (output_root / index_capture.raw_path).read_bytes(),
                canonical_official_url=str(request.canonical_official_url),
            )
            index_decoded_path, index_decoded_size, index_decoded_sha = _write_decoded(
                output_root,
                request.request_id,
                {"captures": list(captures)},
            )
            archive_indexes.append(
                {
                    **response_record(index_capture),
                    "decoded_path": index_decoded_path,
                    "decoded_size": index_decoded_size,
                    "decoded_sha256": index_decoded_sha,
                    "capture_count": len(captures),
                }
            )
            instrument = _instrument_from_canonical_url(str(request.canonical_official_url))
            for index, archived in enumerate(captures, start=1):
                generated = memento_request(
                    archived,
                    parent_request_id=request.request_id,
                    index=index,
                )
                try:
                    capture = capture_request(
                        generated, output_root=output_root, **retry_kwargs
                    )
                    decoded = decode_okx_instruments_response(
                        (output_root / capture.raw_path).read_bytes(),
                        expected_instrument=instrument,
                    )
                    decoded_path, decoded_size, decoded_sha = _write_decoded(
                        output_root, generated.request_id, decoded
                    )
                    source_rows.append(
                        _source_record(
                            capture,
                            authority_class="EXACT_ARCHIVED_OFFICIAL_OKX_RESPONSE",
                            decoded_path=decoded_path,
                            decoded_size=decoded_size,
                            decoded_sha256=decoded_sha,
                            parser_version=str(parser_versions["archived_official_response"]),
                            archive_capture_timestamp=str(archived["captured_at"]),
                        )
                    )
                except (SourceAuthorityError, OSError, ValueError) as exc:
                    _record_error(
                        attempt_log,
                        failures,
                        stage="archive_memento",
                        request=generated,
                        error=exc,
                    )
                    if "forbidden" in str(exc).lower() or "credential" in str(exc).lower():
                        forbidden_access_count += 1
        except (SourceAuthorityError, OSError, ValueError) as exc:
            _record_error(
                attempt_log,
                failures,
                stage="archive_index",
                request=request,
                error=exc,
            )
            if "forbidden" in str(exc).lower() or "credential" in str(exc).lower():
                forbidden_access_count += 1

    atomic_write_json(output_root / "diagnostics" / "attempt_log.json", {"events": attempt_log})
    atomic_write_json(
        output_root / "diagnostics" / "known_transition_notices.json",
        {"notices": notice_proofs},
    )
    atomic_write_json(
        output_root / "diagnostics" / "archive_indexes.json",
        {"indexes": archive_indexes},
    )
    atomic_write_json(
        output_root / "diagnostics" / "authority_gap.json",
        {
            "status": "FAIL_CLOSED",
            "reason": (
                "Point-in-time public instrument snapshots do not by themselves prove "
                "inclusive/exclusive effective intervals; no backward or continuity projection "
                "was emitted."
            ),
            "metadata_states_emitted": 0,
            "transition_proofs_emitted": 0,
            "failure_codes": list(AUTHORITY_GAP_FAILURES),
        },
    )

    source_inventory = {"sources": source_rows}
    announcement_catalog = {
        "pages": catalog_pages,
        "items": catalog_items,
        "terminal_page_proof": terminal_proof or {
            "status": "FAIL",
            "terminal_page": None,
        },
        "duplicate_urls": sorted(duplicate_urls),
    }
    snapshot = GateSnapshot(
        query_inventory_valid=True,
        catalog_complete=catalog_complete,
        metadata_states=(),
        transition_proofs=(),
        source_objects=_source_objects(source_rows),
        source_failures=tuple(code for code in FAILURE_PRIORITY if code in failures),
        forbidden_access_count=forbidden_access_count,
        unsupported_projection_count=0,
        newly_discovered_transition_count=0,
    )
    preliminary, coverage, evaluated_failures = evaluate_gate_snapshot(
        snapshot,
        source_commit_sha=source_commit_sha,
        query_inventory_sha256=inventory_sha256(payload),
        pr_merge_ref=pr_merge_ref,
    )
    return package_gate_artifact(
        output_root,
        query_inventory=payload,
        source_inventory=source_inventory,
        announcement_catalog=announcement_catalog,
        metadata_states=[],
        transition_proofs=[],
        coverage_matrix=list(coverage),
        gate_result=preliminary,
        failures=list(evaluated_failures),
    )
