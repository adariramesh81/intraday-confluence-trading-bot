"""Bollinger Bands indicators."""

from __future__ import annotations

import pandas as pd


def calculate_bollinger_bands(
    data: pd.DataFrame,
    period: int = 20,
    std_dev: float = 2.0,
    price_column: str = "close",
) -> pd.DataFrame:
    """Return data with Bollinger Band columns."""

    if period <= 0:
        raise ValueError("period must be greater than zero.")
    if std_dev <= 0:
        raise ValueError("std_dev must be greater than zero.")
    if price_column not in data.columns:
        raise ValueError(f"Missing price column: {price_column}.")

    result = data.copy()
    prices = pd.to_numeric(result[price_column], errors="coerce")
    middle = prices.rolling(window=period, min_periods=period).mean()
    rolling_std = prices.rolling(window=period, min_periods=period).std(ddof=0)
    upper = middle + (rolling_std * std_dev)
    lower = middle - (rolling_std * std_dev)

    result["bb_middle"] = middle
    result["bb_upper"] = upper
    result["bb_lower"] = lower
    result["bb_bandwidth"] = (upper - lower) / middle
    result["bb_percent_b"] = (prices - lower) / (upper - lower)
    return result
