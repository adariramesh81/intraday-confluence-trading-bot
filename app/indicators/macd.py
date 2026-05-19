"""Moving average convergence/divergence indicator."""

from __future__ import annotations

import pandas as pd


def calculate_macd(
    data: pd.DataFrame,
    fast_period: int = 12,
    slow_period: int = 26,
    signal_period: int = 9,
    price_column: str = "close",
) -> pd.DataFrame:
    """Return data with MACD, signal, histogram, and bearish cross columns."""

    if fast_period <= 0 or slow_period <= 0 or signal_period <= 0:
        raise ValueError("MACD periods must be greater than zero.")
    if fast_period >= slow_period:
        raise ValueError("fast_period must be less than slow_period.")
    if price_column not in data.columns:
        raise ValueError(f"Missing price column: {price_column}.")

    result = data.copy()
    prices = pd.to_numeric(result[price_column], errors="coerce")
    fast_ema = prices.ewm(span=fast_period, adjust=False, min_periods=fast_period).mean()
    slow_ema = prices.ewm(span=slow_period, adjust=False, min_periods=slow_period).mean()
    macd = fast_ema - slow_ema
    signal = macd.ewm(span=signal_period, adjust=False, min_periods=signal_period).mean()

    result["macd"] = macd
    result["macd_signal"] = signal
    result["macd_histogram"] = macd - signal
    previous_macd = macd.shift(1)
    previous_signal = signal.shift(1)
    result["macd_bearish_cross"] = (macd < signal) & (previous_macd >= previous_signal)
    return result
