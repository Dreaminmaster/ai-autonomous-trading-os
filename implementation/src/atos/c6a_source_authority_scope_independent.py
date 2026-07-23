"""Physically separate GLOBAL announcement-scope reviewer.

This module does not import production scope, capture, parser, transport, gate,
or package code.  It recomputes source jurisdiction from the frozen inventory,
retained URLs, raw HTML, and decoded article URLs.
"""
from __future__ import annotations

import json
import re
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Mapping, Sequence
from urllib.parse import urlparse


SCOPE_FAILURE = "FAIL_SOURCE_AUTHORITY_SCOPE_DRIFT"
GLOBAL_CATALOG_REQUEST_ID = "okx-announcement-catalog-global"
_GLOBAL_CATALOG_PATH_RE = re.compile(
    r"^/help/(?:category/announcements|section/announcements-latest-announcements(?:/page/\d+)?)$",
    re.IGNORECASE,
)
_GLOBAL_ARTICLE_PATH_RE = re.compile(r"^/help/[^/].*$", re.IGNORECASE)
_LOCALE_HELP_PATH_RE = re.compile(r"^/[a-z]{2,3}(?:-[a-z]{2,4})?/help(?:/|$)", re.IGNORECASE)
_REQUIRED_GLOBAL_CATEGORY_MARKERS = (
    "latest events",
    "deposit/withdrawal suspension",
    "p2p trading",
    "web3",
    "earn and loan",
    "jumpstart",
    "okb burn",
    "others",
)
_FORBIDDEN_REGIONAL_MARKERS = ("okx united states", "okx europe", "okx tr")


class _VisibleTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        text = " ".join(data.split())
        if text:
            self.parts.append(text)


def _safe_file(root: Path, relative: Any) -> Path | None:
    if not isinstance(relative, str) or not relative:
        return None
    path = (root / relative).resolve()
    if not path.is_relative_to(root.resolve()) or not path.is_file():
        return None
    return path


def _global_catalog_url(url: str) -> bool:
    parsed = urlparse(url)
    return bool(
        parsed.scheme == "https"
        and (parsed.hostname or "").lower() == "www.okx.com"
        and not _LOCALE_HELP_PATH_RE.match(parsed.path)
        and _GLOBAL_CATALOG_PATH_RE.fullmatch(parsed.path)
    )


def _global_article_url(url: str) -> bool:
    parsed = urlparse(url)
    return bool(
        parsed.scheme == "https"
        and (parsed.hostname or "").lower() == "www.okx.com"
        and not _LOCALE_HELP_PATH_RE.match(parsed.path)
        and _GLOBAL_ARTICLE_PATH_RE.fullmatch(parsed.path)
    )


def _inventory_contract_valid(payload: Mapping[str, Any]) -> bool:
    rows = payload.get("requests")
    if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes)):
        return False
    matches = [row for row in rows if isinstance(row, Mapping) and row.get("request_id") == GLOBAL_CATALOG_REQUEST_ID]
    if len(matches) != 1:
        return False
    row = matches[0]
    return bool(
        row.get("request_kind") == "announcement_catalog"
        and row.get("authority_jurisdiction") == "GLOBAL"
        and row.get("requested_scope")
        == {
            "host": "www.okx.com",
            "path_mode": "GLOBAL_LOCALE_NEUTRAL_HELP",
            "regional_substitution_allowed": False,
        }
        and row.get("required_scope_proof")
        == {
            "final_url": True,
            "page_content": True,
            "cross_page_consistency": True,
        }
        and _global_catalog_url(str(row.get("url", "")).replace("{page}", "1"))
    )


