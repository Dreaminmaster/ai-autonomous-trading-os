"""
Risk Supervisor — deterministic safety gate. Cannot be bypassed by AI.

Every TradeIntent MUST pass this supervisor before execution.
This is NOT configurable by the AI provider.

Hard-coded safety gates:
  1. Kill switch (file or flag)
  2. Emergency stop
  3. Mode guard (live requires explicit enable)
  4. Symbol allowlist
  5. Confidence threshold
  6. Position size limits
  7. Daily trade count limit
  8. Duplicate signal cooldown
  9. Max drawdown guard
  10. Required field validation (thesis, evidence, stop_loss, take_profit, invalidation)

Backward compatible with old RiskEngine.evaluate() API.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from atos.core import Action, RunMode
from atos.domain import RiskDecision


class RiskEngine:
    """Deterministic risk engine. AI CANNOT bypass this.

    Enhanced with:
      - Daily trade limits
      - Duplicate signal cooldown
      - Max drawdown pause
      - Quick pre-check method
      - Stats tracking
    """

    def __init__(self, policy: dict[str, Any]):
        self.policy = policy
        self._recent_signals: list[dict] = []
        self._daily_trades: dict[str, int] = {}
        self._today = time.strftime("%Y-%m-%d")

    # ── Main entry point ────────────────────────────────────────

    def evaluate(self, intent: dict[str, Any], state: dict[str, Any] | None = None) -> RiskDecision:
        """Evaluate a TradeIntent against ALL risk rules. Returns RiskDecision."""
        state = state or {}
        reasons: list[str] = []
        checks: dict[str, Any] = {}

        mode = state.get("mode", self.policy.get("mode", RunMode.PAPER.value))
        action = intent.get("action", Action.HOLD.value)
        symbol = intent.get("symbol", "")
        confidence = float(intent.get("confidence", 0.0) or 0.0)
        position_size_pct = float(intent.get("position_size_pct", 0.0) or 0.0)
        selected_strategies = intent.get("selected_strategy_ids", [])

        # ── Gate 1: Kill switch ─────────────────────────────────
        flag_path = self.policy.get("kill_switch", {}).get("flag_path")
        ks_active = bool(state.get("kill_switch_active")) or bool(flag_path and Path(flag_path).exists())
        if not ks_active:
            ks_active = Path("runtime/kill_switch.flag").exists()
        checks["kill_switch"] = ks_active
        if ks_active:
            return RiskDecision("risk_decision.v1", "KILL_SWITCH_ACTIVE", ["kill_switch_active"], 1.0, checks)

        # ── Gate 2: Emergency stop ──────────────────────────────
        if state.get("emergency_stop"):
            return RiskDecision("risk_decision.v1", "PAUSED", ["emergency_stop_activated"], 1.0, checks)

        # ── Gate 3: Mode guard ──────────────────────────────────
        if mode == RunMode.LIVE.value and not state.get("external_execution_enabled", False):
            reasons.append("external_execution_not_enabled")

        # ── Gate 4: Symbol allowlist ────────────────────────────
        allowed_symbols = set(self.policy.get("allowed_symbols", []))
        checks["symbol_allowed"] = symbol in allowed_symbols or action == Action.HOLD.value
        if action != Action.HOLD.value and symbol not in allowed_symbols:
            reasons.append(f"symbol_not_allowed: {symbol}")

        # ── Gate 5: Confidence threshold ────────────────────────
        min_conf = float(self.policy.get("ai_output_limits", {}).get("min_confidence_for_trade", 0.60))
        checks["confidence_ok"] = action == Action.HOLD.value or confidence >= min_conf
        if action != Action.HOLD.value and confidence < min_conf:
            reasons.append(f"confidence_below_threshold: {confidence:.2f} < {min_conf}")

        # ── Gate 6: Position size limits ────────────────────────
        max_pos = float(self.policy.get("position_limits", {}).get("max_position_pct_per_trade", 10.0))
        checks["position_size_ok"] = position_size_pct <= max_pos
        if position_size_pct > max_pos:
            reasons.append(f"position_size_exceeds_limit: {position_size_pct} > {max_pos}")

        # ── Gate 7: Daily trade limit ───────────────────────────
        max_daily = int(self.policy.get("trade_limits", {}).get("max_trades_per_day", 20))
        today = time.strftime("%Y-%m-%d")
        if today != self._today:
            self._daily_trades.clear()
            self._today = today
        current_count = self._daily_trades.get(today, 0)
        checks["daily_limit_ok"] = current_count < max_daily
        if action != Action.HOLD.value and current_count >= max_daily:
            reasons.append(f"daily_trade_limit_reached: {current_count}/{max_daily}")

        # ── Gate 8: Duplicate signal cooldown ───────────────────
        cooldown_sec = float(self.policy.get("trade_limits", {}).get("cooldown_seconds", 300))
        now = time.time()
        for sig in self._recent_signals:
            if sig["symbol"] == symbol and set(sig.get("strategy_ids", [])) & set(selected_strategies):
                if now - sig.get("timestamp", 0) < cooldown_sec:
                    reasons.append(f"duplicate_signal_cooldown: {symbol}")
                    break
        checks["duplicate_guard_ok"] = not any("duplicate" in r for r in reasons)

        # ── Gate 9: Max drawdown guard ──────────────────────────
        max_dd = float(self.policy.get("risk_limits", {}).get("max_drawdown_pct", 20.0))
        current_dd = float(state.get("current_drawdown_pct", 0.0))
        checks["drawdown_ok"] = current_dd < max_dd
        if current_dd >= max_dd:
            return RiskDecision("risk_decision.v1", "PAUSED",
                                [f"max_drawdown_exceeded: {current_dd:.1f}% >= {max_dd}%"], 1.0, checks)

        # ── Gate 10: Required fields for trading actions ────────
        if action != Action.HOLD.value:
            if not intent.get("thesis"):
                reasons.append("missing_thesis")
            if not intent.get("evidence"):
                reasons.append("missing_evidence")
            if float(intent.get("stop_loss_pct", 0.0) or 0.0) <= 0:
                reasons.append("missing_stop_loss")
            if float(intent.get("take_profit_pct", 0.0) or 0.0) <= 0:
                reasons.append("missing_take_profit")
            if not intent.get("invalidation_conditions"):
                reasons.append("missing_invalidation_conditions")

        # ── Decision ────────────────────────────────────────────
        if action == Action.HOLD.value and not reasons:
            return RiskDecision("risk_decision.v1", "APPROVED", ["hold_is_safe_default"], 0.0, checks)

        if reasons:
            score = min(1.0, 0.3 + 0.1 * len(reasons))
            return RiskDecision("risk_decision.v1", "REJECTED", reasons, score, checks)

        # Record signal for duplicate guard
        self._daily_trades[today] = current_count + 1
        self._recent_signals.append({
            "symbol": symbol,
            "strategy_ids": selected_strategies,
            "timestamp": now,
        })
        self._recent_signals = [s for s in self._recent_signals if now - s["timestamp"] < 3600]

        return RiskDecision("risk_decision.v1", "APPROVED", ["all_checks_passed"], 0.1, checks)

    # ── Quick pre-check ────────────────────────────────────────

    def quick_check(self, intent: dict, allowed: set[str] | None = None) -> tuple[bool, str]:
        """Fast pre-check without state modification. Returns (safe, reason)."""
        action = intent.get("action", "HOLD")
        if action == "HOLD":
            return True, "hold_safe"
        if allowed and intent.get("symbol") not in allowed:
            return False, "symbol_not_allowed"
        if not intent.get("thesis"):
            return False, "missing_thesis"
        if intent.get("confidence", 0) < 0.60:
            return False, "low_confidence"
        return True, "ok"

    # ── Stats ──────────────────────────────────────────────────

    def stats(self) -> dict:
        return {"daily_trades": dict(self._daily_trades), "recent_signals": len(self._recent_signals)}
