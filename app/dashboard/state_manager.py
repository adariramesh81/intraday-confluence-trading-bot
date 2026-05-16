"""Thread-safe read-only dashboard state management."""

from __future__ import annotations

from datetime import datetime, timezone
from threading import RLock

from app.dashboard.schemas import (
    BacktestMetricsView,
    DashboardSnapshot,
    HealthStatus,
    PortfolioView,
    PositionView,
    SignalView,
    TradeView,
    to_jsonable,
)


class DashboardStateManager:
    """Store the latest portfolio, trade, signal, backtest, and health snapshots."""

    def __init__(self, initial_snapshot: DashboardSnapshot | None = None) -> None:
        self._lock = RLock()
        self._snapshot = initial_snapshot or DashboardSnapshot()

    def snapshot(self) -> DashboardSnapshot:
        """Return the current dashboard snapshot."""

        with self._lock:
            return self._snapshot

    def snapshot_dict(self) -> dict:
        """Return the current dashboard snapshot as a JSON-safe dict."""

        return to_jsonable(self.snapshot())

    def update_health(self, health: HealthStatus) -> DashboardSnapshot:
        """Update system health state."""

        return self._replace(health=health)

    def update_portfolio(self, portfolio: PortfolioView, positions: list[PositionView] | None = None) -> DashboardSnapshot:
        """Update portfolio summary and optionally open positions."""

        kwargs = {"portfolio": portfolio}
        if positions is not None:
            kwargs["positions"] = positions
        return self._replace(**kwargs)

    def update_trades(self, trades: list[TradeView]) -> DashboardSnapshot:
        """Update trade history state."""

        return self._replace(trades=trades)

    def add_signal(self, signal: SignalView, max_signals: int = 100) -> DashboardSnapshot:
        """Append a signal to the live signal stream."""

        with self._lock:
            signals = [signal, *self._snapshot.signals][:max_signals]
            self._snapshot = DashboardSnapshot(
                health=_touch(self._snapshot.health),
                portfolio=self._snapshot.portfolio,
                positions=self._snapshot.positions,
                trades=self._snapshot.trades,
                signals=signals,
                backtest_metrics=self._snapshot.backtest_metrics,
            )
            return self._snapshot

    def update_backtest_metrics(self, metrics: BacktestMetricsView) -> DashboardSnapshot:
        """Update backtest analytics state."""

        return self._replace(backtest_metrics=metrics)

    def _replace(self, **kwargs) -> DashboardSnapshot:
        with self._lock:
            self._snapshot = DashboardSnapshot(
                health=_touch(kwargs.get("health", self._snapshot.health)),
                portfolio=kwargs.get("portfolio", self._snapshot.portfolio),
                positions=kwargs.get("positions", self._snapshot.positions),
                trades=kwargs.get("trades", self._snapshot.trades),
                signals=kwargs.get("signals", self._snapshot.signals),
                backtest_metrics=kwargs.get("backtest_metrics", self._snapshot.backtest_metrics),
            )
            return self._snapshot


def _touch(health: HealthStatus) -> HealthStatus:
    return HealthStatus(
        status=health.status,
        environment=health.environment,
        paper_trading=health.paper_trading,
        live_trading_enabled=health.live_trading_enabled,
        last_updated=datetime.now(timezone.utc),
        messages=health.messages,
    )
