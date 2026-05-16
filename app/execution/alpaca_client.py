"""Alpaca paper trading client with live trading guardrails."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Literal

import requests

from app.config import AppConfig
from app.execution.types import ExecutionSide, PaperOrderRequest
from app.utils.logger import get_logger

OrderSideName = Literal["buy", "sell"]


class AlpacaExecutionError(RuntimeError):
    """Base exception for Alpaca execution failures."""


class AlpacaCredentialsError(AlpacaExecutionError):
    """Raised when Alpaca credentials are required but not configured."""


class LiveTradingSafetyError(AlpacaExecutionError):
    """Raised when live trading safety requirements are not met."""


class AlpacaExecutionClient:
    """Thin Alpaca trading client that defaults to paper trading."""

    def __init__(
        self,
        config: AppConfig,
        logger: logging.Logger | None = None,
        trading_client: Any | None = None,
    ) -> None:
        self.config = config
        self.logger = logger or get_logger(__name__)
        self._trading_client = trading_client

    def connect(self) -> Any:
        """Create or return the underlying Alpaca TradingClient."""

        self._validate_safety()
        if self._trading_client is not None:
            return self._trading_client

        self._validate_credentials()

        try:
            from alpaca.trading.client import TradingClient
        except ImportError as exc:
            raise AlpacaExecutionError("alpaca-py is required for Alpaca execution.") from exc

        paper = self._paper_mode_enabled()
        self._trading_client = TradingClient(
            api_key=self.config.alpaca.api_key,
            secret_key=self.config.alpaca.secret_key,
            paper=paper,
        )
        self.logger.info("Connected to Alpaca trading API.", extra={"paper": paper})
        return self._trading_client

    def get_account(self) -> Any:
        """Fetch the Alpaca account for the configured trading environment."""

        client = self.connect()
        try:
            account = client.get_account()
        except Exception as exc:
            self.logger.exception("Failed to fetch Alpaca account.")
            raise AlpacaExecutionError("Failed to fetch Alpaca account.") from exc
        self.logger.info("Fetched Alpaca account details.")
        return account

    def submit_market_order(
        self,
        symbol: str,
        quantity: float,
        side: OrderSideName,
        time_in_force: str = "day",
    ) -> Any:
        """Submit a market order through Alpaca after applying safety checks."""

        self._validate_order(symbol=symbol, quantity=quantity, side=side)
        client = self.connect()

        try:
            from alpaca.trading.enums import OrderSide, TimeInForce
            from alpaca.trading.requests import MarketOrderRequest
        except ImportError as exc:
            raise AlpacaExecutionError("alpaca-py is required for order submission.") from exc

        order_request = MarketOrderRequest(
            symbol=symbol.upper(),
            qty=quantity,
            side=OrderSide.BUY if side == "buy" else OrderSide.SELL,
            time_in_force=TimeInForce(time_in_force),
        )

        try:
            order = client.submit_order(order_request)
        except Exception as exc:
            self.logger.exception("Failed to submit Alpaca market order.", extra={"symbol": symbol, "side": side})
            raise AlpacaExecutionError("Failed to submit Alpaca market order.") from exc

        self.logger.info(
            "Submitted Alpaca market order.",
            extra={"symbol": symbol.upper(), "quantity": quantity, "side": side, "paper": self._paper_mode_enabled()},
        )
        return order

    def submit_order(self, order_request: PaperOrderRequest) -> Any:
        """Submit a normalized paper order through Alpaca."""

        if order_request.order_type.value != "market":
            raise AlpacaExecutionError("Only market paper orders are supported in Phase 6.")
        side = "buy" if order_request.side == ExecutionSide.BUY else "sell"
        return self.submit_market_order(
            symbol=order_request.symbol,
            quantity=order_request.quantity,
            side=side,
            time_in_force=order_request.time_in_force,
        )

    def get_orders(self, status: str = "open", limit: int = 100) -> Any:
        """Fetch paper orders from Alpaca."""

        client = self.connect()
        try:
            from alpaca.trading.enums import QueryOrderStatus
            from alpaca.trading.requests import GetOrdersRequest
        except ImportError as exc:
            raise AlpacaExecutionError("alpaca-py is required for order queries.") from exc

        try:
            request = GetOrdersRequest(status=QueryOrderStatus(status), limit=limit)
            return client.get_orders(filter=request)
        except Exception as exc:
            self.logger.exception("Failed to fetch Alpaca orders.", extra={"status": status})
            raise AlpacaExecutionError("Failed to fetch Alpaca orders.") from exc

    def get_all_positions(self) -> Any:
        """Fetch all open paper positions from Alpaca."""

        client = self.connect()
        try:
            return client.get_all_positions()
        except Exception as exc:
            self.logger.exception("Failed to fetch Alpaca positions.")
            raise AlpacaExecutionError("Failed to fetch Alpaca positions.") from exc

    def get_portfolio_history(self, days: int = 30) -> Any:
        """Fetch paper account portfolio history from Alpaca."""

        if days <= 0:
            raise AlpacaExecutionError("days must be greater than zero.")
        client = self.connect()
        try:
            from alpaca.trading.requests import GetPortfolioHistoryRequest
        except ImportError as exc:
            raise AlpacaExecutionError("alpaca-py is required for portfolio history queries.") from exc

        end = datetime.now(timezone.utc)
        start = end - timedelta(days=days)
        try:
            request = GetPortfolioHistoryRequest(start=start, end=end, timeframe="1D")
            return client.get_portfolio_history(request)
        except Exception as exc:
            self.logger.exception("Failed to fetch Alpaca portfolio history.", extra={"days": days})
            raise AlpacaExecutionError("Failed to fetch Alpaca portfolio history.") from exc

    def get_account_activities(self, activity_type: str = "FILL", limit: int = 100) -> Any:
        """Fetch paper account activities from Alpaca REST API."""

        if limit <= 0:
            raise AlpacaExecutionError("limit must be greater than zero.")
        self._validate_safety()
        self._validate_credentials()

        base_url = _with_v2_path(self.config.alpaca.paper_base_url)
        endpoint = f"{base_url}/account/activities/{activity_type}"
        headers = {
            "APCA-API-KEY-ID": self.config.alpaca.api_key,
            "APCA-API-SECRET-KEY": self.config.alpaca.secret_key,
        }
        activities: list[Any] = []
        page_token: str | None = None
        try:
            while len(activities) < limit:
                page_size = min(100, limit - len(activities))
                params = {"direction": "desc", "page_size": page_size}
                if page_token:
                    params["page_token"] = page_token
                response = requests.get(endpoint, headers=headers, params=params, timeout=15)
                response.raise_for_status()
                page = response.json()
                if not isinstance(page, list) or not page:
                    break
                activities.extend(page)
                if len(page) < page_size:
                    break
                page_token = str(_activity_id(page[-1]) or "")
                if not page_token:
                    break
            return activities[:limit]
        except Exception as exc:
            self.logger.warning("Failed to fetch Alpaca account activities.", extra={"activity_type": activity_type})
            raise AlpacaExecutionError("Failed to fetch Alpaca account activities.") from exc

    def cancel_order(self, order_id: str) -> Any:
        """Cancel an open paper order by id."""

        if not order_id:
            raise AlpacaExecutionError("order_id is required.")
        client = self.connect()
        try:
            return client.cancel_order_by_id(order_id)
        except Exception as exc:
            self.logger.exception("Failed to cancel Alpaca order.", extra={"order_id": order_id})
            raise AlpacaExecutionError("Failed to cancel Alpaca order.") from exc

    def close_position(self, symbol: str) -> Any:
        """Close an open paper position by symbol."""

        if not symbol.strip():
            raise AlpacaExecutionError("symbol is required.")
        client = self.connect()
        try:
            return client.close_position(symbol.upper())
        except Exception as exc:
            self.logger.exception("Failed to close Alpaca position.", extra={"symbol": symbol.upper()})
            raise AlpacaExecutionError("Failed to close Alpaca position.") from exc

    def is_paper_trading(self) -> bool:
        """Return whether this client will connect in Alpaca paper trading mode."""

        return self._paper_mode_enabled()

    def _paper_mode_enabled(self) -> bool:
        return not self.config.trading.live_trading

    def _validate_safety(self) -> None:
        if self.config.trading.live_trading and self.config.alpaca.paper:
            raise LiveTradingSafetyError("Live trading requires LIVE_TRADING=true and ALPACA_PAPER=false.")
        if self.config.trading.live_trading:
            raise LiveTradingSafetyError("Phase 6 execution is paper trading only; LIVE_TRADING must be false.")
        if not self.config.trading.live_trading and not self.config.alpaca.paper:
            self.logger.warning("ALPACA_PAPER=false ignored because LIVE_TRADING is not enabled.")

    def _validate_credentials(self) -> None:
        if not self.config.alpaca.api_key or not self.config.alpaca.secret_key:
            raise AlpacaCredentialsError("ALPACA_API_KEY and ALPACA_SECRET_KEY must be configured.")

    @staticmethod
    def _validate_order(symbol: str, quantity: float, side: OrderSideName) -> None:
        if not symbol.strip():
            raise AlpacaExecutionError("Order symbol is required.")
        if quantity <= 0:
            raise AlpacaExecutionError("Order quantity must be greater than zero.")
        if side not in {"buy", "sell"}:
            raise AlpacaExecutionError("Order side must be 'buy' or 'sell'.")


def _with_v2_path(base_url: str) -> str:
    normalized = base_url.rstrip("/")
    if normalized.endswith("/v2"):
        return normalized
    return f"{normalized}/v2"


def _activity_id(activity: Any) -> Any:
    if isinstance(activity, dict):
        return activity.get("id")
    return getattr(activity, "id", None)
