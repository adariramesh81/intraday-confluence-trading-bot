"""Authentication helpers for the read-only dashboard."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
from dataclasses import dataclass
from typing import Any

from fastapi import Request, WebSocket

from app.config import DashboardConfig
from app.dashboard.user_store import DashboardUser, DashboardUserStore

SESSION_COOKIE_NAME = "dashboard_session"
AUTH_REQUIRED_MESSAGE = "Authentication required."
PASSWORD_CHANGE_REQUIRED_MESSAGE = "Password change required."


@dataclass(frozen=True)
class DashboardSession:
    """Authenticated dashboard session payload."""

    email: str
    is_admin: bool
    temporary_password: bool


def public_http_path(path: str) -> bool:
    """Return whether an HTTP path is intentionally public."""

    return path == "/login" or path == "/healthz" or path.startswith("/static/")


def protected_http_path(path: str) -> bool:
    """Return whether an HTTP path should require a dashboard session."""

    return (
        path == "/"
        or path == "/change-password"
        or path == "/trade-history"
        or path.startswith("/api/")
        or path.startswith("/admin/")
    )


def auth_is_configured(config: DashboardConfig) -> bool:
    """Return whether dashboard auth has the required secret material."""

    return bool(config.auth_enabled and config.session_secret)


def get_request_session(
    request: Request,
    config: DashboardConfig,
    user_store: DashboardUserStore,
) -> DashboardSession | None:
    """Return a valid dashboard session for an HTTP request."""

    if not config.auth_enabled:
        return DashboardSession(email="", is_admin=True, temporary_password=False)
    return session_from_cookie(request.cookies.get(SESSION_COOKIE_NAME), config, user_store)


def get_websocket_session(
    websocket: WebSocket,
    config: DashboardConfig,
    user_store: DashboardUserStore,
) -> DashboardSession | None:
    """Return a valid dashboard session for a websocket handshake."""

    if not config.auth_enabled:
        return DashboardSession(email="", is_admin=True, temporary_password=False)
    return session_from_cookie(websocket.cookies.get(SESSION_COOKIE_NAME), config, user_store)


def create_session_cookie_value(user: DashboardUser, config: DashboardConfig) -> str:
    """Create a signed browser-session cookie value for a dashboard user."""

    if not auth_is_configured(config):
        return ""
    payload = _base64_urlsafe_json(
        {
            "email": user.email,
            "is_admin": user.is_admin,
            "temporary_password": user.temporary_password,
        }
    )
    signature = _signature(payload, config.session_secret)
    return f"{payload}.{signature}"


def session_from_cookie(
    cookie_value: str | None,
    config: DashboardConfig,
    user_store: DashboardUserStore,
) -> DashboardSession | None:
    """Validate and load a dashboard session from a signed cookie."""

    if not auth_is_configured(config) or not cookie_value:
        return None
    payload, separator, signature = cookie_value.partition(".")
    if not separator or not payload or not signature:
        return None
    expected_signature = _signature(payload, config.session_secret)
    if not secrets.compare_digest(signature, expected_signature):
        return None
    data = _decode_base64_urlsafe_json(payload)
    user = user_store.get_user(str(data.get("email", "")))
    if user is None or not user.is_active:
        return None
    return DashboardSession(
        email=user.email,
        is_admin=user.is_admin,
        temporary_password=user.temporary_password,
    )


def _base64_urlsafe_json(data: dict[str, Any]) -> str:
    raw = json.dumps(data, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii")


def _decode_base64_urlsafe_json(value: str) -> dict[str, Any]:
    try:
        decoded = base64.urlsafe_b64decode(value.encode("ascii"))
        data = json.loads(decoded.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return {}
    if not isinstance(data, dict):
        return {}
    return data


def _signature(payload: str, secret: str) -> str:
    return hmac.new(secret.encode("utf-8"), payload.encode("ascii"), hashlib.sha256).hexdigest()
