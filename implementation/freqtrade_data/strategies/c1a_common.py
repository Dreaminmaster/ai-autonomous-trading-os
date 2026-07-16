"""C1A fixed strategy-family screen. Historical backtests only; LIVE forbidden."""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

import math
import pandas as pd
from pandas import DataFrame
from freqtrade.exchange import timeframe_to_prev_date
from freqtrade.persistence import Trade
from freqtrade.strategy import IStrategy, merge_informative_pair, stoploss_from_absolute


BTC_PAIR = "BTC/USDT"
DAILY_TIMEFRAME = "1d"


def true_range(dataframe: DataFrame) -> pd.Series:
    previous = dataframe["close"].shift(1)
    return pd.concat(
        [
            dataframe["high"] - dataframe["low"],
            (dataframe["high"] - previous).abs(),
            (dataframe["low"] - previous).abs(),
        ],
        axis=1,
    ).max(axis=1)


def rsi_wilder(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)
    average_gain = gain.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    average_loss = loss.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    relative_strength = average_gain / average_loss.replace(0.0, float("nan"))
    rsi = 100.0 - (100.0 / (1.0 + relative_strength))
    return rsi.where(average_loss != 0.0, 100.0)


def informative_pairs(strategy: Any) -> list[tuple[str, str]]:
    if getattr(strategy, "dp", None) is None:
        return []
    pairs = set(strategy.dp.current_whitelist())
    pairs.add(BTC_PAIR)
    return sorted((pair, DAILY_TIMEFRAME) for pair in pairs)


def _pair_daily(dataframe: DataFrame) -> DataFrame:
    result = dataframe.copy().sort_values("date")
    result["pair_close"] = result["close"]
    result["pair_ema90"] = result["close"].ewm(span=90, adjust=False).mean()
    result["pair_return_20d"] = result["close"].pct_change(20, fill_method=None)
    result["pair_return_60d"] = result["close"].pct_change(60, fill_method=None)
    return result[
        ["date", "pair_close", "pair_ema90", "pair_return_20d", "pair_return_60d"]
    ]


def _btc_daily(dataframe: DataFrame) -> DataFrame:
    result = dataframe.copy().sort_values("date")
    result["btc_close"] = result["close"]
    result["btc_ema90"] = result["close"].ewm(span=90, adjust=False).mean()
    result["btc_ema20"] = result["close"].ewm(span=20, adjust=False).mean()
    result["btc_ema20_slope_5"] = result["btc_ema20"].pct_change(5, fill_method=None)
    result["btc_return_20d"] = result["close"].pct_change(20, fill_method=None)
    return result[
        ["date", "btc_close", "btc_ema90", "btc_ema20", "btc_ema20_slope_5", "btc_return_20d"]
    ]


def merge_daily_context(
    strategy: Any, dataframe: DataFrame, metadata: dict[str, Any]
) -> DataFrame:
    required = [
        "pair_close_1d",
        "pair_ema90_1d",
        "pair_return_20d_1d",
        "pair_return_60d_1d",
        "btc_close_1d",
        "btc_ema90_1d",
        "btc_ema20_1d",
        "btc_ema20_slope_5_1d",
        "btc_return_20d_1d",
    ]
    if getattr(strategy, "dp", None) is None:
        for column in required:
            dataframe[column] = float("nan")
        return dataframe

    pair_daily = _pair_daily(
        strategy.dp.get_pair_dataframe(pair=metadata["pair"], timeframe=DAILY_TIMEFRAME)
    )
    btc_daily = _btc_daily(
        strategy.dp.get_pair_dataframe(pair=BTC_PAIR, timeframe=DAILY_TIMEFRAME)
    )
    daily = pair_daily.merge(
        btc_daily,
        on="date",
        how="left",
        validate="one_to_one",
    ).sort_values("date")
    return merge_informative_pair(
        dataframe,
        daily,
        strategy.timeframe,
        DAILY_TIMEFRAME,
        ffill=True,
    )


