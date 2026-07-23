from __future__ import annotations

from pathlib import Path

import pytest

import atos.c6a_source_authority_transport as transport
from atos.c6a_source_authority import SourceAuthorityError
from atos.c6a_source_authority_capture import CapturedResponse, FrozenRequest


def _request() -> FrozenRequest:
    return FrozenRequest(
        request_id="archive-1",
        request_kind="archive_lookup",
        url="https://web.archive.org/cdx/search/cdx?url=example",
        canonical_official_url="https://www.okx.com/api/v5/public/instruments?instType=SPOT&instId=BTC-USDT",
        expected_content_type="application/json",
    )


def _capture(final_url: str) -> CapturedResponse:
    return CapturedResponse(
        request=_request(),
        retrieval_started_at="2026-01-01T00:00:00+00:00",
        retrieval_completed_at="2026-01-01T00:00:01+00:00",
        status_code=200,
        final_url=final_url,
        headers={"content-type": "application/json"},
        raw_path="raw/archive-1.bin",
        raw_size=2,
        raw_sha256="1" * 64,
    )


def test_archive_redirect_must_remain_on_wayback(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        transport,
        "capture_request",
        lambda *args, **kwargs: _capture("https://web.archive.org/web/20240101id_/https://www.okx.com/"),
    )
    result = transport.strict_capture_request(
        _request(),
        output_root=tmp_path,
        timeout_seconds=1,
        max_attempts=1,
        initial_backoff_seconds=0,
        maximum_backoff_seconds=0,
    )
    assert result.final_url.startswith("https://web.archive.org/")

    monkeypatch.setattr(
        transport,
        "capture_request",
        lambda *args, **kwargs: _capture("https://example.invalid/archive-wrapper"),
    )
    with pytest.raises(SourceAuthorityError, match="escaped frozen host"):
        transport.strict_capture_request(
            _request(),
            output_root=tmp_path,
            timeout_seconds=1,
            max_attempts=1,
            initial_backoff_seconds=0,
            maximum_backoff_seconds=0,
        )
