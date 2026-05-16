from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest

from app.config import AlpacaConfig, AppConfig, TradingConfig
from app.execution import (
    AlpacaExecutionClient,
    ExecutionSide,
    ExecutionStatus,
    LiveTradingSafetyError,
    OrderManager,
    PaperTrader,
    PortfolioManager,
    TradeTracker,
    normalize_order,
    normalize_position,
)
from app.risk import DailyTradeCounter, DrawdownState, RiskDecisionStatus, RiskManager
from app.strategy import MarketBias, SignalSide, SignalType, StrategyDecision, TradeScore


class FakePaperClient:
    def __init__(self) -> None:
        self.submitted_orders = []
        self.cancelled_orders = []
        self.closed_positions = []

    def is_paper_trading(self) -> bool:
        return True

    def submit_order(self, order_request):
        self.submitted_orders.append(order_request)
        return {
            "id": "order-1",
            "client_order_id": "client-1",
            "symbol": order_request.symbol,
            "qty": str(order_request.quantity),
            "side": order_request.side.value,
            "status": "accepted",
            "submitted_at": "2026-05-15T14:00:00+00:00",
            "filled_qty": "0",
        }

    def get_orders(self, status: str = "open", limit: int = 100):
        return [
            {
                "id": "order-2",
                "symbol": "SPY",
                "qty": "5",
                "side": "buy",
                "status": status,
            }
        ]

    def cancel_order(self, order_id: str):
        self.cancelled_orders.append(order_id)
        return None

    def get_account(self):
        return {
            "equity": "100000",
            "last_equity": "99500",
            "cash": "75000",
            "buying_power": "150000",
            "portfolio_value": "100000",
        }

    def get_all_positions(self):
        return [
            {
                "symbol": "SPY",
                "qty": "10",
                "market_value": "1010",
                "avg_entry_price": "100",
                "current_price": "101",
                "unrealized_pl": "10",
                "unrealized_plpc": "0.01",
            }
        ]

    def close_position(self, symbol: str):
        self.closed_positions.append(symbol)
        return {"symbol": symbol}


def _tradable_strategy_decision() -> StrategyDecision:
    return StrategyDecision(
        side=SignalSide.BUY,
        signal_type=SignalType.PULLBACK,
        market_bias=MarketBias.BULLISH,
        score=TradeScore(total=100, components={}, passed=True),
        symbol="SPY",
        timestamp=datetime(2026, 5, 15, 10, 0, tzinfo=ZoneInfo("America/New_York")),
    )


def _risk_decision():
    manager = RiskManager()
    return manager.evaluate_trade(
        side="BUY",
        account_equity=100_000,
        entry_price=100,
        atr=2,
        drawdown_state=DrawdownState(
            starting_equity=100_000,
            current_equity=100_000,
            peak_equity=100_000,
            daily_starting_equity=100_000,
        ),
        daily_counter=DailyTradeCounter(trading_day=date(2026, 5, 15), trades_taken=0),
    )


def test_alpaca_client_blocks_live_trading_even_with_injected_client() -> None:
    config = AppConfig(
        alpaca=AlpacaConfig(api_key="key", secret_key="secret", paper=False),
        trading=TradingConfig(live_trading=True),
    )
    client = AlpacaExecutionClient(config=config, trading_client=object())

    with pytest.raises(LiveTradingSafetyError):
        client.connect()


def test_order_manager_submits_and_normalizes_paper_order() -> None:
    fake_client = FakePaperClient()
    manager = OrderManager(fake_client)

    result = manager.submit_market_order(symbol="spy", quantity=3.5, side=ExecutionSide.BUY)

    assert result.status == ExecutionStatus.SUBMITTED
    assert result.accepted is True
    assert result.order is not None
    assert result.order.symbol == "SPY"
    assert result.order.quantity == 3.5
    assert fake_client.submitted_orders[0].side == ExecutionSide.BUY


def test_order_manager_lists_and_cancels_orders() -> None:
    fake_client = FakePaperClient()
    manager = OrderManager(fake_client)

    orders = manager.list_orders(status="open")
    cancel_result = manager.cancel_order("order-2")

    assert orders[0].id == "order-2"
    assert orders[0].status == "open"
    assert cancel_result.status == ExecutionStatus.CANCELLED
    assert fake_client.cancelled_orders == ["order-2"]


def test_portfolio_manager_normalizes_account_positions_and_daily_pnl() -> None:
    portfolio = PortfolioManager(FakePaperClient()).get_portfolio_snapshot()

    assert portfolio.equity == 100_000
    assert portfolio.daily_pl == 500
    assert len(portfolio.positions) == 1
    assert portfolio.positions[0].symbol == "SPY"
    assert portfolio.positions[0].unrealized_pl == 10


def test_trade_tracker_records_and_closes_trade_pnl() -> None:
    order = normalize_order(
        {
            "id": "order-1",
            "symbol": "SPY",
            "qty": "10",
            "side": "buy",
            "status": "filled",
            "filled_avg_price": "100",
            "filled_at": "2026-05-15T14:00:00+00:00",
        }
    )
    tracker = TradeTracker()

    tracker.record_submitted_order(order)
    trade = tracker.close_trade("SPY", exit_price=102)

    assert trade.realized_pl == 20
    assert tracker.realized_pnl() == 20
    assert tracker.open_trades() == []


def test_paper_trader_executes_only_when_strategy_and_risk_are_approved() -> None:
    fake_client = FakePaperClient()
    trader = PaperTrader(fake_client)
    risk_decision = _risk_decision()

    result = trader.execute_signal(_tradable_strategy_decision(), risk_decision)

    assert risk_decision.status == RiskDecisionStatus.APPROVED
    assert result.status == ExecutionStatus.SUBMITTED
    assert len(fake_client.submitted_orders) == 1
    assert not hasattr(trader, "submit_live_order")


def test_paper_trader_skips_non_tradable_strategy_decision() -> None:
    trader = PaperTrader(FakePaperClient())
    decision = StrategyDecision(
        side=SignalSide.HOLD,
        signal_type=SignalType.NONE,
        market_bias=MarketBias.NEUTRAL,
        score=TradeScore(total=0, components={}, passed=False),
        symbol="SPY",
    )

    result = trader.execute_signal(decision, _risk_decision())

    assert result.status == ExecutionStatus.SKIPPED


def test_normalizers_accept_dict_payloads() -> None:
    order = normalize_order({"symbol": "SPY", "qty": "1", "side": "sell", "status": "filled"})
    position = normalize_position(
        {
            "symbol": "QQQ",
            "qty": "2",
            "market_value": "900",
            "avg_entry_price": "440",
            "current_price": "450",
            "unrealized_pl": "20",
            "unrealized_plpc": "0.02",
        }
    )

    assert order.side == ExecutionSide.SELL
    assert position.symbol == "QQQ"
    assert position.current_price == 450
