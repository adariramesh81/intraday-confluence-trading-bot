"""Paper trading execution package."""

from app.execution.alpaca_client import (
    AlpacaCredentialsError,
    AlpacaExecutionClient,
    AlpacaExecutionError,
    LiveTradingSafetyError,
)
from app.execution.order_manager import OrderManager, normalize_order
from app.execution.paper_trader import PaperTrader
from app.execution.portfolio_manager import PortfolioManager, normalize_position
from app.execution.trade_tracker import TradeTracker
from app.execution.types import (
    ExecutionOrderType,
    ExecutionResult,
    ExecutionSide,
    ExecutionStatus,
    PaperOrder,
    PaperOrderRequest,
    PortfolioSnapshot,
    PositionSnapshot,
    TradeRecord,
)

__all__ = [
    "AlpacaCredentialsError",
    "AlpacaExecutionClient",
    "AlpacaExecutionError",
    "ExecutionOrderType",
    "ExecutionResult",
    "ExecutionSide",
    "ExecutionStatus",
    "LiveTradingSafetyError",
    "OrderManager",
    "PaperOrder",
    "PaperOrderRequest",
    "PaperTrader",
    "PortfolioManager",
    "PortfolioSnapshot",
    "PositionSnapshot",
    "TradeRecord",
    "TradeTracker",
    "normalize_order",
    "normalize_position",
]
