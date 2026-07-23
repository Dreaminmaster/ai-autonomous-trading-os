from __future__ import annotations

import gzip
import json
from pathlib import Path

import pytest

import atos.c6a_common_crawl_probe as probe
import atos.c6a_common_crawl_probe_independent as independent
from atos.c6a_source_authority import SourceAuthorityError


TARGET = "https://www.okx.com/help/category/announcements"
CRAWL = "CC-MAIN-2025-05"
FILENAME = (
    "crawl-data/CC-MAIN-2025-05/segments/1737000000000.0/warc/"
    "test.warc.gz"
)


def _inventory(path: Path) -> Path:
    payload = {
        "schema_version": 1,
        "stage": probe.STAGE,
        "archive_carrier": "COMMON_CRAWL",
        "authority_source": "OFFICIAL_OKX_HTTP_RESPONSE_BYTES",
        "match_type": "exact",
        "max_records_per_query": 1,
        "minimum_request_interval_seconds": 1,
        "targets": [
            {
                "target_id": "global-announcements-category",
                "kind": "catalog",
                "url": TARGET,
                "crawl_indexes": [CRAWL],
                "required_markers": [
                    "announcements",
                    "trading updates",
                ],
            }
        ],
        "article_expansion_authorized": False,
        "third_full_capture_authorized": False,
        "implementation_authorized": False,
        "economic_data_access_authorized": False,
        "paper_state": "PAPER_CLOSED",
        "shadow_state": "SHADOW_CLOSED",
        "live_state": "LIVE_FORBIDDEN",
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _official_html() -> bytes:
    return b"""<!doctype html><html><head>
<link rel="canonical" href="https://www.okx.com/help/category/announcements">
<meta property="og:url" content="https://www.okx.com/help/category/announcements">
</head><body>Announcements Trading Updates
<script type="application/json">{"site":{"siteList":["OKX_GLOBAL"]}}</script>
</body></html>"""


def _warc(body: bytes) -> bytes:
    http = (
        b"HTTP/1.1 200 OK\r\n"
        b"Content-Type: text/html; charset=utf-8\r\n"
        + f"Content-Length: {len(body)}\r\n\r\n".encode()
        + body
    )
    record = (
        b"WARC/1.0\r\n"
        b"WARC-Type: response\r\n"
        + f"WARC-Target-URI: {TARGET}\r\n".encode()
        + b"WARC-Date: 2025-01-20T00:00:00Z\r\n"
        + f"Content-Length: {len(http)}\r\n\r\n".encode()
        + http
        + b"\r\n\r\n"
    )
    return gzip.compress(record)


def _get_factory(*, include_hit: bool = True):
    compressed = _warc(_official_html())

    def get(
        url: str,
        *,
        headers,
        timeout_seconds: int,
        maximum_bytes: int,
    ):
        if "index.commoncrawl.org" in url:
            body = b""
            if include_hit:
                body = (
                    json.dumps(
                        {
                            "url": TARGET,
                            "timestamp": "20250120000000",
                            "status": "200",
                            "mime": "text/html",
                            "filename": FILENAME,
                            "offset": "100",
                            "length": str(len(compressed)),
                            "digest": "sha1:TEST",
                        }
                    )
                    + "\n"
                ).encode()
            return probe.HttpResult(
                200,
                url,
                {"content-type": "application/x-ndjson"},
                body,
            )
        assert url == f"https://data.commoncrawl.org/{FILENAME}"
        assert headers["Range"] == (
            f"bytes=100-{100 + len(compressed) - 1}"
        )
        return probe.HttpResult(
            206,
            url,
            {
                "content-type": "application/warc",
                "content-range": "bytes",
            },
            compressed,
        )

    return get


def test_reviewed_common_crawl_coverage_pass(tmp_path: Path) -> None:
    inventory = _inventory(tmp_path / "inventory.json")
    output = tmp_path / "out"

    result = probe.run_probe(
        inventory,
        output,
        get=_get_factory(),
        environ={},
        sleep=lambda _seconds: None,
    )
    review = independent.review_probe(output)
    probe.atomic_write_json(output / "independent_review.json", review)
    manifest = probe.build_manifest(output)

    assert result["status"] == "PASS"
    assert result["result"] == probe.RESULT_AVAILABLE
    assert result["covered_target_ids"] == [
        "global-announcements-category"
    ]
    assert review["status"] == "PASS"
    assert review["probe_status_recomputed"] == "PASS"
    assert manifest["file_count"] >= 7


def test_no_archive_hit_is_valid_reviewed_coverage_fail(
    tmp_path: Path,
) -> None:
    inventory = _inventory(tmp_path / "inventory.json")
    output = tmp_path / "out"

    result = probe.run_probe(
        inventory,
        output,
        get=_get_factory(include_hit=False),
        environ={},
        sleep=lambda _seconds: None,
    )
    review = independent.review_probe(output)

    assert result["status"] == "FAIL"
    assert result["result"] == probe.RESULT_INSUFFICIENT
    assert result["missing_target_ids"] == [
        "global-announcements-category"
    ]
    assert review["status"] == "PASS"
    assert review["probe_status_recomputed"] == "FAIL"
    assert review["probe_result_recomputed"] == probe.RESULT_INSUFFICIENT


def test_proxy_state_is_rejected_before_any_network(
    tmp_path: Path,
) -> None:
    called = False

    def forbidden_get(*args, **kwargs):
        nonlocal called
        called = True
        raise AssertionError("network must not be reached")

    with pytest.raises(SourceAuthorityError, match="prohibited proxy"):
        probe.run_probe(
            _inventory(tmp_path / "inventory.json"),
            tmp_path / "out",
            get=forbidden_get,
            environ={"HTTPS_PROXY": "http://127.0.0.1:9999"},
            sleep=lambda _seconds: None,
        )
    assert called is False


def test_independent_review_detects_tampered_official_bytes(
    tmp_path: Path,
) -> None:
    inventory = _inventory(tmp_path / "inventory.json")
    output = tmp_path / "out"
    result = probe.run_probe(
        inventory,
        output,
        get=_get_factory(),
        environ={},
        sleep=lambda _seconds: None,
    )
    body_path = output / result["record_results"][0]["body_path"]
    body_path.write_bytes(body_path.read_bytes() + b"tamper")

    review = independent.review_probe(output)

    assert review["status"] == "FAIL"
    assert any(
        "SHA-256 mismatch" in error for error in review["errors"]
    )


def test_regional_canonical_is_not_accepted_as_global() -> None:
    body = _official_html().replace(
        b"https://www.okx.com/help/category/announcements",
        b"https://www.okx.com/en-us/help/category/announcements",
    )
    with pytest.raises(
        SourceAuthorityError, match="Help Center|canonical URL"
    ):
        probe.prove_official_global_html(
            body,
            target_url=TARGET,
            required_markers=("announcements", "trading updates"),
        )
