"""Load hash-bound canonical C6A primitive inputs."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from atos.c6a_contract import (
    C6AError,
    FundingRecord,
    MetadataRecord,
    SPOT_INSTRUMENTS,
    SWAP_INSTRUMENTS,
    validate_funding_records,
)
from atos.c6a_data import C6AMarket, validate_mark_candles, validate_trade_candles
from atos.c6a_evidence import sha256_file


def read_jsonl(path: Path) -> list[Any]:
    if not path.is_file() or path.is_symlink():
        raise C6AError(f"canonical input missing or unsafe: {path}")
    rows: list[Any] = []
    try:
        with path.open("r", encoding="utf-8") as handle:
            for number, line in enumerate(handle, start=1):
                if not line.strip():
                    continue
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError as exc:
                    raise C6AError(f"invalid canonical JSONL {path}:{number}: {exc}") from exc
    except OSError as exc:
        raise C6AError(f"unable to read canonical input {path}: {exc}") from exc
    if not rows:
        raise C6AError(f"canonical input is empty: {path}")
    return rows


def _output_map(report: Mapping[str, Any]) -> dict[tuple[str, str], Mapping[str, Any]]:
    outputs = report.get("outputs")
    if not isinstance(outputs, list):
        raise C6AError("C6A prepare report output list missing")
    result: dict[tuple[str, str], Mapping[str, Any]] = {}
    for row in outputs:
        if not isinstance(row, Mapping):
            raise C6AError("C6A prepare report output row is not an object")
        key = (str(row.get("kind", "")), str(row.get("instrument", "")))
        if key in result:
            raise C6AError(f"duplicate C6A canonical output: {key}")
        result[key] = row
    return result


def _verified_rows(row: Mapping[str, Any]) -> list[Any]:
    path = Path(str(row.get("path", "")))
    if not path.is_file() or path.is_symlink():
        raise C6AError(f"canonical output missing or unsafe: {path}")
    expected_size = int(row.get("size", -1))
    if path.stat().st_size != expected_size:
        raise C6AError(f"canonical output size mismatch: {path}")
    if sha256_file(path) != row.get("sha256"):
        raise C6AError(f"canonical output SHA-256 mismatch: {path}")
    rows = read_jsonl(path)
    if len(rows) != int(row.get("row_count", -1)):
        raise C6AError(f"canonical output row-count mismatch: {path}")
    return rows


def load_canonical_inputs(
    prepare_report: Mapping[str, Any],
) -> tuple[C6AMarket, tuple[FundingRecord, ...], tuple[MetadataRecord, ...]]:
    if (
        prepare_report.get("schema_version") != 1
        or prepare_report.get("stage") != "C6A"
        or prepare_report.get("status") != "PASS"
    ):
        raise C6AError("invalid C6A prepare report identity/status")
    if prepare_report.get("economic_boundary_exclusive") not in {
        "2025-12-29T00:00:00+00:00",
        "2025-12-29T00:00:00Z",
    }:
        raise C6AError("C6A prepare report boundary drift")
    if (
        prepare_report.get("c6b_state") != "C6B_CLOSED"
        or prepare_report.get("c5b_state") != "C5B_CLOSED_AND_UNTOUCHED"
        or prepare_report.get("live") != "FORBIDDEN"
    ):
        raise C6AError("C6A prepare report safety-state drift")
    outputs = _output_map(prepare_report)
    expected = {
        *(("spot_trade_candles", instrument) for instrument in SPOT_INSTRUMENTS),
        *(("swap_trade_candles", instrument) for instrument in SWAP_INSTRUMENTS),
        *(("swap_mark_candles", instrument) for instrument in SWAP_INSTRUMENTS),
        ("funding_history", "ALL"),
        ("instrument_metadata", "ALL"),
    }
    if set(outputs) != expected:
        raise C6AError(
            f"C6A canonical output set mismatch: missing={sorted(expected-set(outputs))} "
            f"extra={sorted(set(outputs)-expected)}"
        )
    spot = {
        instrument: validate_trade_candles(
            _verified_rows(outputs[("spot_trade_candles", instrument)]),
            instrument=instrument,
        )
        for instrument in SPOT_INSTRUMENTS
    }
    swap = {
        instrument: validate_trade_candles(
            _verified_rows(outputs[("swap_trade_candles", instrument)]),
            instrument=instrument,
        )
        for instrument in SWAP_INSTRUMENTS
    }
    mark = {
        instrument: validate_mark_candles(
            _verified_rows(outputs[("swap_mark_candles", instrument)]),
            instrument=instrument,
        )
        for instrument in SWAP_INSTRUMENTS
    }
    market = C6AMarket(spot=spot, swap=swap, mark=mark)
    market.validate_alignment()
    funding = validate_funding_records(
        _verified_rows(outputs[("funding_history", "ALL")])
    )
    metadata_rows = _verified_rows(outputs[("instrument_metadata", "ALL")])
    metadata = tuple(MetadataRecord.from_mapping(row) for row in metadata_rows)
    if {row.instrument for row in metadata} != {*SPOT_INSTRUMENTS, *SWAP_INSTRUMENTS}:
        raise C6AError("C6A metadata instrument set mismatch")
    return market, funding, metadata
