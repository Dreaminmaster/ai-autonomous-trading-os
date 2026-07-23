from __future__ import annotations

from atos.c6a_source_authority_partition_review import review_transition_partition


def _state(
    state_id: str,
    instrument: str,
    start: str,
    end: str,
    mode: str,
) -> dict:
    return {
        "state_id": state_id,
        "instrument": instrument,
        "effective_from": start,
        "effective_to": end,
        "authority_mode": mode,
    }


def test_missing_transition_partition_is_validated_as_expected_gate_failure() -> None:
    result = review_transition_partition(
        [],
        recorded_failures=["FAIL_TRANSITION_WINDOW_UNPROVEN"],
    )
    assert result["status"] == "PASS"
    assert result["observed_transition_state_count"] == 0
    assert len(result["missing_transition_states"]) == 4
    assert result["recorded_transition_failure"] is True


def test_claimed_success_cannot_span_frozen_window_with_exact_state() -> None:
    states = [
        _state(
            "eth-spanning",
            "ETH-USDT-SWAP",
            "2023-06-05T00:00:00Z",
            "2025-12-29T00:00:00Z",
            "EXACT_EFFECTIVE_STATE",
        )
    ]
    result = review_transition_partition(states, recorded_failures=[])
    assert result["status"] == "FAIL"
    assert result["exact_states_spanning_frozen_windows"] == ["eth-spanning", "eth-spanning"]
    assert any("did not record" in error for error in result["errors"])


def test_exact_four_transition_states_pass_partition_review() -> None:
    states = [
        _state(
            "eth-2024",
            "ETH-USDT-SWAP",
            "2024-04-18T06:00:00Z",
            "2024-04-18T08:00:00Z",
            "TRANSITION_SAFE_INTERSECTION",
        ),
        _state(
            "btc-2024",
            "BTC-USDT-SWAP",
            "2024-04-25T06:00:00Z",
            "2024-04-25T08:00:00Z",
            "TRANSITION_SAFE_INTERSECTION",
        ),
        _state(
            "eth-2025",
            "ETH-USDT-SWAP",
            "2025-01-09T06:00:00Z",
            "2025-01-09T10:00:00Z",
            "TRANSITION_SAFE_INTERSECTION",
        ),
        _state(
            "btc-2025",
            "BTC-USDT-SWAP",
            "2025-01-22T06:00:00Z",
            "2025-01-22T08:00:00Z",
            "TRANSITION_SAFE_INTERSECTION",
        ),
    ]
    result = review_transition_partition(states, recorded_failures=[])
    assert result["status"] == "PASS"
    assert result["observed_transition_state_count"] == 4
    assert result["missing_transition_states"] == []
    assert result["exact_states_spanning_frozen_windows"] == []
