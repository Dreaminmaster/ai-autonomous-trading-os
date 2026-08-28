"""Unified, strategy-agnostic Paper and read-only Shadow runtime.

The runtime owns the required execution path:

public/historical market data -> strategy plugins -> provider -> validated
TradeIntent -> deterministic risk -> simulated execution -> audit ledger.

No component in this module can enable or call Live execution. Any malformed
data, plugin, provider result, intent, policy, or execution dependency fails to
an audited HOLD/no-trade outcome.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import asdict, dataclass
from time import sleep

from atos.core import new_id, utc_now
from atos.data_freshness import DataFreshnessGuard
from atos.domain import Candle, make_hold
from atos.durable_execution import DurableSimulatedExecutor
from atos.execution import PaperExecutor, ShadowExecutor
from atos.ledger import Ledger
from atos.market import MarketSnapshot, PublicMarketAdapter
from atos.models.trade_intent import TradeIntent as ValidatedTradeIntent
from atos.providers import ProviderManager, ProviderRequest
from atos.risk import RiskEngine
from atos.strategy_registry import StrategyRegistry, create_default_registry


class RuntimeSafetyError(RuntimeError):
    """The requested runtime configuration violates a safety boundary."""


OPERATING_MODES = frozenset({"paper", "shadow", "backtest"})


@dataclass(frozen=True)
class RuntimeResult:
    loops: int
    ledger_events: int
    last_status: str
    mode: str = "paper"
    session_id: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


class AutonomousRuntime:
    """Dependency-injected operating runtime with fail-closed boundaries."""

    def __init__(
        self,
        policy: dict,
        ledger: Ledger | None = None,
        *,
        registry: StrategyRegistry | None = None,
        providers: ProviderManager | None = None,
        market_adapter: PublicMarketAdapter | None = None,
        freshness_guard: DataFreshnessGuard | None = None,
        executor: PaperExecutor
        | ShadowExecutor
        | DurableSimulatedExecutor
        | None = None,
    ):
        self.policy = dict(policy)
        self.mode = str(self.policy.get("mode", "paper"))
        if self.mode == "live":
            raise RuntimeSafetyError("Live runtime is forbidden and has no adapter")
        if self.mode not in OPERATING_MODES:
            raise RuntimeSafetyError(f"unsupported operating mode: {self.mode}")
        self.ledger = ledger or Ledger()
        self.registry = registry or create_default_registry()
        self.providers = providers or ProviderManager()
        self.market_adapter = market_adapter or PublicMarketAdapter()
        data_policy = self.policy.get("data_freshness", {})
        self.freshness_guard = freshness_guard or DataFreshnessGuard(
            max_candle_age_seconds=float(
                data_policy.get("max_candle_age_seconds", 300.0)
            ),
            min_candles_required=int(data_policy.get("min_candles_required", 20)),
            max_gap_minutes=int(data_policy.get("max_gap_minutes", 15)),
        )
        persistence_policy = self.policy.get("persistence", {})
        if executor is not None:
            self.executor = executor
        elif self.mode in {"paper", "shadow"} and bool(
            persistence_policy.get("enabled", False)
        ):
            self.executor = DurableSimulatedExecutor(
                mode=self.mode,
                database_path=str(
                    persistence_policy.get(
                        "database_path", "runtime/atos_runtime.sqlite"
                    )
                ),
                fee_bps=float(self.policy.get("paper", {}).get("fee_bps", 10.0)),
                slippage_bps=float(
                    self.policy.get("paper", {}).get("slippage_bps", 5.0)
                ),
            )
        elif self.mode == "shadow":
            self.executor = ShadowExecutor(
                fee_bps=float(self.policy.get("paper", {}).get("fee_bps", 10.0)),
                slippage_bps=float(
                    self.policy.get("paper", {}).get("slippage_bps", 5.0)
                ),
            )
        else:
            self.executor = PaperExecutor(
                fee_bps=float(self.policy.get("paper", {}).get("fee_bps", 10.0)),
                slippage_bps=float(
                    self.policy.get("paper", {}).get("slippage_bps", 5.0)
                ),
            )
        if self.mode == "shadow" and not (
            isinstance(self.executor, ShadowExecutor)
            or getattr(self.executor, "mode", None) == "shadow"
        ):
            raise RuntimeSafetyError(
                "Shadow mode requires the no-order Shadow executor"
            )
        self.risk = RiskEngine(self.policy)
        self.session_id = new_id("session")
        self.session_started_at = utc_now()
        self.ledger.record(
            "runtime_session_started",
            {
                "session_id": self.session_id,
                "mode": self.mode,
                "started_at": self.session_started_at,
                "account_access": False,
                "private_api": False,
                "external_execution": False,
                "live": "FORBIDDEN",
            },
        )

    @staticmethod
    def _validate_candles(candles: list[Candle]) -> None:
        if not candles:
            raise RuntimeSafetyError("market candle input is empty")
        seen_timestamps: set[str] = set()
        last_timestamp: str | None = None
        for candle in candles:
            if not isinstance(candle, Candle):
                raise RuntimeSafetyError("market candle input contains a wrong type")
            values = (candle.open, candle.high, candle.low, candle.close, candle.volume)
            if (
                not all(math.isfinite(float(value)) for value in values)
                or min(candle.open, candle.high, candle.low, candle.close) <= 0
                or candle.volume < 0
                or candle.high < max(candle.open, candle.close)
                or candle.low > min(candle.open, candle.close)
                or candle.high < candle.low
            ):
                raise RuntimeSafetyError("market candle OHLCV invariant failed")
            if candle.ts is not None:
                timestamp = str(candle.ts)
                if timestamp in seen_timestamps:
                    raise RuntimeSafetyError("market candle timestamp is duplicated")
                if last_timestamp is not None and timestamp <= last_timestamp:
                    raise RuntimeSafetyError("market candles are not strictly ordered")
                seen_timestamps.add(timestamp)
                last_timestamp = timestamp

    def _record(self, cycle_id: str, kind: str, payload: dict) -> None:
        self.ledger.record(
            kind,
            {"session_id": self.session_id, "cycle_id": cycle_id, **payload},
        )

    def _portfolio_risk_state(self, symbol: str, mark_price: float) -> dict:
        reader = getattr(self.executor, "risk_state", None)
        if not callable(reader):
            return {}
        return dict(
            reader(
                symbol=symbol,
                mark_price=mark_price,
                equity_usdt=float(
                    self.policy.get("paper", {}).get("equity_usdt", 1000.0)
                ),
            )
        )

    def _fail_closed_cycle(
        self, cycle_id: str, symbol: str, reason: str, *, mark_price: float = 0.0
    ) -> dict:
        intent = make_hold(reason, symbol=symbol)
        risk_decision = self.risk.evaluate(
            intent.to_dict(),
            {
                "mode": self.mode,
                "external_execution_enabled": False,
            },
        )
        try:
            execution = self.executor.execute(
                intent.to_dict(),
                risk_decision.to_dict(),
                mark_price=mark_price,
                equity_usdt=float(
                    self.policy.get("paper", {}).get("equity_usdt", 1000.0)
                ),
                execution_context={
                    "session_id": self.session_id,
                    "session_started_at": self.session_started_at,
                    "cycle_id": cycle_id,
                    "mode": self.mode,
                    "observed_at": utc_now(),
                },
            )
        except Exception as exc:  # noqa: BLE001 - failure path must still HOLD
            fallback = ShadowExecutor() if self.mode == "shadow" else PaperExecutor()
            execution = fallback.execute(
                intent.to_dict(),
                risk_decision.to_dict(),
                mark_price=mark_price,
                equity_usdt=float(
                    self.policy.get("paper", {}).get("equity_usdt", 1000.0)
                ),
            )
            reason = f"{reason}; durable HOLD persistence failed: {type(exc).__name__}"
        self._record(cycle_id, "runtime_failure_hold", {"reason": reason})
        self._record(cycle_id, "trade_intent", intent.to_dict())
        self._record(cycle_id, "risk_decision", risk_decision.to_dict())
        self._record(cycle_id, "execution", execution.to_dict())
        self._record(
            cycle_id,
            "runtime_cycle_completed",
            {"status": execution.status, "safe_default": True},
        )
        return {
            "session_id": self.session_id,
            "cycle_id": cycle_id,
            "mode": self.mode,
            "candidates": [],
            "strategy_diagnostics": [],
            "provider_result": {"provider": "none", "error": reason},
            "intent_validation": {"is_valid": True, "errors": []},
            "intent": intent.to_dict(),
            "risk": risk_decision.to_dict(),
            "execution": execution.to_dict(),
            "safe_default": True,
        }

    def run_once(
        self,
        symbol: str,
        candles: list[Candle],
        mark_price: float = 100.0,
        *,
        market_state: dict | None = None,
    ) -> dict:
        cycle_id = new_id("cycle")
        self._record(
            cycle_id,
            "runtime_cycle_started",
            {"symbol": symbol, "mode": self.mode, "started_at": utc_now()},
        )
        try:
            self._validate_candles(candles)
            if not math.isfinite(float(mark_price)) or mark_price <= 0:
                raise RuntimeSafetyError("mark price must be positive and finite")
        except Exception as exc:  # noqa: BLE001 - every invalid input must become HOLD
            return self._fail_closed_cycle(
                cycle_id,
                symbol,
                f"market validation failed: {type(exc).__name__}: {exc}",
            )

        self._record(
            cycle_id,
            "market_snapshot",
            {
                "symbol": symbol,
                "mark_price": mark_price,
                "candles_count": len(candles),
                "source": (market_state or {}).get("source", "CALLER_SUPPLIED"),
                "public_only": (market_state or {}).get("source")
                == "OKX_OFFICIAL_PUBLIC",
                "account_access": bool(
                    (market_state or {}).get("account_access", False)
                ),
            },
        )
        candidates, diagnostics = self.registry.generate_with_diagnostics(
            symbol, candles
        )
        candidate_payloads = [candidate.to_dict() for candidate in candidates]
        self._record(
            cycle_id,
            "strategy_candidates",
            {"items": candidate_payloads, "diagnostics": diagnostics},
        )

        request = ProviderRequest(
            symbol=symbol,
            candidates=candidate_payloads,
            market_state={"mark_price": mark_price, **(market_state or {})},
            risk_state={
                "mode": self.mode,
                "external_execution_enabled": False,
                "live": "FORBIDDEN",
                "max_position_pct_per_trade": float(
                    self.policy.get("position_limits", {}).get(
                        "max_position_pct_per_trade", 0.0
                    )
                ),
            },
        )
        provider_result = self.providers.decide(request)
        self._record(cycle_id, "provider_result", provider_result.to_dict())

        try:
            proposed = ValidatedTradeIntent.from_dict(provider_result.intent.to_dict())
            max_position = float(
                self.policy.get("position_limits", {}).get(
                    "max_position_pct_per_trade", 0.0
                )
            )
            validation = proposed.validate(
                allowed_symbols=set(self.policy.get("allowed_symbols", [])),
                max_position_pct=max_position,
            )
            validated_intent = validation.corrected_intent
        except Exception as exc:  # noqa: BLE001 - untrusted provider boundary
            validated_intent = ValidatedTradeIntent.hold(
                reason=f"intent parsing failed: {type(exc).__name__}", symbol=symbol
            )
            validation = validated_intent.validate(
                allowed_symbols=set(self.policy.get("allowed_symbols", []))
            )
        self._record(cycle_id, "trade_intent_validation", validation.to_dict())
        intent_payload = validated_intent.to_dict()
        self._record(cycle_id, "trade_intent", intent_payload)

        risk_decision = self.risk.evaluate(
            intent_payload,
            {
                "mode": self.mode,
                "external_execution_enabled": False,
                **self._portfolio_risk_state(symbol, mark_price),
            },
        )
        self._record(cycle_id, "risk_decision", risk_decision.to_dict())
        try:
            execution = self.executor.execute(
                intent_payload,
                risk_decision.to_dict(),
                mark_price=mark_price,
                equity_usdt=float(
                    self.policy.get("paper", {}).get("equity_usdt", 1000.0)
                ),
                execution_context={
                    "session_id": self.session_id,
                    "session_started_at": self.session_started_at,
                    "cycle_id": cycle_id,
                    "mode": self.mode,
                    "observed_at": utc_now(),
                },
            )
        except Exception as exc:  # noqa: BLE001 - executor boundary must HOLD
            return self._fail_closed_cycle(
                cycle_id,
                symbol,
                f"simulated execution failed: {type(exc).__name__}: {exc}",
                mark_price=mark_price,
            )
        self._record(cycle_id, "execution", execution.to_dict())
        self._record(
            cycle_id,
            "runtime_cycle_completed",
            {
                "status": execution.status,
                "safe_default": validated_intent.action == "HOLD",
            },
        )
        return {
            "session_id": self.session_id,
            "cycle_id": cycle_id,
            "mode": self.mode,
            "candidates": candidate_payloads,
            "strategy_diagnostics": diagnostics,
            "provider_result": provider_result.to_dict(),
            "intent_validation": validation.to_dict(),
            "intent": intent_payload,
            "risk": risk_decision.to_dict(),
            "execution": execution.to_dict(),
            "safe_default": validated_intent.action == "HOLD",
        }

    def run_public_once(
        self, symbol: str, *, bar: str = "1m", limit: int = 100
    ) -> dict:
        """Run one account-free public-data cycle in Paper or Shadow mode."""
        if self.mode == "backtest":
            raise RuntimeSafetyError("backtest mode requires caller-supplied history")
        cycle_id = new_id("cycle")
        try:
            snapshot: MarketSnapshot = self.market_adapter.snapshot(
                symbol, bar=bar, limit=limit
            )
            snapshot.validate(symbol)
            freshness = self.freshness_guard.check_candles(snapshot.candles)
            if not freshness.is_fresh:
                raise RuntimeSafetyError(
                    "public market data is stale: " + "; ".join(freshness.reasons)
                )
        except Exception as exc:  # noqa: BLE001 - public/custom adapter boundary
            self._record(
                cycle_id,
                "runtime_cycle_started",
                {"symbol": symbol, "mode": self.mode, "started_at": utc_now()},
            )
            return self._fail_closed_cycle(
                cycle_id,
                symbol,
                f"public market acquisition failed: {type(exc).__name__}: {exc}",
            )
        return self.run_once(
            symbol,
            snapshot.candles,
            mark_price=snapshot.mark_price,
            market_state={
                "source": "OKX_OFFICIAL_PUBLIC",
                "freshness": freshness.to_dict(),
                "orderbook": snapshot.orderbook,
                "account_access": False,
            },
        )

    def run_loop(
        self,
        symbol: str,
        candle_supplier: Callable[[], list[Candle]],
        loops: int = 1,
        interval_seconds: float = 0.0,
    ) -> RuntimeResult:
        if type(loops) is not int or loops < 1:
            raise ValueError("loops must be a positive integer")
        last_status = "not_started"
        for index in range(loops):
            candles = candle_supplier()
            mark_price = candles[-1].close if candles else 0.0
            result = self.run_once(symbol, candles, mark_price=mark_price)
            last_status = result["execution"]["status"]
            if interval_seconds > 0 and index + 1 < loops:
                sleep(interval_seconds)
        return RuntimeResult(
            loops=loops,
            ledger_events=self.ledger.count(),
            last_status=last_status,
            mode=self.mode,
            session_id=self.session_id,
        )

    def run_public_loop(
        self,
        symbols: list[str],
        *,
        loops: int = 1,
        interval_seconds: float = 0.0,
        bar: str = "1m",
        limit: int = 100,
    ) -> dict:
        if not symbols or type(loops) is not int or loops < 1:
            raise ValueError("symbols and a positive loop count are required")
        results: list[dict] = []
        for index in range(loops):
            for symbol in symbols:
                results.append(self.run_public_once(symbol, bar=bar, limit=limit))
            if interval_seconds > 0 and index + 1 < loops:
                sleep(interval_seconds)
        return {
            "session_id": self.session_id,
            "mode": self.mode,
            "loops": loops,
            "symbols": list(symbols),
            "cycles": len(results),
            "ledger_events": self.ledger.count(),
            "last_status": results[-1]["execution"]["status"],
            "live": "FORBIDDEN",
            "results": results,
        }
