"""Exact HTTP range transport and remote sorted-line search for raw CDXJ."""
from __future__ import annotations

import hashlib
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

from atos.c6a_common_crawl_raw_cdxj_core import (
    CONTENT_RANGE_RE, ClusterBlock, ProbeError, RangeResponse,
    RangeTransport, TextLine, _validate_data_url, parse_cluster_line,
)


class UrllibRangeTransport:
    """Small exact-range HTTP client with no proxy or cookie state."""

    def __init__(self, *, timeout_seconds: float = 30.0, max_bytes: int = 2_097_152):
        self.timeout_seconds = timeout_seconds
        self.max_bytes = max_bytes
        self._opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def read(self, url: str, start: int, end: int) -> RangeResponse:
        _validate_data_url(url)
        if start < 0 or end < start:
            raise ProbeError("invalid HTTP range")
        expected = end - start + 1
        if expected > self.max_bytes:
            raise ProbeError("requested range exceeds frozen maximum")
        request = urllib.request.Request(
            url,
            headers={
                "Range": f"bytes={start}-{end}",
                "Accept-Encoding": "identity",
                "User-Agent": "ATOS-C6A-Raw-CDXJ-Probe/1.0 (+https://github.com/Dreaminmaster/ai-autonomous-trading-os)",
            },
            method="GET",
        )
        try:
            with self._opener.open(request, timeout=self.timeout_seconds) as response:
                body = response.read(self.max_bytes + 1)
                status = int(response.status)
                headers = {str(k).lower(): str(v) for k, v in response.headers.items()}
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise ProbeError(f"range request failed: {type(exc).__name__}: {exc}") from exc
        if len(body) > self.max_bytes:
            raise ProbeError("range response exceeds frozen maximum")
        content_range = headers.get("content-range", "")
        match = CONTENT_RANGE_RE.fullmatch(content_range.strip())
        if status != 206 or match is None:
            raise ProbeError(f"expected HTTP 206 with Content-Range, got {status}")
        observed_start, observed_end, total = map(int, match.groups())
        if (observed_start, observed_end) != (start, end):
            raise ProbeError("Content-Range does not equal requested range")
        if len(body) != expected:
            raise ProbeError("range response byte length mismatch")
        return RangeResponse(url, start, end, total, status, headers, body)


