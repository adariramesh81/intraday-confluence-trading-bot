"""Validation helpers for symbols, timeframes, and OHLCV data."""

from __future__ import annotations

import re
from typing import Iterable

import pandas as pd

OHLCV_COLUMNS = ["timestamp", "open", "high", "low", "close", "volume"]
VALID_TIMEFRAMES = {
    "1Min",
    "2Min",
    "3Min",
    "5Min",
    "10Min",
    "15Min",
    "30Min",
    "45Min",
    "1Hour",
    "2Hour",
    "4Hour",
    "1Day",
}
_SYMBOL_PATTERN = re.compile(r"^[A-Z][A-Z0-9.\-]{0,14}$")


class DataValidationError(ValueError):
    """Raised when market data fails validation."""


def validate_symbol(symbol: str) -> str:
    """Validate and normalize an equity symbol."""

    normalized = symbol.strip().upper()
    if not _SYMBOL_PATTERN.match(normalized):
        raise DataValidationError(f"Invalid symbol: {symbol!r}.")
    return normalized


def validate_symbols(symbols: str | Iterable[str]) -> list[str]:
    """Validate one or more equity symbols."""

    if isinstance(symbols, str):
        return [validate_symbol(symbols)]

    validated = [validate_symbol(symbol) for symbol in symbols]
    if not validated:
        raise DataValidationError("At least one symbol is required.")
    return validated


def validate_timeframe(timeframe: str) -> str:
    """Validate and normalize a market data timeframe."""

    normalized = timeframe.strip()
    if normalized not in VALID_TIMEFRAMES:
        raise DataValidationError(f"Unsupported timeframe: {timeframe!r}.")
    return normalized


def validate_ohlcv_dataframe(data: pd.DataFrame) -> pd.DataFrame:
    """Validate canonical OHLCV data and return a timestamp-sorted copy."""

    if data.empty:
        raise DataValidationError("OHLCV data is empty.")

    missing_columns = [column for column in OHLCV_COLUMNS if column not in data.columns]
    if missing_columns:
        raise DataValidationError(f"OHLCV data is missing columns: {missing_columns}.")

    validated = data.copy()
    validated["timestamp"] = pd.to_datetime(validated["timestamp"], utc=True)

    numeric_columns = ["open", "high", "low", "close", "volume"]
    for column in numeric_columns:
        validated[column] = pd.to_numeric(validated[column], errors="coerce")

    if validated[OHLCV_COLUMNS].isna().any().any():
        raise DataValidationError("OHLCV data contains null or non-numeric values.")

    if (validated[["open", "high", "low", "close"]] <= 0).any().any():
        raise DataValidationError("OHLC prices must be greater than zero.")

    if (validated["volume"] < 0).any():
        raise DataValidationError("Volume cannot be negative.")

    if (validated["high"] < validated[["open", "close", "low"]].max(axis=1)).any():
        raise DataValidationError("High must be greater than or equal to open, close, and low.")

    if (validated["low"] > validated[["open", "close", "high"]].min(axis=1)).any():
        raise DataValidationError("Low must be less than or equal to open, close, and high.")

    sort_columns = ["timestamp"]
    if "symbol" in validated.columns:
        sort_columns.insert(0, "symbol")
    return validated.sort_values(sort_columns).reset_index(drop=True)
