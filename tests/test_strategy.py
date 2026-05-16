from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from app.strategy import (
    MarketBias,
    SignalEngine,
    SignalSide,
    SignalType,
    determine_market_bias,
    evaluate_trade_filters,
    score_trade,
)


def _base_row(**overrides: object) -> dict[str, object]:
    row: dict[str, object] = {
        "symbol": "SPY",
        "timestamp": datetime(2026, 5, 15, 14, 0, tzinfo=ZoneInfo("America/New_York")),
        "open": 100.0,
        "high": 103.0,
        "low": 98.9,
        "close": 102.0,
        "volume": 3000.0,
        "volume_average": 1000.0,
        "vwap": 100.0,
        "supertrend_direction": 1,
        "ema_crossover": 1,
        "rsi": 62.0,
        "bb_lower": 99.0,
        "bb_upper": 110.0,
        "bb_bandwidth": 0.05,
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


def test_score_trade_returns_spec_weighted_total_for_quality_buy() -> None:
    score = score_trade(pd.Series(_base_row()), SignalSide.BUY, SignalType.PULLBACK)

    assert score.total == 100
    assert score.passed is True
    assert score.components == {
        "vwap_alignment": 30,
        "supertrend_alignment": 20,
        "bollinger_reaction": 20,
        "volume_strength": 15,
        "rsi_strength": 15,
    }


def test_score_trade_penalizes_rsi_neutral_zone_even_inside_buy_range() -> None:
    score = score_trade(pd.Series(_base_row(rsi=52.0)), SignalSide.BUY, SignalType.PULLBACK)

    assert score.total == 85
    assert score.passed is True
    assert "RSI strength failed." in score.reasons


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


def test_signal_engine_generates_buy_pullback_decision_without_execution() -> None:
    data = _prepared_frame(
        _base_row(timestamp=datetime(2026, 5, 15, 13, 55, tzinfo=ZoneInfo("America/New_York")), vwap=99.5),
        _base_row(timestamp=datetime(2026, 5, 15, 13, 56, tzinfo=ZoneInfo("America/New_York")), vwap=99.7),
        _base_row(timestamp=datetime(2026, 5, 15, 13, 57, tzinfo=ZoneInfo("America/New_York")), vwap=99.9),
        _base_row(timestamp=datetime(2026, 5, 15, 13, 58, tzinfo=ZoneInfo("America/New_York")), vwap=100.1),
        _base_row(timestamp=datetime(2026, 5, 15, 13, 59, tzinfo=ZoneInfo("America/New_York")), vwap=100.3),
    )
    engine = SignalEngine()

    decision = engine.generate_signal(data)

    assert decision.side == SignalSide.BUY
    assert decision.signal_type == SignalType.PULLBACK
    assert decision.score.total == 100
    assert decision.should_trade is True
    assert not hasattr(engine, "submit_order")


def test_signal_engine_generates_sell_breakout_decision() -> None:
    row = _base_row(
        open=100.0,
        high=101.0,
        low=96.0,
        close=97.0,
        vwap=99.0,
        supertrend_direction=-1,
        ema_crossover=0,
        rsi=38.0,
        bb_lower=98.0,
        bb_upper=104.0,
    )
    data = _prepared_frame(
        _base_row(timestamp=datetime(2026, 5, 15, 13, 55, tzinfo=ZoneInfo("America/New_York")), vwap=99.8),
        _base_row(timestamp=datetime(2026, 5, 15, 13, 56, tzinfo=ZoneInfo("America/New_York")), vwap=99.7),
        _base_row(timestamp=datetime(2026, 5, 15, 13, 57, tzinfo=ZoneInfo("America/New_York")), vwap=99.6),
        _base_row(timestamp=datetime(2026, 5, 15, 13, 58, tzinfo=ZoneInfo("America/New_York")), vwap=99.5),
        row,
    )
    engine = SignalEngine()

    decision = engine.generate_signal(data)

    assert decision.side == SignalSide.SELL
    assert decision.signal_type == SignalType.BREAKOUT
    assert decision.market_bias == MarketBias.BEARISH
    assert decision.should_trade is True


def test_signal_engine_filters_neutral_rsi_candidate() -> None:
    data = _prepared_frame(
        _base_row(timestamp=datetime(2026, 5, 15, 13, 55, tzinfo=ZoneInfo("America/New_York")), vwap=99.5),
        _base_row(timestamp=datetime(2026, 5, 15, 13, 56, tzinfo=ZoneInfo("America/New_York")), vwap=99.7),
        _base_row(timestamp=datetime(2026, 5, 15, 13, 57, tzinfo=ZoneInfo("America/New_York")), vwap=99.9),
        _base_row(timestamp=datetime(2026, 5, 15, 13, 58, tzinfo=ZoneInfo("America/New_York")), vwap=100.1),
        _base_row(timestamp=datetime(2026, 5, 15, 13, 59, tzinfo=ZoneInfo("America/New_York")), vwap=100.3, rsi=52),
    )

    decision = SignalEngine().generate_signal(data)

    assert decision.side == SignalSide.HOLD
    assert decision.should_trade is False
    assert "RSI is in the 45-55 no-trade zone." in decision.filtered_reasons


def test_signal_engine_requires_ohlcv_input() -> None:
    with pytest.raises(ValueError):
        SignalEngine().generate_signal(pd.DataFrame({"close": [100]}))
