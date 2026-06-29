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

# Load .env BEFORE importing routers/auth (api.auth reads DASHBOARD_API_KEY at import).
# Skipped under pytest so tests control the environment (they set DASHBOARD_API_KEY themselves).
#
# IMPORTANT: we resolve the .env path RELATIVE TO THIS FILE (repo root = api/..), not the
# current working directory. Bare load_dotenv() searches up from cwd, so launching uvicorn
# from anywhere but the repo root silently loaded NO keys → the dashboard reported every
# provider "not configured" even though .env had the keys. Anchoring the path fixes that.
# NOTE: editing .env requires a full API RESTART — `uvicorn --reload` only watches .py files.
import sys as _sys

if "pytest" not in _sys.modules:
    try:
        from pathlib import Path as _Path

        from dotenv import load_dotenv

        _env_path = _Path(__file__).resolve().parent.parent / ".env"
        # override=True so a freshly-edited .env wins over any stale value already in the
        # process env (e.g. an empty placeholder exported by a wrapper script).
        load_dotenv(dotenv_path=_env_path if _env_path.exists() else None, override=True)
    except Exception:  # noqa: BLE001 — dotenv is optional
        pass

from api.routers import controls, dashboard, health, operator
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

    # Phase-6 demo: start the Alpaca paper trading loop in-process (shares ws + state).
    from core.demo.wiring import start_demo, stop_demo

    await start_demo(app)

    yield

    await stop_demo(app)
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
    # GET/POST for the read + control surface; PATCH is allowed ONLY for the audited
    # session-config override layer (4 keys, every change logged) — the client-approved
    # U11 dashboard-override exception. See ROSSBOT_STRATEGY_SPEC.md Appendix A.
    allow_methods=["GET", "POST", "PATCH"],
    allow_headers=["*"],
)

app.include_router(dashboard.router)
app.include_router(operator.router)
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
        demo_state = getattr(websocket.app.state, "demo_state", None)
        if demo_state is not None:
            payload = demo_state.to_state()
        else:
            payload = state_svc.get_state().model_dump(mode="json")
        await websocket.send_text(
            json.dumps({"type": "state_update", "payload": payload}, default=str)
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
