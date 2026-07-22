"""Exact instrument-identity rules for the C6A metadata authority gate.

The gate models exactly two OKX spot instruments and their USDT-settled
perpetual swaps.  A metadata interval is ineligible when its type, currencies,
underlying, settlement, or listing state disagrees with that frozen identity.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from atos.c6a_source_authority import MetadataState, SourceAuthorityError


@dataclass(frozen=True)
class InstrumentIdentity:
    instrument: str
    inst_type: str
    base_ccy: str
    quote_ccy: str
    underlying: str | None
    settle_ccy: str | None
    ct_val_ccy: str | None


IDENTITIES = {
    "BTC-USDT": InstrumentIdentity(
        instrument="BTC-USDT",
        inst_type="SPOT",
        base_ccy="BTC",
        quote_ccy="USDT",
        underlying=None,
        settle_ccy=None,
        ct_val_ccy=None,
    ),
    "ETH-USDT": InstrumentIdentity(
        instrument="ETH-USDT",
        inst_type="SPOT",
        base_ccy="ETH",
        quote_ccy="USDT",
        underlying=None,
        settle_ccy=None,
        ct_val_ccy=None,
    ),
    "BTC-USDT-SWAP": InstrumentIdentity(
        instrument="BTC-USDT-SWAP",
        inst_type="SWAP",
        base_ccy="BTC",
        quote_ccy="USDT",
        underlying="BTC-USDT",
        settle_ccy="USDT",
        ct_val_ccy="BTC",
    ),
    "ETH-USDT-SWAP": InstrumentIdentity(
        instrument="ETH-USDT-SWAP",
        inst_type="SWAP",
        base_ccy="ETH",
        quote_ccy="USDT",
        underlying="ETH-USDT",
        settle_ccy="USDT",
        ct_val_ccy="ETH",
    ),
}


def expected_identity(instrument: str) -> InstrumentIdentity:
    try:
        return IDENTITIES[instrument]
    except KeyError as exc:
        raise SourceAuthorityError("instrument is outside the frozen C6A identity set") from exc


def validate_metadata_state_identity(state: MetadataState) -> None:
    """Reject a state whose normalized identity is inconsistent with its ID."""

    expected = expected_identity(state.instrument)
    observed = {
        "inst_type": state.inst_type,
        "base_ccy": state.base_ccy,
        "quote_ccy": state.quote_ccy,
        "settle_ccy": state.settle_ccy,
        "ct_val_ccy": state.ct_val_ccy,
        "listing_state": state.listing_state,
    }
    required = {
        "inst_type": expected.inst_type,
        "base_ccy": expected.base_ccy,
        "quote_ccy": expected.quote_ccy,
        "settle_ccy": expected.settle_ccy,
        "ct_val_ccy": expected.ct_val_ccy,
        "listing_state": "live",
    }
    mismatches = {
        field: {"expected": value, "observed": observed[field]}
        for field, value in required.items()
        if observed[field] != value
    }
    if mismatches:
        raise SourceAuthorityError(f"FAIL_REQUIRED_FIELD_MISSING: instrument identity mismatch {mismatches}")


def normalized_identity_from_okx_row(
    row: Mapping[str, Any], *, expected_instrument: str
) -> dict[str, str | None]:
    """Normalize an official OKX instruments row without inventing SWAP fields.

    OKX public instrument responses expose ``baseCcy`` and ``quoteCcy`` for
    SPOT/MARGIN.  For SWAP, the frozen base/quote identity is derived only from
    the exact official ``uly`` value, while the original underlying is retained.
    """

    expected = expected_identity(expected_instrument)
    inst_id = row.get("instId")
    inst_type = row.get("instType")
    if inst_id != expected.instrument or inst_type != expected.inst_type:
        raise SourceAuthorityError("archived OKX instrument ID or type mismatch")

    if expected.inst_type == "SPOT":
        base_ccy = row.get("baseCcy")
        quote_ccy = row.get("quoteCcy")
        if base_ccy != expected.base_ccy or quote_ccy != expected.quote_ccy:
            raise SourceAuthorityError("archived OKX spot currency identity mismatch")
        if row.get("uly") not in (None, ""):
            raise SourceAuthorityError("archived OKX spot row unexpectedly carries an underlying")
        return {
            "baseCcy": expected.base_ccy,
            "quoteCcy": expected.quote_ccy,
            "uly": None,
            "settleCcy": None,
            "ctValCcy": None,
            "identity_derivation": "DIRECT_SPOT_BASE_QUOTE",
        }

    underlying = row.get("uly")
    settle_ccy = row.get("settleCcy")
    ct_val_ccy = row.get("ctValCcy")
    if underlying != expected.underlying:
        raise SourceAuthorityError("archived OKX swap underlying identity mismatch")
    if settle_ccy != expected.settle_ccy or ct_val_ccy != expected.ct_val_ccy:
        raise SourceAuthorityError("archived OKX swap settlement or contract-value currency mismatch")
    return {
        "baseCcy": expected.base_ccy,
        "quoteCcy": expected.quote_ccy,
        "uly": expected.underlying,
        "settleCcy": expected.settle_ccy,
        "ctValCcy": expected.ct_val_ccy,
        "identity_derivation": "EXACT_OFFICIAL_UNDERLYING",
    }
