from pathlib import Path

import pytest

from app.data.account_store import AccountDataStore


def _fill(
    activity_id: str,
    order_id: str,
    symbol: str,
    side: str,
    quantity: float,
    price: float,
    timestamp: str,
) -> dict:
    return {
        "activity_id": activity_id,
        "activity_type": "FILL",
        "order_id": order_id,
        "symbol": symbol,
        "side": side,
        "quantity": quantity,
        "price": price,
        "transaction_time": timestamp,
        "raw": {},
    }


def test_completed_trade_history_projects_profit_and_loss(tmp_path: Path) -> None:
    store = AccountDataStore(tmp_path / "trades.sqlite3")
    store.initialize()
    store.save_trade_activities(
        [
            _fill("buy-profit", "buy-profit", "SPY", "buy", 2, 100, "2026-05-21T14:00:00+00:00"),
            _fill("sell-profit", "sell-profit", "SPY", "sell", 2, 102, "2026-05-21T14:01:00+00:00"),
            _fill("buy-loss", "buy-loss", "QQQ", "buy", 1, 500, "2026-05-21T14:02:00+00:00"),
            _fill("sell-loss", "sell-loss", "QQQ", "sell", 1, 495, "2026-05-21T14:03:00+00:00"),
        ]
    )

    trades = store.list_completed_trades()

    assert [trade.symbol for trade in trades] == ["QQQ", "SPY"]
    assert trades[0].realized_pl == -5
    assert trades[1].entry_price == 100
    assert trades[1].exit_price == 102
    assert trades[1].realized_pl == 4


def test_completed_trade_history_groups_partial_fills_per_order(tmp_path: Path) -> None:
    store = AccountDataStore(tmp_path / "trades.sqlite3")
    store.initialize()
    store.save_trade_activities(
        [
            _fill("buy-1", "buy-order", "AAPL", "buy", 1, 100, "2026-05-21T14:00:00+00:00"),
            _fill("buy-2", "buy-order", "AAPL", "buy", 2, 101, "2026-05-21T14:00:01+00:00"),
            _fill("sell-1", "sell-order", "AAPL", "sell", 1, 105, "2026-05-21T14:01:00+00:00"),
            _fill("sell-2", "sell-order", "AAPL", "sell", 2, 104, "2026-05-21T14:01:01+00:00"),
        ]
    )

    trades = store.list_completed_trades()

    assert len(trades) == 1
    assert trades[0].quantity == 3
    assert trades[0].entry_price == pytest.approx((100 + 202) / 3)
    assert trades[0].exit_price == pytest.approx((105 + 208) / 3)


def test_completed_trade_history_matches_fifo_and_skips_open_buys(tmp_path: Path) -> None:
    store = AccountDataStore(tmp_path / "trades.sqlite3")
    store.initialize()
    store.save_trade_activities(
        [
            _fill("buy-1", "buy-1", "NVDA", "buy", 2, 100, "2026-05-21T14:00:00+00:00"),
            _fill("buy-2", "buy-2", "NVDA", "buy", 2, 110, "2026-05-21T14:01:00+00:00"),
            _fill("sell-1", "sell-1", "NVDA", "sell", 3, 120, "2026-05-21T14:02:00+00:00"),
            _fill("open-buy", "open-buy", "MSFT", "buy", 1, 300, "2026-05-21T14:03:00+00:00"),
        ]
    )

    history = store.load_completed_trade_history()

    assert history.total == 1
    assert history.items[0].quantity == 3
    assert history.items[0].entry_price == pytest.approx((200 + 110) / 3)
    assert history.items[0].realized_pl == 50
    assert all(trade.symbol != "MSFT" for trade in history.items)
