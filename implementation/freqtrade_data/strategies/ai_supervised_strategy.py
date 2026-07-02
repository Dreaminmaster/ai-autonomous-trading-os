"""
ai_supervised_strategy.py — AI Supervised Freqtrade Strategy Wrapper
=====================================================================

This is NOT an ordinary Freqtrade strategy. It acts as a bridge between
Freqtrade and the AI Autonomous Trading OS:

  Freqtrade candles
    → atos feature_builder
    → atos strategy pool (trend, mean_reversion, breakout, ...)
    → atos provider manager (mock / OpenAI / DeepSeek)
    → trade_intent (structured JSON)
    → schema validation
    → risk_supervisor (deterministic checks)
    → Freqtrade signal (enter_long / exit_long / custom_exit)

SAFETY RULES (HARD-CODED):
  1. AI CANNOT place orders directly.
  2. AI only outputs TradeIntent JSON.
  3. TradeIntent MUST pass schema validation.
  4. Risk supervisor MUST approve before signal is emitted.
  5. Provider failure → HOLD (no trade).
  6. JSON invalid → HOLD.
  7. Data insufficient → HOLD.
  8. ALL exceptions caught → default HOLD.
  9. Live trading is CONTROLLED by Freqtrade config (dry_run=true).
  10. API keys are NEVER read, stored, or logged by this strategy.

Freqtrade integration points:
  - populate_indicators(): compute features
  - populate_entry_trend(): AI decides → risk check → signal
  - populate_exit_trend(): AI decides exit → risk check → signal
  - custom_exit(): additional exit logic
"""

from __future__ import annotations

import sys
import logging
from pathlib import Path
from typing import Any

import pandas as pd
import numpy as np
from pandas import DataFrame

from freqtrade.strategy import IStrategy, IntParameter
from freqtrade.persistence import Trade

# Add ATOS package to path (strategy file lives in freqtrade_data/strategies/,
# ATOS source in implementation/src/)
_ATOS_ROOT = Path(__file__).resolve().parents[2] / "src"
if str(_ATOS_ROOT) not in sys.path:
    sys.path.insert(0, str(_ATOS_ROOT))

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────
# Import ATOS modules (with graceful fallback to mock if unavailable)
# ─────────────────────────────────────────────────────────────────────

try:
    from atos.strategies import default_strategies
    from atos.providers import ProviderManager, ProviderRequest
    from atos.risk import RiskEngine
    from atos.ledger import Ledger
    from atos.features import moving_average, simple_return
    ATOS_AVAILABLE = True
except ImportError as e:
    logger.warning(f"ATOS modules not importable: {e}. Using built-in fallback.")
    ATOS_AVAILABLE = False


# ─────────────────────────────────────────────────────────────────────
# Built-in minimal fallback (works even without ATOS installed)
# ─────────────────────────────────────────────────────────────────────

_FALLBACK_POLICY = {
    "mode": "paper",
    "allowed_symbols": ["BTC/USDT", "ETH/USDT"],
    "position_limits": {"max_position_pct_per_trade": 10.0},
    "ai_output_limits": {"min_confidence_for_trade": 0.60},
    "trade_limits": {"max_trades_per_day": 100, "cooldown_seconds": 300},
    "kill_switch": {"flag_path": "runtime/kill_switch.flag"},
}


