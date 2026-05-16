"""Paper trading orchestration for strategy and risk decisions."""

from __future__ import annotations

import logging

from app.execution.alpaca_client import AlpacaExecutionClient
from app.execution.order_manager import OrderManager
from app.execution.portfolio_manager import PortfolioManager
from app.execution.trade_tracker import TradeTracker
from app.execution.types import ExecutionResult, ExecutionSide, ExecutionStatus, PortfolioSnapshot
from app.risk.types import RiskDecision
from app.strategy.types import SignalSide, StrategyDecision
from app.utils.logger import get_logger


class PaperTrader:
    """Coordinate strategy, risk, order, portfolio, and trade tracking for paper trading."""

    def __init__(
        self,
        client: AlpacaExecutionClient,
        order_manager: OrderManager | None = None,
        portfolio_manager: PortfolioManager | None = None,
        trade_tracker: TradeTracker | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        if not client.is_paper_trading():
            raise ValueError("PaperTrader requires an Alpaca client configured for paper trading.")
        self.client = client
        self.order_manager = order_manager or OrderManager(client)
        self.portfolio_manager = portfolio_manager or PortfolioManager(client)
        self.trade_tracker = trade_tracker or TradeTracker()
        self.logger = logger or get_logger(__name__)

    def execute_signal(
        self,
        strategy_decision: StrategyDecision,
        risk_decision: RiskDecision,
    ) -> ExecutionResult:
        """Submit a paper order only when strategy and risk decisions are approved."""

        if not strategy_decision.should_trade:
            return ExecutionResult(status=ExecutionStatus.SKIPPED, reasons=["Strategy decision is not tradable."])
        if not risk_decision.approved or risk_decision.position_size is None:
            return ExecutionResult(status=ExecutionStatus.SKIPPED, reasons=["Risk decision is not approved."])
        if strategy_decision.symbol is None:
            return ExecutionResult(status=ExecutionStatus.SKIPPED, reasons=["Strategy decision has no symbol."])

        side = _to_execution_side(strategy_decision.side)
        result = self.order_manager.submit_market_order(
            symbol=strategy_decision.symbol,
            quantity=risk_decision.position_size.quantity,
            side=side,
        )
        if result.order is not None:
            self.trade_tracker.record_submitted_order(result.order)
        return result

    def get_portfolio(self) -> PortfolioSnapshot:
        """Return current paper portfolio state."""

        return self.portfolio_manager.get_portfolio_snapshot()


def _to_execution_side(side: SignalSide) -> ExecutionSide:
    if side == SignalSide.BUY:
        return ExecutionSide.BUY
    if side == SignalSide.SELL:
        return ExecutionSide.SELL
    raise ValueError("Only BUY and SELL strategy decisions can be executed in paper trading.")
