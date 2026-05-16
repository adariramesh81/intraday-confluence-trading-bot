"""Execution engine data types."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class ExecutionSide(str, Enum):
    """Supported paper order sides."""

    BUY = "buy"
    SELL = "sell"


class ExecutionOrderType(str, Enum):
    """Supported paper order types."""

    MARKET = "market"


class ExecutionStatus(str, Enum):
    """Execution result states."""

    SUBMITTED = "SUBMITTED"
    REJECTED = "REJECTED"
    SKIPPED = "SKIPPED"
    CANCELLED = "CANCELLED"


@dataclass(frozen=True)
class PaperOrderRequest:
    """Normalized paper order request."""

    symbol: str
    quantity: float
    side: ExecutionSide
    order_type: ExecutionOrderType = ExecutionOrderType.MARKET
    time_in_force: str = "day"
    client_order_id: str | None = None


@dataclass(frozen=True)
class PaperOrder:
    """Normalized paper order returned from Alpaca."""

    id: str | None
    client_order_id: str | None
    symbol: str
    quantity: float
    side: ExecutionSide
    status: str
    submitted_at: datetime | None = None
    filled_at: datetime | None = None
    filled_quantity: float = 0.0
    filled_average_price: float | None = None
    raw: Any | None = None


@dataclass(frozen=True)
class ExecutionResult:
    """Paper execution result with no live trading side effects."""

    status: ExecutionStatus
    order: PaperOrder | None = None
    reasons: list[str] = field(default_factory=list)

    @property
    def accepted(self) -> bool:
        """Return whether the paper order was accepted for submission."""

        return self.status == ExecutionStatus.SUBMITTED


@dataclass(frozen=True)
class PositionSnapshot:
    """Normalized open position state."""

    symbol: str
    quantity: float
    market_value: float
    average_entry_price: float
    current_price: float
    unrealized_pl: float
    unrealized_plpc: float


@dataclass(frozen=True)
class PortfolioSnapshot:
    """Normalized account and portfolio state."""

    equity: float
    cash: float
    buying_power: float
    portfolio_value: float
    daily_pl: float
    positions: list[PositionSnapshot] = field(default_factory=list)


@dataclass
class TradeRecord:
    """Tracked paper trade lifecycle record."""

    symbol: str
    side: ExecutionSide
    quantity: float
    entry_price: float | None = None
    exit_price: float | None = None
    opened_at: datetime | None = None
    closed_at: datetime | None = None
    realized_pl: float = 0.0
    order_ids: list[str] = field(default_factory=list)

    @property
    def is_open(self) -> bool:
        """Return whether this tracked trade is still open."""

        return self.closed_at is None
