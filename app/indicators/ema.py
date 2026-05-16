"""Exponential moving average indicators."""

from __future__ import annotations

import pandas as pd


def calculate_ema(data: pd.DataFrame, period: int, price_column: str = "close") -> pd.Series:
    """Calculate an exponential moving average for a price column."""

    _validate_period(period)
    _validate_price_column(data, price_column)
    prices = pd.to_numeric(data[price_column], errors="coerce")
    return prices.ewm(span=period, adjust=False, min_periods=period).mean()


def add_ema_columns(
    data: pd.DataFrame,
    fast_period: int = 9,
    slow_period: int = 21,
    price_column: str = "close",
) -> pd.DataFrame:
    """Return data with fast EMA, slow EMA, and crossover marker columns."""

    if fast_period >= slow_period:
        raise ValueError("fast_period must be less than slow_period.")

    result = data.copy()
    result[f"ema_{fast_period}"] = calculate_ema(result, fast_period, price_column)
    result[f"ema_{slow_period}"] = calculate_ema(result, slow_period, price_column)
    fast = result[f"ema_{fast_period}"]
    slow = result[f"ema_{slow_period}"]
    previous_fast = fast.shift(1)
    previous_slow = slow.shift(1)
    result["ema_crossover"] = 0
    result.loc[(fast > slow) & (previous_fast <= previous_slow), "ema_crossover"] = 1
    result.loc[(fast < slow) & (previous_fast >= previous_slow), "ema_crossover"] = -1
    return result


def _validate_period(period: int) -> None:
    if period <= 0:
        raise ValueError("period must be greater than zero.")


def _validate_price_column(data: pd.DataFrame, price_column: str) -> None:
    if price_column not in data.columns:
        raise ValueError(f"Missing price column: {price_column}.")
