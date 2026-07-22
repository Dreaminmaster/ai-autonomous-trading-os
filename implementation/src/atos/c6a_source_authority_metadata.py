"""Exact decoder for retained OKX public-instruments responses."""
from __future__ import annotations

import json
from typing import Any, Mapping

from atos.c6a_source_authority import SourceAuthorityError
from atos.c6a_source_authority_identity import normalized_identity_from_okx_row


COMMON_REQUIRED_FIELDS = (
    "instId",
    "instType",
    "lotSz",
    "minSz",
    "tickSz",
    "state",
)


def _required_exact_strings(row: Mapping[str, Any], fields: tuple[str, ...]) -> None:
    missing = [field for field in fields if not isinstance(row.get(field), str) or not row[field]]
    if missing:
        raise SourceAuthorityError(f"archived OKX response missing required fields: {missing}")


def decode_okx_instruments_response(data: bytes, *, expected_instrument: str) -> dict[str, Any]:
    """Decode one exact official row while preserving decimal strings.

    SPOT base/quote currencies are read directly.  SWAP base/quote currencies
    are normalized only from the exact official ``uly`` field; empty or absent
    SWAP ``baseCcy``/``quoteCcy`` values are neither required nor treated as
    evidence.
    """

    try:
        payload = json.loads(data)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SourceAuthorityError("archived OKX response is not valid JSON") from exc
    if not isinstance(payload, Mapping) or payload.get("code") != "0" or payload.get("msg") not in ("", None):
        raise SourceAuthorityError("archived object is not an eligible OKX public response")
    rows = payload.get("data")
    if not isinstance(rows, list) or len(rows) != 1 or not isinstance(rows[0], Mapping):
        raise SourceAuthorityError("archived OKX instruments response must contain exactly one row")

    row = rows[0]
    _required_exact_strings(row, COMMON_REQUIRED_FIELDS)
    identity = normalized_identity_from_okx_row(row, expected_instrument=expected_instrument)
    inst_type = str(row["instType"])
    if inst_type == "SPOT":
        _required_exact_strings(row, ("baseCcy", "quoteCcy"))
        selected_fields = (*COMMON_REQUIRED_FIELDS, "baseCcy", "quoteCcy")
    elif inst_type == "SWAP":
        _required_exact_strings(row, ("uly", "settleCcy", "ctVal", "ctValCcy"))
        selected_fields = (*COMMON_REQUIRED_FIELDS, "uly", "settleCcy", "ctVal", "ctValCcy")
    else:
        raise SourceAuthorityError("archived OKX instrument type is outside the frozen SPOT/SWAP scope")

    selected = {field: str(row[field]) for field in selected_fields}
    selected.update(identity)
    return {
        "code": "0",
        "msg": "",
        "data": [selected],
    }
