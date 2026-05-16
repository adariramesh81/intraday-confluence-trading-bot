"""Trade filters and institutional market bias helpers."""

from __future__ import annotations

from datetime import time
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd

from app.strategy.types import MarketBias, StrategySettings


def determine_market_bias(row: pd.Series) -> MarketBias:
    """Determine institutional market bias from Supertrend and VWAP alignment."""

    close = _value(row, "close")
    vwap = _value(row, "vwap")
    supertrend_direction = _value(row, "supertrend_direction")

    if pd.isna(close) or pd.isna(vwap) or pd.isna(supertrend_direction):
        return MarketBias.NEUTRAL
    if int(supertrend_direction) == 1 and close > vwap:
        return MarketBias.BULLISH
    if int(supertrend_direction) == -1 and close < vwap:
        return MarketBias.BEARISH
    return MarketBias.NEUTRAL


def evaluate_trade_filters(
    data: pd.DataFrame,
    index: int,
    settings: StrategySettings | None = None,
) -> list[str]:
    """Return no-trade filter reasons for a candidate signal row."""

    config = settings or StrategySettings()
    row = data.iloc[index]
    reasons: list[str] = []

    if _is_rsi_neutral(row, config):
        reasons.append("RSI is in the 45-55 no-trade zone.")
    if _is_first_five_minutes(row, config):
        reasons.append("Within first five minutes after market open.")
    if _is_vwap_flat(data, index, config):
        reasons.append("VWAP is flat.")
    if _has_frequent_supertrend_flips(data, index, config):
        reasons.append("Supertrend flipped too frequently.")
    if _is_bollinger_squeeze(row, config):
        reasons.append("Bollinger Bands are in a squeeze.")
    if _is_low_liquidity(row, config):
        reasons.append("Volume indicates low liquidity.")

    return reasons


def _is_rsi_neutral(row: pd.Series, settings: StrategySettings) -> bool:
    rsi = _value(row, "rsi")
    return not pd.isna(rsi) and settings.rsi_neutral_lower <= rsi <= settings.rsi_neutral_upper


def _is_first_five_minutes(row: pd.Series, settings: StrategySettings) -> bool:
    timestamp = row.get("timestamp")
    if timestamp is None or pd.isna(timestamp):
        return False

    market_timestamp = pd.Timestamp(timestamp)
    if market_timestamp.tzinfo is None:
        market_timestamp = market_timestamp.tz_localize(ZoneInfo(settings.market_timezone))
    else:
        market_timestamp = market_timestamp.tz_convert(ZoneInfo(settings.market_timezone))

    market_time = market_timestamp.time()
    return time(9, 30) <= market_time < time(9, 35)


def _is_vwap_flat(data: pd.DataFrame, index: int, settings: StrategySettings) -> bool:
    if "vwap" not in data.columns or index <= 0:
        return False

    start = max(0, index - settings.vwap_flat_lookback)
    window = pd.to_numeric(data.iloc[start : index + 1]["vwap"], errors="coerce").dropna()
    if len(window) < 2:
        return False

    current_vwap = window.iloc[-1]
    if current_vwap == 0:
        return False

    slope_pct = abs(window.iloc[-1] - window.iloc[0]) / abs(current_vwap)
    return slope_pct <= settings.vwap_flat_tolerance_pct


def _has_frequent_supertrend_flips(data: pd.DataFrame, index: int, settings: StrategySettings) -> bool:
    if "supertrend_direction" not in data.columns:
        return False

    start = max(0, index - settings.supertrend_flip_lookback + 1)
    directions = pd.to_numeric(data.iloc[start : index + 1]["supertrend_direction"], errors="coerce").dropna()
    if len(directions) < 2:
        return False

    flips = (directions != directions.shift(1)).sum() - 1
    return int(flips) > settings.max_supertrend_flips


def _is_bollinger_squeeze(row: pd.Series, settings: StrategySettings) -> bool:
    bandwidth = _value(row, "bb_bandwidth")
    return not pd.isna(bandwidth) and bandwidth <= settings.bollinger_squeeze_threshold


def _is_low_liquidity(row: pd.Series, settings: StrategySettings) -> bool:
    volume = _value(row, "volume")
    average_volume = _value(row, "volume_average")
    if pd.isna(volume) or pd.isna(average_volume) or average_volume <= 0:
        return False
    return volume < average_volume * settings.low_liquidity_volume_ratio


def _value(row: pd.Series, column: str) -> Any:
    return row[column] if column in row else pd.NA
