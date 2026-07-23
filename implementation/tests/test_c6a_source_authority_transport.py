from __future__ import annotations

from email.message import Message
from pathlib import Path
from urllib.request import Request

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


def test_redirect_handler_rejects_archive_escape_before_follow() -> None:
    handler = transport._FrozenRedirectHandler(_request())
    initial = Request(_request().url, method="GET")
    with pytest.raises(SourceAuthorityError, match="before follow"):
        handler.redirect_request(
            initial,
            None,
            302,
            "Found",
            Message(),
            "https://example.invalid/archive-wrapper",
        )


def test_archive_capture_uses_guarded_opener_and_restores_global(monkeypatch, tmp_path: Path) -> None:
    original_urlopen = transport.capture_module.urlopen
    observed = {}

    def capture_stub(*args, **kwargs):
        observed["urlopen_during_capture"] = transport.capture_module.urlopen
        return _capture("https://web.archive.org/web/20240101id_/https://www.okx.com/")

    monkeypatch.setattr(transport.capture_module, "capture_request", capture_stub)
    result = transport.strict_capture_request(
        _request(),
        output_root=tmp_path,
        timeout_seconds=1,
        max_attempts=1,
        initial_backoff_seconds=0,
        maximum_backoff_seconds=0,
    )
    assert result.final_url.startswith("https://web.archive.org/")
    assert observed["urlopen_during_capture"] is not original_urlopen
    assert transport.capture_module.urlopen is original_urlopen


def test_final_url_check_remains_defense_in_depth(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        transport.capture_module,
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
