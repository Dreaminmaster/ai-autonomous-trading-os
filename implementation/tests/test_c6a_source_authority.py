from __future__ import annotations

from decimal import Decimal

import pytest

from atos.c6a_source_authority import (
    AUTHORITY_END_TEXT,
    AUTHORITY_START_TEXT,
    DESIGN_AUTHORITY_SHA,
    FROZEN_TRANSITIONS,
    INSTRUMENTS,
    MetadataState,
    SourceAuthorityError,
    SourceObject,
    build_coverage_matrix,
    gate_result,
    prove_transition,
    quantity_valid,
    transition_intersection,
    validate_query_inventory,
    validate_url,
)


def _query_inventory() -> dict:
    return {
        "schema_version": 1,
        "stage": "C6A_SOURCE_AUTHORITY_GATE",
        "design_authority_sha": DESIGN_AUTHORITY_SHA,
        "authenticated": False,
        "economic_endpoints_forbidden": True,
        "authority_start": AUTHORITY_START_TEXT,
        "authority_end_exclusive": AUTHORITY_END_TEXT,
        "instruments": list(INSTRUMENTS),
        "requests": [
            {
                "request_id": "spot-current-schema",
                "request_kind": "public_instruments",
                "method": "GET",
                "url": "https://www.okx.com/api/v5/public/instruments?instType=SPOT",
                "expected_content_type": "application/json",
            },
            {
                "request_id": "announcement-catalog",
                "request_kind": "announcement_catalog",
                "method": "GET",
                "url": "https://www.okx.com/help/section/announcements-system-upgrades",
                "expected_content_type": "text/html",
            },
            {
                "request_id": "archived-official-response",
                "request_kind": "archive_lookup",
                "method": "GET",
                "url": "https://web.archive.org/cdx/search/cdx?url=www.okx.com/api/v5/public/instruments",
                "canonical_official_url": "https://www.okx.com/api/v5/public/instruments?instType=SWAP",
                "expected_content_type": "application/json",
            },
        ],
        "retry_policy": {"max_attempts": 3, "timeout_seconds": 30},
    }


def _state(
    *,
    state_id: str,
    instrument: str,
    effective_from: str,
    effective_to: str,
    lot_sz: str = "0.00000001",
    min_sz: str = "0.00001",
    tick_sz: str = "0.1",
    authority_mode: str = "EXACT_EFFECTIVE_STATE",
) -> MetadataState:
    swap = instrument.endswith("-SWAP")
    return MetadataState.from_mapping(
        {
            "state_id": state_id,
            "instrument": instrument,
            "authority_mode": authority_mode,
            "inst_type": "SWAP" if swap else "SPOT",
            "base_ccy": instrument.split("-")[0],
            "quote_ccy": "USDT",
            "settle_ccy": "USDT" if swap else None,
            "ct_val": "0.01" if swap else None,
            "ct_val_ccy": instrument.split("-")[0] if swap else None,
            "lot_sz": lot_sz,
            "min_sz": min_sz,
            "tick_sz": tick_sz,
            "listing_state": "live",
            "effective_from": effective_from,
            "effective_to": effective_to,
            "open_ended": False,
            "source_ids": [f"source-{state_id}"],
            "contradiction": False,
        }
    )


def test_query_inventory_accepts_only_frozen_public_scope() -> None:
    rows = validate_query_inventory(_query_inventory())
    assert len(rows) == 3
    assert rows[0]["request_kind"] == "public_instruments"
    assert rows[2]["canonical_official_url"].startswith("https://www.okx.com/")


@pytest.mark.parametrize(
    "url",
    [
        "https://www.okx.com/api/v5/market/history-candles?instId=BTC-USDT",
        "https://www.okx.com/api/v5/market/history-mark-price-candles?instId=BTC-USDT-SWAP",
        "https://www.okx.com/api/v5/public/funding-rate-history?instId=BTC-USDT-SWAP",
        "https://www.okx.com/api/v5/account/balance",
    ],
)
def test_network_guard_rejects_economic_and_private_endpoints(url: str) -> None:
    with pytest.raises(SourceAuthorityError, match="forbidden"):
        validate_url(url, request_kind="announcement_article")


def test_query_inventory_rejects_credentials_and_design_drift() -> None:
    payload = _query_inventory()
    payload["design_authority_sha"] = "0" * 40
    with pytest.raises(SourceAuthorityError, match="design authority"):
        validate_query_inventory(payload)

    payload = _query_inventory()
    payload["requests"][0]["url"] += "&api_key=secret"
    with pytest.raises(SourceAuthorityError, match="credential"):
        validate_query_inventory(payload)


def test_archived_source_retains_official_canonical_authority() -> None:
    source = SourceObject.from_mapping(
        {
            "source_id": "archive-1",
            "authority_class": "EXACT_ARCHIVED_OFFICIAL_OKX_RESPONSE",
            "canonical_official_url": "https://www.okx.com/api/v5/public/instruments?instType=SWAP",
            "retrieval_url": "https://web.archive.org/web/20240401000000id_/https://www.okx.com/api/v5/public/instruments?instType=SWAP",
            "raw_sha256": "1" * 64,
            "decoded_sha256": "2" * 64,
            "raw_size": 100,
            "decoded_size": 90,
            "parser_version": "c6a-source-authority-v1",
            "eligible": True,
            "rejection_reason": None,
        }
    )
    assert source.eligible is True


