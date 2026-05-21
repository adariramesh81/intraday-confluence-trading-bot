"""SQLite persistence for Alpaca paper account sync data."""

from __future__ import annotations

import json
import math
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.dashboard.schemas import BacktestMetricsView, PortfolioView, PositionView, TradeView
from app.utils.validators import DataValidationError, validate_symbols


@dataclass(frozen=True)
class StoredDashboardData:
    """Dashboard-ready values loaded from local SQLite storage."""

    portfolio: PortfolioView
    positions: list[PositionView]
    trades: list[TradeView]
    backtest_metrics: BacktestMetricsView


@dataclass(frozen=True)
class CompletedTradeHistoryPage:
    """Page of completed long trades derived from saved Alpaca fills."""

    items: list[TradeView]
    page: int
    page_size: int
    total: int
    pages: int


@dataclass
class _FillGroup:
    symbol: str
    side: str
    quantity: float
    notional: float
    transaction_time: datetime | None

    @property
    def price(self) -> float:
        return self.notional / self.quantity if self.quantity else 0.0


@dataclass
class _EntryLot:
    quantity: float
    price: float
    opened_at: datetime | None


class AccountDataStore:
    """Persist normalized Alpaca account, position, order, and portfolio history data."""

    def __init__(self, sqlite_path: str | Path) -> None:
        self.sqlite_path = Path(sqlite_path)

    def initialize(self) -> None:
        """Create database tables when they do not already exist."""

        self.sqlite_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS account_snapshots (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    cash REAL NOT NULL,
                    equity REAL NOT NULL,
                    buying_power REAL NOT NULL,
                    portfolio_value REAL NOT NULL,
                    daily_pl REAL NOT NULL
                );

                CREATE TABLE IF NOT EXISTS positions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    snapshot_timestamp TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    quantity REAL NOT NULL,
                    market_value REAL NOT NULL,
                    average_entry_price REAL NOT NULL,
                    current_price REAL NOT NULL,
                    unrealized_pl REAL NOT NULL,
                    unrealized_plpc REAL NOT NULL
                );

                CREATE TABLE IF NOT EXISTS orders (
                    order_id TEXT PRIMARY KEY,
                    client_order_id TEXT,
                    symbol TEXT NOT NULL,
                    side TEXT NOT NULL,
                    quantity REAL NOT NULL,
                    status TEXT NOT NULL,
                    submitted_at TEXT,
                    filled_at TEXT,
                    filled_quantity REAL NOT NULL,
                    filled_average_price REAL,
                    raw_json TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS trade_activities (
                    activity_id TEXT PRIMARY KEY,
                    activity_type TEXT,
                    symbol TEXT,
                    side TEXT,
                    quantity REAL,
                    price REAL,
                    transaction_time TEXT,
                    order_id TEXT,
                    raw_json TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS portfolio_history (
                    timestamp TEXT PRIMARY KEY,
                    equity REAL,
                    profit_loss REAL,
                    profit_loss_pct REAL
                );

                CREATE TABLE IF NOT EXISTS sync_runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    started_at TEXT NOT NULL,
                    finished_at TEXT,
                    status TEXT NOT NULL,
                    error_message TEXT
                );

                CREATE TABLE IF NOT EXISTS watchlist_symbols (
                    symbol TEXT PRIMARY KEY,
                    position INTEGER NOT NULL,
                    updated_at TEXT NOT NULL
                );
                """
            )

    def record_sync_start(self, started_at: datetime) -> int:
        """Record a sync run start and return its id."""

        self.initialize()
        with self._connect() as connection:
            cursor = connection.execute(
                "INSERT INTO sync_runs (started_at, status) VALUES (?, ?)",
                (_to_iso(started_at), "running"),
            )
            return int(cursor.lastrowid)

    def record_sync_finish(self, sync_run_id: int, status: str, error_message: str | None = None) -> None:
        """Record sync run completion."""

        with self._connect() as connection:
            connection.execute(
                "UPDATE sync_runs SET finished_at = ?, status = ?, error_message = ? WHERE id = ?",
                (_to_iso(_utc_now()), status, error_message, sync_run_id),
            )

    def save_account_snapshot(self, portfolio: PortfolioView, timestamp: datetime) -> None:
        """Persist one account snapshot."""

        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO account_snapshots
                (timestamp, cash, equity, buying_power, portfolio_value, daily_pl)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    _to_iso(timestamp),
                    portfolio.cash,
                    portfolio.equity,
                    portfolio.buying_power,
                    portfolio.portfolio_value,
                    portfolio.daily_pl,
                ),
            )

    def save_positions(self, positions: list[PositionView], timestamp: datetime) -> None:
        """Persist open positions for one snapshot timestamp."""

        with self._connect() as connection:
            connection.executemany(
                """
                INSERT INTO positions
                (snapshot_timestamp, symbol, quantity, market_value, average_entry_price, current_price,
                 unrealized_pl, unrealized_plpc)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        _to_iso(timestamp),
                        position.symbol,
                        position.quantity,
                        position.market_value,
                        position.average_entry_price,
                        position.current_price,
                        position.unrealized_pl,
                        position.unrealized_plpc,
                    )
                    for position in positions
                ],
            )

    def save_orders(self, orders: list[dict[str, Any]]) -> None:
        """Persist normalized order dictionaries."""

        with self._connect() as connection:
            connection.executemany(
                """
                INSERT INTO orders
                (order_id, client_order_id, symbol, side, quantity, status, submitted_at, filled_at,
                 filled_quantity, filled_average_price, raw_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(order_id) DO UPDATE SET
                    client_order_id = excluded.client_order_id,
                    symbol = excluded.symbol,
                    side = excluded.side,
                    quantity = excluded.quantity,
                    status = excluded.status,
                    submitted_at = excluded.submitted_at,
                    filled_at = excluded.filled_at,
                    filled_quantity = excluded.filled_quantity,
                    filled_average_price = excluded.filled_average_price,
                    raw_json = excluded.raw_json
                """,
                [
                    (
                        order["order_id"],
                        order.get("client_order_id"),
                        order["symbol"],
                        order["side"],
                        order["quantity"],
                        order["status"],
                        order.get("submitted_at"),
                        order.get("filled_at"),
                        order.get("filled_quantity", 0.0),
                        order.get("filled_average_price"),
                        json.dumps(order.get("raw", {}), default=str),
                    )
                    for order in orders
                ],
            )

    def save_trade_activities(self, activities: list[dict[str, Any]]) -> None:
        """Persist trade activity dictionaries."""

        with self._connect() as connection:
            connection.executemany(
                """
                INSERT INTO trade_activities
                (activity_id, activity_type, symbol, side, quantity, price, transaction_time, order_id, raw_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(activity_id) DO UPDATE SET
                    activity_type = excluded.activity_type,
                    symbol = excluded.symbol,
                    side = excluded.side,
                    quantity = excluded.quantity,
                    price = excluded.price,
                    transaction_time = excluded.transaction_time,
                    order_id = excluded.order_id,
                    raw_json = excluded.raw_json
                """,
                [
                    (
                        activity["activity_id"],
                        activity.get("activity_type"),
                        activity.get("symbol"),
                        activity.get("side"),
                        activity.get("quantity"),
                        activity.get("price"),
                        activity.get("transaction_time"),
                        activity.get("order_id"),
                        json.dumps(activity.get("raw", {}), default=str),
                    )
                    for activity in activities
                ],
            )

    def save_portfolio_history(self, rows: list[dict[str, Any]]) -> None:
        """Persist portfolio history rows."""

        with self._connect() as connection:
            connection.executemany(
                """
                INSERT INTO portfolio_history (timestamp, equity, profit_loss, profit_loss_pct)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(timestamp) DO UPDATE SET
                    equity = excluded.equity,
                    profit_loss = excluded.profit_loss,
                    profit_loss_pct = excluded.profit_loss_pct
                """,
                [
                    (
                        row["timestamp"],
                        row.get("equity"),
                        row.get("profit_loss"),
                        row.get("profit_loss_pct"),
                    )
                    for row in rows
                ],
            )

    def load_completed_trade_history(self, page: int = 1, page_size: int = 25) -> CompletedTradeHistoryPage:
        """Return one page of completed long trades derived from fill activities."""

        if page <= 0:
            raise ValueError("page must be greater than zero.")
        if page_size <= 0:
            raise ValueError("page_size must be greater than zero.")

        trades = self.list_completed_trades()
        total = len(trades)
        pages = max(1, math.ceil(total / page_size))
        normalized_page = min(page, pages)
        offset = (normalized_page - 1) * page_size
        return CompletedTradeHistoryPage(
            items=trades[offset : offset + page_size],
            page=normalized_page,
            page_size=page_size,
            total=total,
            pages=pages,
        )

    def list_completed_trades(self) -> list[TradeView]:
        """Return completed long trades newest first from saved fill activities."""

        self.initialize()
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM trade_activities
                WHERE LOWER(COALESCE(activity_type, '')) = 'fill'
                ORDER BY COALESCE(transaction_time, ''), activity_id
                """
            ).fetchall()
        return _completed_trades_from_fill_rows(rows)

    def list_raw_orders(self) -> list[dict[str, Any]]:
        """Return saved Alpaca order rows newest first for audit display."""

        self.initialize()
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT order_id, symbol, side, quantity, status, submitted_at, filled_at,
                       filled_quantity, filled_average_price
                FROM orders
                ORDER BY COALESCE(filled_at, submitted_at, '') DESC, order_id DESC
                """
            ).fetchall()
        return [dict(row) for row in rows]

    def list_raw_fill_activities(self) -> list[dict[str, Any]]:
        """Return saved Alpaca fill activities newest first for audit display."""

        self.initialize()
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT activity_id, symbol, side, quantity, price, transaction_time, order_id
                FROM trade_activities
                WHERE LOWER(COALESCE(activity_type, '')) = 'fill'
                ORDER BY COALESCE(transaction_time, '') DESC, activity_id DESC
                """
            ).fetchall()
        return [dict(row) for row in rows]

    def load_dashboard_data(self) -> StoredDashboardData:
        """Load latest stored data for dashboard fallback or startup hydration."""

        self.initialize()
        with self._connect() as connection:
            account = connection.execute(
                "SELECT * FROM account_snapshots ORDER BY timestamp DESC, id DESC LIMIT 1"
            ).fetchone()
            portfolio = _portfolio_from_row(account)

            latest_position_timestamp = connection.execute(
                "SELECT snapshot_timestamp FROM positions ORDER BY snapshot_timestamp DESC LIMIT 1"
            ).fetchone()
            positions: list[PositionView] = []
            if latest_position_timestamp:
                positions = [
                    _position_from_row(row)
                    for row in connection.execute(
                        "SELECT * FROM positions WHERE snapshot_timestamp = ? ORDER BY symbol",
                        (latest_position_timestamp["snapshot_timestamp"],),
                    ).fetchall()
                ]

            trades = [
                _trade_from_order_row(row)
                for row in connection.execute(
                    """
                    SELECT * FROM orders
                    ORDER BY COALESCE(filled_at, submitted_at, '') DESC
                    LIMIT 100
                    """
                ).fetchall()
            ]
            metrics = _backtest_metrics_from_history(
                connection.execute("SELECT * FROM portfolio_history ORDER BY timestamp").fetchall()
            )
            return StoredDashboardData(
                portfolio=portfolio,
                positions=positions,
                trades=trades,
                backtest_metrics=metrics,
            )

    def get_watchlist(self, default_symbols: list[str] | tuple[str, ...]) -> list[str]:
        """Return the saved trading watchlist, seeding it from defaults when empty."""

        self.initialize()
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT symbol FROM watchlist_symbols ORDER BY position, symbol"
            ).fetchall()
        if rows:
            return [str(row["symbol"]) for row in rows]
        return self.save_watchlist(list(default_symbols))

    def save_watchlist(self, symbols: list[str] | tuple[str, ...]) -> list[str]:
        """Validate, normalize, deduplicate, and persist the trading watchlist."""

        normalized = _normalize_watchlist(symbols)
        updated_at = _to_iso(_utc_now())
        self.initialize()
        with self._connect() as connection:
            connection.execute("DELETE FROM watchlist_symbols")
            connection.executemany(
                """
                INSERT INTO watchlist_symbols (symbol, position, updated_at)
                VALUES (?, ?, ?)
                """,
                [(symbol, index, updated_at) for index, symbol in enumerate(normalized)],
            )
        return normalized

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.sqlite_path)
        connection.row_factory = sqlite3.Row
        return connection


def _portfolio_from_row(row: sqlite3.Row | None) -> PortfolioView:
    if row is None:
        return PortfolioView()
    daily_pl_pct = row["daily_pl"] / row["portfolio_value"] if row["portfolio_value"] else 0.0
    return PortfolioView(
        equity=float(row["equity"]),
        cash=float(row["cash"]),
        buying_power=float(row["buying_power"]),
        portfolio_value=float(row["portfolio_value"]),
        daily_pl=float(row["daily_pl"]),
        daily_pl_pct=float(daily_pl_pct),
    )


def _position_from_row(row: sqlite3.Row) -> PositionView:
    return PositionView(
        symbol=row["symbol"],
        quantity=float(row["quantity"]),
        market_value=float(row["market_value"]),
        average_entry_price=float(row["average_entry_price"]),
        current_price=float(row["current_price"]),
        unrealized_pl=float(row["unrealized_pl"]),
        unrealized_plpc=float(row["unrealized_plpc"]),
    )


def _trade_from_order_row(row: sqlite3.Row) -> TradeView:
    return TradeView(
        symbol=row["symbol"],
        side=str(row["side"]).upper(),
        quantity=float(row["quantity"]),
        entry_price=_optional_float(row["filled_average_price"]),
        exit_price=None,
        opened_at=_parse_datetime(row["submitted_at"]),
        closed_at=_parse_datetime(row["filled_at"]),
        realized_pl=0.0,
    )


def _completed_trades_from_fill_rows(rows: list[sqlite3.Row]) -> list[TradeView]:
    entry_lots: dict[str, list[_EntryLot]] = {}
    completed: list[TradeView] = []
    for group in _fill_groups(rows):
        lots = entry_lots.setdefault(group.symbol, [])
        if group.side == "buy":
            lots.append(_EntryLot(quantity=group.quantity, price=group.price, opened_at=group.transaction_time))
            continue
        if group.side != "sell":
            continue

        remaining = group.quantity
        matched_quantity = 0.0
        entry_notional = 0.0
        realized_pl = 0.0
        opened_at: datetime | None = None
        while lots and remaining > 1e-9:
            lot = lots[0]
            matched = min(remaining, lot.quantity)
            matched_quantity += matched
            entry_notional += matched * lot.price
            realized_pl += matched * (group.price - lot.price)
            opened_at = _earliest_datetime(opened_at, lot.opened_at)
            remaining -= matched
            lot.quantity -= matched
            if lot.quantity <= 1e-9:
                lots.pop(0)

        if matched_quantity > 1e-9:
            completed.append(
                TradeView(
                    symbol=group.symbol,
                    side="BUY",
                    quantity=matched_quantity,
                    entry_price=entry_notional / matched_quantity,
                    exit_price=group.price,
                    opened_at=opened_at,
                    closed_at=group.transaction_time,
                    realized_pl=realized_pl,
                )
            )

    return sorted(
        completed,
        key=lambda trade: trade.closed_at or datetime.min.replace(tzinfo=timezone.utc),
        reverse=True,
    )


def _fill_groups(rows: list[sqlite3.Row]) -> list[_FillGroup]:
    groups: dict[str, _FillGroup] = {}
    for row in rows:
        symbol = str(row["symbol"] or "").strip().upper()
        side = str(row["side"] or "").strip().lower()
        quantity = _optional_float(row["quantity"]) or 0.0
        price = _optional_float(row["price"]) or 0.0
        if not symbol or side not in {"buy", "sell"} or quantity <= 0 or price <= 0:
            continue

        key = str(row["order_id"] or row["activity_id"])
        timestamp = _parse_datetime(row["transaction_time"])
        group = groups.get(key)
        if group is None or group.symbol != symbol or group.side != side:
            groups[key] = _FillGroup(
                symbol=symbol,
                side=side,
                quantity=quantity,
                notional=quantity * price,
                transaction_time=timestamp,
            )
            continue

        group.quantity += quantity
        group.notional += quantity * price
        if group.side == "sell":
            group.transaction_time = _latest_datetime(group.transaction_time, timestamp)
        else:
            group.transaction_time = _earliest_datetime(group.transaction_time, timestamp)

    return sorted(
        groups.values(),
        key=lambda group: group.transaction_time or datetime.min.replace(tzinfo=timezone.utc),
    )


def _earliest_datetime(left: datetime | None, right: datetime | None) -> datetime | None:
    if left is None:
        return right
    if right is None:
        return left
    return min(left, right)


def _latest_datetime(left: datetime | None, right: datetime | None) -> datetime | None:
    if left is None:
        return right
    if right is None:
        return left
    return max(left, right)


def _backtest_metrics_from_history(rows: list[sqlite3.Row]) -> BacktestMetricsView:
    if len(rows) < 2:
        return BacktestMetricsView()
    first_equity = _optional_float(rows[0]["equity"]) or 0.0
    last_equity = _optional_float(rows[-1]["equity"]) or first_equity
    peak = max((_optional_float(row["equity"]) or 0.0) for row in rows) or first_equity
    drawdown = (peak - last_equity) / peak if peak else 0.0
    expectancy = last_equity - first_equity
    return BacktestMetricsView(
        win_rate=0.0,
        profit_factor=0.0,
        drawdown=max(0.0, drawdown),
        sharpe_ratio=0.0,
        expectancy=expectancy,
        total_trades=0,
    )


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _to_iso(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def _optional_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    return float(value)


def _normalize_watchlist(symbols: list[str] | tuple[str, ...]) -> list[str]:
    try:
        validated = validate_symbols(symbols)
    except DataValidationError:
        raise
    deduped: list[str] = []
    seen: set[str] = set()
    for symbol in validated:
        if symbol not in seen:
            seen.add(symbol)
            deduped.append(symbol)
    if not deduped:
        raise DataValidationError("At least one watchlist symbol is required.")
    return deduped
