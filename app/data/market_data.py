"""Alpaca market data integration for live monitoring and paper trading."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from datetime import datetime
from typing import Any

import pandas as pd

from app.config import AppConfig
from app.utils.logger import get_logger
from app.utils.time_utils import validate_date_range
from app.utils.validators import DataValidationError, validate_ohlcv_dataframe, validate_symbols, validate_timeframe


class MarketDataError(RuntimeError):
    """Raised when market data cannot be fetched or normalized."""


class MarketDataCredentialsError(MarketDataError):
    """Raised when Alpaca credentials are required but unavailable."""


class AlpacaMarketDataClient:
    """Fetch canonical OHLCV bars from Alpaca market data APIs."""

    def __init__(
        self,
        config: AppConfig,
        logger: logging.Logger | None = None,
        data_client: Any | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.config = config
        self.logger = logger or get_logger(__name__)
        self._data_client = data_client
        self._sleep = sleep

    def fetch_ohlcv(
        self,
        symbols: str | list[str],
        start: datetime,
        end: datetime,
        timeframe: str | None = None,
    ) -> pd.DataFrame:
        """Fetch Alpaca OHLCV bars for one or more symbols."""

        normalized_symbols = validate_symbols(symbols)
        normalized_timeframe = validate_timeframe(timeframe or self.config.market_data.default_timeframe)
        start_utc, end_utc = validate_date_range(start, end, self.config.market_data.timezone)

        def operation() -> pd.DataFrame:
            client = self._connect()
            request = self._build_stock_bars_request(
                symbols=normalized_symbols,
                timeframe=normalized_timeframe,
                start=start_utc,
                end=end_utc,
            )
            response = client.get_stock_bars(request)
            return self._normalize_bars(response)

        try:
            data = self._retry(operation)
            validated = validate_ohlcv_dataframe(data)
        except DataValidationError:
            raise
        except MarketDataError:
            raise
        except Exception as exc:
            self.logger.exception("Failed to fetch Alpaca OHLCV data.", extra={"symbols": normalized_symbols})
            raise MarketDataError("Failed to fetch Alpaca OHLCV data.") from exc

        self.logger.info(
            "Fetched Alpaca OHLCV data.",
            extra={"symbols": normalized_symbols, "timeframe": normalized_timeframe, "rows": len(validated)},
        )
        return validated

    def _connect(self) -> Any:
        if self._data_client is not None:
            return self._data_client

        if not self.config.alpaca.api_key or not self.config.alpaca.secret_key:
            raise MarketDataCredentialsError("ALPACA_API_KEY and ALPACA_SECRET_KEY must be configured.")

        try:
            from alpaca.data.historical import StockHistoricalDataClient
        except ImportError as exc:
            raise MarketDataError("alpaca-py is required for Alpaca market data.") from exc

        self._data_client = StockHistoricalDataClient(
            api_key=self.config.alpaca.api_key,
            secret_key=self.config.alpaca.secret_key,
        )
        return self._data_client

    def _build_stock_bars_request(
        self,
        symbols: list[str],
        timeframe: str,
        start: datetime,
        end: datetime,
    ) -> Any:
        try:
            from alpaca.data.enums import Adjustment, DataFeed
            from alpaca.data.requests import StockBarsRequest
        except ImportError as exc:
            raise MarketDataError("alpaca-py is required for Alpaca market data requests.") from exc

        return StockBarsRequest(
            symbol_or_symbols=symbols,
            timeframe=_to_alpaca_timeframe(timeframe),
            start=start,
            end=end,
            adjustment=Adjustment(self.config.market_data.adjustment),
            feed=DataFeed(self.config.market_data.feed),
        )

    def _normalize_bars(self, response: Any) -> pd.DataFrame:
        raw_data = response.df if hasattr(response, "df") else response
        data = pd.DataFrame(raw_data).copy()
        if data.empty:
            raise DataValidationError("Alpaca returned no OHLCV data.")

        if isinstance(data.index, pd.MultiIndex):
            data = data.reset_index()
        elif "timestamp" not in data.columns:
            data = data.reset_index()

        data = data.rename(columns=str.lower)
        if "symbol" not in data.columns and len(data.index.names) > 0 and "symbol" in data.index.names:
            data = data.reset_index()

        canonical_columns = ["symbol", "timestamp", "open", "high", "low", "close", "volume"]
        optional_columns = [column for column in ["trade_count", "vwap"] if column in data.columns]
        return data[[column for column in canonical_columns + optional_columns if column in data.columns]]

    def _retry(self, operation: Callable[[], pd.DataFrame]) -> pd.DataFrame:
        attempts = self.config.market_data.retry_attempts
        backoff = self.config.market_data.retry_backoff_seconds
        last_error: Exception | None = None

        for attempt in range(1, attempts + 1):
            try:
                return operation()
            except DataValidationError:
                raise
            except Exception as exc:
                last_error = exc
                if attempt == attempts:
                    break
                delay = backoff * attempt
                self.logger.warning(
                    "Market data request failed; retrying.",
                    extra={"attempt": attempt, "max_attempts": attempts, "delay_seconds": delay},
                )
                self._sleep(delay)

        raise MarketDataError("Market data request failed after retries.") from last_error


def _to_alpaca_timeframe(timeframe: str) -> Any:
    try:
        from alpaca.data.timeframe import TimeFrame, TimeFrameUnit
    except ImportError as exc:
        raise MarketDataError("alpaca-py is required for Alpaca timeframe conversion.") from exc

    amount_text = "".join(character for character in timeframe if character.isdigit())
    unit_text = timeframe[len(amount_text) :]
    amount = int(amount_text)

    unit_map = {
        "Min": TimeFrameUnit.Minute,
        "Hour": TimeFrameUnit.Hour,
        "Day": TimeFrameUnit.Day,
    }
    unit = unit_map.get(unit_text)
    if unit is None:
        raise DataValidationError(f"Unsupported Alpaca timeframe: {timeframe!r}.")
    return TimeFrame(amount=amount, unit=unit)
