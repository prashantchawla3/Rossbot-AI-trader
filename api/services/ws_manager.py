"""WebSocket connection manager — broadcast live state to all dashboard clients.

spec Phase 5: FastAPI WebSocket push for real-time dashboard updates.
Thread-safety: asyncio single-threaded; all mutations must run in the event loop.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from fastapi import WebSocket

log = logging.getLogger(__name__)


class ConnectionManager:
    """Manages all active WebSocket connections to the dashboard.

    Usage::

        manager = ConnectionManager()

        @app.websocket("/ws/live")
        async def ws_endpoint(websocket: WebSocket):
            await manager.connect(websocket)
            try:
                while True:
                    msg = await websocket.receive_text()
                    if msg == "ping":
                        await websocket.send_text(json.dumps({"type": "pong", "payload": {}}))
            except Exception:
                pass
            finally:
                manager.disconnect(websocket)
    """

    def __init__(self) -> None:
        self._connections: list[WebSocket] = []
        self._lock = asyncio.Lock()

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        async with self._lock:
            self._connections.append(ws)
        log.info("ws_client_connected total=%d", len(self._connections))

    def disconnect(self, ws: WebSocket) -> None:
        try:
            self._connections.remove(ws)
        except ValueError:
            pass
        log.info("ws_client_disconnected total=%d", len(self._connections))

    async def broadcast_json(self, data: dict[str, Any]) -> None:
        """Send a JSON message to all connected clients.

        Dead connections are silently removed.
        """
        if not self._connections:
            return
        text = json.dumps(data, default=str)
        dead: list[WebSocket] = []
        async with self._lock:
            for ws in list(self._connections):
                try:
                    await ws.send_text(text)
                except Exception:  # noqa: BLE001
                    dead.append(ws)
            for ws in dead:
                try:
                    self._connections.remove(ws)
                except ValueError:
                    pass
        if dead:
            log.info("ws_dead_connections_removed count=%d", len(dead))

    @property
    def connection_count(self) -> int:
        return len(self._connections)
