from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from app.indicators import (
    add_ema_columns,
    calculate_atr,
    calculate_bollinger_bands,
    calculate_ema,
    calculate_rsi,
    calculate_supertrend,
    calculate_true_range,
    calculate_vwap,
)


def _sample_ohlcv() -> pd.DataFrame:
    timestamps = pd.date_range("2026-05-15 13:30", periods=30, freq="min", tz="UTC")
    closes = pd.Series(
        [
            100,
            101,
            102,
            101,
            103,
            104,
            105,
            104,
            106,
            107,
            108,
            107,
            109,
            110,
            111,
            112,
            113,
            112,
            114,
            115,
            116,
            117,
            116,
            118,
            119,
            120,
            121,
            120,
            122,
            123,
        ],
        dtype="float64",
    )
    return pd.DataFrame(
        {
            "symbol": ["SPY"] * len(timestamps),
            "timestamp": timestamps,
            "open": closes - 0.25,
            "high": closes + 1,
            "low": closes - 1,
            "close": closes,
            "volume": [1000 + index for index in range(len(timestamps))],
        }
    )


def test_calculate_ema_matches_pandas_ewm() -> None:
    data = _sample_ohlcv()

    ema = calculate_ema(data, period=9)

    expected = data["close"].ewm(span=9, adjust=False, min_periods=9).mean()
    pd.testing.assert_series_equal(ema, expected)


def test_add_ema_columns_flags_bullish_crossover() -> None:
    data = pd.DataFrame({"close": [10, 9, 8, 9, 10, 11, 12, 13]})

    result = add_ema_columns(data, fast_period=2, slow_period=3)

    assert {"ema_2", "ema_3", "ema_crossover"}.issubset(result.columns)
    assert 1 in set(result["ema_crossover"])


def test_calculate_rsi_stays_between_zero_and_one_hundred() -> None:
    data = _sample_ohlcv()

    rsi = calculate_rsi(data, period=14)

    populated = rsi.dropna()
    assert not populated.empty
    assert ((populated >= 0) & (populated <= 100)).all()


def test_bollinger_bands_use_expected_window_math() -> None:
    data = _sample_ohlcv()

    result = calculate_bollinger_bands(data, period=20, std_dev=2)

    expected_middle = data["close"].iloc[:20].mean()
    expected_std = data["close"].iloc[:20].std(ddof=0)
    assert result.loc[19, "bb_middle"] == pytest.approx(expected_middle)
    assert result.loc[19, "bb_upper"] == pytest.approx(expected_middle + (2 * expected_std))
    assert result.loc[19, "bb_lower"] == pytest.approx(expected_middle - (2 * expected_std))
    assert "bb_bandwidth" in result.columns
    assert "bb_percent_b" in result.columns


def test_true_range_and_atr_are_positive_after_warmup() -> None:
    data = _sample_ohlcv()

    true_range = calculate_true_range(data)
    atr = calculate_atr(data, period=14)

    assert (true_range > 0).all()
    assert (atr.dropna() > 0).all()


def test_vwap_resets_each_market_day() -> None:
    data = pd.DataFrame(
        {
            "symbol": ["SPY", "SPY", "SPY"],
            "timestamp": [
                datetime(2026, 5, 15, 13, 30, tzinfo=ZoneInfo("UTC")),
                datetime(2026, 5, 15, 13, 31, tzinfo=ZoneInfo("UTC")),
                datetime(2026, 5, 18, 13, 30, tzinfo=ZoneInfo("UTC")),
            ],
            "open": [100, 102, 110],
            "high": [101, 103, 111],
            "low": [99, 101, 109],
            "close": [100, 102, 110],
            "volume": [10, 30, 5],
        }
    )

    result = calculate_vwap(data)

    assert result.loc[0, "vwap"] == pytest.approx(100)
    assert result.loc[1, "vwap"] == pytest.approx(101.5)
    assert result.loc[2, "vwap"] == pytest.approx(110)


def test_supertrend_adds_direction_and_trailing_line() -> None:
    data = _sample_ohlcv()

    result = calculate_supertrend(data, atr_period=10, multiplier=3)

    assert {"supertrend", "supertrend_direction", "supertrend_upper_band", "supertrend_lower_band"}.issubset(
        result.columns
    )
    populated_direction = result["supertrend_direction"].dropna()
    assert not populated_direction.empty
    assert set(populated_direction.unique()).issubset({-1, 1})
