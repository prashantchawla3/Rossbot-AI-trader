"""Read-only dashboard state endpoints.  spec Phase 5.

U11: no parameter editing mid-session — these endpoints are GET-only.
The dashboard reads state; it never writes strategy parameters.
"""

from __future__ import annotations

from fastapi import APIRouter, Request

from api.schemas.dashboard import DashboardStateOut, WatchlistEntry
from api.services.state_service import StateService

router = APIRouter(prefix="/api", tags=["dashboard"])


def _svc(request: Request) -> StateService:
    return request.app.state.svc  # type: ignore[no-any-return]


@router.get("/state", response_model=DashboardStateOut)
async def get_state(request: Request) -> DashboardStateOut:
    """Full dashboard state snapshot (risk, positions, watchlist, signals, health)."""
    return _svc(request).get_state()


@router.get("/watchlist", response_model=list[WatchlistEntry])
async def get_watchlist(request: Request) -> list[WatchlistEntry]:
    """Current Tier-A / Tier-B watchlist from the scanner."""
    return _svc(request).get_state().watchlist


@router.get("/positions")
async def get_positions(request: Request) -> dict[str, object]:
    """Active open positions and unrealized P&L."""
    state = _svc(request).get_state()
    return {
        "positions": [p.model_dump(mode="json") for p in state.risk.open_positions],
        "realized_pnl": str(state.risk.realized_pnl),
        "peak_pnl": str(state.risk.peak_pnl),
    }


@router.get("/signals")
async def get_signals(request: Request, limit: int = 50) -> dict[str, object]:
    """Recent entry/exit/veto signals (newest first)."""
    signals = _svc(request).get_state().recent_signals[:limit]
    return {"signals": [s.model_dump(mode="json") for s in signals]}


@router.get("/risk-events")
async def get_risk_events(request: Request, limit: int = 50) -> dict[str, object]:
    """Recent risk events (vetoes, halts, give-back warnings) — newest first."""
    events = _svc(request).get_state().recent_risk_events[:limit]
    return {"risk_events": [e.model_dump(mode="json") for e in events]}


@router.get("/journal")
async def get_journal(request: Request) -> object:
    """Post-session trade journal and summary report."""
    return _svc(request).get_journal().model_dump(mode="json")
