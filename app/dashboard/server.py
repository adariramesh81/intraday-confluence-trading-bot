"""FastAPI dashboard server factory."""

from __future__ import annotations

import asyncio
from contextlib import suppress
from pathlib import Path
from urllib.parse import parse_qs

import uvicorn
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.config import AppConfig, load_config
from app.dashboard.api import router as api_router
from app.dashboard.auth import (
    AUTH_REQUIRED_MESSAGE,
    SESSION_COOKIE_NAME,
    create_session_cookie_value,
    credentials_are_valid,
    protected_http_path,
    public_http_path,
    request_is_authorized,
    websocket_is_authorized,
)
from app.dashboard.schemas import HealthStatus
from app.dashboard.state_manager import DashboardStateManager
from app.dashboard.websocket_manager import WebSocketManager
from app.data.alpaca_account_sync import AlpacaAccountSyncService
from app.data.account_store import AccountDataStore

DASHBOARD_DIR = Path(__file__).resolve().parent
TEMPLATES_DIR = DASHBOARD_DIR / "templates"
STATIC_DIR = DASHBOARD_DIR / "static"


def create_app(
    config: AppConfig | None = None,
    state_manager: DashboardStateManager | None = None,
    websocket_manager: WebSocketManager | None = None,
) -> FastAPI:
    """Create the read-only monitoring dashboard app."""

    app_config = config or load_config()
    dashboard_state = state_manager or DashboardStateManager()
    dashboard_state.update_health(
        HealthStatus(
            environment=app_config.env,
            paper_trading=app_config.alpaca.paper,
            live_trading_enabled=app_config.trading.live_trading,
            messages=["Dashboard initialized."],
        )
    )

    app = FastAPI(title=app_config.dashboard.title)
    app.state.config = app_config
    app.state.dashboard_state = dashboard_state
    app.state.websocket_manager = websocket_manager or WebSocketManager()
    app.state.alpaca_sync_task = None

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    templates = Jinja2Templates(directory=TEMPLATES_DIR)
    app.include_router(api_router)

    @app.middleware("http")
    async def require_dashboard_auth(request: Request, call_next):
        """Protect dashboard and account data routes with a signed session cookie."""

        path = request.url.path
        if app_config.dashboard.auth_enabled and not public_http_path(path):
            authorized = request_is_authorized(request, app_config.dashboard)
            if path == "/" and not authorized:
                return RedirectResponse("/login", status_code=303)
            if protected_http_path(path) and not authorized:
                return JSONResponse({"detail": AUTH_REQUIRED_MESSAGE}, status_code=401)
        return await call_next(request)

    @app.on_event("startup")
    async def start_alpaca_sync() -> None:
        """Hydrate dashboard from SQLite and start background Alpaca sync."""

        store = AccountDataStore(app_config.storage.sqlite_path)
        service = AlpacaAccountSyncService(
            config=app_config,
            store=store,
            state_manager=dashboard_state,
        )
        store.initialize()
        service.load_cached_state_into_dashboard()
        if app_config.alpaca_sync.enabled:
            app.state.alpaca_sync_task = asyncio.create_task(
                _alpaca_sync_loop(
                    service=service,
                    state_manager=dashboard_state,
                    websocket_manager=app.state.websocket_manager,
                    refresh_seconds=app_config.alpaca_sync.refresh_seconds,
                )
            )

    @app.on_event("shutdown")
    async def stop_alpaca_sync() -> None:
        """Stop the background Alpaca sync task."""

        task = app.state.alpaca_sync_task
        if task is not None:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task

    @app.get("/", response_class=HTMLResponse)
    async def index(request: Request) -> HTMLResponse:
        """Render the read-only dashboard page."""

        return templates.TemplateResponse(
            request,
            "index.html",
            {
                "title": app_config.dashboard.title,
                "refresh_seconds": app_config.dashboard.refresh_seconds,
                "auth_enabled": app_config.dashboard.auth_enabled,
            },
        )

    @app.get("/login", response_class=HTMLResponse)
    async def login_form(request: Request):
        """Render the dashboard login page."""

        if not app_config.dashboard.auth_enabled or request_is_authorized(request, app_config.dashboard):
            return RedirectResponse("/", status_code=303)
        return templates.TemplateResponse(
            request,
            "login.html",
            {"title": app_config.dashboard.title, "error": None},
        )

    @app.post("/login", response_class=HTMLResponse)
    async def login(request: Request):
        """Validate login credentials and create a browser-session cookie."""

        form = parse_qs((await request.body()).decode("utf-8"))
        username = form.get("username", [""])[0]
        password = form.get("password", [""])[0]
        if credentials_are_valid(username, password, app_config.dashboard):
            response = RedirectResponse("/", status_code=303)
            response.set_cookie(
                SESSION_COOKIE_NAME,
                create_session_cookie_value(app_config.dashboard),
                httponly=True,
                secure=app_config.env == "production",
                samesite="lax",
                path="/",
            )
            return response
        return templates.TemplateResponse(
            request,
            "login.html",
            {"title": app_config.dashboard.title, "error": "Invalid username or password."},
            status_code=401,
        )

    @app.get("/logout")
    async def logout() -> RedirectResponse:
        """Clear the dashboard session cookie and return to login."""

        response = RedirectResponse("/login", status_code=303)
        response.delete_cookie(SESSION_COOKIE_NAME, path="/")
        return response

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        """Return non-sensitive service health for Railway checks."""

        return {"status": "ok"}

    @app.websocket("/ws/dashboard")
    async def dashboard_websocket(websocket: WebSocket) -> None:
        """Stream dashboard snapshots over a read-only websocket."""

        if not websocket_is_authorized(websocket, app_config.dashboard):
            await websocket.close(code=1008)
            return

        manager: WebSocketManager = app.state.websocket_manager
        await manager.connect(websocket)
        try:
            await websocket.send_json(app.state.dashboard_state.snapshot_dict())
            while True:
                await websocket.receive_text()
        except WebSocketDisconnect:
            manager.disconnect(websocket)

    return app


async def _alpaca_sync_loop(
    service: AlpacaAccountSyncService,
    state_manager: DashboardStateManager,
    websocket_manager: WebSocketManager,
    refresh_seconds: int,
) -> None:
    while True:
        try:
            await asyncio.to_thread(service.sync_once)
        except Exception:
            pass
        await websocket_manager.broadcast_json(state_manager.snapshot_dict())
        await asyncio.sleep(refresh_seconds)


def run() -> None:
    """Run the dashboard with uvicorn."""

    config = load_config()
    uvicorn.run(
        "app.dashboard.server:create_app",
        host=config.dashboard.host,
        port=config.dashboard.port,
        factory=True,
        reload=False,
    )


if __name__ == "__main__":
    run()