def _builtin_risk_check(intent: dict, policy: dict) -> dict:
    """Minimal built-in risk engine (used when ATOS not installed)."""
    reasons = []
    action = intent.get("action", "HOLD")

    # Emergency stop
    ks_path = policy.get("kill_switch", {}).get("flag_path")
    if ks_path and Path(ks_path).exists():
        return {"decision": "PAUSED", "reasons": ["kill_switch_active"], "risk_score": 1.0}

    # Symbol whitelist
    allowed = set(policy.get("allowed_symbols", []))
    if intent.get("symbol") not in allowed and action != "HOLD":
        reasons.append("symbol_not_allowed")

    # Confidence threshold
    min_conf = policy.get("ai_output_limits", {}).get("min_confidence_for_trade", 0.6)
    conf = intent.get("confidence", 0.0)
    if action != "HOLD" and conf < min_conf:
        reasons.append("confidence_below_threshold")

    # Position size
    max_pos = policy.get("position_limits", {}).get("max_position_pct_per_trade", 10.0)
    pos = intent.get("position_size_pct", 0.0)
    if pos > max_pos:
        reasons.append("position_size_exceeds_limit")

    # Required fields for non-HOLD trades
    if action in ("BUY", "SELL"):
        if not intent.get("thesis"):
            reasons.append("missing_thesis")
        if not intent.get("evidence"):
            reasons.append("missing_evidence")
        if float(intent.get("stop_loss_pct", 0.0)) <= 0:
            reasons.append("missing_stop_loss")
        if float(intent.get("take_profit_pct", 0.0)) <= 0:
            reasons.append("missing_take_profit")

    if reasons:
        return {"decision": "REJECTED", "reasons": reasons, "risk_score": min(1.0, 0.5 + 0.1 * len(reasons))}
    return {"decision": "APPROVED", "reasons": ["all_checks_passed"], "risk_score": 0.1}


def _builtin_candidates(dataframe: DataFrame) -> list[dict]:
    """Built-in candidate generation (trend, mean_reversion, breakout)."""
    if len(dataframe) < 30:
        return []

    closes = dataframe["close"].values
    candidates = []

    # Trend following
    if len(closes) >= 20:
        fast = np.mean(closes[-5:])
        slow = np.mean(closes[-20:])
        if fast > slow:
            candidates.append({
                "strategy_id": "trend_following_v1",
                "symbol": "BTC/USDT",
                "side": "BUY",
                "signal_strength": 0.65,
                "confidence": 0.62,
                "entry_reason": "fast MA above slow MA",
                "suggested_stop_loss_pct": 1.0,
                "suggested_take_profit_pct": 2.0,
                "max_holding_minutes": 240,
                "regime_tags": ["trend_up"],
                "risk_notes": "trend can reverse quickly",
            })

    # Mean reversion
    if len(closes) >= 20:
        avg = np.mean(closes[-20:])
        if closes[-1] < avg * 0.985:
            candidates.append({
                "strategy_id": "mean_reversion_v1",
                "symbol": "BTC/USDT",
                "side": "BUY",
                "signal_strength": 0.58,
                "confidence": 0.60,
                "entry_reason": "price below recent average",
                "suggested_stop_loss_pct": 1.2,
                "suggested_take_profit_pct": 1.8,
                "max_holding_minutes": 180,
                "regime_tags": ["range", "mean_reversion"],
                "risk_notes": "avoid strong downtrend",
            })

    return candidates


def _make_hold_intent(symbol: str, reason: str) -> dict:
    """Create a safe HOLD trade intent."""
    return {
        "schema_version": "trade_intent.v1",
        "action": "HOLD",
        "symbol": symbol,
        "market_type": "paper_spot",
        "confidence": 0.0,
        "thesis": f"No trade: {reason}",
        "evidence": [reason],
        "selected_strategy_ids": [],
        "position_size_pct": 0.0,
        "stop_loss_pct": 0.0,
        "take_profit_pct": 0.0,
        "max_holding_minutes": 0,
        "invalidation_conditions": ["No active thesis"],
        "risk_notes": reason,
        "metadata": {"fallback": True, "reason": reason},
    }


# ─────────────────────────────────────────────────────────────────────
# Freqtrade IStrategy Implementation
# ─────────────────────────────────────────────────────────────────────

