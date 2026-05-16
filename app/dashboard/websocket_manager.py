"""Dashboard websocket connection management."""

from __future__ import annotations

from fastapi import WebSocket


class WebSocketManager:
    """Track dashboard websocket clients and broadcast snapshot updates."""

    def __init__(self) -> None:
        self._connections: set[WebSocket] = set()

    async def connect(self, websocket: WebSocket) -> None:
        """Accept and register a websocket connection."""

        await websocket.accept()
        self._connections.add(websocket)

    def disconnect(self, websocket: WebSocket) -> None:
        """Remove a websocket connection."""

        self._connections.discard(websocket)

    async def broadcast_json(self, payload: dict) -> None:
        """Broadcast JSON payload to all connected clients."""

        disconnected: list[WebSocket] = []
        for websocket in self._connections:
            try:
                await websocket.send_json(payload)
            except RuntimeError:
                disconnected.append(websocket)
        for websocket in disconnected:
            self.disconnect(websocket)

    def connection_count(self) -> int:
        """Return number of connected websocket clients."""

        return len(self._connections)
