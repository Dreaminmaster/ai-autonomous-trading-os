from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path

import pytest

from scripts import c6a_pack_authoritative_evidence_v2 as v2


def transcript(tmp_path: Path, *, source_id: str = "btc-spot") -> dict:
    tmp_path.mkdir(parents=True, exist_ok=True)
    raw = b'{"code":"0","data":[]}'
    path = tmp_path / f"{source_id}.jsonl"
    row = {
        "request_url": "https://www.okx.com/api/v5/market/history-candles?instId=BTC-USDT",
        "response_size": len(raw),
        "response_sha256": hashlib.sha256(raw).hexdigest(),
        "response_base64": base64.b64encode(raw).decode("ascii"),
    }
    path.write_text(json.dumps(row) + "\n", encoding="utf-8")
    return {
        "source_id": source_id,
        "raw_transcript_path": str(path),
        "raw_transcript_size": path.stat().st_size,
        "raw_transcript_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "raw_transcript_page_count": 1,
        "raw_response_bytes_retained": True,
    }


def test_verify_raw_transcript_checks_url_base64_hash_size_and_count(
    tmp_path: Path,
) -> None:
    row = transcript(tmp_path)
    result = v2.verify_raw_transcript(row)
    assert result["status"] == "PASS"
    assert result["page_count"] == 1
    assert result["source_id"] == "btc-spot"

    row["raw_transcript_page_count"] = 2
    with pytest.raises(v2.C6AAuthoritativePackV2Error, match="page-count"):
        v2.verify_raw_transcript(row)


def test_verify_raw_transcript_rejects_tamper_unsafe_id_or_endpoint(
    tmp_path: Path,
) -> None:
    row = transcript(tmp_path)
    path = Path(row["raw_transcript_path"])
    path.write_text("tampered\n", encoding="utf-8")
    with pytest.raises(v2.C6AAuthoritativePackV2Error, match="hash/size"):
        v2.verify_raw_transcript(row)

    row = transcript(tmp_path / "unsafe", source_id="safe")
    row["source_id"] = "../escape"
    with pytest.raises(v2.C6AAuthoritativePackV2Error, match="unsafe"):
        v2.verify_raw_transcript(row)

    row = transcript(tmp_path / "endpoint", source_id="endpoint")
    path = Path(row["raw_transcript_path"])
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["request_url"] = "https://example.com/data"
    path.write_text(json.dumps(payload) + "\n", encoding="utf-8")
    row["raw_transcript_size"] = path.stat().st_size
    row["raw_transcript_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    with pytest.raises(v2.C6AAuthoritativePackV2Error, match="URL drift"):
        v2.verify_raw_transcript(row)