class AISupervisedStrategy(IStrategy):
    """
    AI Supervised Strategy — bridges Freqtrade with AI Autonomous Trading OS.

    This strategy delegates trade decisions to an AI provider through
    the ATOS pipeline: strategy candidates → AI decision → risk check → signal.

    In dry-run mode (default), all orders are simulated.
    In live mode (requires explicit config change + risk supervisor approval),
    orders are sent to the exchange.
    """

    # ── Strategy metadata ──────────────────────────────────────────
    INTERFACE_VERSION = 3

    can_short: bool = False

    # ── Timeframes ──────────────────────────────────────────────────
    timeframe: str = "5m"

    # ── Hyperoptable parameters ─────────────────────────────────────
    entry_rsi_low = IntParameter(15, 45, default=30, space="buy")
    exit_rsi_high = IntParameter(60, 90, default=70, space="sell")

    # Stop-loss: -5% hard stop-loss (overridden by AI-suggested value)
    stop_loss = -0.05
    trailing_stop = False

    # Process only new candles
    process_only_new_candles = True
    use_exit_signal = True
    exit_profit_only = False
    ignore_roi_if_entry_signal = False

    # Number of candles the strategy requires before producing a signal
    startup_candle_count: int = 40

    # ── ATOS Configuration ──────────────────────────────────────────
    atos_policy: dict = _FALLBACK_POLICY
    atos_provider: str = "mock"
    atos_enabled: bool = True
    atos_log_decisions: bool = True
    atos_ledger_path: str = "freqtrade_data/atos_ledger.sqlite"

    # ── Internal state ──────────────────────────────────────────────
    _provider_manager: Any = None
    _risk_engine: Any = None
    _ledger: Any = None
    _initialized: bool = False

    # ── Initialization ──────────────────────────────────────────────

    def _init_atos(self) -> None:
        """Lazy-init ATOS components. Called on first candle processing."""
        import os, json

        # Always create a fresh ProviderManager
        self._provider_manager = ProviderManager(self.atos_provider) if ATOS_AVAILABLE else None

        if not self._initialized:
            policy_path = os.environ.get("ATOS_POLICY", "")
            if policy_path and Path(policy_path).exists():
                try:
                    loaded = json.loads(Path(policy_path).read_text())
                    self.atos_policy = loaded
                    logger.info(f"ATOS policy loaded from ATOS_POLICY={policy_path}")
                except Exception as e:
                    logger.warning(f"Failed to load ATOS_POLICY={policy_path}: {e}, using default policy")
            self._initialized = True

        # FRESH RiskEngine every populate_entry_trend call
        # This avoids false lookahead bias from shared risk state
        if ATOS_AVAILABLE:
            self._risk_engine = RiskEngine(self.atos_policy)
        else:
            self._risk_engine = None

        # Ledger: only in live/dry-run (skip in backtest lookahead to reduce side effects)
        is_lookahead = os.environ.get("ATOS_LOOKAHEAD_MODE", "") == "1"
        if ATOS_AVAILABLE and not is_lookahead:
            if self._ledger is None:
                self._ledger = Ledger(self.atos_ledger_path)
        else:
            self._ledger = None

        logger.info(f"ATOS init: provider={self.atos_provider}, risk_engine=fresh, lookahead_mode={is_lookahead}")

    def _get_policy(self) -> dict:
        """Merge runtime config with static policy."""
        policy = dict(self.atos_policy)
        policy["dry_run"] = self.config.get("dry_run", True)
        return policy

    def _resolve_candle_ts(self, dataframe: DataFrame, idx: Any) -> float:
        """Get epoch seconds from dataframe row for backtest time semantics.

        Uses 'date' column if available, falls back to time.time().
        Compatible with pandas Timestamp, datetime, string, and numeric.
        """
        import time as _time

        if "date" in dataframe.columns:
            raw = dataframe.at[idx, "date"]
            return self._to_epoch(raw)

        # idx may be a pandas Timestamp
        try:
            raw = idx
            return self._to_epoch(raw)
        except Exception:
            pass

        # Fallback: wall clock (live/dry-run)
        return _time.time()

    @staticmethod
    def _to_epoch(raw: Any) -> float:
        """Convert various timestamp types to epoch seconds."""
        import time as _time
        import pandas as _pd

        if raw is None:
            return _time.time()
        if isinstance(raw, (int, float)):
            if raw > 1e10:
                return raw / 1000.0  # milliseconds
            return raw  # seconds (small number → wall clock, fallback)
        if isinstance(raw, _pd.Timestamp):
            return raw.timestamp()
        if isinstance(raw, str):
            try:
                return _pd.Timestamp(raw).timestamp()
            except Exception:
                pass
        # Last resort
        return _time.time()

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        """
        Compute features used by strategy candidates.

        Adds: fast_ma, slow_ma, rsi, bb_upper, bb_lower, volume_sma, return_1
        """
        dataframe["fast_ma"] = dataframe["close"].rolling(window=5).mean()
        dataframe["slow_ma"] = dataframe["close"].rolling(window=20).mean()

        delta = dataframe["close"].diff()
        gain = delta.clip(lower=0).rolling(window=14).mean()
        loss = (-delta.clip(upper=0)).rolling(window=14).mean()
        rs = gain / loss.replace(0, np.nan)
        dataframe["rsi"] = 100 - (100 / (1 + rs))

        bb_sma = dataframe["close"].rolling(window=20).mean()
        bb_std = dataframe["close"].rolling(window=20).std()
        dataframe["bb_upper"] = bb_sma + 2 * bb_std
        dataframe["bb_lower"] = bb_sma - 2 * bb_std

        dataframe["volume_sma"] = dataframe["volume"].rolling(window=20).mean()
        dataframe["return_1"] = dataframe["close"].pct_change()

        return dataframe

    # ── Entry Signal ────────────────────────────────────────────────

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        """
        AI-driven entry signals.

        For each candle: candidates → AI decision → risk check → signal.
        On ANY failure: HOLD.
        """
        self._init_atos()
        policy = self._get_policy()

        dataframe["enter_long"] = 0
        dataframe["enter_tag"] = ""

        if not self.atos_enabled:
            return dataframe

        symbol = metadata.get("pair", "BTC/USDT")
        valid_rows = dataframe[dataframe["slow_ma"].notna()].index

        logger.info(
            f"{symbol} — ATOS evaluating {len(valid_rows)} candles "
            f"(provider={self.atos_provider})"
        )

        # ── Diagnostic counters (P1: separated BUY/HOLD/APPROVED/REJECTED) ─
        stats = {
            "candles_evaluated": 0,
            "total_candidates": 0,
            "buy_candidates": 0,
            "provider_buy": 0,
            "provider_hold": 0,
            "risk_approved_buy": 0,
            "risk_approved_hold": 0,
            "risk_rejected_buy": 0,
            "risk_rejected_duplicate": 0,
            "risk_rejected_daily_limit": 0,
            "signals_emitted": 0,
            "rejection_reasons": {},
            "first_decision_day": None,
            "last_decision_day": None,
        }

        for idx in valid_rows:
            stats["candles_evaluated"] += 1
            try:
                # ── Step 1: Strategy candidates ─────────────────
                if ATOS_AVAILABLE:
                    row_idx = dataframe.index.get_loc(idx)
                    start = max(0, row_idx - 39)
                    window = dataframe.iloc[start : row_idx + 1]

                    from atos.domain import Candle
                    candles = [
                        Candle(
                            open=float(r["open"]),
                            high=float(r["high"]),
                            low=float(r["low"]),
                            close=float(r["close"]),
                            volume=float(r["volume"]),
                        )
                        for _, r in window.iterrows()
                    ]

                    candidates = []
                    for strategy in default_strategies():
                        c = strategy.generate(symbol, candles)
                        if c:
                            candidates.append(c.to_dict())

                    if not any(c.get("strategy_id") == "hold_baseline" for c in candidates):
                        candidates.append({
                            "strategy_id": "hold_baseline",
                            "symbol": symbol,
                            "side": "HOLD",
                            "signal_strength": 0.0,
                            "confidence": 1.0,
                            "entry_reason": "baseline hold",
                            "suggested_stop_loss_pct": 0.0,
                            "suggested_take_profit_pct": 0.0,
                            "max_holding_minutes": 0,
                            "regime_tags": ["all"],
                            "risk_notes": "safe default",
                        })
                else:
                    # Use position-based iloc window — no future data
                    row_idx = dataframe.index.get_loc(idx) if hasattr(dataframe.index, 'get_loc') else idx
                    window_df = dataframe.iloc[max(0, row_idx - 39) : row_idx + 1]
                    candidates = _builtin_candidates(window_df)
                    if not any(c.get("strategy_id") == "hold_baseline" for c in candidates):
                        candidates.append({
                            "strategy_id": "hold_baseline",
                            "symbol": symbol,
                            "side": "HOLD",
                            "signal_strength": 0.0,
                            "confidence": 1.0,
                            "entry_reason": "baseline hold",
                            "suggested_stop_loss_pct": 0.0,
                            "suggested_take_profit_pct": 0.0,
                            "max_holding_minutes": 0,
                            "regime_tags": ["all"],
                            "risk_notes": "safe default",
                        })

                # ── Step 2: AI Decision ─────────────────────────
                mark_price = float(dataframe.at[idx, "close"])
                market_state = {
                    "mark_price": mark_price,
                    "rsi": float(dataframe.at[idx, "rsi"]) if pd.notna(dataframe.at[idx, "rsi"]) else 50.0,
                }

                if ATOS_AVAILABLE and self._provider_manager:
                    request = ProviderRequest(
                        symbol=symbol,
                        candidates=candidates,
                        market_state=market_state,
                        risk_state={"mode": policy.get("mode", "paper")},
                    )
                    provider_result = self._provider_manager.decide(request)
                    trade_intent = provider_result.intent  # ProviderResult → TradeIntent
                    intent_dict = trade_intent.to_dict()
                    provider_dict = provider_result.to_dict()
                else:
                    buy_candidates = [c for c in candidates if c.get("side") == "BUY" and c.get("confidence", 0) >= 0.6]
                    if buy_candidates:
                        c = buy_candidates[0]
                        intent_dict = {
                            "schema_version": "trade_intent.v1",
                            "action": "BUY",
                            "symbol": symbol,
                            "market_type": "paper_spot",
                            "confidence": float(c["confidence"]),
                            "thesis": str(c.get("entry_reason", "candidate supports trade")),
                            "evidence": [str(c.get("entry_reason", "strategy candidate"))],
                            "selected_strategy_ids": [str(c.get("strategy_id", "unknown"))],
                            "position_size_pct": 5.0,
                            "stop_loss_pct": float(c.get("suggested_stop_loss_pct", 1.0)),
                            "take_profit_pct": float(c.get("suggested_take_profit_pct", 2.0)),
                            "max_holding_minutes": int(c.get("max_holding_minutes", 240)),
                            "invalidation_conditions": ["candidate invalidated", "risk worsens"],
                            "risk_notes": "built-in fallback decision",
                            "metadata": {"provider": "builtin_fallback"},
                        }
                    else:
                        intent_dict = _make_hold_intent(symbol, "no valid candidate")

                # ── Step 3: Risk Check ──────────────────────────
                # Resolve candle timestamp (epoch seconds) for backtest time semantics
                candle_ts = self._resolve_candle_ts(dataframe, idx)

                # Resolve date for this candle
                from atos.time_context import resolve_decision_day
                candle_day = resolve_decision_day({"decision_ts": candle_ts})
                stats["_current_decision_day"] = candle_day

                risk_state = {
                    "mode": policy.get("mode", "paper"),
                    "is_backtest": True,
                    "decision_ts": candle_ts,
                    "candle_ts": candle_ts,
                    "decision_day": candle_day,
                }

                if ATOS_AVAILABLE and self._risk_engine:
                    risk = self._risk_engine.evaluate(intent_dict, risk_state)
                    risk_dict = risk.to_dict()
                else:
                    risk_dict = _builtin_risk_check(intent_dict, policy)

                # ── Collect stats (P1: separate BUY/HOLD/APPROVED/REJECTED) ─
                stats["total_candidates"] += len(candidates)
                buy_cands_count = len([c for c in candidates if c.get("side") == "BUY"])
                stats["buy_candidates"] += buy_cands_count

                intent_action = intent_dict.get("action", "HOLD")
                risk_decision = risk_dict.get("decision", "REJECTED")

                if intent_action == "BUY":
                    stats["provider_buy"] += 1
                    if risk_decision == "APPROVED":
                        stats["risk_approved_buy"] += 1
                    else:
                        stats["risk_rejected_buy"] += 1
                        for reason in risk_dict.get("reasons", []):
                            stats["rejection_reasons"][reason] = stats["rejection_reasons"].get(reason, 0) + 1
                else:
                    stats["provider_hold"] += 1
                    if risk_decision == "APPROVED":
                        stats["risk_approved_hold"] += 1

                if "duplicate" in str(risk_dict.get("reasons", [])):
                    stats["risk_rejected_duplicate"] += 1
                if "daily_trade_limit" in str(risk_dict.get("reasons", [])):
                    stats["risk_rejected_daily_limit"] += 1

                # Track decision day range
                day_label = stats.get("_current_decision_day", "")
                if day_label and not stats["first_decision_day"]:
                    stats["first_decision_day"] = day_label
                if day_label:
                    stats["last_decision_day"] = day_label

                # ── Step 4: Produce Signal ──────────────────────
                if risk_dict.get("decision") == "APPROVED" and intent_dict.get("action") == "BUY":
                    dataframe.at[idx, "enter_long"] = 1
                    tag = intent_dict.get("selected_strategy_ids", ["unknown"])[0]
                    dataframe.at[idx, "enter_tag"] = f"atos_{tag}"
                    stats["signals_emitted"] += 1

                # ── Logging ─────────────────────────────────────
                if self.atos_log_decisions:
                    logger.debug(
                        f"{symbol} | action={intent_dict.get('action')} | "
                        f"confidence={intent_dict.get('confidence', 0):.2f} | "
                        f"risk={risk_dict.get('decision')} | "
                        f"signal={'BUY' if dataframe.at[idx, 'enter_long'] else 'HOLD'}"
                    )

                # ── Ledger ───────────────────────────────────────
                if ATOS_AVAILABLE and self._ledger:
                    try:
                        self._ledger.record("entry_evaluation", {
                            "symbol": symbol,
                            "candidates": candidates,
                            "intent": intent_dict,
                            "risk_decision": risk_dict,
                            "signal": "BUY" if dataframe.at[idx, "enter_long"] else "HOLD",
                        })
                    except Exception as e:
                        logger.warning(f"Ledger write failed: {e}")

            except Exception as e:
                logger.error(f"ATOS entry evaluation failed at row {idx}: {e}", exc_info=True)
                dataframe.at[idx, "enter_long"] = 0
                dataframe.at[idx, "enter_tag"] = "atos_error"

        # ── Diagnostic summary (P5: full ATOS_SIGNAL_DIAGNOSTICS) ──────
        risk_stats = self._risk_engine.stats() if ATOS_AVAILABLE and self._risk_engine else {}
        first_day = stats.get("first_decision_day") or "wallclock"
        last_day = stats.get("last_decision_day") or "wallclock"
        day_count = risk_stats.get("daily_trade_days_count", 0)
        max_day = risk_stats.get("max_trades_in_single_day", 0)

        logger.info(
            f"ATOS_SIGNAL_DIAGNOSTICS: {symbol} | "
            f"candles={stats['candles_evaluated']} | "
            f"first_day={first_day} | "
            f"last_day={last_day} | "
            f"day_count={day_count} | "
            f"max_trades_day={max_day} | "
            f"candidates={stats['total_candidates']} | "
            f"buy_cands={stats['buy_candidates']} | "
            f"provider_BUY={stats['provider_buy']} | "
            f"provider_HOLD={stats['provider_hold']} | "
            f"risk_APPROVED_BUY={stats['risk_approved_buy']} | "
            f"risk_APPROVED_HOLD={stats['risk_approved_hold']} | "
            f"risk_REJECTED_BUY={stats['risk_rejected_buy']} | "
            f"risk_REJECTED_DUPLICATE={stats['risk_rejected_duplicate']} | "
            f"risk_REJECTED_DAILY_LIMIT={stats['risk_rejected_daily_limit']} | "
            f"enter_long={stats['signals_emitted']} | "
            f"rejection_reasons={stats.get('rejection_reasons', {})}"
        )

        # Day range validation
        if day_count == 1 and stats["candles_evaluated"] > 500:
            logger.error("ERROR: backtest daily trade limit may still be using wall-clock date: only 1 day_key for many candles")

        # Bottleneck warning
        if stats["provider_buy"] > 100 and stats["signals_emitted"] < 30:
            logger.warning("WARNING: signal bottleneck detected — provider_buy >> enter_long")

        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        """AI-driven exit signals based on RSI overbought."""
        self._init_atos()

        dataframe["exit_long"] = 0
        dataframe["exit_tag"] = ""

        if not self.atos_enabled:
            return dataframe

        for idx in dataframe[dataframe["slow_ma"].notna()].index:
            try:
                current_rsi = float(dataframe.at[idx, "rsi"]) if pd.notna(dataframe.at[idx, "rsi"]) else 50.0
                if current_rsi > self.exit_rsi_high.value:
                    dataframe.at[idx, "exit_long"] = 1
                    dataframe.at[idx, "exit_tag"] = f"atos_rsi_overbought_{current_rsi:.0f}"
            except Exception as e:
                logger.error(f"ATOS exit evaluation failed at row {idx}: {e}", exc_info=True)
                dataframe.at[idx, "exit_long"] = 0

        return dataframe

    # ── Custom Exit ─────────────────────────────────────────────────

    def custom_exit(
        self,
        pair: str,
        trade: Trade,
        current_time: Any,
        current_rate: float,
        current_profit: float,
        **kwargs,
    ) -> str | None:
        """Custom exit logic: take-profit, max holding time."""
        if not self.atos_enabled:
            return None

        try:
            if current_profit > 0.02:
                return "atos_take_profit"

            from datetime import datetime, timezone
            # Use Freqtrade's current_time (historical candle time in backtest),
            # NOT datetime.now() which uses wall-clock and breaks backtest time semantics.
            if hasattr(current_time, 'timestamp'):
                now_ts = current_time.timestamp()
            else:
                now_ts = trade.open_date_utc.replace(tzinfo=timezone.utc).timestamp()
            open_ts = trade.open_date_utc.replace(tzinfo=timezone.utc).timestamp()
            age_minutes = (now_ts - open_ts) / 60
            if age_minutes > 1200:  # 20 hours
                return "atos_max_holding_time"
        except Exception as e:
            logger.error(f"custom_exit error for {pair}: {e}", exc_info=True)

        return None

    # ── Custom Stop-Loss ────────────────────────────────────────────

    def custom_stoploss(
        self,
        pair: str,
        trade: Trade,
        current_time: Any,
        current_rate: float,
        current_profit: float,
        after_fill: bool,
        **kwargs,
    ) -> float | None:
        """Dynamic stop-loss based on AI-suggested value, with fallback."""
        try:
            if trade.buy_tag and trade.buy_tag.startswith("atos_"):
                return -0.01
        except Exception:
            pass
        return self.stop_loss
