"""Read-only dashboard API routes."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException, Request

from app.data.account_store import AccountDataStore
from app.data.market_data import AlpacaMarketDataClient
from app.utils.validators import DataValidationError
from app.dashboard.state_manager import DashboardStateManager
from app.dashboard.schemas import to_jsonable
from app.utils.logger import get_logger

router = APIRouter(prefix="/api", tags=["dashboard"])
logger = get_logger(__name__)


def get_state_manager(request: Request) -> DashboardStateManager:
    """Return the dashboard state manager stored on the app."""

    return request.app.state.dashboard_state


@router.get("/health")
def get_health(request: Request) -> dict:
    """Return system health state."""

    return to_jsonable(get_state_manager(request).snapshot().health)


@router.get("/portfolio")
def get_portfolio(request: Request) -> dict:
    """Return portfolio summary state."""

    return to_jsonable(get_state_manager(request).snapshot().portfolio)


@router.get("/positions")
def get_positions(request: Request) -> list[dict]:
    """Return open positions state."""

    return to_jsonable(get_state_manager(request).snapshot().positions)


@router.get("/trades")
def get_trades(request: Request) -> list[dict]:
    """Return trade history state."""

    return to_jsonable(get_state_manager(request).snapshot().trades)


@router.get("/signals")
def get_signals(request: Request) -> list[dict]:
    """Return live signal monitoring state."""

    return to_jsonable(get_state_manager(request).snapshot().signals)


@router.get("/backtests")
def get_backtests(request: Request) -> dict:
    """Return backtest analytics state."""

    return to_jsonable(get_state_manager(request).snapshot().backtest_metrics)


@router.get("/snapshot")
def get_snapshot(request: Request) -> dict:
    """Return the complete dashboard snapshot."""

    return get_state_manager(request).snapshot_dict()


@router.get("/watchlist")
def get_watchlist(request: Request) -> dict:
    """Return the persisted Bot 2 trading watchlist."""

    config = request.app.state.config
    store = AccountDataStore(config.storage.sqlite_path)
    symbols = store.get_watchlist(config.trading.watchlist)
    market_data_client = getattr(request.app.state, "watchlist_market_data_client", None)
    return {"symbols": symbols, "items": _watchlist_items(config, symbols, market_data_client)}


@router.put("/watchlist")
async def update_watchlist(request: Request) -> dict:
    """Replace the Bot 2 trading watchlist when an admin is authenticated."""

    config = request.app.state.config
    if not config.dashboard.auth_enabled:
        raise HTTPException(
            status_code=403,
            detail="Enable dashboard auth and sign in as an admin to edit the trading watchlist.",
        )
    session = getattr(request.state, "dashboard_session", None)
    if session is None or not session.is_admin or session.temporary_password:
        raise HTTPException(status_code=403, detail="Admin access required.")

    payload = await request.json()
    symbols = payload.get("symbols") if isinstance(payload, dict) else None
    if not isinstance(symbols, list):
        raise HTTPException(status_code=422, detail="symbols must be a list.")

    store = AccountDataStore(config.storage.sqlite_path)
    try:
        return {"symbols": store.save_watchlist(symbols)}
    except DataValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def _watchlist_items(config: Any, symbols: list[str], market_data_client: Any | None = None) -> list[dict[str, Any]]:
    prices = _fetch_watchlist_prices(config, symbols, market_data_client)
    return [{"symbol": symbol, "current_price": prices.get(symbol)} for symbol in symbols]


def _fetch_watchlist_prices(config: Any, symbols: list[str], market_data_client: Any | None = None) -> dict[str, float]:
    if not symbols or not config.alpaca.api_key or not config.alpaca.secret_key:
        return {}

    try:
        timezone = ZoneInfo(config.market_data.timezone)
        end = datetime.now(timezone)
        start = end - timedelta(days=7)
        client = market_data_client or AlpacaMarketDataClient(
            config=replace(
                config,
                market_data=replace(config.market_data, retry_attempts=1, retry_backoff_seconds=0),
            ),
            logger=logger,
        )
        data = client.fetch_ohlcv(
            symbols=symbols,
            start=start,
            end=end,
            timeframe=config.market_data.default_timeframe,
        )
    except Exception:
        logger.exception("Failed to fetch watchlist market prices.", extra={"symbols": symbols})
        return {}

    prices: dict[str, float] = {}
    for symbol, rows in data.sort_values("timestamp").groupby("symbol"):
        close = rows.iloc[-1]["close"]
        try:
            prices[str(symbol).upper()] = float(close)
        except (TypeError, ValueError):
            continue
    return prices
