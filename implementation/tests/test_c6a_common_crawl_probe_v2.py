from __future__ import annotations

import gzip
import json
from pathlib import Path

import pytest

import atos.c6a_common_crawl_probe as legacy
import atos.c6a_common_crawl_probe_independent_v2 as independent
import atos.c6a_common_crawl_probe_v2 as probe
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
        "stage": legacy.STAGE,
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


def _warc(body: bytes) -> tuple[bytes, str]:
    digest = probe.sha1_payload_digest(body)
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
        + f"WARC-Payload-Digest: {digest}\r\n".encode()
        + f"Content-Length: {len(http)}\r\n\r\n".encode()
        + http
        + b"\r\n\r\n"
    )
    return gzip.compress(record), digest


def _get_factory(
    *,
    include_hit: bool = True,
    body: bytes | None = None,
    fail_index: bool = False,
    fail_warc: bool = False,
):
    compressed, payload_digest = _warc(
        _official_html() if body is None else body
    )

    def get(
        url: str,
        *,
        headers,
        timeout_seconds: int,
        maximum_bytes: int,
    ):
        if "index.commoncrawl.org" in url:
            if fail_index:
                raise TimeoutError("synthetic index timeout")
            response_body = b""
            if include_hit:
                response_body = (
                    json.dumps(
                        {
                            "url": TARGET,
                            "timestamp": "20250120000000",
                            "status": "200",
                            "mime": "text/html",
                            "filename": FILENAME,
                            "offset": "100",
                            "length": str(len(compressed)),
                            "digest": payload_digest,
                        }
                    )
                    + "\n"
                ).encode()
            return legacy.HttpResult(
                200,
                url,
                {"content-type": "application/x-ndjson"},
                response_body,
            )
        if fail_warc:
            raise TimeoutError("synthetic WARC timeout")
        assert url == f"https://data.commoncrawl.org/{FILENAME}"
        assert headers["Range"] == (
            f"bytes=100-{100 + len(compressed) - 1}"
        )
        return legacy.HttpResult(
            206,
            url,
            {
                "content-type": "application/warc",
                "content-range": "bytes",
            },
            compressed,
        )

    return get


def test_reviewed_coverage_pass(tmp_path: Path) -> None:
    output = tmp_path / "out"
    result = probe.run_probe(
        _inventory(tmp_path / "inventory.json"),
        output,
        get=_get_factory(),
        environ={},
        sleep=lambda _seconds: None,
    )
    review = independent.review_probe(output)

    assert result["status"] == "PASS"
    assert result["covered_target_ids"] == [
        "global-announcements-category"
    ]
    assert review["status"] == "PASS"
    assert review["probe_status_recomputed"] == "PASS"
    assert review["coverage_findings"] == []


def test_successful_no_hit_is_reviewed_coverage_fail(tmp_path: Path) -> None:
    output = tmp_path / "out"
    result = probe.run_probe(
        _inventory(tmp_path / "inventory.json"),
        output,
        get=_get_factory(include_hit=False),
        environ={},
        sleep=lambda _seconds: None,
    )
    review = independent.review_probe(output)

    assert result["status"] == "FAIL"
    assert result["result"] == legacy.RESULT_INSUFFICIENT
    assert review["status"] == "PASS"
    assert review["probe_status_recomputed"] == "FAIL"


def test_index_failure_rejects_execution_evidence(tmp_path: Path) -> None:
    output = tmp_path / "out"
    result = probe.run_probe(
        _inventory(tmp_path / "inventory.json"),
        output,
        get=_get_factory(fail_index=True),
        environ={},
        sleep=lambda _seconds: None,
    )
    review = independent.review_probe(output)

    assert result["status"] == "FAIL"
    assert review["status"] == "FAIL"
    assert any(
        "index query execution failed" in error
        for error in review["errors"]
    )


def test_selected_warc_failure_rejects_execution_evidence(
    tmp_path: Path,
) -> None:
    output = tmp_path / "out"
    result = probe.run_probe(
        _inventory(tmp_path / "inventory.json"),
        output,
        get=_get_factory(fail_warc=True),
        environ={},
        sleep=lambda _seconds: None,
    )
    review = independent.review_probe(output)

    assert result["status"] == "FAIL"
    assert review["status"] == "FAIL"
    assert any(
        "selected WARC retrieval or parse failed" in error
        for error in review["errors"]
    )


def test_retained_regional_page_is_valid_coverage_finding(
    tmp_path: Path,
) -> None:
    regional = _official_html().replace(
        b"https://www.okx.com/help/category/announcements",
        b"https://www.okx.com/en-us/help/category/announcements",
    )
    output = tmp_path / "out"
    result = probe.run_probe(
        _inventory(tmp_path / "inventory.json"),
        output,
        get=_get_factory(body=regional),
        environ={},
        sleep=lambda _seconds: None,
    )
    review = independent.review_probe(output)

    assert result["status"] == "FAIL"
    assert result["record_results"][0][
        "usable_official_global_bytes"
    ] is False
    assert review["status"] == "PASS"
    assert review["probe_status_recomputed"] == "FAIL"
    assert review["coverage_findings"]


def test_payload_digest_tamper_rejects_evidence(tmp_path: Path) -> None:
    output = tmp_path / "out"
    result = probe.run_probe(
        _inventory(tmp_path / "inventory.json"),
        output,
        get=_get_factory(),
        environ={},
        sleep=lambda _seconds: None,
    )
    metadata_path = output / result["record_results"][0]["metadata_path"]
    metadata = json.loads(metadata_path.read_text())
    metadata["cdx_payload_digest"] = "sha1:WRONG"
    metadata_path.write_text(json.dumps(metadata))
    result_path = output / "probe_result.json"
    aggregate = json.loads(result_path.read_text())
    aggregate["record_results"][0]["cdx_payload_digest"] = "sha1:WRONG"
    result_path.write_text(json.dumps(aggregate))

    review = independent.review_probe(output)

    assert review["status"] == "FAIL"
    assert any(
        "payload digest reconciliation failed" in error
        for error in review["errors"]
    )


def test_proxy_rejected_before_network(tmp_path: Path) -> None:
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
