"""Relative strength index indicator."""

from __future__ import annotations

import pandas as pd


def calculate_rsi(data: pd.DataFrame, period: int = 14, price_column: str = "close") -> pd.Series:
    """Calculate Wilder's relative strength index."""

    if period <= 0:
        raise ValueError("period must be greater than zero.")
    if price_column not in data.columns:
        raise ValueError(f"Missing price column: {price_column}.")

    prices = pd.to_numeric(data[price_column], errors="coerce")
    delta = prices.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)

    average_gain = gain.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    average_loss = loss.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()

    relative_strength = average_gain / average_loss
    rsi = 100 - (100 / (1 + relative_strength))
    rsi = rsi.mask((average_loss == 0) & (average_gain > 0), 100)
    rsi = rsi.mask((average_gain == 0) & (average_loss > 0), 0)
    rsi = rsi.mask((average_gain == 0) & (average_loss == 0), 50)
    return rsi
