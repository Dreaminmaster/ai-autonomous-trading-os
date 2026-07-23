from __future__ import annotations

import pytest

from atos.c6a_source_authority import MetadataState, SourceAuthorityError
from atos.c6a_source_authority_identity import (
    normalized_identity_from_okx_row,
    validate_metadata_state_identity,
)


def _state(**overrides) -> MetadataState:
    values = {
        "state_id": "btc-swap-state",
        "instrument": "BTC-USDT-SWAP",
        "authority_mode": "EXACT_EFFECTIVE_STATE",
        "inst_type": "SWAP",
        "base_ccy": "BTC",
        "quote_ccy": "USDT",
        "settle_ccy": "USDT",
        "ct_val": "0.01",
        "ct_val_ccy": "BTC",
        "lot_sz": "0.1",
        "min_sz": "0.1",
        "tick_sz": "0.1",
        "listing_state": "live",
        "effective_from": "2023-06-05T00:00:00Z",
        "effective_to": "2025-12-29T00:00:00Z",
        "open_ended": False,
        "source_ids": ["source-1"],
        "contradiction": False,
    }
    values.update(overrides)
    return MetadataState.from_mapping(values)


def test_swap_identity_is_derived_only_from_exact_underlying() -> None:
    identity = normalized_identity_from_okx_row(
        {
            "instId": "BTC-USDT-SWAP",
            "instType": "SWAP",
            "uly": "BTC-USDT",
            "baseCcy": "",
            "quoteCcy": "",
            "settleCcy": "USDT",
            "ctValCcy": "BTC",
        },
        expected_instrument="BTC-USDT-SWAP",
    )
    assert identity == {
        "baseCcy": "BTC",
        "quoteCcy": "USDT",
        "uly": "BTC-USDT",
        "settleCcy": "USDT",
        "ctValCcy": "BTC",
        "identity_derivation": "EXACT_OFFICIAL_UNDERLYING",
    }


def test_metadata_state_identity_rejects_wrong_base_or_non_live_state() -> None:
    validate_metadata_state_identity(_state())
    with pytest.raises(SourceAuthorityError, match="identity mismatch"):
        validate_metadata_state_identity(_state(base_ccy="ETH"))
    with pytest.raises(SourceAuthorityError, match="identity mismatch"):
        validate_metadata_state_identity(_state(listing_state="suspend"))