def test_transition_intersection_uses_coarser_nested_increment() -> None:
    result = transition_intersection(
        old_lot="1",
        new_lot="0.1",
        old_min="1",
        new_min="0.1",
    )
    assert result == {
        "transition_lot": "1",
        "transition_min": "1",
        "nested_ratio": "10",
    }
    assert quantity_valid(Decimal("2"), lot=Decimal("1"), minimum=Decimal("1"))
    assert not quantity_valid(Decimal("0.5"), lot=Decimal("1"), minimum=Decimal("1"))


def test_transition_intersection_rejects_non_nested_lots() -> None:
    with pytest.raises(SourceAuthorityError, match="NOT_NESTED"):
        transition_intersection(
            old_lot="0.3",
            new_lot="0.2",
            old_min="0.3",
            new_min="0.2",
        )


def test_prove_transition_rejects_changed_contract_fields() -> None:
    window = FROZEN_TRANSITIONS[0]
    old = _state(
        state_id="old",
        instrument=window.instrument,
        effective_from=AUTHORITY_START_TEXT,
        effective_to="2024-04-18T06:00:00Z",
        lot_sz="1",
        min_sz="1",
    )
    new = _state(
        state_id="new",
        instrument=window.instrument,
        effective_from="2024-04-18T08:00:00Z",
        effective_to=AUTHORITY_END_TEXT,
        lot_sz="0.1",
        min_sz="0.1",
    )
    proof = prove_transition(old, new, window)
    assert proof["status"] == "PASS"
    assert proof["transition_lot"] == "1"
    assert all(
        not row["admitted_by_intersection"] or (row["valid_old"] and row["valid_new"])
        for row in proof["boundary_cases"]
    )

    changed = MetadataState.from_mapping(
        {
            **new.__dict__,
            "effective_from": "2024-04-18T08:00:00Z",
            "effective_to": AUTHORITY_END_TEXT,
            "tick_sz": "0.01",
            "source_ids": ["source-changed"],
        }
    )
    with pytest.raises(SourceAuthorityError, match="FIELDS_CHANGED"):
        prove_transition(old, changed, window)


def test_coverage_matrix_detects_gap_and_overlap() -> None:
    complete = [
        _state(
            state_id=f"{instrument}-complete",
            instrument=instrument,
            effective_from=AUTHORITY_START_TEXT,
            effective_to=AUTHORITY_END_TEXT,
            lot_sz="0.1" if instrument.endswith("-SWAP") else "0.00000001",
            min_sz="0.1" if instrument.endswith("-SWAP") else "0.00001",
        )
        for instrument in INSTRUMENTS
    ]
    matrix = build_coverage_matrix(complete)
    assert len(matrix) == 4

    gap = [state for state in complete if state.instrument != "BTC-USDT"]
    gap.extend(
        [
            _state(
                state_id="btc-a",
                instrument="BTC-USDT",
                effective_from=AUTHORITY_START_TEXT,
                effective_to="2024-01-01T00:00:00Z",
            ),
            _state(
                state_id="btc-b",
                instrument="BTC-USDT",
                effective_from="2024-01-02T00:00:00Z",
                effective_to=AUTHORITY_END_TEXT,
            ),
        ]
    )
    with pytest.raises(SourceAuthorityError, match="UNCOVERED_INTERVAL"):
        build_coverage_matrix(gap)

    overlap = [state for state in complete if state.instrument != "BTC-USDT"]
    overlap.extend(
        [
            _state(
                state_id="btc-a",
                instrument="BTC-USDT",
                effective_from=AUTHORITY_START_TEXT,
                effective_to="2024-01-02T00:00:00Z",
            ),
            _state(
                state_id="btc-b",
                instrument="BTC-USDT",
                effective_from="2024-01-01T00:00:00Z",
                effective_to=AUTHORITY_END_TEXT,
            ),
        ]
    )
    with pytest.raises(SourceAuthorityError, match="AMBIGUOUS"):
        build_coverage_matrix(overlap)


def test_gate_result_is_non_authorizing_and_uses_frozen_failure_priority() -> None:
    result = gate_result(
        source_commit_sha="a" * 40,
        query_inventory_sha256="b" * 64,
        failures=[
            "FAIL_MANIFEST_INCOMPLETE",
            "FAIL_FORBIDDEN_DATA_ACCESS",
            "FAIL_UNCOVERED_INTERVAL",
        ],
        source_object_count=10,
        eligible_source_object_count=8,
        coverage_rows=4,
        transition_proof_count=0,
    )
    assert result["status"] == "FAIL"
    assert result["result"] == "FAIL_FORBIDDEN_DATA_ACCESS"
    assert result["secondary_failures"] == [
        "FAIL_UNCOVERED_INTERVAL",
        "FAIL_MANIFEST_INCOMPLETE",
    ]
    assert result["implementation_authorized"] is False
    assert result["economic_data_access_authorized"] is False
    assert result["live_state"] == "LIVE_FORBIDDEN"
