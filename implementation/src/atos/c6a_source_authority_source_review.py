"""Independent retained-source host and provenance review for C6A.

This module imports no production gate, capture, parser, or package code.  It
prevents a manually assembled source inventory from treating arbitrary HTTPS
content as an eligible archived official OKX response.
"""
from __future__ import annotations

from typing import Any, Mapping, Sequence
from urllib.parse import urlparse


ALLOWED_AUTHORITY_CLASSES = {
    "DIRECT_OFFICIAL_OKX_RESPONSE",
    "OFFICIAL_OKX_ANNOUNCEMENT",
    "EXACT_ARCHIVED_OFFICIAL_OKX_RESPONSE",
    "OFFICIAL_OKX_METADATA_DOWNLOAD",
}


def _is_okx_host(hostname: str) -> bool:
    hostname = hostname.lower()
    return hostname == "okx.com" or hostname.endswith(".okx.com")


def review_source_boundaries(source_inventory: Mapping[str, Any]) -> dict[str, Any]:
    errors: list[str] = []
    rows = source_inventory.get("sources")
    if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes)):
        rows = []
        errors.append("source inventory sources must be a list")

    seen: set[str] = set()
    archived_count = 0
    for index, row in enumerate(rows):
        if not isinstance(row, Mapping):
            errors.append(f"source {index} is not an object")
            continue
        source_id = str(row.get("source_id", ""))
        if not source_id or source_id in seen:
            errors.append(f"source {index} ID is missing or duplicated")
            continue
        seen.add(source_id)
        authority_class = str(row.get("authority_class", ""))
        if authority_class not in ALLOWED_AUTHORITY_CLASSES:
            errors.append(f"source {source_id} authority class is not permitted")

        canonical = urlparse(str(row.get("canonical_official_url", "")))
        canonical_host = (canonical.hostname or "").lower()
        if canonical.scheme != "https" or not _is_okx_host(canonical_host):
            errors.append(f"source {source_id} canonical authority is not official OKX HTTPS")

        retrieval = urlparse(str(row.get("retrieval_url", "")))
        retrieval_host = (retrieval.hostname or "").lower()
        if retrieval.scheme != "https" or not retrieval_host:
            errors.append(f"source {source_id} retrieval URL is not HTTPS")
        elif authority_class == "EXACT_ARCHIVED_OFFICIAL_OKX_RESPONSE":
            archived_count += 1
            if retrieval_host != "web.archive.org":
                errors.append(f"source {source_id} archived retrieval host is not web.archive.org")
            if not isinstance(row.get("archive_capture_timestamp"), str) or not row.get(
                "archive_capture_timestamp"
            ):
                errors.append(f"source {source_id} archive capture timestamp is missing")
        elif not _is_okx_host(retrieval_host):
            errors.append(f"source {source_id} non-archive retrieval escaped official OKX")

        if row.get("eligible") is True and row.get("rejection_reason") not in (None, ""):
            errors.append(f"source {source_id} eligible row carries a rejection reason")
        if row.get("eligible") is False and not isinstance(row.get("rejection_reason"), str):
            errors.append(f"source {source_id} ineligible row lacks a rejection reason")

    return {
        "schema_version": 1,
        "stage": "C6A_SOURCE_AUTHORITY_RETAINED_SOURCE_REVIEW",
        "status": "PASS" if not errors else "FAIL",
        "source_count": len(rows),
        "archived_source_count": archived_count,
        "errors": errors,
        "implementation_authorized": False,
        "economic_data_access_authorized": False,
        "live_state": "LIVE_FORBIDDEN",
    }
