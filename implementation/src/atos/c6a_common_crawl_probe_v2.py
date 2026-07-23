"""Remediated execution semantics for the C6A Common Crawl coverage probe.

The original bounded protocol and parsers remain frozen in
``c6a_common_crawl_probe``.  This module narrows result semantics so transport
or selected-record failures reject execution evidence instead of masquerading
as valid insufficient coverage.  It also reconciles the CDX, WARC, and
independently computed payload digests before an official page can be usable.
"""
from __future__ import annotations

import base64
import hashlib
import time
from pathlib import Path
from typing import Any, Callable, Mapping
from urllib.error import HTTPError, URLError

import atos.c6a_common_crawl_probe as legacy
from atos.c6a_source_authority import SourceAuthorityError


def sha1_payload_digest(data: bytes) -> str:
    """Return the Common Crawl SHA-1/Base32 payload-digest representation."""
    encoded = base64.b32encode(hashlib.sha1(data).digest()).decode("ascii")
    return "sha1:" + encoded.rstrip("=")


def _query_once(
    target: legacy.Target,
    crawl_id: str,
    output_root: Path,
    *,
    get: Callable[..., legacy.HttpResult],
    timeout_seconds: int,
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    query_url = legacy.build_index_query_url(crawl_id, target.url)
    query_id = f"{target.target_id}--{crawl_id.lower()}"
    base = {
        "query_id": query_id,
        "target_id": target.target_id,
        "target_kind": target.kind,
        "target_url": target.url,
        "crawl_id": crawl_id,
        "query_url": query_url,
    }

    try:
        response = get(
            query_url,
            headers={
                "User-Agent": legacy.USER_AGENT,
                "Accept": "application/x-ndjson,application/json",
            },
            timeout_seconds=timeout_seconds,
            maximum_bytes=legacy.MAX_INDEX_BYTES,
        )
        legacy._validate_index_query_url(response.final_url)
        if response.status != 200:
            raise SourceAuthorityError(
                f"Common Crawl index returned HTTP {response.status}"
            )
        raw_index_path = Path("index") / f"{query_id}.ndjson"
        legacy.atomic_write_bytes(output_root / raw_index_path, response.body)
        hits = legacy.parse_cdx_lines(response.body, target_url=target.url)
    except (
        HTTPError,
        URLError,
        TimeoutError,
        OSError,
        ValueError,
        SourceAuthorityError,
    ) as exc:
        return {
            **base,
            "status": "FAIL",
            "error_type": type(exc).__name__,
            "error": str(exc),
            "hit_count": 0,
            "selected_count": 0,
            "record_fetch_status": "NOT_ATTEMPTED",
        }, None

    query_meta: dict[str, Any] = {
        **base,
        "status": "PASS",
        "http_status": response.status,
        "response_headers": dict(response.headers),
        "raw_index_path": raw_index_path.as_posix(),
        "raw_index_size": len(response.body),
        "raw_index_sha256": legacy.sha256_bytes(response.body),
        "hit_count": len(hits),
        "selected_count": min(1, len(hits)),
        "record_fetch_status": "NOT_APPLICABLE" if not hits else "PENDING",
    }
    if not hits:
        return query_meta, None

    hit = hits[0]
    try:
        filename = str(hit["filename"])
        data_url = f"https://{legacy.DATA_HOST}/{filename}"
        legacy._validate_data_url(data_url)
        length = int(hit["length"])
        offset = int(hit["offset"])
        warc_response = get(
            data_url,
            headers={
                "User-Agent": legacy.USER_AGENT,
                "Accept": "application/warc",
                "Range": f"bytes={offset}-{offset + length - 1}",
            },
            timeout_seconds=timeout_seconds,
            maximum_bytes=length,
        )
        legacy._validate_data_url(warc_response.final_url)
        if warc_response.status != 206:
            raise SourceAuthorityError(
                "Common Crawl range request must return 206, got "
                f"{warc_response.status}"
            )
        if len(warc_response.body) != length:
            raise SourceAuthorityError(
                "Common Crawl range length mismatch: "
                f"expected={length} observed={len(warc_response.body)}"
            )

        parsed = legacy.parse_warc_record(
            warc_response.body, expected_target_url=target.url
        )
        timestamp = str(hit.get("timestamp", "unknown"))
        paths = legacy._record_paths(target.target_id, crawl_id, timestamp)
        legacy.atomic_write_bytes(
            output_root / paths["compressed"], warc_response.body
        )
        record = bytes(parsed.pop("record_bytes"))
        legacy.atomic_write_bytes(output_root / paths["record"], record)
        http_body = parsed.pop("http_body", None)

        cdx_digest = str(hit.get("digest", "")).casefold()
        warc_payload_digest = str(
            (parsed.get("warc_headers") or {}).get(
                "warc-payload-digest", ""
            )
        ).casefold()
        computed_payload_digest: str | None = None
        payload_digest_reconciled = False
        proof: dict[str, Any] | None = None
        proof_error: str | None = None

        if isinstance(http_body, bytes):
            legacy.atomic_write_bytes(output_root / paths["body"], http_body)
            computed_payload_digest = sha1_payload_digest(http_body).casefold()
            payload_digest_reconciled = bool(
                cdx_digest
                and warc_payload_digest
                and cdx_digest
                == warc_payload_digest
                == computed_payload_digest
            )
            if not payload_digest_reconciled:
                proof_error = (
                    "Common Crawl CDX/WARC/computed payload digest "
                    "reconciliation failed"
                )
            else:
                try:
                    proof = legacy.prove_official_global_html(
                        http_body,
                        target_url=target.url,
                        required_markers=target.required_markers,
                    )
                except SourceAuthorityError as exc:
                    proof_error = str(exc)

        usable = bool(
            parsed.get("usable")
            and payload_digest_reconciled
            and proof is not None
        )
        record_meta = {
            **base,
            "status": "PASS" if usable else "FAIL",
            "usable_official_global_bytes": usable,
            "cdx_record": hit,
            "data_url": data_url,
            "range_header": f"bytes={offset}-{offset + length - 1}",
            "range_http_status": warc_response.status,
            "range_response_headers": dict(warc_response.headers),
            "compressed_path": paths["compressed"].as_posix(),
            "compressed_size": len(warc_response.body),
            "compressed_sha256": legacy.sha256_bytes(warc_response.body),
            "record_path": paths["record"].as_posix(),
            "record_size": len(record),
            "record_sha256": legacy.sha256_bytes(record),
            "body_path": (
                paths["body"].as_posix()
                if isinstance(http_body, bytes)
                else None
            ),
            "body_size": (
                len(http_body) if isinstance(http_body, bytes) else None
            ),
            "body_sha256": (
                legacy.sha256_bytes(http_body)
                if isinstance(http_body, bytes)
                else None
            ),
            "warc_target_uri": parsed.get("warc_target_uri"),
            "warc_headers": parsed.get("warc_headers"),
            "http_status": parsed.get("http_status"),
            "http_headers": parsed.get("http_headers"),
            "cdx_payload_digest": cdx_digest or None,
            "warc_payload_digest": warc_payload_digest or None,
            "computed_payload_digest": computed_payload_digest,
            "payload_digest_reconciled": payload_digest_reconciled,
            "global_proof": proof,
            "failure": proof_error or parsed.get("failure"),
        }
        legacy.atomic_write_json(output_root / paths["metadata"], record_meta)
        record_meta["metadata_path"] = paths["metadata"].as_posix()
        query_meta["record_fetch_status"] = "PASS"
        return query_meta, record_meta
    except (
        HTTPError,
        URLError,
        TimeoutError,
        OSError,
        ValueError,
        SourceAuthorityError,
    ) as exc:
        query_meta["record_fetch_status"] = "FAIL"
        query_meta["record_error_type"] = type(exc).__name__
        query_meta["record_error"] = str(exc)
        return query_meta, None


def run_probe(
    inventory_path: Path,
    output_root: Path,
    *,
    get: Callable[..., legacy.HttpResult] = legacy.network_get,
    timeout_seconds: int = 60,
    environ: Mapping[str, str] | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    """Run the frozen inventory with execution failures kept distinct."""
    legacy.assert_clean_network_environment(environ)
    inventory, targets = legacy.load_inventory(inventory_path)
    output_root.mkdir(parents=True, exist_ok=True)
    inventory_bytes = legacy.canonical_json_bytes(inventory)
    legacy.atomic_write_bytes(
        output_root / "inventory_snapshot.json", inventory_bytes
    )

    query_rows: list[dict[str, Any]] = []
    record_rows: list[dict[str, Any]] = []
    first = True
    for target in targets:
        for crawl_id in target.crawl_indexes:
            if not first:
                sleep(float(inventory["minimum_request_interval_seconds"]))
            first = False
            query_row, record_row = _query_once(
                target,
                crawl_id,
                output_root,
                get=get,
                timeout_seconds=timeout_seconds,
            )
            query_rows.append(query_row)
            if record_row is not None:
                record_rows.append(record_row)

    covered = sorted(
        {
            str(row["target_id"])
            for row in record_rows
            if row.get("usable_official_global_bytes") is True
        }
    )
    target_ids = sorted(target.target_id for target in targets)
    missing = sorted(set(target_ids) - set(covered))
    status = "PASS" if not missing else "FAIL"
    result = (
        legacy.RESULT_AVAILABLE
        if status == "PASS"
        else legacy.RESULT_INSUFFICIENT
    )
    payload = {
        "schema_version": 1,
        "stage": legacy.STAGE,
        "status": status,
        "result": result,
        "inventory_sha256": legacy.sha256_bytes(inventory_bytes),
        "query_count": len(query_rows),
        "target_count": len(targets),
        "covered_target_ids": covered,
        "missing_target_ids": missing,
        "query_results": query_rows,
        "record_results": record_rows,
        "archive_carrier": "COMMON_CRAWL",
        "authority_source": "OFFICIAL_OKX_HTTP_RESPONSE_BYTES",
        "article_expansion_authorized": False,
        "third_full_capture_authorized": False,
        "implementation_authorized": False,
        "economic_data_access_authorized": False,
        "paper_state": "PAPER_CLOSED",
        "shadow_state": "SHADOW_CLOSED",
        "live_state": "LIVE_FORBIDDEN",
    }
    legacy.atomic_write_json(output_root / "probe_result.json", payload)
    return payload
