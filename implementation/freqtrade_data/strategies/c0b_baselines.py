"""C0B deterministic Freqtrade baselines.

These strategies are deliberately small, vectorized, long-only and independent
of the ATOS provider/router.  They are research baselines, not live strategies.
"""

from __future__ import annotations

from typing import Any

import pandas as pd
from pandas import DataFrame
from freqtrade.strategy import IStrategy, merge_informative_pair


def _rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    relative_strength = gain / loss.replace(0, float("nan"))
    return (100 - (100 / (1 + relative_strength))).fillna(50.0)


def _true_range(dataframe: DataFrame) -> pd.Series:
    previous_close = dataframe["close"].shift(1)
    return pd.concat(
        [
            dataframe["high"] - dataframe["low"],
            (dataframe["high"] - previous_close).abs(),
            (dataframe["low"] - previous_close).abs(),
        ],
        axis=1,
    ).max(axis=1)


class _C0BMixin:
    INTERFACE_VERSION = 3
    can_short = False
    timeframe = "5m"
    process_only_new_candles = True
    startup_candle_count = 240
    use_exit_signal = True
    exit_profit_only = False
    ignore_roi_if_entry_signal = False

    @staticmethod
    def _initialize_signals(dataframe: DataFrame) -> DataFrame:
        dataframe["enter_long"] = 0
        dataframe["exit_long"] = 0
        dataframe["enter_tag"] = ""
        dataframe["exit_tag"] = ""
        return dataframe


class C0BEMATrend(_C0BMixin, IStrategy):
    """EMA crossover with positive slow-trend and volatility guards."""

    stoploss = -0.05
    minimal_roi = {"0": 0.04, "720": 0.02, "1440": 0.0}

    def populate_indicators(self, dataframe: DataFrame, metadata: dict[str, Any]) -> DataFrame:
        dataframe["ema_fast"] = dataframe["close"].ewm(span=20, adjust=False).mean()
        dataframe["ema_slow"] = dataframe["close"].ewm(span=50, adjust=False).mean()
        dataframe["slow_slope_10"] = dataframe["ema_slow"].pct_change(10)
        dataframe["return_vol_20"] = dataframe["close"].pct_change().rolling(20).std()
        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict[str, Any]) -> DataFrame:
        dataframe = self._initialize_signals(dataframe)
        crossed_above = (
            (dataframe["ema_fast"] > dataframe["ema_slow"])
            & (dataframe["ema_fast"].shift(1) <= dataframe["ema_slow"].shift(1))
        )
        guard = (
            (dataframe["slow_slope_10"] > 0.001)
            & dataframe["return_vol_20"].between(0.0005, 0.04)
            & (dataframe["volume"] > 0)
        )
        dataframe.loc[crossed_above & guard, ["enter_long", "enter_tag"]] = (
            1,
            "c0b_ema_trend",
        )
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict[str, Any]) -> DataFrame:
        crossed_below = (
            (dataframe["ema_fast"] < dataframe["ema_slow"])
            & (dataframe["ema_fast"].shift(1) >= dataframe["ema_slow"].shift(1))
        )
        dataframe.loc[
            crossed_below & (dataframe["volume"] > 0),
            ["exit_long", "exit_tag"],
        ] = (1, "c0b_ema_cross_down")
        return dataframe


