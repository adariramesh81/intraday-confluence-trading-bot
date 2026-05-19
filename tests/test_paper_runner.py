from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd

from app.config import AppConfig, TradingConfig
from app.execution.types import ExecutionResult, ExecutionSide, ExecutionStatus, PaperOrder, PortfolioSnapshot, PositionSnapshot
from app.trading.paper_runner import Bot2PaperRunner


def _bot2_buy_bars() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "symbol": "SPY",
                "timestamp": datetime(2026, 5, 15, 14, 0, tzinfo=ZoneInfo("America/New_York")),
                "open": 96.0,
                "high": 97.0,
                "low": 94.0,
                "close": 95.0,
                "volume": 1500.0,
                "volume_average": 1000.0,
                "vwap": 100.0,
                "supertrend_direction": -1,
                "rsi": 39.0,
                "bb_lower": 96.0,
                "bb_middle": 100.0,
                "bb_upper": 104.0,
                "bb_bandwidth": 0.05,
                "ema_20": 97.0,
                "ma_50": 100.0,
                "macd": -1.0,
                "macd_signal": 0.0,
                "macd_bearish_cross": False,
            }
        ]
    )


def _bot2_exit_bars() -> pd.DataFrame:
    data = _bot2_buy_bars()
    data.loc[0, "close"] = 103.0
    data.loc[0, "rsi"] = 60.0
    data.loc[0, "ema_20"] = 100.0
    return data


class _FakeMarketDataClient:
    def __init__(self, bars: pd.DataFrame) -> None:
        self.bars = bars

    def fetch_ohlcv(self, **kwargs):
        return self.bars


class _FakeOrderManager:
    def __init__(self, open_orders: list[PaperOrder] | None = None) -> None:
        self.open_orders = open_orders or []
        self.submitted: list[tuple[str, float, ExecutionSide]] = []

    def list_orders(self, status: str = "open", limit: int = 100):
        return self.open_orders

    def submit_market_order(self, symbol: str, quantity: float, side: ExecutionSide, time_in_force: str = "day"):
        self.submitted.append((symbol, quantity, side))
        return ExecutionResult(status=ExecutionStatus.SUBMITTED)


class _FakePortfolioManager:
    def __init__(self, snapshot: PortfolioSnapshot, fail: bool = False) -> None:
        self.snapshot = snapshot
        self.fail = fail
        self.closed: list[str] = []

    def get_portfolio_snapshot(self):
        if self.fail:
            raise RuntimeError("unauthorized")
        return self.snapshot

    def close_position(self, symbol: str):
        self.closed.append(symbol)
        return {"symbol": symbol}


def _portfolio(positions: list[PositionSnapshot] | None = None) -> PortfolioSnapshot:
    return PortfolioSnapshot(
        equity=100_000,
        cash=100_000,
        buying_power=100_000,
        portfolio_value=100_000,
        daily_pl=0,
        positions=positions or [],
    )


def _runner(
    bars: pd.DataFrame,
    portfolio_manager: _FakePortfolioManager,
    order_manager: _FakeOrderManager | None = None,
) -> Bot2PaperRunner:
    return Bot2PaperRunner(
        config=AppConfig(trading=TradingConfig(watchlist=("SPY",), scan_interval_seconds=60)),
        market_data_client=_FakeMarketDataClient(bars),
        portfolio_manager=portfolio_manager,
        order_manager=order_manager or _FakeOrderManager(),
    )


def test_runner_submits_buy_when_no_position_and_bot2_signal_is_valid() -> None:
    order_manager = _FakeOrderManager()
    runner = _runner(_bot2_buy_bars(), _FakePortfolioManager(_portfolio()), order_manager)

    runner.scan_once()

    assert len(order_manager.submitted) == 1
    assert order_manager.submitted[0][0] == "SPY"
    assert order_manager.submitted[0][2] == ExecutionSide.BUY


def test_runner_closes_existing_position_on_exit_signal() -> None:
    position = PositionSnapshot(
        symbol="SPY",
        quantity=10,
        market_value=1030,
        average_entry_price=100,
        current_price=103,
        unrealized_pl=30,
        unrealized_plpc=0.03,
    )
    portfolio_manager = _FakePortfolioManager(_portfolio([position]))
    runner = _runner(_bot2_exit_bars(), portfolio_manager)

    runner.scan_once()

    assert portfolio_manager.closed == ["SPY"]


def test_runner_skips_duplicate_entry_when_open_order_exists() -> None:
    open_order = PaperOrder(
        id="order-1",
        client_order_id=None,
        symbol="SPY",
        quantity=1,
        side=ExecutionSide.BUY,
        status="open",
    )
    order_manager = _FakeOrderManager(open_orders=[open_order])
    runner = _runner(_bot2_buy_bars(), _FakePortfolioManager(_portfolio()), order_manager)

    runner.scan_once()

    assert order_manager.submitted == []


def test_runner_handles_account_fetch_failure_without_crashing() -> None:
    runner = _runner(_bot2_buy_bars(), _FakePortfolioManager(_portfolio(), fail=True))

    runner.scan_once()
