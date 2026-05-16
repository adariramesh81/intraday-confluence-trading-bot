"""Paper order lifecycle management."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from app.execution.alpaca_client import AlpacaExecutionClient, AlpacaExecutionError
from app.execution.types import ExecutionResult, ExecutionSide, ExecutionStatus, PaperOrder, PaperOrderRequest
from app.utils.logger import get_logger


class OrderManager:
    """Submit and manage Alpaca paper orders."""

    def __init__(
        self,
        client: AlpacaExecutionClient,
        logger: logging.Logger | None = None,
    ) -> None:
        self.client = client
        self.logger = logger or get_logger(__name__)

    def submit_market_order(
        self,
        symbol: str,
        quantity: float,
        side: ExecutionSide,
        time_in_force: str = "day",
    ) -> ExecutionResult:
        """Submit a paper market order and return a normalized result."""

        request = PaperOrderRequest(
            symbol=symbol.upper(),
            quantity=quantity,
            side=side,
            time_in_force=time_in_force,
        )
        try:
            raw_order = self.client.submit_order(request)
            order = normalize_order(raw_order, fallback_request=request)
        except AlpacaExecutionError as exc:
            self.logger.exception("Paper order rejected by Alpaca.")
            return ExecutionResult(status=ExecutionStatus.REJECTED, reasons=[str(exc)])

        self.logger.info(
            "Submitted paper order.",
            extra={"symbol": order.symbol, "side": order.side.value, "quantity": order.quantity, "status": order.status},
        )
        return ExecutionResult(status=ExecutionStatus.SUBMITTED, order=order)

    def list_orders(self, status: str = "open", limit: int = 100) -> list[PaperOrder]:
        """Return normalized paper orders."""

        raw_orders = self.client.get_orders(status=status, limit=limit)
        return [normalize_order(order) for order in raw_orders]

    def cancel_order(self, order_id: str) -> ExecutionResult:
        """Cancel an open paper order."""

        try:
            self.client.cancel_order(order_id)
        except AlpacaExecutionError as exc:
            return ExecutionResult(status=ExecutionStatus.REJECTED, reasons=[str(exc)])
        return ExecutionResult(status=ExecutionStatus.CANCELLED, reasons=[f"Cancelled order {order_id}."])


def normalize_order(raw_order: Any, fallback_request: PaperOrderRequest | None = None) -> PaperOrder:
    """Normalize an Alpaca SDK order object or dict into a PaperOrder."""

    symbol = str(_get(raw_order, "symbol", fallback_request.symbol if fallback_request else "")).upper()
    raw_side = str(_enum_value(_get(raw_order, "side", fallback_request.side.value if fallback_request else "buy"))).lower()
    quantity = _float(_get(raw_order, "qty", _get(raw_order, "quantity", fallback_request.quantity if fallback_request else 0)))

    return PaperOrder(
        id=_optional_str(_get(raw_order, "id", None)),
        client_order_id=_optional_str(_get(raw_order, "client_order_id", fallback_request.client_order_id if fallback_request else None)),
        symbol=symbol,
        quantity=quantity,
        side=ExecutionSide.BUY if raw_side == "buy" else ExecutionSide.SELL,
        status=str(_enum_value(_get(raw_order, "status", "unknown"))),
        submitted_at=_datetime_or_none(_get(raw_order, "submitted_at", None)),
        filled_at=_datetime_or_none(_get(raw_order, "filled_at", None)),
        filled_quantity=_float(_get(raw_order, "filled_qty", 0)),
        filled_average_price=_optional_float(_get(raw_order, "filled_avg_price", None)),
        raw=raw_order,
    )


def _get(value: Any, name: str, default: Any = None) -> Any:
    if isinstance(value, dict):
        return value.get(name, default)
    return getattr(value, name, default)


def _enum_value(value: Any) -> Any:
    return getattr(value, "value", value)


def _float(value: Any) -> float:
    if value is None or value == "":
        return 0.0
    return float(value)


def _optional_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    return float(value)


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)


def _datetime_or_none(value: Any) -> datetime | None:
    if value is None or isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
