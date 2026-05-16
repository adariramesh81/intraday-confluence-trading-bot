"""Volume-weighted average price indicator."""

from __future__ import annotations

from zoneinfo import ZoneInfo

import pandas as pd


def calculate_vwap(data: pd.DataFrame, timezone: str = "America/New_York") -> pd.DataFrame:
    """Return data with VWAP reset for each market date."""

    _validate_vwap_columns(data)
    result = data.copy()
    timestamps = pd.to_datetime(result["timestamp"], utc=True)
    market_dates = timestamps.dt.tz_convert(ZoneInfo(timezone)).dt.date
    typical_price = (
        pd.to_numeric(result["high"], errors="coerce")
        + pd.to_numeric(result["low"], errors="coerce")
        + pd.to_numeric(result["close"], errors="coerce")
    ) / 3
    volume = pd.to_numeric(result["volume"], errors="coerce")

    group_keys: list[pd.Series] = [pd.Series(market_dates, index=result.index)]
    if "symbol" in result.columns:
        group_keys.insert(0, result["symbol"])

    cumulative_price_volume = (typical_price * volume).groupby(group_keys).cumsum()
    cumulative_volume = volume.groupby(group_keys).cumsum()
    result["vwap"] = cumulative_price_volume / cumulative_volume.where(cumulative_volume != 0)
    return result


def _validate_vwap_columns(data: pd.DataFrame) -> None:
    missing_columns = [
        column for column in ["timestamp", "high", "low", "close", "volume"] if column not in data.columns
    ]
    if missing_columns:
        raise ValueError(f"Missing VWAP columns: {missing_columns}.")
