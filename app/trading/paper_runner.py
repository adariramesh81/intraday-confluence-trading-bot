"""Bot 2 automated paper-trading runner."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone

import pandas as pd

from app.config import AppConfig, load_config
from app.data.account_store import AccountDataStore
from app.data.market_data import AlpacaMarketDataClient
from app.execution import AlpacaExecutionClient, ExecutionSide, OrderManager, PortfolioManager
from app.execution.types import ExecutionStatus, PortfolioSnapshot, PositionSnapshot
from app.risk import DailyTradeCounter, DrawdownState, RiskManager, RiskSettings, TradeSide
from app.strategy import SignalEngine, SignalSide
from app.strategy.signal_engine import bot2_locked_stop, should_move_bot2_stop_to_break_even
from app.utils.logger import configure_logging, get_logger


@dataclass
class Bot2TrailingState:
    """Per-symbol Bot 2 trailing stop state."""

    stops: dict[str, float] = field(default_factory=dict)

    def update(self, symbol: str, entry_price: float, current_price: float) -> float | None:
        """Update and return the current protective stop for a long position."""

        normalized = symbol.upper()
        current_stop = self.stops.get(normalized)
        if should_move_bot2_stop_to_break_even(entry_price, current_price):
            current_stop = max(current_stop or 0.0, entry_price)
        locked_stop = bot2_locked_stop(entry_price, current_price)
        if locked_stop is not None:
            current_stop = max(current_stop or 0.0, locked_stop)
        if current_stop is not None:
            self.stops[normalized] = current_stop
        return current_stop

    def clear(self, symbol: str) -> None:
        """Clear trailing state for a symbol."""

        self.stops.pop(symbol.upper(), None)


class Bot2PaperRunner:
    """Scan a watchlist and submit Bot 2 paper-trading orders."""

    def __init__(
        self,
        config: AppConfig,
        execution_client: AlpacaExecutionClient | None = None,
        market_data_client: AlpacaMarketDataClient | None = None,
        order_manager: OrderManager | None = None,
        portfolio_manager: PortfolioManager | None = None,
        signal_engine: SignalEngine | None = None,
        risk_manager: RiskManager | None = None,
        watchlist_store: AccountDataStore | None = None,
        trailing_state: Bot2TrailingState | None = None,
        logger: logging.Logger | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.config = config
        self.logger = logger or get_logger(__name__)
        self.execution_client = execution_client or AlpacaExecutionClient(config=config, logger=self.logger)
        self.market_data_client = market_data_client or AlpacaMarketDataClient(config=config, logger=self.logger)
        self.order_manager = order_manager or OrderManager(self.execution_client, logger=self.logger)
        self.portfolio_manager = portfolio_manager or PortfolioManager(self.execution_client, logger=self.logger)
        self.signal_engine = signal_engine or SignalEngine(logger=self.logger)
        self.risk_manager = risk_manager or RiskManager(_risk_settings_from_config(config), logger=self.logger)
        self.watchlist_store = watchlist_store or AccountDataStore(config.storage.sqlite_path)
        self.trailing_state = trailing_state or Bot2TrailingState()
        self.sleep = sleep

    def run_forever(self) -> None:
        """Run the Bot 2 scan loop until interrupted."""

        self.logger.info(
            "Starting Bot 2 paper runner.",
            extra={"watchlist": list(self.config.trading.watchlist), "interval": self.config.trading.scan_interval_seconds},
        )
        while True:
            self.scan_once()
            self.sleep(self.config.trading.scan_interval_seconds)

    def scan_once(self) -> None:
        """Scan the configured watchlist once and submit safe paper actions."""

        try:
            portfolio = self.portfolio_manager.get_portfolio_snapshot()
            open_orders = self.order_manager.list_orders(status="open", limit=100)
            watchlist = self.watchlist_store.get_watchlist(self.config.trading.watchlist)
        except Exception:
            self.logger.exception("Bot 2 scan skipped because account state could not be fetched.")
            return

        open_order_symbols = {order.symbol.upper() for order in open_orders}
        positions = {position.symbol.upper(): position for position in portfolio.positions}
        deployed_notional = sum(abs(position.market_value) for position in portfolio.positions)

        self.logger.info("Scanning Bot 2 watchlist.", extra={"watchlist": watchlist})
        for symbol in watchlist:
            normalized = symbol.upper()
            try:
                bars = self._fetch_recent_bars(normalized)
                if normalized in positions:
                    self._manage_position(normalized, bars, positions[normalized])
                elif normalized not in open_order_symbols:
                    self._evaluate_entry(normalized, bars, portfolio, deployed_notional, positions)
                else:
                    self.logger.info("Skipping symbol with open order.", extra={"symbol": normalized})
            except Exception:
                self.logger.exception("Bot 2 symbol scan failed.", extra={"symbol": normalized})

    def _fetch_recent_bars(self, symbol: str) -> pd.DataFrame:
        end = datetime.now(timezone.utc)
        start = end - timedelta(days=3)
        return self.market_data_client.fetch_ohlcv(
            symbols=symbol,
            start=start,
            end=end,
            timeframe=self.config.market_data.default_timeframe,
        )

    def _manage_position(self, symbol: str, bars: pd.DataFrame, position: PositionSnapshot) -> None:
        trailing_stop = self.trailing_state.update(
            symbol=symbol,
            entry_price=position.average_entry_price,
            current_price=position.current_price,
        )
        decision = self.signal_engine.generate_signal(
            bars,
            position_entry_price=position.average_entry_price,
            trailing_stop_loss=trailing_stop,
        )
        if decision.side != SignalSide.SELL:
            return
        try:
            self.portfolio_manager.close_position(symbol)
            self.trailing_state.clear(symbol)
            self.logger.info("Closed Bot 2 paper position.", extra={"symbol": symbol, "reasons": decision.reasons})
        except Exception:
            self.logger.exception("Failed to close Bot 2 paper position.", extra={"symbol": symbol})

    def _evaluate_entry(
        self,
        symbol: str,
        bars: pd.DataFrame,
        portfolio: PortfolioSnapshot,
        deployed_notional: float,
        positions: dict[str, PositionSnapshot],
    ) -> None:
        decision = self.signal_engine.generate_signal(bars)
        if not decision.should_trade:
            self.logger.info("Bot 2 entry skipped.", extra={"symbol": symbol, "reasons": decision.reasons})
            return

        entry_price = float(decision.metadata["close"])
        atr_for_three_pct_stop = entry_price * 0.03
        risk_decision = self.risk_manager.evaluate_trade(
            side=TradeSide.BUY,
            account_equity=portfolio.equity,
            entry_price=entry_price,
            atr=atr_for_three_pct_stop,
            drawdown_state=_drawdown_state_from_portfolio(portfolio),
            daily_counter=DailyTradeCounter(trading_day=date.today(), trades_taken=0),
            timestamp=decision.timestamp,
            open_positions_count=len(positions),
            deployed_notional=deployed_notional,
            cash=portfolio.cash,
            sector_notional=_sector_notional(symbol, positions, self.config),
        )
        if not risk_decision.approved or risk_decision.position_size is None:
            self.logger.info("Bot 2 risk rejected entry.", extra={"symbol": symbol, "reasons": risk_decision.reasons})
            return

        result = self.order_manager.submit_market_order(
            symbol=symbol,
            quantity=risk_decision.position_size.quantity,
            side=ExecutionSide.BUY,
        )
        if result.status == ExecutionStatus.SUBMITTED:
            self.logger.info("Submitted Bot 2 paper BUY.", extra={"symbol": symbol, "quantity": risk_decision.position_size.quantity})
        else:
            self.logger.warning("Bot 2 paper BUY was not submitted.", extra={"symbol": symbol, "reasons": result.reasons})


def _risk_settings_from_config(config: AppConfig) -> RiskSettings:
    return RiskSettings(
        risk_per_trade=config.trading.risk_per_trade,
        max_trades_per_day=config.trading.max_trades_per_day,
        max_daily_drawdown_pct=config.risk.max_daily_drawdown,
        max_position_notional_pct=config.risk.max_position_notional_pct,
        max_open_positions=config.risk.max_open_positions,
        cash_reserve_pct=config.risk.cash_reserve_pct,
        max_deployed_pct=config.risk.max_deployed_pct,
        max_sector_pct=config.risk.max_sector_pct,
    )


def _drawdown_state_from_portfolio(portfolio: PortfolioSnapshot) -> DrawdownState:
    daily_starting_equity = portfolio.equity - portfolio.daily_pl
    if daily_starting_equity <= 0:
        daily_starting_equity = portfolio.equity
    return DrawdownState(
        starting_equity=portfolio.equity,
        current_equity=portfolio.equity,
        peak_equity=max(portfolio.equity, portfolio.portfolio_value),
        daily_starting_equity=daily_starting_equity,
        daily_realized_pnl=portfolio.daily_pl,
    )


def _sector_notional(symbol: str, positions: dict[str, PositionSnapshot], config: AppConfig) -> float:
    sectors = config.risk.symbol_sectors
    target_sector = sectors.get(symbol.upper(), "UNCLASSIFIED")
    return sum(
        abs(position.market_value)
        for position in positions.values()
        if sectors.get(position.symbol.upper(), "UNCLASSIFIED") == target_sector
    )


def main() -> None:
    """Load configuration and start the Bot 2 paper-trading runner."""

    config = load_config()
    logger = configure_logging(config.logging)
    Bot2PaperRunner(config=config, logger=logger).run_forever()


if __name__ == "__main__":
    main()
