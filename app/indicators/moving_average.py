"""Simple moving average indicator."""

from __future__ import annotations

import pandas as pd


def calculate_sma(data: pd.DataFrame, period: int, price_column: str = "close") -> pd.Series:
    """Calculate a simple moving average for a price column."""

    if period <= 0:
        raise ValueError("period must be greater than zero.")
    if price_column not in data.columns:
        raise ValueError(f"Missing price column: {price_column}.")
    prices = pd.to_numeric(data[price_column], errors="coerce")
    return prices.rolling(window=period, min_periods=period).mean()
