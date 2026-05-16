"""Supertrend indicator."""

from __future__ import annotations

import pandas as pd

from app.indicators.atr import calculate_atr


def calculate_supertrend(
    data: pd.DataFrame,
    atr_period: int = 10,
    multiplier: float = 3.0,
) -> pd.DataFrame:
    """Return data with Supertrend line, bands, and trend direction."""

    if atr_period <= 0:
        raise ValueError("atr_period must be greater than zero.")
    if multiplier <= 0:
        raise ValueError("multiplier must be greater than zero.")
    _validate_supertrend_columns(data)

    result = data.copy()
    high = pd.to_numeric(result["high"], errors="coerce")
    low = pd.to_numeric(result["low"], errors="coerce")
    close = pd.to_numeric(result["close"], errors="coerce")
    atr = calculate_atr(result, atr_period)
    hl2 = (high + low) / 2
    basic_upper = hl2 + (multiplier * atr)
    basic_lower = hl2 - (multiplier * atr)

    final_upper = pd.Series(index=result.index, dtype="float64")
    final_lower = pd.Series(index=result.index, dtype="float64")
    supertrend = pd.Series(index=result.index, dtype="float64")
    direction = pd.Series(index=result.index, dtype="Int64")

    for position in range(len(result)):
        if pd.isna(atr.iloc[position]):
            continue

        if position == 0 or pd.isna(final_upper.iloc[position - 1]):
            final_upper.iloc[position] = basic_upper.iloc[position]
            final_lower.iloc[position] = basic_lower.iloc[position]
            direction.iloc[position] = 1
            supertrend.iloc[position] = final_lower.iloc[position]
            continue

        previous_close = close.iloc[position - 1]
        previous_upper = final_upper.iloc[position - 1]
        previous_lower = final_lower.iloc[position - 1]

        if basic_upper.iloc[position] < previous_upper or previous_close > previous_upper:
            final_upper.iloc[position] = basic_upper.iloc[position]
        else:
            final_upper.iloc[position] = previous_upper

        if basic_lower.iloc[position] > previous_lower or previous_close < previous_lower:
            final_lower.iloc[position] = basic_lower.iloc[position]
        else:
            final_lower.iloc[position] = previous_lower

        previous_direction = direction.iloc[position - 1]
        if close.iloc[position] > final_upper.iloc[position - 1]:
            current_direction = 1
        elif close.iloc[position] < final_lower.iloc[position - 1]:
            current_direction = -1
        else:
            current_direction = int(previous_direction)

        direction.iloc[position] = current_direction
        supertrend.iloc[position] = final_lower.iloc[position] if current_direction == 1 else final_upper.iloc[position]

    result["supertrend_atr"] = atr
    result["supertrend_upper_band"] = final_upper
    result["supertrend_lower_band"] = final_lower
    result["supertrend"] = supertrend
    result["supertrend_direction"] = direction
    return result


def _validate_supertrend_columns(data: pd.DataFrame) -> None:
    missing_columns = [column for column in ["high", "low", "close"] if column not in data.columns]
    if missing_columns:
        raise ValueError(f"Missing Supertrend columns: {missing_columns}.")
