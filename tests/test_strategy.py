from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from app.strategy import (
    MarketBias,
    SignalEngine,
    SignalSide,
    SignalType,
    StrategySettings,
    determine_market_bias,
    evaluate_trade_filters,
)


def _base_row(**overrides: object) -> dict[str, object]:
    row: dict[str, object] = {
        "symbol": "SPY",
        "timestamp": datetime(2026, 5, 15, 14, 0, tzinfo=ZoneInfo("America/New_York")),
        "open": 100.0,
        "high": 103.0,
        "low": 98.0,
        "close": 102.0,
        "volume": 2200.0,
        "volume_average": 1000.0,
        "vwap": 100.0,
        "supertrend_direction": 1,
        "rsi": 52.0,
        "bb_lower": 95.0,
        "bb_middle": 100.0,
        "bb_upper": 105.0,
        "bb_bandwidth": 0.05,
        "ema_20": 101.0,
        "ma_50": 100.0,
        "macd": 1.0,
        "macd_signal": 0.5,
        "macd_bearish_cross": False,
    }
    row.update(overrides)
    return row


def _prepared_frame(*rows: dict[str, object]) -> pd.DataFrame:
    return pd.DataFrame(rows)


def test_determine_market_bias_uses_supertrend_and_vwap_alignment() -> None:
    bullish = pd.Series(_base_row())
    bearish = pd.Series(_base_row(close=98.0, vwap=100.0, supertrend_direction=-1))
    neutral = pd.Series(_base_row(close=102.0, vwap=100.0, supertrend_direction=-1))

    assert determine_market_bias(bullish) == MarketBias.BULLISH
    assert determine_market_bias(bearish) == MarketBias.BEARISH
    assert determine_market_bias(neutral) == MarketBias.NEUTRAL


def test_trade_filters_detect_bad_market_conditions() -> None:
    data = _prepared_frame(
        _base_row(timestamp=datetime(2026, 5, 15, 9, 30, tzinfo=ZoneInfo("America/New_York")), rsi=50),
        _base_row(timestamp=datetime(2026, 5, 15, 9, 31, tzinfo=ZoneInfo("America/New_York")), rsi=50),
        _base_row(
            timestamp=datetime(2026, 5, 15, 9, 32, tzinfo=ZoneInfo("America/New_York")),
            rsi=50,
            bb_bandwidth=0.001,
            volume=100,
            volume_average=1000,
        ),
    )

    reasons = evaluate_trade_filters(data, 2)

    assert "RSI is in the 45-55 no-trade zone." in reasons
    assert "Within first five minutes after market open." in reasons
    assert "Bollinger Bands are in a squeeze." in reasons
    assert "Volume indicates low liquidity." in reasons


def test_bot2_mean_reversion_buy_fires_on_rsi_and_lower_band() -> None:
    data = _prepared_frame(
        _base_row(
            close=95.0,
            low=94.0,
            rsi=39.0,
            bb_lower=96.0,
            ema_20=97.0,
            vwap=100.0,
            supertrend_direction=-1,
            macd=-1.0,
            macd_signal=0.0,
        )
    )

    decision = SignalEngine().generate_signal(data)

    assert decision.side == SignalSide.BUY
    assert decision.signal_type == SignalType.MEAN_REVERSION
    assert decision.score.total == 85
    assert decision.should_trade is True


def test_bot2_volume_below_one_point_one_blocks_volume_condition() -> None:
    data = _prepared_frame(_base_row(volume=1000, volume_average=1000))

    decision = SignalEngine().generate_signal(data)

    assert decision.metadata["conditions"]["volume_confirmed"] is False
    assert "Volume is at least 1.1x the 20-bar average." not in decision.reasons


def test_bot2_price_extension_blocks_buy() -> None:
    data = _prepared_frame(_base_row(close=131.0, high=132.0, low=130.0, ema_20=120.0, ma_50=100.0))

    decision = SignalEngine().generate_signal(data)

    assert decision.side == SignalSide.HOLD
    assert decision.should_trade is False
    assert "Price is more than 30% above MA(50)." in decision.filtered_reasons


def test_bot2_confidence_and_consensus_thresholds_are_enforced() -> None:
    data = _prepared_frame(
        _base_row(
            close=100,
            vwap=100,
            supertrend_direction=-1,
            rsi=59,
            macd=-1,
            macd_signal=0,
            ema_20=101,
            volume=100,
            volume_average=1000,
        )
    )

    decision = SignalEngine().generate_signal(data)

    assert decision.side == SignalSide.HOLD
    assert decision.metadata["confidence"] == pytest.approx(0.10)
    assert "Confidence 0.10 is below minimum 0.40." in decision.reasons


@pytest.mark.parametrize(
    ("overrides", "expected_reason"),
    [
        ({"close": 103.0}, "Hard take-profit reached at +3%."),
        ({"close": 97.0}, "Hard stop-loss reached at -3%."),
        ({"close": 101.0, "rsi": 76.0}, "RSI overbought exit triggered."),
        ({"close": 101.0, "macd": -1.0, "macd_signal": 0.0, "macd_bearish_cross": True}, "MACD bearish cross exit triggered."),
        ({"close": 99.0, "ema_20": 100.0}, "Price broke below EMA(20)."),
        ({"close": 103.0, "rsi": 66.0, "bb_middle": 100.0}, "Mean reversion exit condition met."),
    ],
)
def test_bot2_long_exit_conditions(overrides: dict[str, object], expected_reason: str) -> None:
    data = _prepared_frame(_base_row(**overrides))

    decision = SignalEngine().generate_signal(data, position_entry_price=100.0)

    assert decision.side == SignalSide.SELL
    assert decision.signal_type == SignalType.EXIT
    assert decision.should_trade is False
    assert expected_reason in decision.reasons


def test_signal_engine_requires_ohlcv_input() -> None:
    with pytest.raises(ValueError):
        SignalEngine().generate_signal(pd.DataFrame({"close": [100]}))


def test_bot2_defaults_include_pdf_thresholds() -> None:
    settings = StrategySettings()

    assert settings.rsi_oversold_threshold == 40
    assert settings.rsi_overbought_exit == 75
    assert settings.volume_confirmation_multiplier == 1.1
