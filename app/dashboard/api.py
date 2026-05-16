"""Read-only dashboard API routes."""

from __future__ import annotations

from fastapi import APIRouter, Request

from app.dashboard.state_manager import DashboardStateManager
from app.dashboard.schemas import to_jsonable

router = APIRouter(prefix="/api", tags=["dashboard"])


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
