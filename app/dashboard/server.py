"""FastAPI dashboard server factory."""

from __future__ import annotations

import asyncio
import sqlite3
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
    PASSWORD_CHANGE_REQUIRED_MESSAGE,
    SESSION_COOKIE_NAME,
    create_session_cookie_value,
    get_request_session,
    get_websocket_session,
    protected_http_path,
    public_http_path,
)
from app.dashboard.schemas import HealthStatus
from app.dashboard.state_manager import DashboardStateManager
from app.dashboard.user_store import DashboardUserStore, generate_temporary_password
from app.dashboard.websocket_manager import WebSocketManager
from app.data.alpaca_account_sync import AlpacaAccountSyncService
from app.data.account_store import AccountDataStore
from app.utils.logger import get_logger

DASHBOARD_DIR = Path(__file__).resolve().parent
TEMPLATES_DIR = DASHBOARD_DIR / "templates"
STATIC_DIR = DASHBOARD_DIR / "static"
logger = get_logger(__name__)


def create_app(
    config: AppConfig | None = None,
    state_manager: DashboardStateManager | None = None,
    websocket_manager: WebSocketManager | None = None,
    user_store: DashboardUserStore | None = None,
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
    app.state.dashboard_user_store = user_store or DashboardUserStore(app_config.storage.sqlite_path)
    app.state.alpaca_sync_task = None

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    templates = Jinja2Templates(directory=TEMPLATES_DIR)
    app.include_router(api_router)

    if app_config.dashboard.auth_enabled:
        app.state.dashboard_user_store.initialize()
        if app_config.dashboard.admin_email:
            created_admin = app.state.dashboard_user_store.ensure_admin_user(app_config.dashboard.admin_email)
            if created_admin:
                logger.warning(
                    "Dashboard admin user was bootstrapped with a generated temporary password. "
                    "Run the dashboard user_admin CLI to reset it and print a usable password."
                )

    @app.middleware("http")
    async def require_dashboard_auth(request: Request, call_next):
        """Protect dashboard and account data routes with a signed session cookie."""

        path = request.url.path
        if app_config.dashboard.auth_enabled and not public_http_path(path):
            session = get_request_session(request, app_config.dashboard, app.state.dashboard_user_store)
            request.state.dashboard_session = session
            if session is None:
                if path == "/" or path == "/change-password" or path.startswith("/admin/"):
                    return RedirectResponse("/login", status_code=303)
                if protected_http_path(path):
                    return JSONResponse({"detail": AUTH_REQUIRED_MESSAGE}, status_code=401)
            elif session.temporary_password and path not in {"/change-password", "/logout"}:
                if path.startswith("/api/"):
                    return JSONResponse({"detail": PASSWORD_CHANGE_REQUIRED_MESSAGE}, status_code=403)
                return RedirectResponse("/change-password", status_code=303)
            elif path.startswith("/admin/") and not session.is_admin:
                return JSONResponse({"detail": "Admin access required."}, status_code=403)
            if path == "/" and session is None:
                return RedirectResponse("/login", status_code=303)
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
                "user_email": _session_email(request),
                "user_is_admin": _session_is_admin(request),
            },
        )

    @app.get("/login", response_class=HTMLResponse)
    async def login_form(request: Request):
        """Render the dashboard login page."""

        session = get_request_session(request, app_config.dashboard, app.state.dashboard_user_store)
        if not app_config.dashboard.auth_enabled:
            return RedirectResponse("/", status_code=303)
        if session is not None:
            return RedirectResponse("/change-password" if session.temporary_password else "/", status_code=303)
        return templates.TemplateResponse(
            request,
            "login.html",
            {"title": app_config.dashboard.title, "error": None},
        )

    @app.post("/login", response_class=HTMLResponse)
    async def login(request: Request):
        """Validate login credentials and create a browser-session cookie."""

        form = parse_qs((await request.body()).decode("utf-8"))
        email = form.get("email", [""])[0]
        password = form.get("password", [""])[0]
        user = app.state.dashboard_user_store.authenticate(email, password)
        if user is not None:
            response = RedirectResponse("/", status_code=303)
            if user.temporary_password:
                response = RedirectResponse("/change-password", status_code=303)
            response.set_cookie(
                SESSION_COOKIE_NAME,
                create_session_cookie_value(user, app_config.dashboard),
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

    @app.get("/change-password", response_class=HTMLResponse)
    async def change_password_form(request: Request):
        """Render first-login password change form."""

        return templates.TemplateResponse(
            request,
            "change_password.html",
            {"title": app_config.dashboard.title, "error": None},
        )

    @app.post("/change-password", response_class=HTMLResponse)
    async def change_password(request: Request):
        """Set a permanent password for the logged-in user."""

        session = get_request_session(request, app_config.dashboard, app.state.dashboard_user_store)
        if session is None:
            return RedirectResponse("/login", status_code=303)
        form = parse_qs((await request.body()).decode("utf-8"))
        password = form.get("password", [""])[0]
        confirm_password = form.get("confirm_password", [""])[0]
        if len(password) < 10:
            return templates.TemplateResponse(
                request,
                "change_password.html",
                {"title": app_config.dashboard.title, "error": "Use at least 10 characters."},
                status_code=400,
            )
        if password != confirm_password:
            return templates.TemplateResponse(
                request,
                "change_password.html",
                {"title": app_config.dashboard.title, "error": "Passwords do not match."},
                status_code=400,
            )
        user = app.state.dashboard_user_store.change_password(session.email, password)
        response = RedirectResponse("/", status_code=303)
        response.set_cookie(
            SESSION_COOKIE_NAME,
            create_session_cookie_value(user, app_config.dashboard),
            httponly=True,
            secure=app_config.env == "production",
            samesite="lax",
            path="/",
        )
        return response

    @app.get("/logout")
    async def logout() -> RedirectResponse:
        """Clear the dashboard session cookie and return to login."""

        response = RedirectResponse("/login", status_code=303)
        response.delete_cookie(SESSION_COOKIE_NAME, path="/")
        return response

    @app.get("/admin/users", response_class=HTMLResponse)
    async def admin_users(request: Request):
        """Render admin user management."""

        return _render_admin_users(request, templates, app_config, app.state.dashboard_user_store)

    @app.post("/admin/users", response_class=HTMLResponse)
    async def admin_users_action(request: Request):
        """Create, reset, activate, or deactivate dashboard users."""

        form = parse_qs((await request.body()).decode("utf-8"))
        action = form.get("action", [""])[0]
        email = form.get("email", [""])[0]
        generated_password = None
        message = None
        error = None
        try:
            if action == "create":
                generated_password = generate_temporary_password()
                app.state.dashboard_user_store.create_user(email, generated_password, temporary_password=True)
                message = f"Created {email.strip().lower()}."
            elif action == "reset":
                generated_password = app.state.dashboard_user_store.reset_temporary_password(email)
                message = f"Reset password for {email.strip().lower()}."
            elif action == "deactivate":
                app.state.dashboard_user_store.set_active(email, False)
                message = f"Deactivated {email.strip().lower()}."
            elif action == "activate":
                app.state.dashboard_user_store.set_active(email, True)
                message = f"Activated {email.strip().lower()}."
            else:
                error = "Choose a valid action."
        except (ValueError, sqlite3.IntegrityError) as exc:
            error = str(exc)
        return _render_admin_users(
            request,
            templates,
            app_config,
            app.state.dashboard_user_store,
            message=message,
            error=error,
            generated_password=generated_password,
        )

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        """Return non-sensitive service health for Railway checks."""

        return {"status": "ok"}

    @app.websocket("/ws/dashboard")
    async def dashboard_websocket(websocket: WebSocket) -> None:
        """Stream dashboard snapshots over a read-only websocket."""

        session = get_websocket_session(websocket, app_config.dashboard, app.state.dashboard_user_store)
        if session is None or session.temporary_password:
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


def _render_admin_users(
    request: Request,
    templates: Jinja2Templates,
    config: AppConfig,
    user_store: DashboardUserStore,
    message: str | None = None,
    error: str | None = None,
    generated_password: str | None = None,
) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "admin_users.html",
        {
            "title": config.dashboard.title,
            "auth_enabled": config.dashboard.auth_enabled,
            "refresh_seconds": config.dashboard.refresh_seconds,
            "user_email": _session_email(request),
            "user_is_admin": _session_is_admin(request),
            "users": user_store.list_users(),
            "message": message,
            "error": error,
            "generated_password": generated_password,
        },
    )


def _session_email(request: Request) -> str:
    session = getattr(request.state, "dashboard_session", None)
    return getattr(session, "email", "")


def _session_is_admin(request: Request) -> bool:
    session = getattr(request.state, "dashboard_session", None)
    return bool(getattr(session, "is_admin", False))


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
