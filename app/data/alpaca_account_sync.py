"""Read-only Alpaca paper account sync service and CLI."""

from __future__ import annotations

import argparse
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from app.config import AppConfig, load_config
from app.dashboard.schemas import BacktestMetricsView, HealthStatus, PortfolioView, PositionView, TradeView
from app.dashboard.state_manager import DashboardStateManager
from app.data.account_store import AccountDataStore
from app.execution.alpaca_client import AlpacaExecutionClient, AlpacaExecutionError, LiveTradingSafetyError
from app.execution.order_manager import normalize_order
from app.execution.portfolio_manager import normalize_position
from app.utils.logger import configure_logging, get_logger


@dataclass(frozen=True)
class AlpacaSyncSummary:
    """Safe summary of a completed Alpaca paper account sync."""

    cash: float
    equity: float
    buying_power: float
    position_count: int
    order_count: int
    activity_count: int
    portfolio_history_count: int
    synced_at: datetime


class AlpacaAccountSyncService:
    """Pull Alpaca paper account data, persist it, and update dashboard state."""

    def __init__(
        self,
        config: AppConfig,
        client: AlpacaExecutionClient | None = None,
        store: AccountDataStore | None = None,
        state_manager: DashboardStateManager | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self.config = config
        self.client = client or AlpacaExecutionClient(config)
        self.store = store or AccountDataStore(config.storage.sqlite_path)
        self.state_manager = state_manager
        self.logger = logger or get_logger(__name__)

    def sync_once(self) -> AlpacaSyncSummary:
        """Run one paper account sync and update storage/dashboard state."""

        self._validate_paper_only()
        started_at = _utc_now()
        sync_run_id = self.store.record_sync_start(started_at)
        try:
            account = self.client.get_account()
            positions = [normalize_position(position) for position in self.client.get_all_positions()]
            orders = [normalize_order(order) for order in self.client.get_orders(status="all", limit=self.config.alpaca_sync.order_limit)]
            portfolio_history_rows = _normalize_portfolio_history(
                self.client.get_portfolio_history(days=self.config.alpaca_sync.portfolio_history_days)
            )
            activities = self._try_get_fill_activities()

            portfolio = _portfolio_from_account(account)
            timestamp = _utc_now()
            normalized_orders = [_order_to_row(order) for order in orders]
            self.store.save_account_snapshot(portfolio, timestamp)
            self.store.save_positions(positions, timestamp)
            self.store.save_orders(normalized_orders)
            self.store.save_trade_activities(activities)
            self.store.save_portfolio_history(portfolio_history_rows)
            self.store.record_sync_finish(sync_run_id, "success")

            if self.state_manager is not None:
                self._update_dashboard_state(
                    portfolio=portfolio,
                    positions=positions,
                    trades=_trades_from_orders(orders),
                    metrics=_metrics_from_portfolio_history(portfolio_history_rows),
                    message="Alpaca paper account synced.",
                )

            summary = AlpacaSyncSummary(
                cash=portfolio.cash,
                equity=portfolio.equity,
                buying_power=portfolio.buying_power,
                position_count=len(positions),
                order_count=len(orders),
                activity_count=len(activities),
                portfolio_history_count=len(portfolio_history_rows),
                synced_at=timestamp,
            )
            self.logger.info(
                "Alpaca paper account sync completed.",
                extra={
                    "positions": summary.position_count,
                    "orders": summary.order_count,
                    "activities": summary.activity_count,
                },
            )
            return summary
        except Exception as exc:
            self.store.record_sync_finish(sync_run_id, "failed", _safe_error(exc))
            self.load_cached_state_into_dashboard(message=f"Alpaca sync failed: {_safe_error(exc)}", status="warning")
            raise

    def load_cached_state_into_dashboard(self, message: str = "Loaded cached Alpaca account data.", status: str = "ok") -> None:
        """Load the latest SQLite state into the dashboard manager."""

        if self.state_manager is None:
            return
        cached = self.store.load_dashboard_data()
        self.state_manager.update_portfolio(cached.portfolio, cached.positions)
        self.state_manager.update_trades(cached.trades)
        self.state_manager.update_backtest_metrics(cached.backtest_metrics)
        self.state_manager.update_health(
            HealthStatus(
                status=status,
                environment=self.config.env,
                paper_trading=self.config.alpaca.paper,
                live_trading_enabled=self.config.trading.live_trading,
                messages=[message],
            )
        )

    def _validate_paper_only(self) -> None:
        if self.config.trading.live_trading or not self.client.is_paper_trading():
            raise LiveTradingSafetyError("Alpaca account sync is paper trading only.")

    def _try_get_fill_activities(self) -> list[dict[str, Any]]:
        try:
            raw_activities = self.client.get_account_activities(
                activity_type="FILL",
                limit=self.config.alpaca_sync.order_limit,
            )
        except AlpacaExecutionError as exc:
            self.logger.warning("Skipping Alpaca fill activities during sync.", extra={"reason": _safe_error(exc)})
            return []
        if not isinstance(raw_activities, list):
            return []
        return [_activity_to_row(activity) for activity in raw_activities]

    def _update_dashboard_state(
        self,
        portfolio: PortfolioView,
        positions: list[PositionView],
        trades: list[TradeView],
        metrics: BacktestMetricsView,
        message: str,
    ) -> None:
        if self.state_manager is None:
            return
        self.state_manager.update_portfolio(portfolio, positions)
        self.state_manager.update_trades(trades)
        self.state_manager.update_backtest_metrics(metrics)
        self.state_manager.update_health(
            HealthStatus(
                status="ok",
                environment=self.config.env,
                paper_trading=self.config.alpaca.paper,
                live_trading_enabled=self.config.trading.live_trading,
                messages=[message],
            )
        )


def main() -> None:
    """Run one read-only Alpaca paper account sync and print a safe summary."""

    parser = argparse.ArgumentParser(description="Sync Alpaca paper account data into local SQLite.")
    parser.add_argument("--config", default="config.yaml", help="Path to config YAML.")
    args = parser.parse_args()

    config = load_config(args.config)
    logger = configure_logging(config.logging)
    service = AlpacaAccountSyncService(config=config, logger=logger)
    summary = service.sync_once()
    print(
        "Alpaca paper sync complete: "
        f"cash=${summary.cash:,.2f}, "
        f"equity=${summary.equity:,.2f}, "
        f"buying_power=${summary.buying_power:,.2f}, "
        f"positions={summary.position_count}, "
        f"orders={summary.order_count}, "
        f"fills={summary.activity_count}"
    )


def _portfolio_from_account(account: Any) -> PortfolioView:
    equity = _float(_get(account, "equity", 0))
    last_equity = _float(_get(account, "last_equity", equity))
    portfolio_value = _float(_get(account, "portfolio_value", equity))
    daily_pl = equity - last_equity
    return PortfolioView(
        equity=equity,
        cash=_float(_get(account, "cash", 0)),
        buying_power=_float(_get(account, "buying_power", 0)),
        portfolio_value=portfolio_value,
        daily_pl=daily_pl,
        daily_pl_pct=daily_pl / portfolio_value if portfolio_value else 0.0,
    )


def _normalize_portfolio_history(raw_history: Any) -> list[dict[str, Any]]:
    timestamps = list(_get(raw_history, "timestamp", []) or [])
    equities = list(_get(raw_history, "equity", []) or [])
    profit_loss = list(_get(raw_history, "profit_loss", []) or [])
    profit_loss_pct = list(_get(raw_history, "profit_loss_pct", []) or [])
    rows: list[dict[str, Any]] = []
    for index, timestamp in enumerate(timestamps):
        rows.append(
            {
                "timestamp": _timestamp_to_iso(timestamp),
                "equity": _index_or_none(equities, index),
                "profit_loss": _index_or_none(profit_loss, index),
                "profit_loss_pct": _index_or_none(profit_loss_pct, index),
            }
        )
    return rows


def _metrics_from_portfolio_history(rows: list[dict[str, Any]]) -> BacktestMetricsView:
    if len(rows) < 2:
        return BacktestMetricsView(total_trades=0)
    equities = [row.get("equity") for row in rows if row.get("equity") is not None]
    if len(equities) < 2:
        return BacktestMetricsView(total_trades=0)
    first = float(equities[0])
    last = float(equities[-1])
    peak = max(float(value) for value in equities)
    drawdown = (peak - last) / peak if peak else 0.0
    return BacktestMetricsView(
        drawdown=max(0.0, drawdown),
        expectancy=last - first,
        total_trades=0,
    )


def _order_to_row(order: Any) -> dict[str, Any]:
    order_id = order.id or order.client_order_id or f"{order.symbol}-{order.side.value}-{order.submitted_at}-{order.quantity}"
    return {
        "order_id": str(order_id),
        "client_order_id": order.client_order_id,
        "symbol": order.symbol,
        "side": order.side.value,
        "quantity": order.quantity,
        "status": order.status,
        "submitted_at": _datetime_to_iso(order.submitted_at),
        "filled_at": _datetime_to_iso(order.filled_at),
        "filled_quantity": order.filled_quantity,
        "filled_average_price": order.filled_average_price,
        "raw": _raw_to_dict(order.raw),
    }


def _activity_to_row(activity: Any) -> dict[str, Any]:
    activity_id = str(_get(activity, "id", f"{_get(activity, 'order_id', '')}-{_get(activity, 'transaction_time', '')}"))
    return {
        "activity_id": activity_id,
        "activity_type": _get(activity, "activity_type", _get(activity, "type", None)),
        "symbol": _get(activity, "symbol", None),
        "side": _get(activity, "side", None),
        "quantity": _optional_float(_get(activity, "qty", _get(activity, "cum_qty", None))),
        "price": _optional_float(_get(activity, "price", None)),
        "transaction_time": _timestamp_to_iso(_get(activity, "transaction_time", None)),
        "order_id": _get(activity, "order_id", None),
        "raw": _raw_to_dict(activity),
    }


def _trades_from_orders(orders: list[Any]) -> list[TradeView]:
    return [
        TradeView(
            symbol=order.symbol,
            side=order.side.value.upper(),
            quantity=order.quantity,
            entry_price=order.filled_average_price,
            opened_at=order.submitted_at,
            closed_at=order.filled_at,
            realized_pl=0.0,
        )
        for order in orders[:100]
    ]


def _get(value: Any, name: str, default: Any = None) -> Any:
    if isinstance(value, dict):
        return value.get(name, default)
    return getattr(value, name, default)


def _raw_to_dict(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, dict):
        return value
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if hasattr(value, "dict"):
        return value.dict()
    return {"repr": repr(value)}


def _float(value: Any) -> float:
    if value is None or value == "":
        return 0.0
    return float(value)


def _optional_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    return float(value)


def _index_or_none(values: list[Any], index: int) -> float | None:
    if index >= len(values) or values[index] is None:
        return None
    return float(values[index])


def _timestamp_to_iso(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value, tz=timezone.utc).isoformat()
    if isinstance(value, datetime):
        return _datetime_to_iso(value) or ""
    return str(value)


def _datetime_to_iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _safe_error(exc: Exception) -> str:
    return str(exc).replace("\n", " ")[:300]


if __name__ == "__main__":
    main()