def review_global_scope(
    root: Path,
    *,
    query_inventory: Mapping[str, Any],
    source_inventory: Mapping[str, Any],
    announcement_catalog: Mapping[str, Any],
) -> dict[str, Any]:
    """Recompute GLOBAL scope without trusting the production scope verdict."""

    errors: list[str] = []
    failures: set[str] = set()
    if not _inventory_contract_valid(query_inventory):
        errors.append("GLOBAL source-scope inventory contract missing or changed")
        failures.add("FAIL_QUERY_INVENTORY_MISSING_OR_CHANGED")

    rows = source_inventory.get("sources")
    if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes)):
        rows = []
        errors.append("source inventory sources missing for scope review")
    catalog_rows = [
        row
        for row in rows
        if isinstance(row, Mapping)
        and str(row.get("source_id", "")).startswith(f"{GLOBAL_CATALOG_REQUEST_ID}-page-")
    ]

    page_numbers: set[int] = set()
    observed_scope_fingerprints: set[tuple[str, ...]] = set()
    for index, row in enumerate(catalog_rows):
        requested = str(row.get("requested_url", ""))
        retrieval = str(row.get("retrieval_url", ""))
        if not _global_catalog_url(requested) or not _global_catalog_url(retrieval):
            failures.add(SCOPE_FAILURE)
            errors.append(f"catalog source {index} requested/final URL is not GLOBAL")

        raw_path = _safe_file(root, row.get("raw_path"))
        decoded_path = _safe_file(root, row.get("decoded_path"))
        if raw_path is None or decoded_path is None:
            errors.append(f"catalog source {index} lacks retained raw or decoded bytes")
            continue
        try:
            raw_text = raw_path.read_bytes().decode("utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            errors.append(f"catalog source {index} raw HTML unreadable: {exc}")
            failures.add(SCOPE_FAILURE)
            continue
        visible_parser = _VisibleTextParser()
        visible_parser.feed(raw_text)
        folded = " ".join(visible_parser.parts).casefold()
        forbidden = tuple(marker for marker in _FORBIDDEN_REGIONAL_MARKERS if marker in folded)
        present = tuple(marker for marker in _REQUIRED_GLOBAL_CATEGORY_MARKERS if marker in folded)
        missing = tuple(marker for marker in _REQUIRED_GLOBAL_CATEGORY_MARKERS if marker not in folded)
        if forbidden or missing:
            failures.add(SCOPE_FAILURE)
            errors.append(
                f"catalog source {index} GLOBAL evidence mismatch: forbidden={list(forbidden)} missing={list(missing)}"
            )
        observed_scope_fingerprints.add(present)

        try:
            decoded = json.loads(decoded_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            errors.append(f"catalog source {index} decoded record unreadable: {exc}")
            continue
        if not isinstance(decoded, Mapping):
            errors.append(f"catalog source {index} decoded record is not an object")
            continue
        proof = decoded.get("scope_proof")
        producer_pass = bool(
            isinstance(proof, Mapping)
            and proof.get("status") == "PASS"
            and proof.get("authority_jurisdiction") == "GLOBAL"
        )
        recomputed_pass = not forbidden and not missing and _global_catalog_url(retrieval)
        if producer_pass != recomputed_pass:
            errors.append(f"catalog source {index} production/reviewer scope verdict mismatch")
        page_number = decoded.get("page_number")
        if type(page_number) is int and page_number > 0:
            if page_number in page_numbers:
                failures.add(SCOPE_FAILURE)
                errors.append(f"duplicate GLOBAL catalog page number: {page_number}")
            page_numbers.add(page_number)
        else:
            errors.append(f"catalog source {index} page number missing")
        articles = decoded.get("articles")
        if not isinstance(articles, Sequence) or isinstance(articles, (str, bytes)):
            errors.append(f"catalog source {index} articles missing")
        else:
            for article in articles:
                if not isinstance(article, Mapping) or not _global_article_url(
                    str(article.get("canonical_url", ""))
                ):
                    failures.add(SCOPE_FAILURE)
                    errors.append(f"catalog source {index} contains a non-GLOBAL article URL")
                    break

    pages = announcement_catalog.get("pages")
    if catalog_rows and isinstance(pages, Sequence) and not isinstance(pages, (str, bytes)):
        if len(catalog_rows) != len(pages):
            errors.append("scope-reviewed source/page count mismatch")
    if len(observed_scope_fingerprints) > 1:
        failures.add(SCOPE_FAILURE)
        errors.append("GLOBAL category fingerprint changed between catalog pages")

    return {
        "schema_version": 1,
        "stage": "C6A_SOURCE_AUTHORITY_GLOBAL_SCOPE_INDEPENDENT_REVIEW",
        "status": "PASS" if not errors else "FAIL",
        "authority_jurisdiction": "GLOBAL",
        "catalog_source_count": len(catalog_rows),
        "page_numbers": sorted(page_numbers),
        "recomputed_failures": sorted(failures),
        "errors": errors,
        "implementation_authorized": False,
        "economic_data_access_authorized": False,
        "live_state": "LIVE_FORBIDDEN",
    }
