"""Trade quality scoring for confluence setups."""

from __future__ import annotations

import pandas as pd

from app.strategy.filters import determine_market_bias
from app.strategy.types import MarketBias, SignalSide, SignalType, StrategySettings, TradeScore


def score_trade(
    row: pd.Series,
    side: SignalSide,
    signal_type: SignalType,
    settings: StrategySettings | None = None,
) -> TradeScore:
    """Score a BUY or SELL candidate using the specification weights."""

    config = settings or StrategySettings()
    components = {
        "vwap_alignment": 0,
        "supertrend_alignment": 0,
        "bollinger_reaction": 0,
        "volume_strength": 0,
        "rsi_strength": 0,
    }
    reasons: list[str] = []

    if _has_vwap_alignment(row, side):
        components["vwap_alignment"] = 30
    else:
        reasons.append("VWAP alignment failed.")

    if _has_supertrend_alignment(row, side):
        components["supertrend_alignment"] = 20
    else:
        reasons.append("Supertrend alignment failed.")

    if _has_bollinger_reaction(row, side, signal_type, config):
        components["bollinger_reaction"] = 20
    else:
        reasons.append("Bollinger reaction failed.")

    if has_volume_confirmation(row, config):
        components["volume_strength"] = 15
    else:
        reasons.append("Volume confirmation failed.")

    if _has_rsi_strength(row, side, config):
        components["rsi_strength"] = 15
    else:
        reasons.append("RSI strength failed.")

    total = sum(components.values())
    passed = total >= config.minimum_trade_score
    if not passed:
        reasons.append(f"Trade score {total} is below minimum {config.minimum_trade_score}.")
    return TradeScore(total=total, components=components, passed=passed, reasons=reasons)


def has_volume_confirmation(row: pd.Series, settings: StrategySettings | None = None) -> bool:
    """Return whether current volume confirms the setup."""

    config = settings or StrategySettings()
    volume = _value(row, "volume")
    average_volume = _value(row, "volume_average")
    if pd.isna(volume) or pd.isna(average_volume) or average_volume <= 0:
        return False
    return volume >= average_volume * config.volume_confirmation_multiplier


def _has_vwap_alignment(row: pd.Series, side: SignalSide) -> bool:
    bias = determine_market_bias(row)
    if side == SignalSide.BUY:
        return bias == MarketBias.BULLISH
    if side == SignalSide.SELL:
        return bias == MarketBias.BEARISH
    return False


def _has_supertrend_alignment(row: pd.Series, side: SignalSide) -> bool:
    direction = _value(row, "supertrend_direction")
    if pd.isna(direction):
        return False
    if side == SignalSide.BUY:
        return int(direction) == 1
    if side == SignalSide.SELL:
        return int(direction) == -1
    return False


def _has_bollinger_reaction(
    row: pd.Series,
    side: SignalSide,
    signal_type: SignalType,
    settings: StrategySettings,
) -> bool:
    if signal_type == SignalType.BREAKOUT:
        return _is_breakout(row, side)
    return _is_pullback_to_vwap_or_band(row, side, settings)


def _has_rsi_strength(row: pd.Series, side: SignalSide, settings: StrategySettings) -> bool:
    rsi = _value(row, "rsi")
    if pd.isna(rsi):
        return False
    if settings.rsi_neutral_lower <= rsi <= settings.rsi_neutral_upper:
        return False
    if side == SignalSide.BUY:
        return settings.rsi_neutral_upper < rsi <= 70
    if side == SignalSide.SELL:
        return 30 <= rsi < settings.rsi_neutral_lower
    return False


def _is_pullback_to_vwap_or_band(row: pd.Series, side: SignalSide, settings: StrategySettings) -> bool:
    low = _value(row, "low")
    high = _value(row, "high")
    vwap = _value(row, "vwap")
    lower_band = _value(row, "bb_lower")
    upper_band = _value(row, "bb_upper")
    if side == SignalSide.BUY and not pd.isna(low):
        return _buy_touches_level(low, vwap, settings) or _buy_touches_level(low, lower_band, settings)
    if side == SignalSide.SELL and not pd.isna(high):
        return _sell_touches_level(high, vwap, settings) or _sell_touches_level(high, upper_band, settings)
    return False


def _is_breakout(row: pd.Series, side: SignalSide) -> bool:
    close = _value(row, "close")
    upper_band = _value(row, "bb_upper")
    lower_band = _value(row, "bb_lower")
    if side == SignalSide.BUY:
        return not pd.isna(close) and not pd.isna(upper_band) and close > upper_band
    if side == SignalSide.SELL:
        return not pd.isna(close) and not pd.isna(lower_band) and close < lower_band
    return False


def _buy_touches_level(price: float, level: float, settings: StrategySettings) -> bool:
    if pd.isna(level) or level == 0:
        return False
    tolerance = abs(level) * settings.pullback_tolerance_pct
    return price <= level + tolerance


def _sell_touches_level(price: float, level: float, settings: StrategySettings) -> bool:
    if pd.isna(level) or level == 0:
        return False
    tolerance = abs(level) * settings.pullback_tolerance_pct
    return price >= level - tolerance


def _value(row: pd.Series, column: str) -> float:
    return row[column] if column in row else pd.NA
