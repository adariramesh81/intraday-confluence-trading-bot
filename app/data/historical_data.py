"""Historical OHLCV data fetching through yfinance for backtesting."""

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
from app.utils.validators import DataValidationError, validate_ohlcv_dataframe, validate_symbol, validate_timeframe


class HistoricalDataError(RuntimeError):
    """Raised when historical market data cannot be fetched or normalized."""


class YFinanceHistoricalDataClient:
    """Fetch canonical OHLCV bars from yfinance for backtesting."""

    def __init__(
        self,
        config: AppConfig,
        logger: logging.Logger | None = None,
        downloader: Callable[..., Any] | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.config = config
        self.logger = logger or get_logger(__name__)
        self._downloader = downloader
        self._sleep = sleep

    def fetch_ohlcv(
        self,
        symbol: str,
        start: datetime,
        end: datetime,
        timeframe: str | None = None,
        auto_adjust: bool = False,
    ) -> pd.DataFrame:
        """Fetch yfinance historical OHLCV data for one symbol."""

        normalized_symbol = validate_symbol(symbol)
        normalized_timeframe = validate_timeframe(timeframe or self.config.market_data.default_timeframe)
        start_utc, end_utc = validate_date_range(start, end, self.config.market_data.timezone)
        interval = _to_yfinance_interval(normalized_timeframe)

        def operation() -> pd.DataFrame:
            downloader = self._resolve_downloader()
            response = downloader(
                tickers=normalized_symbol,
                start=start_utc,
                end=end_utc,
                interval=interval,
                auto_adjust=auto_adjust,
                progress=False,
                threads=False,
                timeout=self.config.market_data.timeout_seconds,
                multi_level_index=False,
            )
            return self._normalize_response(response, normalized_symbol)

        try:
            data = self._retry(operation)
            validated = validate_ohlcv_dataframe(data)
        except DataValidationError:
            raise
        except HistoricalDataError:
            raise
        except Exception as exc:
            self.logger.exception("Failed to fetch yfinance OHLCV data.", extra={"symbol": normalized_symbol})
            raise HistoricalDataError("Failed to fetch yfinance OHLCV data.") from exc

        self.logger.info(
            "Fetched yfinance OHLCV data.",
            extra={"symbol": normalized_symbol, "timeframe": normalized_timeframe, "rows": len(validated)},
        )
        return validated

    def _resolve_downloader(self) -> Callable[..., Any]:
        if self._downloader is not None:
            return self._downloader

        try:
            import yfinance as yf
        except ImportError as exc:
            raise HistoricalDataError("yfinance is required for historical data.") from exc

        self._downloader = yf.download
        return self._downloader

    @staticmethod
    def _normalize_response(response: Any, symbol: str) -> pd.DataFrame:
        data = pd.DataFrame(response).copy()
        if data.empty:
            raise DataValidationError("yfinance returned no OHLCV data.")

        if isinstance(data.columns, pd.MultiIndex):
            data.columns = [column[0] for column in data.columns]

        data = data.reset_index()
        data.columns = [str(column).strip().lower().replace(" ", "_") for column in data.columns]
        data = data.rename(columns={"date": "timestamp", "datetime": "timestamp"})
        data["symbol"] = symbol

        canonical_columns = ["symbol", "timestamp", "open", "high", "low", "close", "volume"]
        return data[canonical_columns]

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
                    "Historical data request failed; retrying.",
                    extra={"attempt": attempt, "max_attempts": attempts, "delay_seconds": delay},
                )
                self._sleep(delay)

        raise HistoricalDataError("Historical data request failed after retries.") from last_error


def _to_yfinance_interval(timeframe: str) -> str:
    interval_map = {
        "1Min": "1m",
        "2Min": "2m",
        "5Min": "5m",
        "15Min": "15m",
        "30Min": "30m",
        "1Hour": "1h",
        "1Day": "1d",
    }
    if timeframe not in interval_map:
        raise DataValidationError(f"Unsupported yfinance timeframe: {timeframe!r}.")
    return interval_map[timeframe]
