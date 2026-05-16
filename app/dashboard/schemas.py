"""Dashboard response schemas and serialization helpers."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, is_dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any


@dataclass(frozen=True)
class HealthStatus:
    """System health details for monitoring."""

    status: str = "ok"
    environment: str = "development"
    paper_trading: bool = True
    live_trading_enabled: bool = False
    last_updated: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    messages: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class PortfolioView:
    """Portfolio summary displayed in the dashboard."""

    equity: float = 0.0
    cash: float = 0.0
    buying_power: float = 0.0
    portfolio_value: float = 0.0
    daily_pl: float = 0.0
    daily_pl_pct: float = 0.0


@dataclass(frozen=True)
class PositionView:
    """Open position row for dashboard display."""

    symbol: str
    quantity: float
    market_value: float
    average_entry_price: float
    current_price: float
    unrealized_pl: float
    unrealized_plpc: float


@dataclass(frozen=True)
class TradeView:
    """Tracked trade history row."""

    symbol: str
    side: str
    quantity: float
    entry_price: float | None = None
    exit_price: float | None = None
    opened_at: datetime | None = None
    closed_at: datetime | None = None
    realized_pl: float = 0.0


@dataclass(frozen=True)
class SignalView:
    """Live strategy signal row."""

    symbol: str
    side: str
    signal_type: str
    score: int
    should_trade: bool
    timestamp: datetime | None = None
    reasons: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class BacktestMetricsView:
    """Backtest analytics summary displayed in the dashboard."""

    win_rate: float = 0.0
    profit_factor: float = 0.0
    drawdown: float = 0.0
    sharpe_ratio: float = 0.0
    expectancy: float = 0.0
    total_trades: int = 0


@dataclass(frozen=True)
class DashboardSnapshot:
    """Complete read-only dashboard state."""

    health: HealthStatus = field(default_factory=HealthStatus)
    portfolio: PortfolioView = field(default_factory=PortfolioView)
    positions: list[PositionView] = field(default_factory=list)
    trades: list[TradeView] = field(default_factory=list)
    signals: list[SignalView] = field(default_factory=list)
    backtest_metrics: BacktestMetricsView = field(default_factory=BacktestMetricsView)


def to_jsonable(value: Any) -> Any:
    """Convert dashboard dataclasses and Python values into JSON-safe structures."""

    if is_dataclass(value):
        return {key: to_jsonable(item) for key, item in asdict(value).items()}
    if isinstance(value, dict):
        return {key: to_jsonable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [to_jsonable(item) for item in value]
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    return value
