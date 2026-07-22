#!/usr/bin/env python3
"""Retain exact raw response bytes for a paginated C6A candle capture.

The lower-level public API capture validates and publishes the exact hourly
series.  This authoritative wrapper records every requested URL and exact raw
response body in a base64 JSONL transcript, verifies the lower-level page hashes
against that transcript, and binds the transcript by SHA-256 for final evidence.
"""
from __future__ import annotations

import base64
import io
import json
from pathlib import Path
from typing import Any, Callable

from atos.c6a_evidence import sha256_file
from scripts import c6a_capture_public_api as base


class C6AAuthoritativeApiCaptureError(RuntimeError):
    pass


def capture_series_with_raw_transcript(
    plan: base.CandleApiPlan,
    *,
    destination: Path,
    transcript_path: Path,
    network_opener: Callable[[str], Any] = base._open,
    sleep: Callable[[float], None],
) -> dict[str, Any]:
    if transcript_path.exists():
        raise C6AAuthoritativeApiCaptureError(
            f"refusing to overwrite raw API transcript: {transcript_path}"
        )
    captured: list[dict[str, Any]] = []

    def recording_opener(url: str):
        try:
            with network_opener(url) as response:
                raw = response.read()
        except Exception as exc:
            raise C6AAuthoritativeApiCaptureError(
                f"unable to retain raw OKX API response: {exc}"
            ) from exc
        if not isinstance(raw, (bytes, bytearray)) or not raw:
            raise C6AAuthoritativeApiCaptureError(
                "raw OKX API response must be non-empty bytes"
            )
        payload = bytes(raw)
        captured.append(
            {
                "request_url": url,
                "response_size": len(payload),
                "response_sha256": __import__("hashlib").sha256(payload).hexdigest(),
                "response_base64": base64.b64encode(payload).decode("ascii"),
            }
        )
        return io.BytesIO(payload)

    try:
        report = base.capture_series(
            plan,
            destination=destination,
            opener=recording_opener,
            sleep=sleep,
        )
        pages = report.get("pages")
        if not isinstance(pages, list) or len(pages) != len(captured):
            raise C6AAuthoritativeApiCaptureError(
                "validated page report/raw transcript count mismatch"
            )
        for index, (validated, raw) in enumerate(
            zip(pages, captured, strict=True), start=1
        ):
            if (
                validated.get("request_url") != raw["request_url"]
                or validated.get("response_size") != raw["response_size"]
                or validated.get("response_sha256") != raw["response_sha256"]
            ):
                raise C6AAuthoritativeApiCaptureError(
                    f"validated page/raw transcript mismatch at page {index}"
                )
        transcript_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = transcript_path.with_suffix(transcript_path.suffix + ".part")
        with temporary.open("w", encoding="utf-8") as handle:
            for row in captured:
                handle.write(
                    json.dumps(row, sort_keys=True, separators=(",", ":"))
                )
                handle.write("\n")
        temporary.replace(transcript_path)
        report.update(
            {
                "raw_transcript_path": str(transcript_path),
                "raw_transcript_size": transcript_path.stat().st_size,
                "raw_transcript_sha256": sha256_file(transcript_path),
                "raw_transcript_page_count": len(captured),
                "raw_response_bytes_retained": True,
            }
        )
        return report
    except Exception:
        destination.unlink(missing_ok=True)
        destination.with_suffix(destination.suffix + ".part").unlink(missing_ok=True)
        transcript_path.unlink(missing_ok=True)
        transcript_path.with_suffix(transcript_path.suffix + ".part").unlink(
            missing_ok=True
        )
        raise
