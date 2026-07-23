"""Execution boundary for the bounded GLOBAL announcements-category probe.

The previously frozen latest-announcements section probe remains immutable. This
module temporarily binds both the production probe and the physically separate
reviewer to the official locale-neutral announcements category root, runs one
bounded page/root-only matrix, writes the independent review and manifest, and
restores every binding in ``finally``.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

import atos.c6a_source_scope_probe as probe
import atos.c6a_source_scope_probe_independent as independent


CATEGORY_PROBE_URL = "https://www.okx.com/help/category/announcements"


def run_category_scope_probe(
    output_root: Path,
    *,
    fetch_candidate: Callable[[probe.ProbeCandidate], Mapping[str, Any]] = probe.network_fetch_candidate,
    candidates: Sequence[probe.ProbeCandidate] = probe.CANDIDATES,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    """Run the fixed category-root probe and restore the original probe URLs."""

    original_probe_url = probe.PROBE_URL
    original_review_url = independent.PROBE_URL
    probe.PROBE_URL = CATEGORY_PROBE_URL
    independent.PROBE_URL = CATEGORY_PROBE_URL
    try:
        result = probe.run_probe(
            output_root,
            fetch_candidate=fetch_candidate,
            candidates=candidates,
        )
        review = independent.review_probe(output_root)
        probe.atomic_write_json(output_root / "independent_review.json", review)
        manifest = probe.build_manifest(output_root)
        return result, review, manifest
    finally:
        independent.PROBE_URL = original_review_url
        probe.PROBE_URL = original_probe_url
