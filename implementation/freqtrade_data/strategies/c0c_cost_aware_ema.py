"""C0C V1 cost-aware EMA research candidate. Backtest-only; LIVE forbidden."""
from __future__ import annotations

from typing import Any
import pandas as pd
from pandas import DataFrame
from freqtrade.strategy import DecimalParameter, IStrategy, merge_informative_pair


class C0CCostAwareEMA(IStrategy):
    INTERFACE_VERSION = 3
    can_short = False
    timeframe = "5m"
    process_only_new_candles = True
    startup_candle_count = 1499
    use_exit_signal = True
    exit_profit_only = False
    ignore_roi_if_entry_signal = False
    stoploss = -0.05
    minimal_roi = {"0": 0.04, "720": 0.02, "1440": 0.0}

    enter_spread_threshold = DecimalParameter(0.001, 0.008, decimals=3, default=0.003, space="enter")
    enter_slow_slope_min = DecimalParameter(0.001, 0.010, decimals=3, default=0.003, space="enter")
    enter_atr_ratio_min = DecimalParameter(0.002, 0.012, decimals=3, default=0.004, space="enter")
    enter_htf_slope_min = DecimalParameter(0.000, 0.010, decimals=3, default=0.002, space="enter")

    def informative_pairs(self) -> list[tuple[str, str]]:
        if getattr(self, "dp", None) is None:
            return []
        return [(pair, "1h") for pair in self.dp.current_whitelist()]

    @staticmethod
    def _true_range(dataframe: DataFrame) -> pd.Series:
        previous = dataframe["close"].shift(1)
        return pd.concat(
            [
                dataframe["high"] - dataframe["low"],
                (dataframe["high"] - previous).abs(),
                (dataframe["low"] - previous).abs(),
            ],
            axis=1,
        ).max(axis=1)

    def populate_indicators(self, dataframe: DataFrame, metadata: dict[str, Any]) -> DataFrame:
        dataframe["ema_fast_20"] = dataframe["close"].ewm(span=20, adjust=False).mean()
        dataframe["ema_slow_50"] = dataframe["close"].ewm(span=50, adjust=False).mean()
        dataframe["ema_spread"] = dataframe["ema_fast_20"] / dataframe["ema_slow_50"] - 1
        dataframe["slow_slope_12"] = dataframe["ema_slow_50"].pct_change(12)
        dataframe["atr_ratio_14"] = self._true_range(dataframe).rolling(14).mean() / dataframe["close"]

        if getattr(self, "dp", None) is None:
            dataframe["htf_ema_100_1h"] = float("nan")
            dataframe["htf_slope_6_1h"] = float("nan")
            dataframe["close_1h"] = float("nan")
            return dataframe
        informative = self.dp.get_pair_dataframe(pair=metadata["pair"], timeframe="1h").copy()
        informative["htf_ema_100"] = informative["close"].ewm(span=100, adjust=False).mean()
        informative["htf_slope_6"] = informative["htf_ema_100"].pct_change(6)
        informative = informative[["date", "close", "htf_ema_100", "htf_slope_6"]]
        return merge_informative_pair(dataframe, informative, self.timeframe, "1h", ffill=True)

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict[str, Any]) -> DataFrame:
        dataframe["enter_long"] = 0
        dataframe["enter_tag"] = ""
        threshold = float(self.enter_spread_threshold.value)
        trigger = (dataframe["ema_spread"] > threshold) & (dataframe["ema_spread"].shift(1) <= threshold)
        guards = (
            (dataframe["slow_slope_12"] > float(self.enter_slow_slope_min.value))
            & (dataframe["atr_ratio_14"] > float(self.enter_atr_ratio_min.value))
            & (dataframe["htf_slope_6_1h"] > float(self.enter_htf_slope_min.value))
            & (dataframe["close_1h"] > dataframe["htf_ema_100_1h"])
            & (dataframe["volume"] > 0)
        )
        dataframe.loc[trigger & guards, ["enter_long", "enter_tag"]] = (1, "c0c_cost_aware_ema")
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict[str, Any]) -> DataFrame:
        dataframe["exit_long"] = 0
        dataframe["exit_tag"] = ""
        trigger = (
            (dataframe["ema_fast_20"] < dataframe["ema_slow_50"])
            & (dataframe["ema_fast_20"].shift(1) >= dataframe["ema_slow_50"].shift(1))
            & (dataframe["volume"] > 0)
        )
        dataframe.loc[trigger, ["exit_long", "exit_tag"]] = (1, "c0c_ema_cross_down")
        return dataframe
