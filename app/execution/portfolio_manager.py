"""Portfolio and open position tracking from Alpaca paper account state."""

from __future__ import annotations

import logging
from typing import Any

from app.execution.alpaca_client import AlpacaExecutionClient
from app.execution.types import PortfolioSnapshot, PositionSnapshot
from app.utils.logger import get_logger


class PortfolioManager:
    """Fetch and normalize account, position, and P&L data."""

    def __init__(
        self,
        client: AlpacaExecutionClient,
        logger: logging.Logger | None = None,
    ) -> None:
        self.client = client
        self.logger = logger or get_logger(__name__)

    def get_portfolio_snapshot(self) -> PortfolioSnapshot:
        """Return normalized paper account and position state."""

        account = self.client.get_account()
        positions = self.get_open_positions()
        equity = _float(_get(account, "equity", 0))
        last_equity = _float(_get(account, "last_equity", equity))
        snapshot = PortfolioSnapshot(
            equity=equity,
            cash=_float(_get(account, "cash", 0)),
            buying_power=_float(_get(account, "buying_power", 0)),
            portfolio_value=_float(_get(account, "portfolio_value", equity)),
            daily_pl=equity - last_equity,
            positions=positions,
        )
        self.logger.info(
            "Fetched paper portfolio snapshot.",
            extra={"equity": snapshot.equity, "positions": len(snapshot.positions), "daily_pl": snapshot.daily_pl},
        )
        return snapshot

    def get_open_positions(self) -> list[PositionSnapshot]:
        """Return normalized open paper positions."""

        raw_positions = self.client.get_all_positions()
        return [normalize_position(position) for position in raw_positions]

    def close_position(self, symbol: str) -> Any:
        """Request Alpaca to close a paper position."""

        return self.client.close_position(symbol)


def normalize_position(raw_position: Any) -> PositionSnapshot:
    """Normalize an Alpaca SDK position object or dict."""

    return PositionSnapshot(
        symbol=str(_get(raw_position, "symbol", "")).upper(),
        quantity=_float(_get(raw_position, "qty", 0)),
        market_value=_float(_get(raw_position, "market_value", 0)),
        average_entry_price=_float(_get(raw_position, "avg_entry_price", 0)),
        current_price=_float(_get(raw_position, "current_price", 0)),
        unrealized_pl=_float(_get(raw_position, "unrealized_pl", 0)),
        unrealized_plpc=_float(_get(raw_position, "unrealized_plpc", 0)),
    )


def _get(value: Any, name: str, default: Any = None) -> Any:
    if isinstance(value, dict):
        return value.get(name, default)
    return getattr(value, name, default)


def _float(value: Any) -> float:
    if value is None or value == "":
        return 0.0
    return float(value)
