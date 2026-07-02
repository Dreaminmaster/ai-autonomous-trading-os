"""
OKX Data Cache — local cache with freshness tracking.

Caches market data locally to:
  1. Reduce API calls to OKX
  2. Track data freshness
  3. Reject stale data before trading decisions
  4. Store minimal data — no API keys, no account info

Uses JSON files in runtime/cache/.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from dataclasses import dataclass, asdict
from typing import Any


@dataclass
class CacheEntry:
    key: str
    data: Any
    cached_at: float  # epoch seconds
    source: str  # "okx_public", "csv", etc.

    @property
    def age_seconds(self) -> float:
        return time.time() - self.cached_at

    def is_fresh(self, max_age_seconds: float) -> bool:
        return self.age_seconds <= max_age_seconds

    def to_dict(self) -> dict:
        return {
            "key": self.key,
            "cached_at": self.cached_at,
            "age_seconds": round(self.age_seconds, 1),
            "source": self.source,
            "fresh": self.is_fresh(300),
        }


class OKXDataCache:
    """Simple file-based cache for OKX public market data."""

    def __init__(self, cache_dir: str = "runtime/cache"):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._memory: dict[str, CacheEntry] = {}

    def _key(self, prefix: str, identifier: str) -> str:
        return f"{prefix}:{identifier}"

    def get(self, prefix: str, identifier: str, max_age_seconds: float = 60.0) -> dict | None:
        """Get cached data if fresh. Returns None if stale or missing."""
        key = self._key(prefix, identifier)

        # Check memory first
        if key in self._memory:
            entry = self._memory[key]
            if entry.is_fresh(max_age_seconds):
                return entry.data

        # Check disk
        file_path = self.cache_dir / f"{key.replace(':', '_')}.json"
        if file_path.exists():
            try:
                raw = json.loads(file_path.read_text(encoding="utf-8"))
                entry = CacheEntry(
                    key=key,
                    data=raw.get("data"),
                    cached_at=raw.get("cached_at", 0),
                    source=raw.get("source", "unknown"),
                )
                if entry.is_fresh(max_age_seconds):
                    self._memory[key] = entry
                    return entry.data
            except (json.JSONDecodeError, KeyError):
                pass

        return None

    def put(self, prefix: str, identifier: str, data: Any, source: str = "okx_public") -> None:
        """Cache data with timestamp."""
        key = self._key(prefix, identifier)
        entry = CacheEntry(key=key, data=data, cached_at=time.time(), source=source)

        self._memory[key] = entry

        # Write to disk
        file_path = self.cache_dir / f"{key.replace(':', '_')}.json"
        file_path.write_text(json.dumps({
            "key": key,
            "cached_at": entry.cached_at,
            "source": source,
            "data": data,
        }, ensure_ascii=False, default=str))

    def invalidate(self, prefix: str | None = None) -> int:
        """Clear cached entries. Returns count cleared."""
        count = 0
        if prefix:
            keys_to_remove = [k for k in self._memory if k.startswith(f"{prefix}:")]
            for k in keys_to_remove:
                del self._memory[k]
                count += 1
                file_path = self.cache_dir / f"{k.replace(':', '_')}.json"
                file_path.unlink(missing_ok=True)
        else:
            count = len(self._memory)
            self._memory.clear()
            for f in self.cache_dir.glob("*.json"):
                f.unlink(missing_ok=True)
                count += 1
        return count

    def stats(self) -> dict:
        """Cache statistics."""
        entries = list(self._memory.values())
        if not entries:
            return {"entries": 0}
        ages = [e.age_seconds for e in entries]
        return {
            "entries": len(entries),
            "oldest_age_seconds": round(max(ages), 1),
            "newest_age_seconds": round(min(ages), 1),
            "mean_age_seconds": round(sum(ages) / len(ages), 1),
        }
