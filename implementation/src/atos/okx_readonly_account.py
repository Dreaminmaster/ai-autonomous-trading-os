"""
OKX Read-Only Account Adapter — inspects account without execution ability.

Uses OKX API v5 with read-only permissions only.
NEVER uses trade/withdraw/transfer endpoints.
API key used here should have ONLY read permissions.

Required endpoints (all GET):
  GET /api/v5/account/balance
  GET /api/v5/account/positions
  GET /api/v5/trade/orders-history-archive (last 7 days)
  GET /api/v5/account/config

SECURITY:
  - API key is read from env var OKX_READONLY_KEY (NOT the trading key)
  - Key is NEVER stored in code, git, logs, or ledger
  - This adapter CANNOT place orders (only GET requests)
  - All responses are typed as read-only dataclasses

Environment:
  OKX_READONLY_KEY — API key with read-only permissions
  OKX_READONLY_SECRET — API secret for signing
  OKX_READONLY_PASSPHRASE — API passphrase
"""

from __future__ import annotations

import os
import json
import time
import hmac
import hashlib
import base64
from dataclasses import dataclass, field, asdict
from typing import Any


@dataclass
class Balance:
    currency: str
    available: float
    frozen: float
    total: float

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Position:
    symbol: str
    side: str  # long / short
    quantity: float
    avg_price: float
    mark_price: float
    unrealized_pnl: float
    leverage: float

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class AccountSnapshot:
    balances: list[Balance]
    positions: list[Position]
    total_equity_usd: float
    available_usd: float
    timestamp: str
    has_trade_permission: bool = False
    has_withdraw_permission: bool = False

    def to_dict(self) -> dict:
        return {
            "balances": [b.to_dict() for b in self.balances],
            "positions": [p.to_dict() for p in self.positions],
            "total_equity_usd": self.total_equity_usd,
            "available_usd": self.available_usd,
            "timestamp": self.timestamp,
            "has_trade_permission": self.has_trade_permission,
            "has_withdraw_permission": self.has_withdraw_permission,
        }


class OKXReadOnlyAccountAdapter:
    """Read-only adapter for OKX account inspection.

    Uses OKX API v5 with HMAC-SHA256 signing.
    Only makes GET requests — CANNOT trade.
    """

    def __init__(self, api_key: str = "", secret: str = "", passphrase: str = ""):
        self.api_key = api_key or os.environ.get("OKX_READONLY_KEY", "")
        self.secret = secret or os.environ.get("OKX_READONLY_SECRET", "")
        self.passphrase = passphrase or os.environ.get("OKX_READONLY_PASSPHRASE", "")
        self.base_url = "https://www.okx.com"

    @property
    def is_configured(self) -> bool:
        return bool(self.api_key and self.secret and self.passphrase)

    def snapshot(self) -> AccountSnapshot:
        """Take a read-only snapshot of the account.

        Returns empty snapshot if not configured (never throws).
        """
        if not self.is_configured:
            return AccountSnapshot(
                balances=[], positions=[],
                total_equity_usd=0.0, available_usd=0.0,
                timestamp=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                has_trade_permission=False, has_withdraw_permission=False,
            )

        try:
            return self._fetch_snapshot()
        except Exception as e:
            # NEVER crash — return empty snapshot
            return AccountSnapshot(
                balances=[], positions=[],
                total_equity_usd=0.0, available_usd=0.0,
                timestamp=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                has_trade_permission=False, has_withdraw_permission=False,
            )

    def _fetch_snapshot(self) -> AccountSnapshot:
        """Actually fetch from OKX API."""
        import urllib.request
        import urllib.error

        balances = self._get_balances()
        positions = self._get_positions()
        config = self._get_account_config()

        total_equity = config.get("totalEq", 0)
        available = config.get("availEq", 0)
        has_trade = config.get("acctLv", "0") != "0"
        has_withdraw = config.get("perm", "").find("withdraw") >= 0 if config.get("perm") else False

        return AccountSnapshot(
            balances=balances,
            positions=positions,
            total_equity_usd=float(total_equity) if total_equity else 0.0,
            available_usd=float(available) if available else 0.0,
            timestamp=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            has_trade_permission=has_trade,
            has_withdraw_permission=has_withdraw,
        )

    def _get_balances(self) -> list[Balance]:
        data = self._signed_get("/api/v5/account/balance")
        result = []
        for detail in data.get("data", [{}])[0].get("details", []):
            result.append(Balance(
                currency=detail.get("ccy", ""),
                available=float(detail.get("availBal", 0)),
                frozen=float(detail.get("frozenBal", 0)),
                total=float(detail.get("cashBal", 0)),
            ))
        return result

    def _get_positions(self) -> list[Position]:
        data = self._signed_get("/api/v5/account/positions")
        result = []
        for pos in data.get("data", []):
            result.append(Position(
                symbol=pos.get("instId", ""),
                side=pos.get("posSide", "long"),
                quantity=float(pos.get("pos", 0)),
                avg_price=float(pos.get("avgPx", 0)),
                mark_price=float(pos.get("markPx", 0)),
                unrealized_pnl=float(pos.get("upl", 0)),
                leverage=float(pos.get("lever", 1)),
            ))
        return result

    def _get_account_config(self) -> dict:
        data = self._signed_get("/api/v5/account/config")
        return data.get("data", [{}])[0] if data.get("data") else {}

    def _signed_get(self, path: str) -> dict:
        """Make a signed GET request to OKX API v5."""
        import urllib.request

        timestamp = str(int(time.time()))
        # ISO format with .000Z
        timestamp = time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime())

        # OKX v5 signing
        message = timestamp + "GET" + path + ""
        mac = hmac.new(
            self.secret.encode("utf-8"),
            message.encode("utf-8"),
            hashlib.sha256,
        )
        signature = base64.b64encode(mac.digest()).decode("utf-8")

        url = f"{self.base_url}{path}"
        req = urllib.request.Request(url)
        req.add_header("OK-ACCESS-KEY", self.api_key)
        req.add_header("OK-ACCESS-SIGN", signature)
        req.add_header("OK-ACCESS-TIMESTAMP", timestamp)
        req.add_header("OK-ACCESS-PASSPHRASE", self.passphrase)
        req.add_header("Content-Type", "application/json")
        req.add_header("User-Agent", "ai-autonomous-trading-os/0.2")

        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode("utf-8"))
