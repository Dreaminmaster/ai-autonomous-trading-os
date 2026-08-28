"""Fail-closed, account-free OKX public market data adapter.

This adapter is the only network dependency of the unified Paper/Shadow
runtime. It permits a small allowlist of public HTTPS GET endpoints, rejects
redirect drift and authentication material, and only exposes confirmed,
strictly ordered candles to strategies.
"""

from __future__ import annotations

import json
import math
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from atos.domain import Candle


class PublicMarketDataError(RuntimeError):
    """The public response cannot be proven safe and usable."""


OFFICIAL_API_HOSTS = frozenset(
    {"www.okx.com", "openapi.okx.com", "us.okx.com", "eea.okx.com"}
)
PUBLIC_PATH_KEYS = {
    "/api/v5/market/ticker": frozenset({"instId"}),
    "/api/v5/market/candles": frozenset({"instId", "bar", "limit"}),
    "/api/v5/market/trades": frozenset({"instId", "limit"}),
    "/api/v5/market/books": frozenset({"instId", "sz"}),
    "/api/v5/public/instruments": frozenset({"instType"}),
    "/api/v5/public/funding-rate": frozenset({"instId"}),
    "/api/v5/public/open-interest": frozenset({"instType", "instId"}),
}
PROHIBITED_KEYS = frozenset(
    {
        "apikey",
        "api_key",
        "secret",
        "passphrase",
        "signature",
        "sign",
        "token",
        "authorization",
    }
)
MAX_RESPONSE_BYTES = 8 * 1024 * 1024
ALLOWED_BARS = frozenset(
    {"1m", "3m", "5m", "15m", "30m", "1H", "2H", "4H", "6H", "12H", "1D"}
)


@dataclass(frozen=True)
class MarketSnapshot:
    symbol: str
    ticker: dict[str, Any]
    candles: list[Candle]
    orderbook: dict[str, Any]

    @staticmethod
    def _timestamp(value: Any, field_name: str) -> int:
        try:
            timestamp = int(value)
        except (TypeError, ValueError) as exc:
            raise PublicMarketDataError(f"{field_name} timestamp is invalid") from exc
        if timestamp <= 0:
            raise PublicMarketDataError(f"{field_name} timestamp is invalid")
        return timestamp

    def validate(self, expected_symbol: str) -> None:
        """Validate cross-endpoint identity and deterministic book invariants."""
        if self.symbol != expected_symbol:
            raise PublicMarketDataError("snapshot symbol identity drift")
        try:
            ticker_row = self.ticker["data"][0]
            book_row = self.orderbook["data"][0]
        except (KeyError, IndexError, TypeError) as exc:
            raise PublicMarketDataError("snapshot response shape drift") from exc
        if not isinstance(ticker_row, dict) or not isinstance(book_row, dict):
            raise PublicMarketDataError("snapshot response row shape drift")
        if ticker_row.get("instId") != expected_symbol:
            raise PublicMarketDataError("ticker instrument identity drift")
        self._timestamp(ticker_row.get("ts"), "ticker")
        self._timestamp(book_row.get("ts"), "orderbook")
        _ = self.mark_price

        sides: dict[str, list[float]] = {}
        for side in ("bids", "asks"):
            rows = book_row.get(side)
            if not isinstance(rows, list) or not rows:
                raise PublicMarketDataError(f"orderbook {side} is empty or malformed")
            prices: list[float] = []
            seen_prices: set[float] = set()
            for row in rows:
                if not isinstance(row, list) or len(row) < 2:
                    raise PublicMarketDataError("orderbook level shape drift")
                try:
                    price = float(row[0])
                    size = float(row[1])
                except (TypeError, ValueError) as exc:
                    raise PublicMarketDataError(
                        "orderbook level is not numeric"
                    ) from exc
                if (
                    not math.isfinite(price)
                    or not math.isfinite(size)
                    or price <= 0
                    or size < 0
                    or price in seen_prices
                ):
                    raise PublicMarketDataError("orderbook level invariant failed")
                seen_prices.add(price)
                prices.append(price)
            sides[side] = prices
        if sides["bids"] != sorted(sides["bids"], reverse=True):
            raise PublicMarketDataError("orderbook bids are not descending")
        if sides["asks"] != sorted(sides["asks"]):
            raise PublicMarketDataError("orderbook asks are not ascending")
        if sides["bids"][0] > sides["asks"][0]:
            raise PublicMarketDataError("orderbook is crossed")

    @property
    def mark_price(self) -> float:
        try:
            value = float(self.ticker["data"][0]["last"])
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise PublicMarketDataError(
                "ticker does not contain a valid last price"
            ) from exc
        if not math.isfinite(value) or value <= 0:
            raise PublicMarketDataError("ticker last price must be positive and finite")
        return value

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "mark_price": self.mark_price,
            "ticker": self.ticker,
            "candles": [c.to_dict() for c in self.candles],
            "orderbook": self.orderbook,
        }


