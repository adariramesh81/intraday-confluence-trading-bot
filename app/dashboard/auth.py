"""Authentication helpers for the read-only dashboard."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
from typing import Any

from fastapi import Request, WebSocket

from app.config import DashboardConfig

SESSION_COOKIE_NAME = "dashboard_session"
AUTH_REQUIRED_MESSAGE = "Authentication required."


def public_http_path(path: str) -> bool:
    """Return whether an HTTP path is intentionally public."""

    return path == "/login" or path == "/healthz" or path.startswith("/static/")


def protected_http_path(path: str) -> bool:
    """Return whether an HTTP path should require a dashboard session."""

    return path == "/" or path.startswith("/api/")


def auth_is_configured(config: DashboardConfig) -> bool:
    """Return whether dashboard auth has the required secret material."""

    return bool(config.auth_enabled and config.username and config.password and config.session_secret)


def credentials_are_valid(username: str, password: str, config: DashboardConfig) -> bool:
    """Validate submitted credentials using constant-time comparison."""

    if not auth_is_configured(config):
        return False
    return secrets.compare_digest(username, config.username) and secrets.compare_digest(password, config.password)


def request_is_authorized(request: Request, config: DashboardConfig) -> bool:
    """Return whether an HTTP request has a valid dashboard session."""

    if not config.auth_enabled:
        return True
    return session_cookie_is_valid(request.cookies.get(SESSION_COOKIE_NAME), config)


def websocket_is_authorized(websocket: WebSocket, config: DashboardConfig) -> bool:
    """Return whether a websocket handshake has a valid dashboard session."""

    if not config.auth_enabled:
        return True
    return session_cookie_is_valid(websocket.cookies.get(SESSION_COOKIE_NAME), config)


def create_session_cookie_value(config: DashboardConfig) -> str:
    """Create a signed browser-session cookie value for the configured dashboard user."""

    if not auth_is_configured(config):
        return ""
    payload = _base64_urlsafe_json({"username": config.username})
    signature = _signature(payload, config.session_secret)
    return f"{payload}.{signature}"


def session_cookie_is_valid(cookie_value: str | None, config: DashboardConfig) -> bool:
    """Validate the signed dashboard session cookie."""

    if not auth_is_configured(config) or not cookie_value:
        return False
    payload, separator, signature = cookie_value.partition(".")
    if not separator or not payload or not signature:
        return False
    expected_signature = _signature(payload, config.session_secret)
    if not secrets.compare_digest(signature, expected_signature):
        return False
    data = _decode_base64_urlsafe_json(payload)
    return secrets.compare_digest(str(data.get("username", "")), config.username)


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
