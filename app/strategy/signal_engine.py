"""Bot 2 momentum and mean-reversion signal generation."""

from __future__ import annotations

import logging
from typing import Any

import pandas as pd

from app.indicators import (
    calculate_bollinger_bands,
    calculate_ema,
    calculate_macd,
    calculate_rsi,
    calculate_sma,
    calculate_supertrend,
    calculate_vwap,
)
from app.strategy.filters import determine_market_bias
from app.strategy.types import MarketBias, SignalSide, SignalType, StrategyDecision, StrategySettings, TradeScore
from app.utils.logger import get_logger


class SignalEngine:
    """Generate Bot 2 paper-trading signals from OHLCV data."""

    def __init__(
        self,
        settings: StrategySettings | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self.settings = settings or StrategySettings()
        self.logger = logger or get_logger(__name__)

    def prepare_indicators(self, data: pd.DataFrame) -> pd.DataFrame:
        """Return OHLCV data with all Bot 2 indicator columns present."""

        self._validate_input_data(data)
        result = data.copy()

        if "rsi" not in result.columns:
            result["rsi"] = calculate_rsi(result, period=self.settings.rsi_period)
        if not {"bb_middle", "bb_upper", "bb_lower", "bb_bandwidth"}.issubset(result.columns):
            result = calculate_bollinger_bands(
                result,
                period=self.settings.bollinger_period,
                std_dev=self.settings.bollinger_std_dev,
            )
        ema_column = f"ema_{self.settings.trend_ema_period}"
        if ema_column not in result.columns:
            result[ema_column] = calculate_ema(result, self.settings.trend_ema_period)
        ma_column = f"ma_{self.settings.ma_period}"
        if ma_column not in result.columns:
            result[ma_column] = calculate_sma(result, self.settings.ma_period)
        if not {"macd", "macd_signal", "macd_bearish_cross"}.issubset(result.columns):
            result = calculate_macd(
                result,
                fast_period=self.settings.macd_fast_period,
                slow_period=self.settings.macd_slow_period,
                signal_period=self.settings.macd_signal_period,
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

    def generate_signal(
        self,
        data: pd.DataFrame,
        index: int = -1,
        position_entry_price: float | None = None,
        trailing_stop_loss: float | None = None,
    ) -> StrategyDecision:
        """Generate a Bot 2 entry or long-exit decision for one OHLCV row."""

        prepared = self.prepare_indicators(data)
        normalized_index = index if index >= 0 else len(prepared) + index
        if normalized_index < 0 or normalized_index >= len(prepared):
            raise IndexError("Signal index is out of range.")

        row = prepared.iloc[normalized_index]
        market_bias = determine_market_bias(row)

        if position_entry_price is not None:
            decision = self._exit_decision(row, market_bias, position_entry_price, trailing_stop_loss)
        else:
            decision = self._entry_decision(row, market_bias)

        self.logger.info(
            "Generated Bot 2 strategy signal.",
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
        """Generate Bot 2 entry decisions for every row in an OHLCV DataFrame."""

        prepared = self.prepare_indicators(data)
        return [self.generate_signal(prepared, index=index) for index in range(len(prepared))]

    def _entry_decision(self, row: pd.Series, market_bias: MarketBias) -> StrategyDecision:
        conditions = _bot2_conditions(row, self.settings)
        weights = _regime_weights(row, market_bias)
        momentum_score = _score_booleans(
            [
                conditions["rsi_momentum"],
                conditions["macd_bullish"],
                conditions["above_ema"],
                conditions["volume_confirmed"],
            ]
        )
        mean_reversion_score = 1.0 if conditions["mean_reversion"] else 0.0
        confidence = (momentum_score * weights["momentum"]) + (mean_reversion_score * weights["mean_reversion"])
        consensus = confidence
        passed = (
            confidence >= self.settings.min_confidence
            and consensus > self.settings.buy_consensus_threshold
            and not conditions["price_extended"]
        )

        components = {
            "momentum": int(round(momentum_score * 100)),
            "mean_reversion": int(round(mean_reversion_score * 100)),
            "confidence": int(round(confidence * 100)),
            "consensus": int(round(consensus * 100)),
        }
        reasons = _entry_reasons(conditions, confidence, consensus, self.settings)
        filtered_reasons = ["Price is more than 30% above MA(50)."] if conditions["price_extended"] else []
        signal_type = _entry_signal_type(momentum_score, mean_reversion_score)
        side = SignalSide.BUY if passed else SignalSide.HOLD
        score = TradeScore(total=components["confidence"], components=components, passed=passed, reasons=reasons)
        return self._decision(
            row=row,
            side=side,
            signal_type=signal_type if side == SignalSide.BUY else SignalType.NONE,
            market_bias=market_bias,
            score=score,
            reasons=reasons,
            filtered_reasons=filtered_reasons,
            metadata={
                **_base_metadata(row, self.settings),
                "strategy": "bot2",
                "regime_weights": weights,
                "conditions": conditions,
                "confidence": confidence,
                "consensus": consensus,
            },
        )

    def _exit_decision(
        self,
        row: pd.Series,
        market_bias: MarketBias,
        entry_price: float,
        trailing_stop_loss: float | None,
    ) -> StrategyDecision:
        exit_reasons = _exit_reasons(row, entry_price, trailing_stop_loss, self.settings)
        should_exit = bool(exit_reasons)
        score = TradeScore(
            total=100 if should_exit else 0,
            components={"exit": 100 if should_exit else 0},
            passed=should_exit,
            reasons=exit_reasons or ["No Bot 2 exit condition met."],
        )
        return self._decision(
            row=row,
            side=SignalSide.SELL if should_exit else SignalSide.HOLD,
            signal_type=SignalType.EXIT if should_exit else SignalType.NONE,
            market_bias=market_bias,
            score=score,
            reasons=score.reasons,
            filtered_reasons=[],
            metadata={
                **_base_metadata(row, self.settings),
                "strategy": "bot2",
                "entry_price": entry_price,
                "trailing_stop_loss": trailing_stop_loss,
                "unrealized_pct": _unrealized_pct(row, entry_price),
            },
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
    def _decision(
        row: pd.Series,
        side: SignalSide,
        signal_type: SignalType,
        market_bias: MarketBias,
        score: TradeScore,
        reasons: list[str],
        filtered_reasons: list[str],
        metadata: dict[str, Any],
    ) -> StrategyDecision:
        return StrategyDecision(
            side=side,
            signal_type=signal_type,
            market_bias=market_bias,
            score=score,
            symbol=row["symbol"] if "symbol" in row and not pd.isna(row["symbol"]) else None,
            timestamp=pd.Timestamp(row["timestamp"]).to_pydatetime() if "timestamp" in row else None,
            reasons=reasons,
            filtered_reasons=filtered_reasons,
            metadata=metadata,
        )


def should_move_bot2_stop_to_break_even(entry_price: float, current_price: float, settings: StrategySettings | None = None) -> bool:
    """Return whether Bot 2 should move the long stop to break-even."""

    config = settings or StrategySettings()
    if entry_price <= 0:
        return False
    return (current_price - entry_price) / entry_price >= config.break_even_profit_pct


def bot2_locked_stop(entry_price: float, current_price: float, settings: StrategySettings | None = None) -> float | None:
    """Return Bot 2's locked-profit stop when the +20% trigger is met."""

    config = settings or StrategySettings()
    if entry_price <= 0:
        return None
    if (current_price - entry_price) / entry_price >= config.lock_profit_trigger_pct:
        return entry_price * (1 + config.lock_profit_pct)
    return None


def _bot2_conditions(row: pd.Series, settings: StrategySettings) -> dict[str, bool]:
    close = _value(row, "close")
    rsi = _value(row, "rsi")
    macd = _value(row, "macd")
    macd_signal = _value(row, "macd_signal")
    ema_20 = _value(row, f"ema_{settings.trend_ema_period}")
    ma_50 = _value(row, f"ma_{settings.ma_period}")
    lower_band = _value(row, "bb_lower")
    volume = _value(row, "volume")
    average_volume = _value(row, "volume_average")
    return {
        "rsi_momentum": bool(not pd.isna(rsi) and rsi < settings.rsi_momentum_buy_max),
        "macd_bullish": bool(not pd.isna(macd) and not pd.isna(macd_signal) and macd >= macd_signal),
        "above_ema": bool(not pd.isna(close) and not pd.isna(ema_20) and close > ema_20),
        "volume_confirmed": bool(
            not pd.isna(volume)
            and not pd.isna(average_volume)
            and average_volume > 0
            and volume >= average_volume * settings.volume_confirmation_multiplier
        ),
        "mean_reversion": bool(
            not pd.isna(rsi)
            and not pd.isna(close)
            and not pd.isna(lower_band)
            and rsi < settings.rsi_oversold_threshold
            and close < lower_band
        ),
        "price_extended": bool(
            not pd.isna(close)
            and not pd.isna(ma_50)
            and ma_50 > 0
            and close > ma_50 * settings.price_extension_ma_multiplier
        ),
    }


def _entry_reasons(
    conditions: dict[str, bool],
    confidence: float,
    consensus: float,
    settings: StrategySettings,
) -> list[str]:
    reasons: list[str] = []
    for key, text in {
        "rsi_momentum": "RSI momentum buy condition met.",
        "macd_bullish": "MACD is at or above signal.",
        "above_ema": "Price is above EMA(20).",
        "volume_confirmed": "Volume is at least 1.1x the 20-bar average.",
        "mean_reversion": "Mean reversion entry condition met.",
    }.items():
        if conditions[key]:
            reasons.append(text)
    if confidence < settings.min_confidence:
        reasons.append(f"Confidence {confidence:.2f} is below minimum {settings.min_confidence:.2f}.")
    if consensus <= settings.buy_consensus_threshold:
        reasons.append(f"Buy consensus {consensus:.2f} is not above {settings.buy_consensus_threshold:.2f}.")
    if conditions["price_extended"]:
        reasons.append("Price extension block is active.")
    return reasons


def _entry_signal_type(momentum_score: float, mean_reversion_score: float) -> SignalType:
    if mean_reversion_score > 0 and momentum_score < 0.75:
        return SignalType.MEAN_REVERSION
    if momentum_score > 0 and mean_reversion_score > 0:
        return SignalType.COMPOSITE
    if mean_reversion_score > 0:
        return SignalType.MEAN_REVERSION
    if momentum_score > 0:
        return SignalType.MOMENTUM
    return SignalType.NONE


def _exit_reasons(
    row: pd.Series,
    entry_price: float,
    trailing_stop_loss: float | None,
    settings: StrategySettings,
) -> list[str]:
    close = _value(row, "close")
    rsi = _value(row, "rsi")
    ema_20 = _value(row, f"ema_{settings.trend_ema_period}")
    bb_middle = _value(row, "bb_middle")
    reasons: list[str] = []

    unrealized_pct = _unrealized_pct(row, entry_price)
    if unrealized_pct is not None and unrealized_pct >= settings.hard_take_profit_pct:
        reasons.append("Hard take-profit reached at +3%.")
    if unrealized_pct is not None and unrealized_pct <= -settings.hard_stop_loss_pct:
        reasons.append("Hard stop-loss reached at -3%.")
    if trailing_stop_loss is not None and not pd.isna(close) and close <= trailing_stop_loss:
        reasons.append("Bot 2 trailing stop reached.")
    if not pd.isna(rsi) and rsi > settings.rsi_overbought_exit:
        reasons.append("RSI overbought exit triggered.")
    if bool(_value(row, "macd_bearish_cross")):
        reasons.append("MACD bearish cross exit triggered.")
    if not pd.isna(close) and not pd.isna(ema_20) and close < ema_20:
        reasons.append("Price broke below EMA(20).")
    if (
        not pd.isna(rsi)
        and not pd.isna(close)
        and not pd.isna(bb_middle)
        and rsi > settings.mean_reversion_exit_rsi
        and close > bb_middle * settings.mean_reversion_exit_bb_multiplier
    ):
        reasons.append("Mean reversion exit condition met.")
    if _sell_consensus(row, settings) < settings.sell_consensus_threshold:
        reasons.append("Sell consensus is below -0.20.")
    return reasons


def _sell_consensus(row: pd.Series, settings: StrategySettings) -> float:
    bearish_votes = [
        bool(_value(row, "macd_bearish_cross")),
        _numeric_lt(row, "close", f"ema_{settings.trend_ema_period}"),
        _numeric_gt_value(row, "rsi", settings.rsi_overbought_exit),
    ]
    return -(_score_booleans(bearish_votes))


def _regime_weights(row: pd.Series, market_bias: MarketBias) -> dict[str, float]:
    bandwidth = _value(row, "bb_bandwidth")
    if not pd.isna(bandwidth) and bandwidth >= 0.08:
        return {"momentum": 0.50, "mean_reversion": 0.50, "regime": "HIGH_VOLATILITY"}
    if market_bias == MarketBias.BULLISH:
        return {"momentum": 0.75, "mean_reversion": 0.25, "regime": "BULL"}
    if market_bias == MarketBias.BEARISH:
        return {"momentum": 0.30, "mean_reversion": 0.70, "regime": "BEAR"}
    return {"momentum": 0.40, "mean_reversion": 0.60, "regime": "SIDEWAYS"}


def _base_metadata(row: pd.Series, settings: StrategySettings) -> dict[str, Any]:
    return {
        "close": _value(row, "close"),
        "rsi": _value(row, "rsi"),
        "volume": _value(row, "volume"),
        "volume_average": _value(row, "volume_average"),
        "ema_20": _value(row, f"ema_{settings.trend_ema_period}"),
        "ma_50": _value(row, f"ma_{settings.ma_period}"),
        "macd": _value(row, "macd"),
        "macd_signal": _value(row, "macd_signal"),
        "bb_lower": _value(row, "bb_lower"),
        "bb_middle": _value(row, "bb_middle"),
        "bb_upper": _value(row, "bb_upper"),
    }


def _unrealized_pct(row: pd.Series, entry_price: float) -> float | None:
    close = _value(row, "close")
    if pd.isna(close) or entry_price <= 0:
        return None
    return (close - entry_price) / entry_price


def _score_booleans(values: list[bool]) -> float:
    if not values:
        return 0.0
    return sum(1 for value in values if value) / len(values)


def _numeric_lt(row: pd.Series, left_column: str, right_column: str) -> bool:
    left = _value(row, left_column)
    right = _value(row, right_column)
    return not pd.isna(left) and not pd.isna(right) and left < right


def _numeric_gt_value(row: pd.Series, column: str, threshold: float) -> bool:
    value = _value(row, column)
    return not pd.isna(value) and value > threshold


def _value(row: pd.Series, column: str) -> Any:
    return row[column] if column in row else pd.NA