def broad_regime(dataframe: DataFrame) -> pd.Series:
    return (
        (dataframe["btc_close_1d"] > dataframe["btc_ema90_1d"])
        & (dataframe["btc_ema20_slope_5_1d"] > 0.0)
    )


def pair_regime(dataframe: DataFrame) -> pd.Series:
    return dataframe["pair_close_1d"] > dataframe["pair_ema90_1d"]


def atr_stoploss_from_entry(
    strategy: Any,
    pair: str,
    trade: Trade,
    current_time: datetime,
    current_rate: float,
) -> float | None:
    del current_time
    if getattr(strategy, "dp", None) is None:
        return None
    dataframe, _ = strategy.dp.get_analyzed_dataframe(pair, strategy.timeframe)
    if dataframe.empty or "atr_14" not in dataframe:
        return None
    trade_date = timeframe_to_prev_date(strategy.timeframe, trade.open_date_utc)
    eligible = dataframe.loc[dataframe["date"] <= trade_date]
    if eligible.empty:
        return None
    entry_atr = float(eligible.iloc[-1]["atr_14"])
    if not math.isfinite(entry_atr) or entry_atr <= 0.0:
        return None
    stop_price = float(trade.open_rate) - 2.5 * entry_atr
    if not math.isfinite(stop_price) or stop_price <= 0.0:
        return None
    return stoploss_from_absolute(
        stop_price,
        current_rate=current_rate,
        is_short=trade.is_short,
        leverage=trade.leverage,
    )


class _C1ASettingsMixin:
    INTERFACE_VERSION = 3
    can_short = False
    timeframe = "1h"
    process_only_new_candles = True
    startup_candle_count = 1499
    use_exit_signal = True
    exit_profit_only = False
    ignore_roi_if_entry_signal = False
    minimal_roi = {}
    stoploss = -0.30

    def informative_pairs(self) -> list[tuple[str, str]]:
        return informative_pairs(self)


class _C1AATRStopMixin:
    use_custom_stoploss = True

    def custom_stoploss(
        self,
        pair: str,
        trade: Trade,
        current_time: datetime,
        current_rate: float,
        current_profit: float,
        **kwargs: Any,
    ) -> float | None:
        del current_profit, kwargs
        return atr_stoploss_from_entry(self, pair, trade, current_time, current_rate)


class C1ARegimeBreakout(_C1AATRStopMixin, _C1ASettingsMixin, IStrategy):
    """Broad-regime 20-day breakout with a 10-day channel exit."""

    def populate_indicators(self, dataframe: DataFrame, metadata: dict[str, Any]) -> DataFrame:
        dataframe["atr_14"] = true_range(dataframe).rolling(14).mean()
        dataframe["donchian_high_480"] = dataframe["high"].shift(1).rolling(480).max()
        dataframe["donchian_low_240"] = dataframe["low"].shift(1).rolling(240).min()
        return merge_daily_context(self, dataframe, metadata)

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict[str, Any]) -> DataFrame:
        del metadata
        dataframe["enter_long"] = 0
        dataframe["enter_tag"] = ""
        cross_up = (
            (dataframe["close"] > dataframe["donchian_high_480"])
            & (dataframe["close"].shift(1) <= dataframe["donchian_high_480"].shift(1))
        )
        signal = cross_up & broad_regime(dataframe) & pair_regime(dataframe) & (dataframe["volume"] > 0)
        dataframe.loc[signal, ["enter_long", "enter_tag"]] = (1, "c1a_regime_breakout")
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict[str, Any]) -> DataFrame:
        del metadata
        dataframe["exit_long"] = 0
        dataframe["exit_tag"] = ""
        cross_down = (
            (dataframe["close"] < dataframe["donchian_low_240"])
            & (dataframe["close"].shift(1) >= dataframe["donchian_low_240"].shift(1))
        )
        regime_failure = ~broad_regime(dataframe) | ~pair_regime(dataframe)
        dataframe.loc[cross_down & (dataframe["volume"] > 0), ["exit_long", "exit_tag"]] = (
            1,
            "c1a_donchian_failure",
        )
        dataframe.loc[
            regime_failure & (dataframe["volume"] > 0) & (dataframe["exit_long"] == 0),
            ["exit_long", "exit_tag"],
        ] = (1, "c1a_regime_failure")
        return dataframe


