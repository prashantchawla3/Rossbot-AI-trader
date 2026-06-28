"""Read-only dashboard state endpoints.  spec Phase 5 + Phase 6 demo.

U11: no parameter editing mid-session — these endpoints are GET-only (plus the
demo test-signal injector, which writes no strategy parameters).

When the in-process demo engine is running, these endpoints serve its live state
(``app.state.demo_state``) in the exact shape the Next.js dashboard expects
(``dashboard/lib/types.ts``). Otherwise they fall back to the Phase-5 StateService.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request

from api.services.state_service import StateService

router = APIRouter(prefix="/api", tags=["dashboard"])


def _svc(request: Request) -> StateService:
    return request.app.state.svc  # type: ignore[no-any-return]


def _demo(request: Request) -> Any | None:
    return getattr(request.app.state, "demo_state", None)


def _engine(request: Request) -> Any | None:
    return getattr(request.app.state, "demo_engine", None)


@router.get("/state")
async def get_state(request: Request) -> dict[str, Any]:
    """Full dashboard state snapshot (risk, positions, watchlist, signals, health)."""
    demo = _demo(request)
    if demo is not None:
        return demo.to_state()
    return _svc(request).get_state().model_dump(mode="json")


@router.get("/watchlist")
async def get_watchlist(request: Request) -> list[dict[str, Any]]:
    """Current Tier-A / Tier-B watchlist from the scanner."""
    demo = _demo(request)
    if demo is not None:
        state = demo.to_state()
        return state["watchlist_tier_a"] + state["watchlist_tier_b"]
    return [w.model_dump(mode="json") for w in _svc(request).get_state().watchlist]


@router.get("/positions")
async def get_positions(request: Request) -> dict[str, object]:
    """Active open positions and unrealized P&L."""
    demo = _demo(request)
    if demo is not None:
        state = demo.to_state()
        return {"positions": state["positions"], "risk": state["risk"]}
    state = _svc(request).get_state()
    return {
        "positions": [p.model_dump(mode="json") for p in state.risk.open_positions],
        "realized_pnl": str(state.risk.realized_pnl),
        "peak_pnl": str(state.risk.peak_pnl),
    }


@router.get("/signals")
async def get_signals(request: Request, limit: int = 50) -> dict[str, object]:
    """Recent entry/exit/veto signals (newest first)."""
    demo = _demo(request)
    if demo is not None:
        sigs = demo.signals(limit)
        return {"signals": sigs, "total": len(sigs)}
    signals = _svc(request).get_state().recent_signals[:limit]
    return {"signals": [s.model_dump(mode="json") for s in signals]}


@router.get("/risk-events")
async def get_risk_events(request: Request, limit: int = 50) -> dict[str, object]:
    """Recent risk events (vetoes, halts, give-back warnings) — newest first."""
    demo = _demo(request)
    if demo is not None:
        events = demo.risk_events(limit)
        return {"risk_events": events, "total": len(events)}
    events = _svc(request).get_state().recent_risk_events[:limit]
    return {"risk_events": [e.model_dump(mode="json") for e in events]}


@router.get("/journal")
async def get_journal(request: Request) -> object:
    """Post-session trade journal and summary report."""
    return _svc(request).get_journal().model_dump(mode="json")


@router.post("/demo/test-signal")
async def inject_test_signal(request: Request, symbol: str = "TEST") -> dict[str, Any]:
    """DEMO: inject a manual test signal so the dashboard signal feed can be verified."""
    engine = _engine(request)
    if engine is None:
        return {"ok": False, "message": "demo engine not running"}
    sig = await engine.inject_test_signal(symbol)
    return {"ok": True, "signal": sig}
