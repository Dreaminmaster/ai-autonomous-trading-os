"""Final production C6A safe aggregate semantics.

The economic meaning of undefined weekly statistics is encoded as a canonical
state rather than a library-dependent exception string.  This keeps production
and independent evidence stable while still rejecting the candidate.
"""
from __future__ import annotations

from dataclasses import replace
from typing import Any, Mapping, Sequence

from atos.c6a_safe_aggregate import (
    SafeAggregateResult,
    aggregate_window_results_safe,
    decide_candidate_safe,
)

UNDEFINED_WEEKLY_STATISTICS = "UNDEFINED_WEEKLY_VARIANCE"


def aggregate_window_results_final(
    results: Sequence[Mapping[str, Any]], replays: Sequence[Any]
) -> SafeAggregateResult:
    result = aggregate_window_results_safe(results, replays)
    if result.statistics is None:
        return replace(
            result,
            statistics_error=UNDEFINED_WEEKLY_STATISTICS,
        )
    return replace(result, statistics_error=None)


__all__ = [
    "SafeAggregateResult",
    "UNDEFINED_WEEKLY_STATISTICS",
    "aggregate_window_results_final",
    "decide_candidate_safe",
]
