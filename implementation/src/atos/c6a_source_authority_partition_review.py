"""Independent transition-state partition review for C6A source authority.

This module imports no production gate, parser, capture, or package code.  It
checks that a claimed successful authority package uses exactly the four frozen
transition-state intervals and that exact states do not span those ambiguous
windows.  An incomplete partition is acceptable only when the recorded gate
already fails with the corresponding frozen transition failure.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Mapping, Sequence


FROZEN_WINDOWS = {
    ("ETH-USDT-SWAP", "2024-04-18T06:00:00+00:00", "2024-04-18T08:00:00+00:00"),
    ("BTC-USDT-SWAP", "2024-04-25T06:00:00+00:00", "2024-04-25T08:00:00+00:00"),
    ("ETH-USDT-SWAP", "2025-01-09T06:00:00+00:00", "2025-01-09T10:00:00+00:00"),
    ("BTC-USDT-SWAP", "2025-01-22T06:00:00+00:00", "2025-01-22T08:00:00+00:00"),
}
TRANSITION_FAILURES = {
    "FAIL_TRANSITION_WINDOW_UNPROVEN",
    "FAIL_NEW_UNFROZEN_TRANSITION",
    "FAIL_AMBIGUOUS_OR_CONTRADICTORY_STATE",
}


def _timestamp(value: Any) -> datetime:
    if not isinstance(value, str) or not value:
        raise ValueError("timestamp must be a non-empty string")
    text = value[:-1] + "+00:00" if value.endswith("Z") else value
    result = datetime.fromisoformat(text)
    if result.tzinfo is None or result.utcoffset() != timedelta(0):
        raise ValueError("timestamp must carry explicit UTC")
    return result.astimezone(timezone.utc)


def review_transition_partition(
    states: Sequence[Mapping[str, Any]],
    *,
    recorded_failures: Sequence[str],
) -> dict[str, Any]:
    diagnostics: list[str] = []
    transition_keys: list[tuple[str, str, str]] = []
    spanning_exact_states: list[str] = []

    for index, state in enumerate(states):
        if not isinstance(state, Mapping):
            diagnostics.append(f"metadata state {index} is not an object")
            continue
        try:
            instrument = str(state["instrument"])
            start = _timestamp(state["effective_from"])
            end = _timestamp(state["effective_to"])
        except (KeyError, TypeError, ValueError) as exc:
            diagnostics.append(f"metadata state {index} interval is malformed: {exc}")
            continue
        mode = state.get("authority_mode")
        key = (instrument, start.isoformat(), end.isoformat())
        if mode == "TRANSITION_SAFE_INTERSECTION":
            transition_keys.append(key)
        elif mode == "EXACT_EFFECTIVE_STATE":
            for frozen_instrument, frozen_start_text, frozen_end_text in FROZEN_WINDOWS:
                if instrument != frozen_instrument:
                    continue
                frozen_start = _timestamp(frozen_start_text)
                frozen_end = _timestamp(frozen_end_text)
                if start < frozen_end and end > frozen_start:
                    spanning_exact_states.append(str(state.get("state_id", index)))

    observed = set(transition_keys)
    missing = sorted(FROZEN_WINDOWS - observed)
    extra = sorted(observed - FROZEN_WINDOWS)
    duplicates = sorted({key for key in transition_keys if transition_keys.count(key) > 1})
    partition_incomplete = bool(missing or extra or duplicates or spanning_exact_states or diagnostics)
    recorded_transition_failure = bool(set(recorded_failures) & TRANSITION_FAILURES)

    errors = list(diagnostics)
    if partition_incomplete and not recorded_transition_failure:
        errors.append(
            "transition-state partition is incomplete or unsafe but the gate did not record a frozen transition failure"
        )

    return {
        "schema_version": 1,
        "stage": "C6A_SOURCE_AUTHORITY_TRANSITION_PARTITION_REVIEW",
        "status": "PASS" if not errors else "FAIL",
        "required_transition_state_count": len(FROZEN_WINDOWS),
        "observed_transition_state_count": len(observed),
        "missing_transition_states": [list(key) for key in missing],
        "extra_transition_states": [list(key) for key in extra],
        "duplicate_transition_states": [list(key) for key in duplicates],
        "exact_states_spanning_frozen_windows": spanning_exact_states,
        "recorded_transition_failure": recorded_transition_failure,
        "errors": errors,
        "implementation_authorized": False,
        "economic_data_access_authorized": False,
        "live_state": "LIVE_FORBIDDEN",
    }