class RecordingRangeReader:
    """Caches exact byte ranges and retains every unique response."""

    def __init__(
        self,
        transport: RangeTransport,
        output: Path,
        *,
        minimum_interval_seconds: float,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        self.transport = transport
        self.output = output
        self.minimum_interval_seconds = minimum_interval_seconds
        self.sleeper = sleeper
        self._cache: dict[tuple[str, int, int], RangeResponse] = {}
        self._last_request_at: float | None = None
        self._sequence = 0
        self.evidence: list[dict[str, Any]] = []

    def read(self, url: str, start: int, end: int, purpose: str) -> RangeResponse:
        key = (url, start, end)
        cached = self._cache.get(key)
        if cached is not None:
            return cached
        if self._last_request_at is not None and self.minimum_interval_seconds > 0:
            elapsed = time.monotonic() - self._last_request_at
            if elapsed < self.minimum_interval_seconds:
                self.sleeper(self.minimum_interval_seconds - elapsed)
        response = self.transport.read(url, start, end)
        self._last_request_at = time.monotonic()
        self._sequence += 1
        relative = f"ranges/range-{self._sequence:04d}.bin"
        path = self.output / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(response.body)
        row = {
            "sequence": self._sequence,
            "purpose": purpose,
            "url": response.url,
            "start": response.start,
            "end": response.end,
            "total_size": response.total_size,
            "status": response.status,
            "content_range": response.headers.get("content-range"),
            "content_type": response.headers.get("content-type"),
            "path": relative,
            "size": len(response.body),
            "sha256": hashlib.sha256(response.body).hexdigest(),
        }
        self.evidence.append(row)
        self._cache[key] = response
        return response


class RemoteSortedLineIndex:
    """Binary-search a remote newline-delimited sorted file with byte ranges."""

    def __init__(
        self,
        reader: RecordingRangeReader,
        url: str,
        *,
        window_bytes: int,
        max_requests: int,
    ) -> None:
        self.reader = reader
        self.url = url
        self.window_bytes = window_bytes
        self.max_requests = max_requests
        self._request_count = 0
        first = self._read(0, 0, "cluster-size-probe")
        self.total_size = first.total_size
        if self.total_size <= 0:
            raise ProbeError("empty remote sorted index")

    def _read(self, start: int, end: int, purpose: str) -> RangeResponse:
        self._request_count += 1
        if self._request_count > self.max_requests:
            raise ProbeError("cluster range-request budget exceeded")
        return self.reader.read(self.url, start, end, purpose)

    def _window(self, center: int, purpose: str) -> tuple[RangeResponse, list[TextLine]]:
        radius = max(1024, self.window_bytes // 2)
        start = max(0, center - radius)
        end = min(self.total_size - 1, center + radius - 1)
        response = self._read(start, end, purpose)
        lines = _complete_lines(response.body, start, self.total_size)
        if not lines:
            raise ProbeError("cluster range contains no complete line")
        return response, lines

    def context_for_predecessor(self, target: str, *, following: int) -> list[ClusterBlock]:
        low = 0
        high = self.total_size
        seen: set[tuple[int, int]] = set()
        for iteration in range(self.max_requests - 2):
            if high - low <= self.window_bytes:
                break
            midpoint = (low + high) // 2
            response, lines = self._window(midpoint, f"cluster-binary-search-{iteration:02d}")
            pair = (response.start, response.end)
            if pair in seen:
                break
            seen.add(pair)
            pivot = next((line for line in lines if line.start >= midpoint), lines[-1])
            block = parse_cluster_line(pivot.text)
            if block.sort_key <= target:
                low = max(low + 1, pivot.end + 1)
            else:
                high = min(high - 1, pivot.start)
        center = min(self.total_size - 1, max(0, (low + high) // 2))
        _, lines = self._window(center, "cluster-final-context")
        parsed: list[tuple[TextLine, ClusterBlock]] = []
        for line in lines:
            try:
                parsed.append((line, parse_cluster_line(line.text)))
            except ProbeError:
                continue
        if not parsed:
            raise ProbeError("no valid cluster lines in final context")
        predecessors = [item for item in parsed if item[1].sort_key <= target]
        if predecessors:
            anchor_line, _ = max(predecessors, key=lambda item: item[1].sort_key)
            anchor_index = next(i for i, item in enumerate(parsed) if item[0] == anchor_line)
        else:
            anchor_index = 0
        start_index = max(0, anchor_index - 1)
        end_index = min(len(parsed), anchor_index + following + 3)
        context = [item[1] for item in parsed[start_index:end_index]]
        if len(context) < 2:
            raise ProbeError("cluster context lacks an upper boundary line")
        return context


class MemoryRangeTransport:
    """Deterministic test transport."""

    def __init__(self, objects: Mapping[str, bytes], failures: Iterable[str] = ()) -> None:
        self.objects = dict(objects)
        self.failures = set(failures)
        self.calls: list[tuple[str, int, int]] = []

    def read(self, url: str, start: int, end: int) -> RangeResponse:
        self.calls.append((url, start, end))
        if url in self.failures:
            raise ProbeError("synthetic transport failure")
        data = self.objects.get(url)
        if data is None:
            raise ProbeError("synthetic object missing")
        if start < 0 or end >= len(data) or end < start:
            raise ProbeError("synthetic range outside object")
        body = data[start : end + 1]
        headers = {
            "content-range": f"bytes {start}-{end}/{len(data)}",
            "content-type": "application/octet-stream",
        }
        return RangeResponse(url, start, end, len(data), 206, headers, body)


def _complete_lines(data: bytes, global_start: int, total_size: int) -> list[TextLine]:
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ProbeError("cluster index is not UTF-8") from exc
    raw_lines = text.splitlines(keepends=True)
    lines: list[TextLine] = []
    cursor = global_start
    for index, raw in enumerate(raw_lines):
        encoded = raw.encode("utf-8")
        line_start = cursor
        line_end = cursor + len(encoded) - 1
        cursor += len(encoded)
        complete_left = global_start == 0 or index > 0
        complete_right = raw.endswith(("\n", "\r")) or cursor >= total_size
        if complete_left and complete_right:
            lines.append(TextLine(line_start, line_end, raw.rstrip("\r\n")))
    return lines
