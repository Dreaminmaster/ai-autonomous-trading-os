"""Independent remediation reviewer for the C6A Common Crawl probe.

This module imports only the original physically separate reviewer helpers, not
the producer, HTTP client, WARC parser, or execution wrapper. It distinguishes
valid coverage findings from transport/integrity failures and independently
reconciles all retained digests.
"""
from __future__ import annotations

import base64
import hashlib
import json
import re
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import parse_qs, urlparse

import atos.c6a_common_crawl_probe_independent as legacy


STAGE = "C6A_COMMON_CRAWL_OFFICIAL_SOURCE_COVERAGE_PROBE"
RESULT_AVAILABLE = "COMMON_CRAWL_OFFICIAL_BYTES_AVAILABLE"
RESULT_INSUFFICIENT = "COMMON_CRAWL_COVERAGE_INSUFFICIENT"


def _sha1_payload_digest(data: bytes) -> str:
    encoded = base64.b32encode(hashlib.sha1(data).digest()).decode("ascii")
    return "sha1:" + encoded.rstrip("=")


def review_probe(root: Path) -> dict[str, Any]:
    errors: list[str] = []
    coverage_findings: list[str] = []
    inventory = legacy._load_object(root / "inventory_snapshot.json", errors)
    result = legacy._load_object(root / "probe_result.json", errors)

    if inventory.get("schema_version") != 1 or inventory.get("stage") != STAGE:
        errors.append("inventory identity drift")
    if result.get("schema_version") != 1 or result.get("stage") != STAGE:
        errors.append("probe result identity drift")
    inventory_bytes = (
        json.dumps(
            inventory,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )
        + "\n"
    ).encode("utf-8")
    if result.get("inventory_sha256") != hashlib.sha256(
        inventory_bytes
    ).hexdigest():
        errors.append("inventory snapshot digest mismatch")

    targets_raw = inventory.get("targets")
    targets: dict[str, Mapping[str, Any]] = {}
    expected_queries: set[tuple[str, str]] = set()
    if not isinstance(targets_raw, list) or not targets_raw:
        errors.append("inventory targets missing")
    else:
        for row in targets_raw:
            if not isinstance(row, Mapping):
                errors.append("inventory target row is invalid")
                continue
            target_id = str(row.get("target_id", ""))
            target_url = legacy._normalized_official_url(row.get("url"))
            if not target_id or target_id in targets or target_url is None:
                errors.append(
                    f"inventory target invalid or duplicated: {target_id}"
                )
                continue
            crawls = row.get("crawl_indexes")
            if not isinstance(crawls, list) or not crawls:
                errors.append(
                    f"inventory crawl coverage missing: {target_id}"
                )
                continue
            targets[target_id] = row
            for crawl_id in crawls:
                if re.fullmatch(
                    r"CC-MAIN-\d{4}-\d{2}", str(crawl_id)
                ) is None:
                    errors.append(
                        f"invalid crawl ID in inventory: {crawl_id}"
                    )
                expected_queries.add((target_id, str(crawl_id)))

    query_rows = result.get("query_results")
    observed_queries: set[tuple[str, str]] = set()
    selected_queries: set[tuple[str, str]] = set()
    if not isinstance(query_rows, list):
        errors.append("query result rows missing")
        query_rows = []
    for row in query_rows:
        if not isinstance(row, Mapping):
            errors.append("query result row is invalid")
            continue
        key = (
            str(row.get("target_id", "")),
            str(row.get("crawl_id", "")),
        )
        if key in observed_queries:
            errors.append(f"duplicate query result: {key}")
        observed_queries.add(key)
        parsed = urlparse(str(row.get("query_url", "")))
        query = parse_qs(parsed.query, keep_blank_values=True)
        if (
            parsed.scheme != "https"
            or (parsed.hostname or "").lower()
            != "index.commoncrawl.org"
            or re.fullmatch(
                r"/CC-MAIN-\d{4}-\d{2}-index", parsed.path
            )
            is None
            or set(query) != {"url", "output", "matchType", "filter"}
            or query.get("output") != ["json"]
            or query.get("matchType") != ["exact"]
            or query.get("filter") != ["status:200"]
            or legacy._normalized_official_url(
                (query.get("url") or [""])[0]
            )
            != legacy._normalized_official_url(row.get("target_url"))
        ):
            errors.append(
                f"query escaped Common Crawl index boundary: {key}"
            )
        if row.get("status") != "PASS":
            errors.append(f"index query execution failed: {key}")
            continue
        legacy._hash_matches(
            root,
            row.get("raw_index_path"),
            row.get("raw_index_size"),
            row.get("raw_index_sha256"),
            errors,
            f"query {key} raw index",
        )
        hit_count = row.get("hit_count")
        selected_count = row.get("selected_count")
        if not isinstance(hit_count, int) or hit_count < 0:
            errors.append(f"query hit count invalid: {key}")
            continue
        if selected_count != min(1, hit_count):
            errors.append(f"query selected count mismatch: {key}")
        if selected_count == 0:
            if row.get("record_fetch_status") != "NOT_APPLICABLE":
                errors.append(f"no-hit query fetch-state mismatch: {key}")
        else:
            selected_queries.add(key)
            if row.get("record_fetch_status") != "PASS":
                errors.append(
                    f"selected WARC retrieval or parse failed: {key}"
                )
    if observed_queries != expected_queries:
        errors.append("exact target/crawl query coverage mismatch")
    if result.get("query_count") != len(expected_queries):
        errors.append("query count mismatch")

    covered: set[str] = set()
    record_rows = result.get("record_results")
    if not isinstance(record_rows, list):
        errors.append("record result rows missing")
        record_rows = []
    seen_record_keys: set[tuple[str, str]] = set()
    seen_metadata: set[str] = set()
    for index, row in enumerate(record_rows):
        label = f"record[{index}]"
        if not isinstance(row, Mapping):
            errors.append(f"{label} is invalid")
            continue
        target_id = str(row.get("target_id", ""))
        crawl_id = str(row.get("crawl_id", ""))
        record_key = (target_id, crawl_id)
        if record_key in seen_record_keys:
            errors.append(f"duplicate retained record: {record_key}")
        seen_record_keys.add(record_key)
        if record_key not in selected_queries:
            errors.append(f"retained record lacks selected query: {record_key}")
        target = targets.get(target_id)
        if target is None:
            errors.append(f"{label} references unknown target")
            continue
        target_url = legacy._normalized_official_url(target.get("url"))
        if legacy._normalized_official_url(row.get("target_url")) != target_url:
            errors.append(f"{label} target URL mismatch")
        if legacy._normalized_official_url(row.get("warc_target_uri")) != target_url:
            coverage_findings.append(f"{label} WARC target URI is not GLOBAL")

        data_url = urlparse(str(row.get("data_url", "")))
        if (
            data_url.scheme != "https"
            or (data_url.hostname or "").lower()
            != "data.commoncrawl.org"
            or not data_url.path.endswith(".warc.gz")
        ):
            errors.append(f"{label} data URL escaped Common Crawl")

        metadata_path = row.get("metadata_path")
        if isinstance(metadata_path, str):
            if metadata_path in seen_metadata:
                errors.append(f"{label} duplicate metadata path")
            seen_metadata.add(metadata_path)
            metadata = legacy._load_object(root / metadata_path, errors)
            comparable = dict(row)
            comparable.pop("metadata_path", None)
            if metadata != comparable:
                errors.append(
                    f"{label} metadata file does not equal result row"
                )
        else:
            errors.append(f"{label} metadata path missing")

        legacy._hash_matches(
            root,
            row.get("compressed_path"),
            row.get("compressed_size"),
            row.get("compressed_sha256"),
            errors,
            f"{label} compressed WARC",
        )
        legacy._hash_matches(
            root,
            row.get("record_path"),
            row.get("record_size"),
            row.get("record_sha256"),
            errors,
            f"{label} decompressed WARC",
        )
        body = legacy._hash_matches(
            root,
            row.get("body_path"),
            row.get("body_size"),
            row.get("body_sha256"),
            errors,
            f"{label} official body",
        )

        digest_ok = False
        if body is not None:
            computed = _sha1_payload_digest(body).casefold()
            cdx = str(row.get("cdx_payload_digest") or "").casefold()
            warc = str(row.get("warc_payload_digest") or "").casefold()
            recorded = str(
                row.get("computed_payload_digest") or ""
            ).casefold()
            digest_ok = bool(cdx and cdx == warc == recorded == computed)
            if not digest_ok:
                errors.append(f"{label} payload digest reconciliation failed")
            if row.get("payload_digest_reconciled") is not digest_ok:
                errors.append(f"{label} payload digest verdict mismatch")

        proof_findings: list[str] = []
        body_global = False
        if body is not None:
            try:
                body_global = bool(
                    legacy._prove_body(body, target, proof_findings, label)
                )
            except TypeError:
                body_global, compact_findings = legacy._prove_body(body, target)
                proof_findings.extend(
                    f"{label} {finding}" for finding in compact_findings
                )
        coverage_findings.extend(proof_findings)
        independently_usable = bool(
            body is not None
            and row.get("range_http_status") == 206
            and row.get("http_status") == 200
            and digest_ok
            and body_global
        )
        if (
            row.get("usable_official_global_bytes")
            is not independently_usable
        ):
            errors.append(
                f"{label} producer/reviewer usability mismatch"
            )
        if independently_usable:
            covered.add(target_id)
        elif not proof_findings and digest_ok:
            coverage_findings.append(f"{label} retained record is unusable")

    if seen_record_keys != selected_queries:
        errors.append("selected query/retained record coverage mismatch")

    target_ids = set(targets)
    missing = sorted(target_ids - covered)
    recomputed_status = "PASS" if not missing else "FAIL"
    recomputed_result = (
        RESULT_AVAILABLE
        if recomputed_status == "PASS"
        else RESULT_INSUFFICIENT
    )
    if result.get("covered_target_ids") != sorted(covered):
        errors.append("covered target IDs mismatch")
    if result.get("missing_target_ids") != missing:
        errors.append("missing target IDs mismatch")
    if result.get("status") != recomputed_status:
        errors.append("producer/reviewer probe status mismatch")
    if result.get("result") != recomputed_result:
        errors.append("producer/reviewer probe result mismatch")
    if result.get("target_count") != len(targets):
        errors.append("target count mismatch")
    if result.get("archive_carrier") != "COMMON_CRAWL":
        errors.append("archive-carrier identity drift")
    if (
        result.get("authority_source")
        != "OFFICIAL_OKX_HTTP_RESPONSE_BYTES"
    ):
        errors.append("authority-source identity drift")

    for payload_name, payload in (
        ("inventory", inventory),
        ("result", result),
    ):
        for key in (
            "article_expansion_authorized",
            "third_full_capture_authorized",
            "implementation_authorized",
            "economic_data_access_authorized",
        ):
            if payload.get(key) is not False:
                errors.append(
                    f"{payload_name} improperly authorizes {key}"
                )
        if payload.get("paper_state") != "PAPER_CLOSED":
            errors.append(f"{payload_name} paper-state drift")
        if payload.get("shadow_state") != "SHADOW_CLOSED":
            errors.append(f"{payload_name} shadow-state drift")
        if payload.get("live_state") != "LIVE_FORBIDDEN":
            errors.append(f"{payload_name} live-state drift")

    return {
        "schema_version": 1,
        "stage": f"{STAGE}_INDEPENDENT_REVIEW",
        "status": "PASS" if not errors else "FAIL",
        "probe_status_recomputed": recomputed_status,
        "probe_result_recomputed": recomputed_result,
        "covered_target_ids_recomputed": sorted(covered),
        "missing_target_ids_recomputed": missing,
        "coverage_findings": coverage_findings,
        "errors": errors,
        "article_expansion_authorized": False,
        "third_full_capture_authorized": False,
        "implementation_authorized": False,
        "economic_data_access_authorized": False,
        "paper_state": "PAPER_CLOSED",
        "shadow_state": "SHADOW_CLOSED",
        "live_state": "LIVE_FORBIDDEN",
    }
