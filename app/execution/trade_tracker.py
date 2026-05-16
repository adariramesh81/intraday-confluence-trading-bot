"""In-memory paper trade lifecycle and P&L tracking."""

from __future__ import annotations

from datetime import datetime

from app.execution.types import ExecutionSide, PaperOrder, TradeRecord


class TradeTracker:
    """Track paper trades and realized P&L from normalized order fills."""

    def __init__(self) -> None:
        self._trades: list[TradeRecord] = []

    def record_submitted_order(self, order: PaperOrder) -> TradeRecord:
        """Record a submitted paper order and return the trade record."""

        trade = TradeRecord(
            symbol=order.symbol,
            side=order.side,
            quantity=order.quantity,
            entry_price=order.filled_average_price,
            opened_at=order.filled_at or order.submitted_at,
            order_ids=[order.id] if order.id else [],
        )
        self._trades.append(trade)
        return trade

    def close_trade(
        self,
        symbol: str,
        exit_price: float,
        closed_at: datetime | None = None,
    ) -> TradeRecord:
        """Close the latest open trade for a symbol and calculate realized P&L."""

        if exit_price <= 0:
            raise ValueError("exit_price must be greater than zero.")

        trade = self._latest_open_trade(symbol)
        if trade is None:
            raise ValueError(f"No open trade found for {symbol.upper()}.")
        if trade.entry_price is None:
            raise ValueError("Cannot close trade before entry price is known.")

        trade.exit_price = exit_price
        trade.closed_at = closed_at or datetime.utcnow()
        trade.realized_pl = _realized_pl(trade)
        return trade

    def open_trades(self) -> list[TradeRecord]:
        """Return currently open tracked trades."""

        return [trade for trade in self._trades if trade.is_open]

    def all_trades(self) -> list[TradeRecord]:
        """Return all tracked paper trades."""

        return list(self._trades)

    def realized_pnl(self) -> float:
        """Return total realized P&L for closed tracked trades."""

        return sum(trade.realized_pl for trade in self._trades if not trade.is_open)

    def _latest_open_trade(self, symbol: str) -> TradeRecord | None:
        normalized_symbol = symbol.upper()
        for trade in reversed(self._trades):
            if trade.symbol == normalized_symbol and trade.is_open:
                return trade
        return None


def _realized_pl(trade: TradeRecord) -> float:
    if trade.entry_price is None or trade.exit_price is None:
        return 0.0
    if trade.side == ExecutionSide.BUY:
        return (trade.exit_price - trade.entry_price) * trade.quantity
    return (trade.entry_price - trade.exit_price) * trade.quantity
