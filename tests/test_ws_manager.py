"""Unit tests for the WebSocket connection manager.  spec Phase 5."""

from __future__ import annotations

import asyncio
import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from api.services.ws_manager import ConnectionManager


def run(coro: Any) -> Any:
    return asyncio.get_event_loop().run_until_complete(coro)


class TestConnectionManager:
    def test_initial_connection_count_zero(self) -> None:
        mgr = ConnectionManager()
        assert mgr.connection_count == 0

    def test_connect_increments_count(self) -> None:
        mgr = ConnectionManager()
        ws = AsyncMock()
        run(mgr.connect(ws))
        assert mgr.connection_count == 1
        ws.accept.assert_awaited_once()

    def test_disconnect_decrements_count(self) -> None:
        mgr = ConnectionManager()
        ws = AsyncMock()
        run(mgr.connect(ws))
        mgr.disconnect(ws)
        assert mgr.connection_count == 0

    def test_disconnect_nonexistent_no_error(self) -> None:
        mgr = ConnectionManager()
        ws = MagicMock()
        mgr.disconnect(ws)  # should not raise

    def test_broadcast_sends_to_all_clients(self) -> None:
        mgr = ConnectionManager()
        ws1 = AsyncMock()
        ws2 = AsyncMock()
        run(mgr.connect(ws1))
        run(mgr.connect(ws2))

        payload = {"type": "state_update", "payload": {"x": 1}}
        run(mgr.broadcast_json(payload))

        ws1.send_text.assert_awaited_once()
        ws2.send_text.assert_awaited_once()
        sent_text = ws1.send_text.call_args[0][0]
        assert json.loads(sent_text)["type"] == "state_update"

    def test_broadcast_removes_dead_connections(self) -> None:
        mgr = ConnectionManager()
        ws_ok = AsyncMock()
        ws_dead = AsyncMock()
        ws_dead.send_text.side_effect = RuntimeError("disconnected")

        run(mgr.connect(ws_ok))
        run(mgr.connect(ws_dead))
        assert mgr.connection_count == 2

        run(mgr.broadcast_json({"type": "ping", "payload": {}}))

        assert mgr.connection_count == 1  # dead one removed

    def test_broadcast_noop_when_no_clients(self) -> None:
        mgr = ConnectionManager()
        # Should not raise
        run(mgr.broadcast_json({"type": "pong", "payload": {}}))
