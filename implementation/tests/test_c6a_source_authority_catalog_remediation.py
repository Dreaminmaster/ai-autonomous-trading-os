from __future__ import annotations

import pytest

from atos.c6a_source_authority import SourceAuthorityError
from atos.c6a_source_authority_catalog_remediation import (
    is_bounded_okx_help_path,
    parse_announcement_catalog,
)


def _page(href: str) -> bytes:
    return f"""
    <html><body>
      <a href="{href}">OKX to adjust lot size for BTC-USDT-SWAP Published on Apr 17, 2024</a>
      <div>Showing 1-1 of 1 articles</div>
    </body></html>
    """.encode()


@pytest.mark.parametrize(
    "path",
    [
        "/help/example",
        "/en-us/help/example",
        "/zh-hans/help/example",
        "/pt/help/example",
        "/es-la/help/example",
    ],
)
def test_bounded_okx_help_path_accepts_global_and_one_locale_segment(path: str) -> None:
    assert is_bounded_okx_help_path(path) is True


@pytest.mark.parametrize(
    "path",
    [
        "/en-us/not-help/example",
        "/foo/bar/help/example",
        "/api/v5/help/example",
        "/en_us/help/example",
    ],
)
def test_bounded_okx_help_path_rejects_scope_escape(path: str) -> None:
    assert is_bounded_okx_help_path(path) is False


def test_catalog_parser_preserves_exact_locale_prefixed_article_url() -> None:
    page = parse_announcement_catalog(
        "https://www.okx.com/help/section/announcements-latest-announcements/page/1",
        _page("/en-us/help/adjust-btc-swap"),
    )
    assert page["is_terminal_page"] is True
    assert page["articles"][0]["canonical_url"] == (
        "https://www.okx.com/en-us/help/adjust-btc-swap"
    )


def test_catalog_parser_rejects_nested_or_non_help_official_path() -> None:
    with pytest.raises(SourceAuthorityError, match="escaped the frozen OKX help scope"):
        parse_announcement_catalog(
            "https://www.okx.com/help/section/announcements-latest-announcements/page/1",
            _page("/foo/bar/help/adjust-btc-swap"),
        )
