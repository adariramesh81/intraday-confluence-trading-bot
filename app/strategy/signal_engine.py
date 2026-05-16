"""Confluence-based signal generation with no trade execution."""

from __future__ import annotations

import logging
from typing import Any

import pandas as pd

from app.indicators import (
    add_ema_columns,
    calculate_bollinger_bands,
    calculate_rsi,
    calculate_supertrend,
    calculate_vwap,
)
from app.strategy.filters import determine_market_bias, evaluate_trade_filters
from app.strategy.trade_scoring import has_volume_confirmation, score_trade
from app.strategy.types import MarketBias, SignalSide, SignalType, StrategyDecision, StrategySettings, TradeScore
from app.utils.logger import get_logger


class SignalEngine:
    """Generate strategy signals from OHLCV data and indicator confluence."""

    def __init__(
        self,
        settings: StrategySettings | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self.settings = settings or StrategySettings()
        self.logger = logger or get_logger(__name__)

    def prepare_indicators(self, data: pd.DataFrame) -> pd.DataFrame:
        """Return OHLCV data with all strategy indicator columns present."""

        self._validate_input_data(data)
        result = data.copy()

        if "ema_crossover" not in result.columns:
            result = add_ema_columns(
                result,
                fast_period=self.settings.fast_ema_period,
                slow_period=self.settings.slow_ema_period,
            )
        if "rsi" not in result.columns:
            result["rsi"] = calculate_rsi(result, period=self.settings.rsi_period)
        if not {"bb_upper", "bb_lower", "bb_bandwidth"}.issubset(result.columns):
            result = calculate_bollinger_bands(
                result,
                period=self.settings.bollinger_period,
                std_dev=self.settings.bollinger_std_dev,
            )
        if "vwap" not in result.columns:
            result = calculate_vwap(result, timezone=self.settings.market_timezone)
        if "supertrend_direction" not in result.columns:
            result = calculate_supertrend(
                result,
                atr_period=self.settings.supertrend_atr_period,
                multiplier=self.settings.supertrend_multiplier,
            )
        if "volume_average" not in result.columns:
            volume = pd.to_numeric(result["volume"], errors="coerce")
            result["volume_average"] = volume.rolling(
                window=self.settings.volume_average_period,
                min_periods=1,
            ).mean().shift(1)
        return result

    def generate_signal(self, data: pd.DataFrame, index: int = -1) -> StrategyDecision:
        """Generate a signal decision for one row of OHLCV data."""

        prepared = self.prepare_indicators(data)
        normalized_index = index if index >= 0 else len(prepared) + index
        if normalized_index < 0 or normalized_index >= len(prepared):
            raise IndexError("Signal index is out of range.")

        row = prepared.iloc[normalized_index]
        market_bias = determine_market_bias(row)
        filter_reasons = evaluate_trade_filters(prepared, normalized_index, self.settings)
        side, signal_type, setup_reasons = self._classify_setup(row, market_bias)

        if side == SignalSide.HOLD:
            score = self._empty_score(["No valid BUY or SELL setup."])
            return self._decision(row, side, SignalType.NONE, market_bias, score, setup_reasons, filter_reasons)

        score = score_trade(row, side, signal_type, self.settings)
        reasons = setup_reasons + score.reasons
        decision = self._decision(row, side, signal_type, market_bias, score, reasons, filter_reasons)
        self.logger.info(
            "Generated strategy signal.",
            extra={
                "symbol": decision.symbol,
                "side": decision.side.value,
                "signal_type": decision.signal_type.value,
                "score": decision.score.total,
                "should_trade": decision.should_trade,
            },
        )
        return decision

    def generate_signals(self, data: pd.DataFrame) -> list[StrategyDecision]:
        """Generate signal decisions for every row in an OHLCV DataFrame."""

        prepared = self.prepare_indicators(data)
        return [self.generate_signal(prepared, index=index) for index in range(len(prepared))]

    def _classify_setup(self, row: pd.Series, market_bias: MarketBias) -> tuple[SignalSide, SignalType, list[str]]:
        if market_bias == MarketBias.BULLISH:
            if self._is_buy_pullback(row):
                return SignalSide.BUY, SignalType.PULLBACK, ["Bullish pullback setup detected."]
            if self._is_buy_breakout(row):
                return SignalSide.BUY, SignalType.BREAKOUT, ["Bullish breakout setup detected."]
        if market_bias == MarketBias.BEARISH:
            if self._is_sell_pullback(row):
                return SignalSide.SELL, SignalType.PULLBACK, ["Bearish pullback setup detected."]
            if self._is_sell_breakout(row):
                return SignalSide.SELL, SignalType.BREAKOUT, ["Bearish breakout setup detected."]
        return SignalSide.HOLD, SignalType.NONE, [f"Market bias is {market_bias.value}."]

    def _is_buy_pullback(self, row: pd.Series) -> bool:
        return (
            _value(row, "ema_crossover") == 1
            and _is_buy_pullback_location(row, self.settings)
            and _is_bullish_rejection(row, self.settings)
            and _is_buy_rsi(row, self.settings)
            and has_volume_confirmation(row, self.settings)
        )

    def _is_sell_pullback(self, row: pd.Series) -> bool:
        return (
            _value(row, "ema_crossover") == -1
            and _is_sell_pullback_location(row, self.settings)
            and _is_bearish_rejection(row, self.settings)
            and _is_sell_rsi(row, self.settings)
            and has_volume_confirmation(row, self.settings)
        )

    def _is_buy_breakout(self, row: pd.Series) -> bool:
        close = _value(row, "close")
        upper_band = _value(row, "bb_upper")
        return (
            not pd.isna(close)
            and not pd.isna(upper_band)
            and close > upper_band
            and has_volume_confirmation(row, self.settings)
        )

    def _is_sell_breakout(self, row: pd.Series) -> bool:
        close = _value(row, "close")
        lower_band = _value(row, "bb_lower")
        return (
            not pd.isna(close)
            and not pd.isna(lower_band)
            and close < lower_band
            and has_volume_confirmation(row, self.settings)
        )

    @staticmethod
    def _validate_input_data(data: pd.DataFrame) -> None:
        required_columns = ["timestamp", "open", "high", "low", "close", "volume"]
        missing_columns = [column for column in required_columns if column not in data.columns]
        if missing_columns:
            raise ValueError(f"Missing strategy input columns: {missing_columns}.")
        if data.empty:
            raise ValueError("Strategy input data is empty.")

    @staticmethod
    def _empty_score(reasons: list[str]) -> TradeScore:
        return TradeScore(
            total=0,
            components={
                "vwap_alignment": 0,
                "supertrend_alignment": 0,
                "bollinger_reaction": 0,
                "volume_strength": 0,
                "rsi_strength": 0,
            },
            passed=False,
            reasons=reasons,
        )

    @staticmethod
    def _decision(
        row: pd.Series,
        side: SignalSide,
        signal_type: SignalType,
        market_bias: MarketBias,
        score: TradeScore,
        reasons: list[str],
        filter_reasons: list[str],
    ) -> StrategyDecision:
        return StrategyDecision(
            side=side,
            signal_type=signal_type,
            market_bias=market_bias,
            score=score,
            symbol=row["symbol"] if "symbol" in row and not pd.isna(row["symbol"]) else None,
            timestamp=pd.Timestamp(row["timestamp"]).to_pydatetime() if "timestamp" in row else None,
            reasons=reasons,
            filtered_reasons=filter_reasons,
            metadata={
                "close": _value(row, "close"),
                "vwap": _value(row, "vwap"),
                "rsi": _value(row, "rsi"),
                "volume": _value(row, "volume"),
                "volume_average": _value(row, "volume_average"),
            },
        )


def _is_bullish_rejection(row: pd.Series, settings: StrategySettings) -> bool:
    open_price = _value(row, "open")
    high = _value(row, "high")
    low = _value(row, "low")
    close = _value(row, "close")
    if any(pd.isna(value) for value in [open_price, high, low, close]):
        return False

    body = abs(close - open_price)
    lower_wick = min(open_price, close) - low
    closes_strong = close > open_price and close >= (high + low) / 2
    return closes_strong and lower_wick >= body * settings.rejection_wick_body_ratio


def _is_bearish_rejection(row: pd.Series, settings: StrategySettings) -> bool:
    open_price = _value(row, "open")
    high = _value(row, "high")
    low = _value(row, "low")
    close = _value(row, "close")
    if any(pd.isna(value) for value in [open_price, high, low, close]):
        return False

    body = abs(close - open_price)
    upper_wick = high - max(open_price, close)
    closes_weak = close < open_price and close <= (high + low) / 2
    return closes_weak and upper_wick >= body * settings.rejection_wick_body_ratio


def _is_buy_pullback_location(row: pd.Series, settings: StrategySettings) -> bool:
    low = _value(row, "low")
    vwap = _value(row, "vwap")
    lower_band = _value(row, "bb_lower")
    if pd.isna(low):
        return False
    return _buy_touches_level(low, vwap, settings) or _buy_touches_level(low, lower_band, settings)


def _is_sell_pullback_location(row: pd.Series, settings: StrategySettings) -> bool:
    high = _value(row, "high")
    vwap = _value(row, "vwap")
    upper_band = _value(row, "bb_upper")
    if pd.isna(high):
        return False
    return _sell_touches_level(high, vwap, settings) or _sell_touches_level(high, upper_band, settings)


def _is_buy_rsi(row: pd.Series, settings: StrategySettings) -> bool:
    rsi = _value(row, "rsi")
    return not pd.isna(rsi) and settings.rsi_neutral_upper < rsi <= 70


def _is_sell_rsi(row: pd.Series, settings: StrategySettings) -> bool:
    rsi = _value(row, "rsi")
    return not pd.isna(rsi) and 30 <= rsi < settings.rsi_neutral_lower


def _buy_touches_level(price: float, level: float, settings: StrategySettings) -> bool:
    if pd.isna(level) or level == 0:
        return False
    return price <= level + (abs(level) * settings.pullback_tolerance_pct)


def _sell_touches_level(price: float, level: float, settings: StrategySettings) -> bool:
    if pd.isna(level) or level == 0:
        return False
    return price >= level - (abs(level) * settings.pullback_tolerance_pct)


def _value(row: pd.Series, column: str) -> Any:
    return row[column] if column in row else pd.NA