class C0BDonchianBreakout(_C0BMixin, IStrategy):
    """Prior-channel Donchian breakout with normalized ATR guard."""

    stoploss = -0.06
    minimal_roi = {"0": 0.06, "1440": 0.02, "2880": 0.0}

    def populate_indicators(self, dataframe: DataFrame, metadata: dict[str, Any]) -> DataFrame:
        dataframe["donchian_upper_20"] = dataframe["high"].shift(1).rolling(20).max()
        dataframe["donchian_lower_10"] = dataframe["low"].shift(1).rolling(10).min()
        dataframe["atr_14"] = _true_range(dataframe).rolling(14).mean()
        dataframe["atr_ratio"] = dataframe["atr_14"] / dataframe["close"]
        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict[str, Any]) -> DataFrame:
        dataframe = self._initialize_signals(dataframe)
        breakout = (
            (dataframe["close"] > dataframe["donchian_upper_20"])
            & (dataframe["close"].shift(1) <= dataframe["donchian_upper_20"].shift(1))
        )
        guard = dataframe["atr_ratio"].between(0.001, 0.08) & (dataframe["volume"] > 0)
        dataframe.loc[breakout & guard, ["enter_long", "enter_tag"]] = (
            1,
            "c0b_donchian_breakout",
        )
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict[str, Any]) -> DataFrame:
        exit_signal = dataframe["close"] < dataframe["donchian_lower_10"]
        dataframe.loc[
            exit_signal & (dataframe["volume"] > 0),
            ["exit_long", "exit_tag"],
        ] = (1, "c0b_donchian_channel_exit")
        return dataframe


class C0BMeanReversion(_C0BMixin, IStrategy):
    """RSI/Bollinger mean reversion with a genuinely higher-timeframe trend guard."""

    stoploss = -0.035
    minimal_roi = {"0": 0.025, "720": 0.01, "1440": 0.0}

    _HIGHER_TIMEFRAME = {"5m": "1h", "15m": "4h", "1h": "4h"}

    def _informative_timeframe(self) -> str:
        return self._HIGHER_TIMEFRAME.get(self.timeframe, "4h")

    def informative_pairs(self) -> list[tuple[str, str]]:
        if getattr(self, "dp", None) is None:
            return []
        timeframe = self._informative_timeframe()
        return [(pair, timeframe) for pair in self.dp.current_whitelist()]

    def populate_indicators(self, dataframe: DataFrame, metadata: dict[str, Any]) -> DataFrame:
        middle = dataframe["close"].rolling(20).mean()
        deviation = dataframe["close"].rolling(20).std(ddof=0)
        dataframe["bb_middle_20"] = middle
        dataframe["bb_lower_20"] = middle - 2 * deviation
        dataframe["rsi_14"] = _rsi(dataframe["close"], 14)

        informative_timeframe = self._informative_timeframe()
        if getattr(self, "dp", None) is None:
            dataframe["htf_trend_ok"] = False
            return dataframe

        informative = self.dp.get_pair_dataframe(
            pair=metadata["pair"],
            timeframe=informative_timeframe,
        ).copy()
        informative["htf_ema_100"] = informative["close"].ewm(span=100, adjust=False).mean()
        informative["htf_trend_ok"] = informative["close"] > informative["htf_ema_100"]
        informative = informative[["date", "htf_trend_ok"]]
        dataframe = merge_informative_pair(
            dataframe,
            informative,
            self.timeframe,
            informative_timeframe,
            ffill=True,
        )
        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict[str, Any]) -> DataFrame:
        dataframe = self._initialize_signals(dataframe)
        guard_column = f"htf_trend_ok_{self._informative_timeframe()}"
        if guard_column not in dataframe:
            dataframe[guard_column] = False
        entry = (
            (dataframe["close"] < dataframe["bb_lower_20"])
            & (dataframe["rsi_14"] < 30)
            & dataframe[guard_column].fillna(False).astype(bool)
            & (dataframe["volume"] > 0)
        )
        dataframe.loc[entry, ["enter_long", "enter_tag"]] = (
            1,
            "c0b_mean_reversion",
        )
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict[str, Any]) -> DataFrame:
        exit_signal = (dataframe["close"] >= dataframe["bb_middle_20"]) | (
            dataframe["rsi_14"] > 55
        )
        dataframe.loc[
            exit_signal & (dataframe["volume"] > 0),
            ["exit_long", "exit_tag"],
        ] = (1, "c0b_mean_reversion_exit")
        return dataframe
