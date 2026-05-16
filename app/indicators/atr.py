"""Average true range indicator."""

from __future__ import annotations

import pandas as pd


def calculate_true_range(data: pd.DataFrame) -> pd.Series:
    """Calculate true range for OHLC data."""

    _validate_ohlc_columns(data)
    high = pd.to_numeric(data["high"], errors="coerce")
    low = pd.to_numeric(data["low"], errors="coerce")
    close = pd.to_numeric(data["close"], errors="coerce")
    previous_close = close.shift(1)

    ranges = pd.concat(
        [
            high - low,
            (high - previous_close).abs(),
            (low - previous_close).abs(),
        ],
        axis=1,
    )
    return ranges.max(axis=1)


def calculate_atr(data: pd.DataFrame, period: int = 14) -> pd.Series:
    """Calculate Wilder's average true range."""

    if period <= 0:
        raise ValueError("period must be greater than zero.")

    true_range = calculate_true_range(data)
    return true_range.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()


def _validate_ohlc_columns(data: pd.DataFrame) -> None:
    missing_columns = [column for column in ["high", "low", "close"] if column not in data.columns]
    if missing_columns:
        raise ValueError(f"Missing OHLC columns: {missing_columns}.")
