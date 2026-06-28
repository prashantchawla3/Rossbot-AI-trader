"""Glue that starts/stops the DemoEngine inside the FastAPI lifespan.

Kept out of ``api/main.py`` so the API module stays small. The engine runs in the
same event loop as the API so it shares the WebSocket ``ConnectionManager`` and
respects the dashboard pause/kill-switch controls (it reads ``StateService`` flags).

Gated by ``ROSSBOT_RUN_ENGINE`` (default on). Tests set it to ``false``.
"""

from __future__ import annotations

import asyncio
import logging
import os

from core.demo.config import DemoConfig
from core.demo.engine import DemoEngine
from core.demo.state import DemoDashboardState

log = logging.getLogger(__name__)


def _enabled() -> bool:
    return os.environ.get("ROSSBOT_RUN_ENGINE", "true").strip().lower() in {
        "1", "true", "yes", "on",
    }


async def start_demo(app) -> None:  # noqa: ANN001 — FastAPI app
    """Construct the demo engine and launch its loop as a background task."""
    if not _enabled():
        log.info("demo_engine.disabled (ROSSBOT_RUN_ENGINE=false)")
        return
    try:
        cfg = DemoConfig.from_env()
        ws_manager = app.state.ws_manager
        svc = app.state.svc

        demo_state = DemoDashboardState(broadcast=ws_manager.broadcast_json)
        engine = DemoEngine(
            cfg,
            demo_state,
            connection_count=lambda: ws_manager.connection_count,
        )
        engine.set_control_hooks(lambda: svc.paused, lambda: svc.halted)
        engine.connect()

        # Kill-switch (POST /controls/kill-switch → svc.halt_session) halts the demo
        # engine and flattens all Alpaca positions. Always registered so the halt flag
        # flips even before credentials are supplied.
        async def _flatten() -> None:
            engine._halt("manual_kill_switch")  # noqa: SLF001 — intentional engine control
            if engine.broker is not None:
                await engine.broker.cancel_all_flatten()
            engine.positions.clear()

        svc.register_broker_cancel(_flatten)

        if not cfg.has_credentials:
            log.warning(
                "demo_engine.no_credentials — set ALPACA_API_KEY / ALPACA_SECRET_KEY in .env. "
                "Get free paper keys at https://alpaca.markets → Paper Trading → API Keys. "
                "Running in replay/idle mode until keys are provided."
            )

        app.state.demo_state = demo_state
        app.state.demo_engine = engine
        app.state.demo_task = asyncio.create_task(engine.run())
        log.info("demo_engine.launched auto_trade=%s replay=%s", cfg.auto_trade, cfg.demo_replay_mode)
    except Exception:  # noqa: BLE001 — never block API startup
        log.exception("demo_engine.start_failed")


async def stop_demo(app) -> None:  # noqa: ANN001
    task = getattr(app.state, "demo_task", None)
    engine = getattr(app.state, "demo_engine", None)
    if engine is not None:
        engine.stop()
    if task is not None:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        except Exception:  # noqa: BLE001
            pass
