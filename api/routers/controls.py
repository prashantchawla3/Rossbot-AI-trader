"""Trading controls — kill-switch and pause.  spec Phase 5 / U11.

HARD RULE (U11 / CLAUDE.md §4): this module exposes ONLY:
  POST /controls/kill-switch  — immediate halt + flatten all positions
  POST /controls/pause        — pause new trade entry (current positions held)
  POST /controls/resume       — resume if not risk-halted

NO parameter editing.  No config mutation.  No strategy overrides.
Any attempt to add param-editing endpoints here is a U11 violation.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Request, status

from api.auth import require_api_key
from api.schemas.dashboard import ControlResult
from api.services.alert_service import AlertService, AlertSeverity
from api.services.state_service import StateService

log = logging.getLogger(__name__)

router = APIRouter(
    prefix="/controls",
    tags=["controls"],
    dependencies=[Depends(require_api_key)],
)


def _svc(request: Request) -> StateService:
    return request.app.state.svc  # type: ignore[no-any-return]


def _alerts(request: Request) -> AlertService:
    return request.app.state.alert_svc  # type: ignore[no-any-return]


@router.post("/kill-switch", response_model=ControlResult)
async def kill_switch(request: Request) -> ControlResult:
    """EMERGENCY HALT: halt the risk manager + cancel all broker positions.

    Mirrors Ross Cameron's discipline of walking away when risk limits are hit (U11).
    This is the only parameter-modifying action the dashboard exposes mid-session.
    spec §11 U4/U5/U11; CLAUDE.md §4.
    """
    svc = _svc(request)
    alerts = _alerts(request)

    log.warning("controls.kill_switch_triggered")
    await svc.halt_session("manual_kill_switch")
    await alerts.fire(
        AlertSeverity.CRITICAL,
        "kill_switch",
        "Manual kill-switch activated — all positions being flattened.",
    )
    return ControlResult(ok=True, message="Session halted and positions cancelled.")


@router.post("/pause", response_model=ControlResult)
async def pause(request: Request) -> ControlResult:
    """Pause new trade entry.  Existing positions continue to be monitored.

    Does NOT modify any strategy parameters (U11).
    """
    svc = _svc(request)
    if svc.halted:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Session is already halted — use kill-switch reset to restart.",
        )
    svc.pause()
    log.info("controls.session_paused")
    return ControlResult(ok=True, message="Trading paused — no new entries will be taken.")


@router.post("/resume", response_model=ControlResult)
async def resume(request: Request) -> ControlResult:
    """Resume trading after a manual pause.  Blocked if risk manager is halted."""
    svc = _svc(request)
    try:
        svc.resume()
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
    log.info("controls.session_resumed")
    return ControlResult(ok=True, message="Trading resumed.")
