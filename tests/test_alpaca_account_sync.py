from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from app.config import AlpacaConfig, AlpacaSyncConfig, AppConfig, StorageConfig, TradingConfig
from app.dashboard.state_manager import DashboardStateManager
from app.data.account_store import AccountDataStore
from app.data.alpaca_account_sync import AlpacaAccountSyncService
from app.execution.alpaca_client import LiveTradingSafetyError


class FakeSyncClient:
    def __init__(self, fail_account: bool = False) -> None:
        self.fail_account = fail_account

    def is_paper_trading(self) -> bool:
        return True

    def get_account(self):
        if self.fail_account:
            raise RuntimeError("account unavailable")
        return {
            "cash": "75000",
            "equity": "100000",
            "last_equity": "99500",
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

    def get_orders(self, status: str = "all", limit: int = 500):
        return [
            {
                "id": "order-1",
                "client_order_id": "client-1",
                "symbol": "SPY",
                "qty": "10",
                "side": "buy",
                "status": "filled",
                "submitted_at": "2026-05-15T14:00:00+00:00",
                "filled_at": "2026-05-15T14:01:00+00:00",
                "filled_qty": "10",
                "filled_avg_price": "100",
            }
        ]

    def get_portfolio_history(self, days: int = 30):
        return {
            "timestamp": [1_768_000_000, 1_768_086_400],
            "equity": [99_500, 100_000],
            "profit_loss": [0, 500],
            "profit_loss_pct": [0, 0.005],
        }

    def get_account_activities(self, activity_type: str = "FILL", limit: int = 500):
        return [
            {
                "id": "fill-1",
                "activity_type": "FILL",
                "symbol": "SPY",
                "side": "buy",
                "qty": "10",
                "price": "100",
                "transaction_time": "2026-05-15T14:01:00+00:00",
                "order_id": "order-1",
            }
        ]


def _config(tmp_path: Path) -> AppConfig:
    return AppConfig(
        alpaca=AlpacaConfig(api_key="key", secret_key="secret", paper=True),
        storage=StorageConfig(sqlite_path=tmp_path / "account.sqlite3"),
        alpaca_sync=AlpacaSyncConfig(enabled=True, refresh_seconds=30, order_limit=500, portfolio_history_days=30),
    )


def test_alpaca_account_sync_persists_and_updates_dashboard(tmp_path: Path) -> None:
    state = DashboardStateManager()
    service = AlpacaAccountSyncService(
        config=_config(tmp_path),
        client=FakeSyncClient(),
        store=AccountDataStore(tmp_path / "account.sqlite3"),
        state_manager=state,
    )

    summary = service.sync_once()
    snapshot = state.snapshot()

    assert summary.cash == 75_000
    assert summary.position_count == 1
    assert summary.order_count == 1
    assert summary.activity_count == 1
    assert snapshot.portfolio.cash == 75_000
    assert snapshot.positions[0].symbol == "SPY"
    assert snapshot.trades[0].symbol == "SPY"
    assert snapshot.health.status == "ok"


def test_account_store_loads_cached_dashboard_data(tmp_path: Path) -> None:
    store = AccountDataStore(tmp_path / "account.sqlite3")
    service = AlpacaAccountSyncService(config=_config(tmp_path), client=FakeSyncClient(), store=store)
    service.sync_once()

    cached = store.load_dashboard_data()

    assert cached.portfolio.equity == 100_000
    assert cached.positions[0].quantity == 10
    assert cached.trades[0].entry_price == 100


def test_alpaca_account_sync_refuses_live_trading(tmp_path: Path) -> None:
    config = AppConfig(
        alpaca=AlpacaConfig(api_key="key", secret_key="secret", paper=False),
        trading=TradingConfig(live_trading=True),
        storage=StorageConfig(sqlite_path=tmp_path / "account.sqlite3"),
    )
    service = AlpacaAccountSyncService(config=config, client=FakeSyncClient())

    with pytest.raises(LiveTradingSafetyError):
        service.sync_once()


def test_alpaca_account_sync_records_failure_and_keeps_cached_state(tmp_path: Path) -> None:
    state = DashboardStateManager()
    store = AccountDataStore(tmp_path / "account.sqlite3")
    service = AlpacaAccountSyncService(config=_config(tmp_path), client=FakeSyncClient(), store=store, state_manager=state)
    service.sync_once()
    failing_service = AlpacaAccountSyncService(
        config=_config(tmp_path),
        client=FakeSyncClient(fail_account=True),
        store=store,
        state_manager=state,
    )

    with pytest.raises(RuntimeError):
        failing_service.sync_once()

    assert state.snapshot().portfolio.equity == 100_000
    assert state.snapshot().health.status == "warning"


def test_account_store_handles_empty_positions_and_orders(tmp_path: Path) -> None:
    class EmptyClient(FakeSyncClient):
        def get_all_positions(self):
            return []

        def get_orders(self, status: str = "all", limit: int = 500):
            return []

        def get_account_activities(self, activity_type: str = "FILL", limit: int = 500):
            return []

    state = DashboardStateManager()
    service = AlpacaAccountSyncService(
        config=_config(tmp_path),
        client=EmptyClient(),
        store=AccountDataStore(tmp_path / "account.sqlite3"),
        state_manager=state,
    )

    summary = service.sync_once()

    assert summary.position_count == 0
    assert summary.order_count == 0
    assert state.snapshot().positions == []
