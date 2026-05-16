from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from app.config import AppConfig, MarketDataConfig
from app.data.historical_data import YFinanceHistoricalDataClient
from app.data.market_data import AlpacaMarketDataClient, MarketDataError
from app.utils.time_utils import to_utc, validate_date_range
from app.utils.validators import DataValidationError, validate_ohlcv_dataframe, validate_symbol


class FakeAlpacaResponse:
    def __init__(self, data: pd.DataFrame) -> None:
        self.df = data


class FakeAlpacaDataClient:
    def __init__(self, response: FakeAlpacaResponse) -> None:
        self.response = response
        self.requests = []

    def get_stock_bars(self, request: object) -> FakeAlpacaResponse:
        self.requests.append(request)
        return self.response


def test_validate_symbol_normalizes_ticker() -> None:
    assert validate_symbol(" spy ") == "SPY"


def test_validate_ohlcv_rejects_invalid_price_relationship() -> None:
    data = pd.DataFrame(
        {
            "timestamp": [datetime(2026, 5, 15, 14, 30, tzinfo=ZoneInfo("UTC"))],
            "open": [100],
            "high": [99],
            "low": [98],
            "close": [101],
            "volume": [1000],
        }
    )

    with pytest.raises(DataValidationError):
        validate_ohlcv_dataframe(data)


def test_alpaca_fetch_returns_canonical_timezone_safe_ohlcv() -> None:
    index = pd.MultiIndex.from_tuples(
        [("SPY", pd.Timestamp("2026-05-15T14:30:00Z"))],
        names=["symbol", "timestamp"],
    )
    response = FakeAlpacaResponse(
        pd.DataFrame(
            {"open": [100], "high": [101], "low": [99], "close": [100.5], "volume": [5000]},
            index=index,
        )
    )
    client = AlpacaMarketDataClient(
        AppConfig(market_data=MarketDataConfig(retry_backoff_seconds=0)),
        data_client=FakeAlpacaDataClient(response),
        sleep=lambda _: None,
    )

    data = client.fetch_ohlcv(
        "spy",
        start=datetime(2026, 5, 15, 9, 30, tzinfo=ZoneInfo("America/New_York")),
        end=datetime(2026, 5, 15, 10, 0, tzinfo=ZoneInfo("America/New_York")),
    )

    assert list(data.columns) == ["symbol", "timestamp", "open", "high", "low", "close", "volume"]
    assert data.loc[0, "symbol"] == "SPY"
    assert str(data.loc[0, "timestamp"].tz) == "UTC"


def test_alpaca_fetch_retries_transient_errors() -> None:
    calls = {"count": 0}

    class FlakyDataClient:
        def get_stock_bars(self, request: object) -> FakeAlpacaResponse:
            calls["count"] += 1
            if calls["count"] == 1:
                raise RuntimeError("rate limited")
            return FakeAlpacaResponse(
                pd.DataFrame(
                    {
                        "symbol": ["SPY"],
                        "timestamp": [pd.Timestamp("2026-05-15T14:30:00Z")],
                        "open": [100],
                        "high": [101],
                        "low": [99],
                        "close": [100],
                        "volume": [10],
                    }
                )
            )

    client = AlpacaMarketDataClient(
        AppConfig(market_data=MarketDataConfig(retry_backoff_seconds=0)),
        data_client=FlakyDataClient(),
        sleep=lambda _: None,
    )

    data = client.fetch_ohlcv(
        "SPY",
        datetime(2026, 5, 15, 9, 30, tzinfo=ZoneInfo("America/New_York")),
        datetime(2026, 5, 15, 10, 0, tzinfo=ZoneInfo("America/New_York")),
    )

    assert calls["count"] == 2
    assert len(data) == 1


def test_alpaca_fetch_raises_after_retry_exhaustion() -> None:
    class FailingDataClient:
        def get_stock_bars(self, request: object) -> FakeAlpacaResponse:
            raise RuntimeError("unavailable")

    client = AlpacaMarketDataClient(
        AppConfig(market_data=MarketDataConfig(retry_attempts=2, retry_backoff_seconds=0)),
        data_client=FailingDataClient(),
        sleep=lambda _: None,
    )

    with pytest.raises(MarketDataError):
        client.fetch_ohlcv(
            "SPY",
            datetime(2026, 5, 15, 9, 30, tzinfo=ZoneInfo("America/New_York")),
            datetime(2026, 5, 15, 10, 0, tzinfo=ZoneInfo("America/New_York")),
        )


def test_yfinance_fetch_normalizes_download_response() -> None:
    def downloader(**kwargs: object) -> pd.DataFrame:
        assert kwargs["tickers"] == "SPY"
        assert kwargs["interval"] == "1m"
        return pd.DataFrame(
            {
                "Open": [100],
                "High": [101],
                "Low": [99],
                "Close": [100.25],
                "Volume": [2000],
            },
            index=pd.DatetimeIndex([pd.Timestamp("2026-05-15T14:30:00Z")], name="Datetime"),
        )

    client = YFinanceHistoricalDataClient(
        AppConfig(market_data=MarketDataConfig(retry_backoff_seconds=0)),
        downloader=downloader,
        sleep=lambda _: None,
    )

    data = client.fetch_ohlcv(
        "SPY",
        datetime(2026, 5, 15, 9, 30, tzinfo=ZoneInfo("America/New_York")),
        datetime(2026, 5, 15, 10, 0, tzinfo=ZoneInfo("America/New_York")),
    )

    assert data.loc[0, "symbol"] == "SPY"
    assert data.loc[0, "timestamp"] == pd.Timestamp("2026-05-15T14:30:00Z")


def test_to_utc_assigns_timezone_to_naive_datetime() -> None:
    assert to_utc(datetime(2026, 5, 15, 14, 30)).tzinfo == ZoneInfo("UTC")


def test_validate_date_range_treats_naive_datetimes_as_market_time() -> None:
    start_utc, end_utc = validate_date_range(
        datetime(2026, 5, 15, 9, 30),
        datetime(2026, 5, 15, 10, 0),
        "America/New_York",
    )

    assert start_utc == datetime(2026, 5, 15, 13, 30, tzinfo=ZoneInfo("UTC"))
    assert end_utc == datetime(2026, 5, 15, 14, 0, tzinfo=ZoneInfo("UTC"))
