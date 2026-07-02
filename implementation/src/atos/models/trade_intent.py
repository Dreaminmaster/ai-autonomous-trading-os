"""
TradeIntent — the core intermediate representation of the AI Trading OS.

Every AI decision MUST produce a TradeIntent.
Every TradeIntent MUST pass schema validation before execution.
Any invalid TradeIntent defaults to HOLD.

This module provides:
  1. Pydantic model (runtime validation, Python-native)
  2. JSON Schema validator (language-agnostic, cross-check)
  3. Safe fallback: to_hold() converts any invalid intent to HOLD
  4. IntentLogger: records every intent with its validation result

Hard rules:
  - HOLD is always valid
  - BUY/SELL require thesis, evidence, stop_loss, take_profit, invalidation_conditions
  - symbol must be in the allowed list (checked at runtime, not in schema)
  - position_size_pct capped by risk policy
  - confidence 0-1
  - action is strict enum
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, asdict, field
from enum import StrEnum
from pathlib import Path
from typing import Any

from jsonschema import validate as jsonschema_validate, ValidationError as JsonSchemaError

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────
# Enums & Constants
# ─────────────────────────────────────────────────────────────────────

class TradeAction(StrEnum):
    BUY = "BUY"
    SELL = "SELL"
    REDUCE = "REDUCE"
    CLOSE = "CLOSE"
    HOLD = "HOLD"


TRADING_ACTIONS = {TradeAction.BUY, TradeAction.SELL, TradeAction.REDUCE, TradeAction.CLOSE}
SAFE_ACTION = TradeAction.HOLD

SCHEMA_VERSION = "trade_intent.v1"
JSON_SCHEMA_PATH = Path(__file__).resolve().parents[3] / "schemas" / "trade_intent.schema.json"


# ─────────────────────────────────────────────────────────────────────
# Pydantic-style validation (implemented as dataclass + validate method)
# ─────────────────────────────────────────────────────────────────────

@dataclass
class TradeIntent:
    """A structured trading decision from the AI provider.

    This is NOT a suggestion — it is the formal output of the AI decision layer.
    It MUST pass both Pydantic and JSON Schema validation before execution.
    """

    schema_version: str = SCHEMA_VERSION
    action: str = TradeAction.HOLD.value
    symbol: str = ""
    market_type: str = "paper_spot"
    confidence: float = 0.0
    thesis: str = ""
    evidence: list[str] = field(default_factory=list)
    selected_strategy_ids: list[str] = field(default_factory=list)
    position_size_pct: float = 0.0
    stop_loss_pct: float = 0.0
    take_profit_pct: float = 0.0
    max_holding_minutes: int = 0
    invalidation_conditions: list[str] = field(default_factory=list)
    risk_notes: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TradeIntent:
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})

    @classmethod
    def hold(cls, reason: str = "safe default", symbol: str = "BTC/USDT:USDT") -> TradeIntent:
        """Create a safe HOLD intent."""
        return cls(
            schema_version=SCHEMA_VERSION,
            action=TradeAction.HOLD.value,
            symbol=symbol,
            market_type="paper_spot",
            confidence=0.0,
            thesis=f"No trade: {reason}",
            evidence=[reason],
            selected_strategy_ids=[],
            position_size_pct=0.0,
            stop_loss_pct=0.0,
            take_profit_pct=0.0,
            max_holding_minutes=0,
            invalidation_conditions=["No active thesis"],
            risk_notes=reason,
            metadata={"safe_default": True, "reason": reason},
        )

    def validate(self, allowed_symbols: set[str] | None = None, max_position_pct: float = 100.0) -> ValidationResult:
        """Validate this TradeIntent against all rules.

        Returns ValidationResult with:
          - is_valid: bool
          - errors: list of error messages
          - corrected_intent: TradeIntent (same object if valid, HOLD if invalid)
        """
        errors: list[str] = []

        # ── Schema version ──────────────────────────────────────
        if self.schema_version != SCHEMA_VERSION:
            errors.append(f"schema_version must be '{SCHEMA_VERSION}', got '{self.schema_version}'")

        # ── Action ──────────────────────────────────────────────
        if self.action not in TradeAction.__members__.values():
            errors.append(f"action must be one of {[a.value for a in TradeAction]}, got '{self.action}'")

        # ── Market type ─────────────────────────────────────────
        if self.market_type not in ("spot", "paper_spot"):
            errors.append(f"market_type must be 'spot' or 'paper_spot', got '{self.market_type}'")

        # ── Confidence ──────────────────────────────────────────
        if not (0.0 <= self.confidence <= 1.0):
            errors.append(f"confidence must be in [0, 1], got {self.confidence}")

        # ── Position size ───────────────────────────────────────
        if self.position_size_pct < 0.0:
            errors.append(f"position_size_pct must be >= 0, got {self.position_size_pct}")
        if self.position_size_pct > max_position_pct:
            errors.append(f"position_size_pct ({self.position_size_pct}) exceeds max ({max_position_pct})")

        # ── Stop loss / Take profit ─────────────────────────────
        if self.stop_loss_pct < 0.0:
            errors.append(f"stop_loss_pct must be >= 0, got {self.stop_loss_pct}")
        if self.take_profit_pct < 0.0:
            errors.append(f"take_profit_pct must be >= 0, got {self.take_profit_pct}")

        # ── Max holding ─────────────────────────────────────────
        if self.max_holding_minutes < 0 or self.max_holding_minutes > 43200:
            errors.append(f"max_holding_minutes must be in [0, 43200], got {self.max_holding_minutes}")

        # ── Symbol allowlist ────────────────────────────────────
        if allowed_symbols and self.symbol and self.symbol not in allowed_symbols:
            errors.append(f"symbol '{self.symbol}' not in allowed list")

        # ── Non-HOLD trading action requirements ────────────────
        if self.action in {a.value for a in TRADING_ACTIONS}:
            if not self.thesis or len(self.thesis.strip()) < 10:
                errors.append(f"{self.action} requires a thesis of at least 10 characters")
            if not self.evidence:
                errors.append(f"{self.action} requires at least one piece of evidence")
            if self.stop_loss_pct <= 0.0:
                errors.append(f"{self.action} requires stop_loss_pct > 0")
            if self.take_profit_pct <= 0.0:
                errors.append(f"{self.action} requires take_profit_pct > 0")
            if not self.invalidation_conditions:
                errors.append(f"{self.action} requires at least one invalidation condition")

        # ── Schema version specific checks ──────────────────────
        if self.schema_version == SCHEMA_VERSION:
            try:
                _validate_against_json_schema(self.to_dict())
            except JsonSchemaError as e:
                errors.append(f"JSON schema validation failed: {e.message}")

        # ── Result ──────────────────────────────────────────────
        if errors:
            logger.warning(f"TradeIntent validation failed: {errors}")
            hold = TradeIntent.hold(reason=f"validation failed: {'; '.join(errors)}", symbol=self.symbol)
            return ValidationResult(is_valid=False, errors=errors, corrected_intent=hold)

        return ValidationResult(is_valid=True, errors=[], corrected_intent=self)


@dataclass
class ValidationResult:
    """Result of TradeIntent validation.

    If is_valid=False, corrected_intent is always a safe HOLD intent.
    """
    is_valid: bool
    errors: list[str]
    corrected_intent: TradeIntent

    def to_dict(self) -> dict[str, Any]:
        return {
            "is_valid": self.is_valid,
            "errors": self.errors,
            "corrected_action": self.corrected_intent.action,
        }


# ─────────────────────────────────────────────────────────────────────
# JSON Schema Validation (language-agnostic cross-check)
# ─────────────────────────────────────────────────────────────────────

def _validate_against_json_schema(intent_dict: dict[str, Any]) -> None:
    """Validate intent dict against trade_intent.schema.json.

    Raises jsonschema.ValidationError on failure.
    """
    if JSON_SCHEMA_PATH.exists():
        schema = json.loads(JSON_SCHEMA_PATH.read_text(encoding="utf-8"))
        jsonschema_validate(instance=intent_dict, schema=schema)


def validate_json_schema(intent_dict: dict[str, Any]) -> tuple[bool, str]:
    """Public API: validate intent dict against JSON schema.

    Returns (is_valid, error_message).
    """
    try:
        _validate_against_json_schema(intent_dict)
        return True, ""
    except JsonSchemaError as e:
        return False, e.message
    except Exception as e:
        return False, str(e)


# ─────────────────────────────────────────────────────────────────────
# Intent Logger
# ─────────────────────────────────────────────────────────────────────

class IntentLogger:
    """Records every TradeIntent to the ledger with validation results.

    This is used by the Freqtrade strategy wrapper to log each decision,
    ensuring a complete audit trail.
    """

    def __init__(self, ledger=None):
        self.ledger = ledger
        self.log: list[dict[str, Any]] = []

    def record(self, intent: TradeIntent, validation: ValidationResult, symbol: str, timestamp: str = "") -> None:
        """Log an intent + validation to ledger and in-memory log."""
        entry = {
            "symbol": symbol,
            "action": intent.action,
            "confidence": intent.confidence,
            "thesis": intent.thesis,
            "is_valid": validation.is_valid,
            "errors": validation.errors,
            "final_action": validation.corrected_intent.action,
            "timestamp": timestamp,
        }
        self.log.append(entry)

        if self.ledger:
            try:
                self.ledger.record("trade_intent_validation", entry)
            except Exception as e:
                logger.warning(f"Failed to write intent to ledger: {e}")

    def recent(self, limit: int = 20) -> list[dict[str, Any]]:
        return self.log[-limit:]

    def summary(self) -> dict[str, Any]:
        if not self.log:
            return {"total": 0}
        actions = [e["action"] for e in self.log]
        hold_count = actions.count("HOLD")
        trade_count = len(actions) - hold_count
        valid_count = sum(1 for e in self.log if e["is_valid"])
        return {
            "total": len(self.log),
            "trading_actions": trade_count,
            "hold_actions": hold_count,
            "valid_intents": valid_count,
            "invalid_intents": len(self.log) - valid_count,
        }
