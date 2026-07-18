from __future__ import annotations

from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd

from .c3a_residual_common import C3AError, PAIR_TO_ASSET


def frame_from_rows(rows_by_pair: Mapping[str, Sequence[Mapping[str, Any]]]) -> pd.DataFrame:
    if set(rows_by_pair) != set(PAIR_TO_ASSET):
        raise C3AError("C3A requires exactly BTC/USDT, ETH/USDT, and SOL/USDT")
    frames: list[pd.DataFrame] = []
    expected_index: pd.DatetimeIndex | None = None
    for pair, asset in PAIR_TO_ASSET.items():
        rows = rows_by_pair[pair]
        if not rows:
            raise C3AError(f"no candles for {pair}")
        frame = pd.DataFrame([dict(row) for row in rows])
        required = {"date", "open", "close"}
        missing = required.difference(frame.columns)
        if missing:
            raise C3AError(f"{pair} missing columns: {sorted(missing)}")
        index = pd.DatetimeIndex(pd.to_datetime(frame["date"], utc=True))
        if index.has_duplicates:
            raise C3AError(f"duplicate timestamps for {pair}")
        if not index.is_monotonic_increasing:
            raise C3AError(f"unordered timestamps for {pair}")
        if expected_index is None:
            expected_index = index
        elif not index.equals(expected_index):
            raise C3AError(f"misaligned timestamps for {pair}")
        local = pd.DataFrame(index=index)
        local[f"{asset}_open"] = pd.to_numeric(frame["open"], errors="coerce").to_numpy()
        local[f"{asset}_close"] = pd.to_numeric(frame["close"], errors="coerce").to_numpy()
        if not np.isfinite(local.to_numpy(dtype=float)).all():
            raise C3AError(f"non-finite prices for {pair}")
        if (local <= 0).any().any():
            raise C3AError(f"non-positive prices for {pair}")
        frames.append(local)
    result = pd.concat(frames, axis=1)
    result.index.name = "date"
    return result


def compute_indicators(frame: pd.DataFrame) -> pd.DataFrame:
    required = {
        "BTC_open",
        "BTC_close",
        "ETH_open",
        "ETH_close",
        "SOL_open",
        "SOL_close",
    }
    missing = required.difference(frame.columns)
    if missing:
        raise C3AError(f"missing price columns: {sorted(missing)}")
    result = frame.copy()
    btc_return = np.log(result["BTC_close"] / result["BTC_close"].shift(1))
    result["BTC_return"] = btc_return
    for asset in ("ETH", "SOL"):
        asset_return = np.log(result[f"{asset}_close"] / result[f"{asset}_close"].shift(1))
        result[f"{asset}_return"] = asset_return
        x = btc_return.shift(1)
        y = asset_return.shift(1)
        mean_x = x.rolling(180, min_periods=180).mean()
        mean_y = y.rolling(180, min_periods=180).mean()
        cov = (x * y).rolling(180, min_periods=180).mean() - mean_x * mean_y
        var = (x * x).rolling(180, min_periods=180).mean() - mean_x * mean_x
        beta = cov / var
        beta = beta.where(np.isfinite(beta) & (var > 0)).clip(lower=0.25, upper=2.50)
        residual = asset_return - beta * btc_return
        cumulative = residual.rolling(6, min_periods=6).sum()
        reference = cumulative.shift(1)
        reference_mean = reference.rolling(180, min_periods=180).mean()
        reference_std = reference.rolling(180, min_periods=180).std(ddof=0)
        z = (cumulative - reference_mean) / reference_std
        z = z.where(np.isfinite(z) & (reference_std > 0))
        result[f"{asset}_beta"] = beta
        result[f"{asset}_residual"] = residual
        result[f"{asset}_residual_6"] = cumulative
        result[f"{asset}_z"] = z
    result["BTC_sma300"] = result["BTC_close"].rolling(300, min_periods=300).mean()
    result["btc_regime_on"] = result["BTC_close"] >= result["BTC_sma300"]
    return result
