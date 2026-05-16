"""Authentication helpers for the read-only dashboard."""

from __future__ import annotations

import base64
import binascii
import secrets

from fastapi import Request, WebSocket
from fastapi.responses import Response

from app.config import DashboardConfig

AUTH_REALM = "Intraday Confluence Dashboard"


def protected_http_path(path: str) -> bool:
    """Return whether an HTTP path should require dashboard authentication."""

    return path == "/" or path.startswith("/api/")


def unauthorized_response() -> Response:
    """Return a Basic Auth challenge response."""

    return Response(
        status_code=401,
        headers={"WWW-Authenticate": f'Basic realm="{AUTH_REALM}"'},
        content="Authentication required.",
    )


def request_is_authorized(request: Request, config: DashboardConfig) -> bool:
    """Return whether an HTTP request has valid dashboard credentials."""

    return authorization_header_is_valid(request.headers.get("authorization"), config)


def websocket_is_authorized(websocket: WebSocket, config: DashboardConfig) -> bool:
    """Return whether a websocket handshake has valid dashboard credentials."""

    return authorization_header_is_valid(websocket.headers.get("authorization"), config)


def authorization_header_is_valid(header: str | None, config: DashboardConfig) -> bool:
    """Validate a Basic Auth header using constant-time credential comparison."""

    if not config.auth_enabled:
        return True
    if not config.username or not config.password or not header:
        return False
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "basic" or not token:
        return False
    try:
        decoded = base64.b64decode(token, validate=True).decode("utf-8")
    except (binascii.Error, UnicodeDecodeError):
        return False
    username, separator, password = decoded.partition(":")
    if not separator:
        return False
    return secrets.compare_digest(username, config.username) and secrets.compare_digest(password, config.password)
