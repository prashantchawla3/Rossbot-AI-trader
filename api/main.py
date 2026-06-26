"""FastAPI application — Phase 5: dashboard API + WebSocket + alerting + health.

Phase 5 deliverables (ROSSBOT_PROJECT_PLAN.md Phase 5):
- Read-only dashboard REST endpoints (GET /api/state, watchlist, positions, signals, …)
- WebSocket live push (WS /ws/live)
- Kill-switch + pause controls (POST /controls/*)
- Health monitors background task (feed liveness, clock drift)
- Alerting (Slack/email) wired to StateService events

U11 (CLAUDE.md §4): no mid-session parameter editing is exposed anywhere in this API.
spec Phase 5.  FastAPI 0.138.1 (web-verified pypi.org 2026-06).
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from api.routers import controls, dashboard, health
from api.services.alert_service import AlertService, AlertSeverity
from api.services.health_service import HealthService, _HEALTH_POLL_S
from api.services.state_service import StateService
from api.services.ws_manager import ConnectionManager
from core.logging import configure_logging

log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    configure_logging()

    ws_manager = ConnectionManager()
    state_svc = StateService()
    alert_svc = AlertService()
    health_svc = HealthService()

    state_svc.set_broadcast_hook(ws_manager.broadcast_json)

    app.state.ws_manager = ws_manager
    app.state.svc = state_svc
    app.state.alert_svc = alert_svc
    app.state.health_svc = health_svc

    log.info("rossbot_dashboard_startup")

    health_task = asyncio.create_task(
        _health_loop(ws_manager, state_svc, health_svc, alert_svc)
    )

    yield

    health_task.cancel()
    try:
        await health_task
    except asyncio.CancelledError:
        pass
    log.info("rossbot_dashboard_shutdown")


async def _health_loop(
    ws_manager: ConnectionManager,
    state_svc: StateService,
    health_svc: HealthService,
    alert_svc: AlertService,
) -> None:
    """Refresh health snapshot every HEALTH_POLL_SECONDS and push over WebSocket.

    Fires a CRITICAL alert on first detected feed gap (spec Phase 5).
    """
    was_healthy = True
    while True:
        await asyncio.sleep(_HEALTH_POLL_S)
        try:
            await health_svc.refresh_clock_drift()
            health_svc.set_ws_clients(ws_manager.connection_count)
            snap = health_svc.build_health_snapshot()
            await state_svc.update_health(snap)

            if not snap.all_healthy and was_healthy:
                stale = [f.name for f in snap.feeds if not f.alive]
                await alert_svc.fire(
                    AlertSeverity.CRITICAL,
                    "feed_gap",
                    f"Data feed gap detected: {stale}",
                    f"clock_drift_ms={snap.clock_drift_ms:.0f}",
                )
                was_healthy = False
            elif snap.all_healthy:
                was_healthy = True
        except Exception:  # noqa: BLE001
            log.exception("health_loop_error")


app = FastAPI(
    title="RossBot Dashboard API",
    version="5.0.0",
    description="Read-mostly monitoring dashboard for RossBot (Phase 5).",
    lifespan=lifespan,
)

_DASHBOARD_ORIGIN = os.environ.get("DASHBOARD_ORIGIN", "http://localhost:3000")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[_DASHBOARD_ORIGIN],
    allow_credentials=True,
    allow_methods=["GET", "POST"],  # no PATCH/PUT/DELETE/OPTIONS mutation — U11
    allow_headers=["*"],
)

app.include_router(dashboard.router)
app.include_router(controls.router)
app.include_router(health.router)


@app.get("/health")
async def health_liveness() -> dict[str, Any]:
    """Simple liveness probe."""
    return {"status": "ok", "service": "rossbot", "phase": 5}


@app.websocket("/ws/live")
async def ws_live(websocket: WebSocket) -> None:
    """WebSocket endpoint — streams state updates to dashboard clients.

    On connect: sends the full current state snapshot immediately.
    Ongoing: every state mutation triggers a push via ConnectionManager.broadcast_json.
    Ping/pong: client sends "ping", server responds {"type":"pong","payload":{}}.
    spec Phase 5.
    """
    ws_manager: ConnectionManager = websocket.app.state.ws_manager
    state_svc: StateService = websocket.app.state.svc

    await ws_manager.connect(websocket)

    try:
        initial = state_svc.get_state()
        await websocket.send_text(
            json.dumps(
                {"type": "state_update", "payload": initial.model_dump(mode="json")},
                default=str,
            )
        )
    except Exception:  # noqa: BLE001
        ws_manager.disconnect(websocket)
        return

    try:
        while True:
            text = await websocket.receive_text()
            if text.strip() == "ping":
                await websocket.send_text('{"type":"pong","payload":{}}')
    except WebSocketDisconnect:
        pass
    except Exception:  # noqa: BLE001
        log.debug("ws_live_closed_unexpectedly")
    finally:
        ws_manager.disconnect(websocket)