class C1ATrendPullback(_C1AATRStopMixin, _C1ASettingsMixin, IStrategy):
    """Broad-regime hourly pullback entry with deterministic exits."""

    def populate_indicators(self, dataframe: DataFrame, metadata: dict[str, Any]) -> DataFrame:
        dataframe["ema20_1h"] = dataframe["close"].ewm(span=20, adjust=False).mean()
        dataframe["rsi14_1h"] = rsi_wilder(dataframe["close"], 14)
        dataframe["atr_14"] = true_range(dataframe).rolling(14).mean()
        return merge_daily_context(self, dataframe, metadata)

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict[str, Any]) -> DataFrame:
        del metadata
        dataframe["enter_long"] = 0
        dataframe["enter_tag"] = ""
        signal = (
            broad_regime(dataframe)
            & pair_regime(dataframe)
            & (dataframe["close"] < dataframe["ema20_1h"])
            & (dataframe["rsi14_1h"] <= 35.0)
            & (dataframe["volume"] > 0)
        )
        dataframe.loc[signal, ["enter_long", "enter_tag"]] = (1, "c1a_trend_pullback")
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict[str, Any]) -> DataFrame:
        del metadata
        dataframe["exit_long"] = 0
        dataframe["exit_tag"] = ""
        mean_recovery = (dataframe["close"] >= dataframe["ema20_1h"]) | (dataframe["rsi14_1h"] >= 55.0)
        regime_failure = ~broad_regime(dataframe) | ~pair_regime(dataframe)
        dataframe.loc[
            mean_recovery & (dataframe["volume"] > 0), ["exit_long", "exit_tag"]
        ] = (1, "c1a_pullback_recovered")
        dataframe.loc[
            regime_failure & (dataframe["volume"] > 0) & (dataframe["exit_long"] == 0),
            ["exit_long", "exit_tag"],
        ] = (1, "c1a_regime_failure")
        return dataframe

    def custom_exit(
        self,
        pair: str,
        trade: Trade,
        current_time: datetime,
        current_rate: float,
        current_profit: float,
        **kwargs: Any,
    ) -> str | None:
        del pair, current_rate, current_profit, kwargs
        if current_time - trade.open_date_utc >= timedelta(hours=168):
            return "c1a_168h_time_stop"
        return None


class C1ADualMomentum(_C1ASettingsMixin, IStrategy):
    """Completed-daily-candle absolute and relative momentum candidate."""

    @staticmethod
    def _condition(dataframe: DataFrame, pair: str) -> pd.Series:
        condition = (
            broad_regime(dataframe)
            & pair_regime(dataframe)
            & (dataframe["pair_return_20d_1d"] > 0.0)
            & (dataframe["pair_return_60d_1d"] > 0.0)
        )
        if pair != BTC_PAIR:
            condition &= dataframe["pair_return_20d_1d"] > dataframe["btc_return_20d_1d"]
        return condition

    def populate_indicators(self, dataframe: DataFrame, metadata: dict[str, Any]) -> DataFrame:
        return merge_daily_context(self, dataframe, metadata)

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict[str, Any]) -> DataFrame:
        dataframe["enter_long"] = 0
        dataframe["enter_tag"] = ""
        condition = self._condition(dataframe, metadata["pair"])
        event = condition & ~condition.shift(1).fillna(False)
        dataframe.loc[event & (dataframe["volume"] > 0), ["enter_long", "enter_tag"]] = (
            1,
            "c1a_dual_momentum",
        )
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict[str, Any]) -> DataFrame:
        dataframe["exit_long"] = 0
        dataframe["exit_tag"] = ""
        condition = self._condition(dataframe, metadata["pair"])
        failure = ~condition
        dataframe.loc[failure & (dataframe["volume"] > 0), ["exit_long", "exit_tag"]] = (
            1,
            "c1a_momentum_failure",
        )
        return dataframe
