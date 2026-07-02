from __future__ import annotations

from pathlib import Path
from typing import Any

from atos.core import Action, RunMode
from atos.domain import RiskDecision


class RiskEngine:
    def __init__(self, policy: dict[str, Any]):
        self.policy = policy

    def evaluate(self, intent: dict[str, Any], state: dict[str, Any] | None = None) -> RiskDecision:
        state = state or {}
        reasons: list[str] = []
        checks: dict[str, Any] = {}

        mode = state.get("mode", self.policy.get("mode", RunMode.PAPER.value))
        action = intent.get("action", Action.HOLD.value)
        symbol = intent.get("symbol")
        confidence = float(intent.get("confidence", 0.0) or 0.0)
        position_size_pct = float(intent.get("position_size_pct", 0.0) or 0.0)

        flag_path = self.policy.get("kill_switch", {}).get("flag_path")
        stop_active = bool(state.get("emergency_stop")) or bool(flag_path and Path(flag_path).exists())
        checks["emergency_stop"] = stop_active
        if stop_active:
            return RiskDecision("risk_decision.v1", "PAUSED", ["emergency_stop_active"], 1.0, checks)

        if mode == RunMode.LIVE.value and not state.get("external_execution_enabled", False):
            reasons.append("external_execution_not_enabled")

        allowed_symbols = set(self.policy.get("allowed_symbols", []))
        checks["symbol_allowed"] = symbol in allowed_symbols
        if symbol not in allowed_symbols:
            reasons.append("symbol_not_allowed")

        min_conf = float(self.policy.get("ai_output_limits", {}).get("min_confidence_for_trade", 0.60))
        checks["confidence_ok"] = action == Action.HOLD.value or confidence >= min_conf
        if action != Action.HOLD.value and confidence < min_conf:
            reasons.append("confidence_below_threshold")

        max_pos = float(self.policy.get("position_limits", {}).get("max_position_pct_per_trade", 1.0))
        checks["position_size_ok"] = position_size_pct <= max_pos
        if position_size_pct > max_pos:
            reasons.append("position_size_exceeds_limit")

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

        if action == Action.HOLD.value and not reasons:
            return RiskDecision("risk_decision.v1", "APPROVED", ["hold_is_safe_default"], 0.0, checks)
        if reasons:
            return RiskDecision("risk_decision.v1", "REJECTED", reasons, min(1.0, 0.5 + 0.1 * len(reasons)), checks)
        return RiskDecision("risk_decision.v1", "APPROVED", ["all_checks_passed"], 0.1, checks)