class PublicMarketAdapter:
    """Strict public-only REST adapter; it has no private endpoint methods."""

    def __init__(
        self,
        base_url: str = "https://www.okx.com",
        *,
        opener: Callable[..., Any] | None = None,
        timeout_seconds: float = 10.0,
    ):
        parsed = urllib.parse.urlparse(base_url.rstrip("/"))
        if (
            parsed.scheme != "https"
            or parsed.hostname not in OFFICIAL_API_HOSTS
            or parsed.username
            or parsed.password
            or parsed.path not in {"", "/"}
            or parsed.query
            or parsed.fragment
        ):
            raise PublicMarketDataError("base URL must be an official OKX HTTPS origin")
        self.base_url = f"https://{parsed.hostname}"
        self._open = opener or urllib.request.urlopen
        self.timeout_seconds = float(timeout_seconds)

    @staticmethod
    def _validate_instrument(inst_id: str) -> None:
        if (
            not isinstance(inst_id, str)
            or not inst_id
            or len(inst_id) > 64
            or any(ch not in "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-" for ch in inst_id)
        ):
            raise PublicMarketDataError("invalid OKX public instrument ID")

    def _build_url(self, path: str, params: dict[str, Any]) -> str:
        if path not in PUBLIC_PATH_KEYS or set(params) != set(PUBLIC_PATH_KEYS[path]):
            raise PublicMarketDataError("public endpoint or query contract drift")
        lowered = {str(key).lower() for key in params}
        if lowered & PROHIBITED_KEYS:
            raise PublicMarketDataError("credential material is forbidden")
        if "instId" in params:
            self._validate_instrument(str(params["instId"]))
        query = urllib.parse.urlencode(params)
        return f"{self.base_url}{path}?{query}"

    def _get(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        url = self._build_url(path, params)
        req = urllib.request.Request(
            url,
            method="GET",
            headers={
                "Accept": "application/json",
                "User-Agent": "ai-autonomous-trading-os/public-runtime-v1",
            },
        )
        try:
            with self._open(req, timeout=self.timeout_seconds) as resp:
                final_url = resp.geturl()
                if final_url != url:
                    raise PublicMarketDataError("public request redirect drift")
                raw = resp.read(MAX_RESPONSE_BYTES + 1)
        except PublicMarketDataError:
            raise
        except Exception as exc:
            raise PublicMarketDataError(
                f"public OKX request failed: {type(exc).__name__}"
            ) from exc
        if len(raw) > MAX_RESPONSE_BYTES:
            raise PublicMarketDataError("public response exceeds size limit")
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise PublicMarketDataError("public response is not valid JSON") from exc
        if (
            not isinstance(payload, dict)
            or payload.get("code") != "0"
            or not isinstance(payload.get("data"), list)
        ):
            raise PublicMarketDataError(
                "OKX public response reports failure or malformed data"
            )
        return payload

    def ticker(self, inst_id: str) -> dict[str, Any]:
        return self._get("/api/v5/market/ticker", {"instId": inst_id})

    def candles_raw(
        self, inst_id: str, bar: str = "1m", limit: int = 100
    ) -> dict[str, Any]:
        if bar not in ALLOWED_BARS or type(limit) is not int or not 1 <= limit <= 300:
            raise PublicMarketDataError("invalid public candle bar or limit")
        return self._get(
            "/api/v5/market/candles",
            {"instId": inst_id, "bar": bar, "limit": limit},
        )

    def trades(self, inst_id: str, limit: int = 100) -> dict[str, Any]:
        if type(limit) is not int or not 1 <= limit <= 500:
            raise PublicMarketDataError("invalid public trade limit")
        return self._get("/api/v5/market/trades", {"instId": inst_id, "limit": limit})

    def orderbook(self, inst_id: str, depth: int = 20) -> dict[str, Any]:
        if type(depth) is not int or not 1 <= depth <= 400:
            raise PublicMarketDataError("invalid public orderbook depth")
        return self._get("/api/v5/market/books", {"instId": inst_id, "sz": depth})

    def instruments(self, inst_type: str = "SPOT") -> dict[str, Any]:
        if inst_type not in {"SPOT", "MARGIN", "SWAP", "FUTURES", "OPTION"}:
            raise PublicMarketDataError("invalid public instrument type")
        return self._get("/api/v5/public/instruments", {"instType": inst_type})

    def funding_rate(self, inst_id: str) -> dict[str, Any]:
        return self._get("/api/v5/public/funding-rate", {"instId": inst_id})

    def open_interest(self, inst_id: str, inst_type: str = "SWAP") -> dict[str, Any]:
        if inst_type not in {"SWAP", "FUTURES", "OPTION"}:
            raise PublicMarketDataError("invalid open-interest instrument type")
        return self._get(
            "/api/v5/public/open-interest",
            {"instType": inst_type, "instId": inst_id},
        )

    def candles(self, inst_id: str, bar: str = "1m", limit: int = 100) -> list[Candle]:
        rows = self.candles_raw(inst_id, bar=bar, limit=limit)["data"]
        if not rows:
            raise PublicMarketDataError("public candle response is empty")
        parsed: list[tuple[int, Candle]] = []
        seen: set[int] = set()
        previous_raw_ts: int | None = None
        for row in rows:
            if not isinstance(row, list) or len(row) < 9:
                raise PublicMarketDataError("public candle row shape drift")
            try:
                timestamp = int(row[0])
                values = [float(row[index]) for index in range(1, 6)]
            except (TypeError, ValueError) as exc:
                raise PublicMarketDataError("public candle row is not numeric") from exc
            if timestamp <= 0 or timestamp in seen:
                raise PublicMarketDataError(
                    "public candle timestamps are invalid or duplicate"
                )
            if previous_raw_ts is not None and timestamp >= previous_raw_ts:
                raise PublicMarketDataError(
                    "public candles are not reverse chronological"
                )
            previous_raw_ts = timestamp
            seen.add(timestamp)
            if row[8] not in {"0", "1"}:
                raise PublicMarketDataError("public candle confirmation flag drift")
            if row[8] == "0":
                continue
            open_, high, low, close, volume = values
            if (
                not all(math.isfinite(value) for value in values)
                or min(open_, high, low, close) <= 0
                or volume < 0
                or high < max(open_, close)
                or low > min(open_, close)
                or high < low
            ):
                raise PublicMarketDataError("public candle OHLCV invariant failed")
            parsed.append(
                (
                    timestamp,
                    Candle(
                        open=open_,
                        high=high,
                        low=low,
                        close=close,
                        volume=volume,
                        ts=datetime.fromtimestamp(timestamp / 1000, tz=UTC)
                        .isoformat()
                        .replace("+00:00", "Z"),
                    ),
                )
            )
        if not parsed:
            raise PublicMarketDataError("no confirmed public candle is available")
        parsed.reverse()
        return [candle for _, candle in parsed]

    def snapshot(
        self,
        inst_id: str,
        *,
        bar: str = "1m",
        limit: int = 100,
        depth: int = 20,
    ) -> MarketSnapshot:
        snapshot = MarketSnapshot(
            symbol=inst_id,
            ticker=self.ticker(inst_id),
            candles=self.candles(inst_id, bar=bar, limit=limit),
            orderbook=self.orderbook(inst_id, depth=depth),
        )
        snapshot.validate(inst_id)
        return snapshot
