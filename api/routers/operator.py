"""Operator-console endpoints — interactive dashboard controls (spec Phase 5 + dashboard).

These power the rebuilt operator console: live chart data, manual scanner trigger,
position controls (close / scale-out / move-stop), manual trades, the audited
session-config override layer, day controls, and the session journal.

GUARDRAILS (CLAUDE.md §4):
- All MUTATING endpoints require the X-API-Key header (``require_api_key``).
- Every manual BUY/trade is routed through the DemoEngine risk gate (U4/U5/U7) —
  the gate can VETO or RESIZE. Execution never bypasses it.
- Config overrides are limited to FOUR keys (AUTO_TRADE, MARKET_STATE,
  MAX_DAILY_LOSS, SCAN_INTERVAL); each writes a risk_event audit row. This is the
  spec Appendix-A U11 dashboard-override exception (client-approved).

When the demo engine is not running, mutating endpoints return 503.
"""

from __future__ import annotations

import io
from decimal import Decimal, InvalidOperation
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from api.auth import require_api_key
from core.indicators import macd, macd_positive

router = APIRouter(prefix="/api", tags=["operator"])

# Mutating endpoints carry the API-key dependency per-route (``_AUTH``); read endpoints
# (bars, analyze, config GET, journal) are open like the rest of the dashboard read
# surface. A single router avoids the double-prefix trap of nesting two /api routers.
_AUTH = [Depends(require_api_key)]


def _engine(request: Request) -> Any:
    eng = getattr(request.app.state, "demo_engine", None)
    if eng is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Demo trading engine is not running (set ROSSBOT_RUN_ENGINE=true).",
        )
    return eng


def _svc(request: Request) -> Any:
    return request.app.state.svc


def _analyzer(request: Request) -> Any:
    """Lazily construct and cache the StrategyAnalyzer on app.state."""
    an = getattr(request.app.state, "analyzer", None)
    if an is None:
        from adapters.analyzer import StrategyAnalyzer

        an = StrategyAnalyzer()
        request.app.state.analyzer = an
    return an


def _dec(value: Any, field: str) -> Decimal:
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=f"{field} must be a number") from exc


# ── request bodies ──────────────────────────────────────────────────────────────

class StopBody(BaseModel):
    stop_price: float


class ManualTradeBody(BaseModel):
    symbol: str
    entry: float
    stop: float
    shares: int


class ManualOrderBody(BaseModel):
    symbol: str
    side: str  # BUY | SELL
    qty: int
    limit_price: float


class ConfigBody(BaseModel):
    key: str
    value: Any


# ── chart / scanner ─────────────────────────────────────────────────────────────

@router.get("/bars/{symbol}")
async def get_bars(request: Request, symbol: str, limit: int = 50) -> dict[str, Any]:
    """Last ``limit`` 1-min bars for ``symbol`` (TradingView fallback feed)."""
    eng = _engine(request)
    bars = await eng.get_bars_payload(symbol, min(max(limit, 1), 500))
    return {"symbol": symbol.upper().strip(), "bars": bars}


@router.post("/scanner/trigger", dependencies=_AUTH)
async def scanner_trigger(request: Request) -> dict[str, Any]:
    """Run the scanner immediately and return the Tier-A / Tier-B counts."""
    return await _engine(request).trigger_scan()


# ── AI analysis (selectable provider/model) ─────────────────────────────────────

@router.get("/models")
async def list_models() -> dict[str, Any]:
    """Provider/model catalog for the AI-analysis picker (which keys are configured)."""
    from adapters.llm_providers import catalog

    return catalog()


@router.get("/account")
async def get_account(request: Request) -> dict[str, Any]:
    """Live Alpaca paper-account snapshot (read-only) for the Command Center.

    Returns connection status + equity / buying-power / cash / day-trade count so the
    operator can confirm the bot is wired to Alpaca before placing a manual test trade.
    Never raises: an unconfigured or unreachable broker returns ``connected: false``.
    """
    eng = getattr(request.app.state, "demo_engine", None)
    if eng is None:
        return {"connected": False, "error": "engine_not_running"}
    info = await eng.verify_broker()
    cfg = getattr(eng, "cfg", None)
    if cfg is not None:
        info.setdefault("paper", bool(getattr(cfg, "paper", True)))
        info["auto_trade"] = bool(eng.effective_auto_trade)
        info["replay_mode"] = bool(getattr(cfg, "demo_replay_mode", False))
    return info


@router.get("/analyze/{symbol}")
async def analyze_symbol(
    request: Request,
    symbol: str,
    provider: str | None = None,
    model: str | None = None,
) -> dict[str, Any]:
    """Full Ross-strategy analysis of a symbol (advisory only).

    ``provider`` / ``model`` select the AI model (Anthropic / OpenAI / NVIDIA NIM /
    Google); both are optional and fall back to the configured default.
    """
    sym = symbol.upper().strip()
    md = await _gather_market_data(request, sym)
    verdict = _analyzer(request).analyze(sym, md, provider=provider, model=model)
    verdict["market_data"] = md
    return verdict


async def _gather_market_data(request: Request, sym: str) -> dict[str, Any]:
    """Best-effort live snapshot + bars + quote + MACD for the analyzer."""
    eng = getattr(request.app.state, "demo_engine", None)
    md: dict[str, Any] = {"symbol": sym}
    if eng is None or getattr(eng, "data", None) is None:
        return md
    data = eng.data
    try:
        from core.demo.universe import float_for

        md["float_shares"] = float_for(sym)
    except Exception:  # noqa: BLE001
        md["float_shares"] = None
    try:
        snap = await data.get_snapshot([sym])
        s = snap.get(sym, {})
        md["price"] = str(s.get("price")) if s.get("price") is not None else None
        md["change_pct"] = str(s.get("change_pct")) if s.get("change_pct") is not None else None
        md["volume"] = s.get("volume")
        md["rvol"] = str(await data.get_rvol(sym, current_volume=s.get("volume")) or "")
    except Exception:  # noqa: BLE001
        pass
    try:
        bars = await eng.get_bars_payload(sym, 50)
        md["bars"] = bars
        closes = [Decimal(b["close"]) for b in bars]
        if len(closes) >= 6:
            last = macd(closes)[-1]
            md["macd_positive"] = macd_positive(last)
            md["macd_hist"] = (
                str(last.histogram) if last is not None and last.histogram is not None else None
            )
    except Exception:  # noqa: BLE001
        pass
    try:
        q = await data.get_quote(sym)
        md["bid"], md["ask"] = str(q.bid), str(q.ask)
        md["spread"] = str(q.ask - q.bid)
    except Exception:  # noqa: BLE001
        pass
    return md


# ── position controls ───────────────────────────────────────────────────────────

@router.post("/positions/{symbol}/close", dependencies=_AUTH)
async def close_position(request: Request, symbol: str) -> dict[str, Any]:
    """Close a position fully at the bid (limit-style exit)."""
    return await _engine(request).close_position(symbol)


@router.post("/positions/{symbol}/scale-out", dependencies=_AUTH)
async def scale_out(request: Request, symbol: str) -> dict[str, Any]:
    """Sell half the position at the bid; move the mental stop to breakeven."""
    return await _engine(request).scale_out_position(symbol)


@router.post("/positions/{symbol}/stop", dependencies=_AUTH)
async def move_stop(request: Request, symbol: str, body: StopBody) -> dict[str, Any]:
    """Update the internal (mental) stop price — U13, no resting broker stop."""
    return await _engine(request).move_stop(symbol, _dec(body.stop_price, "stop_price"))


# ── manual trading (through the risk gate) ──────────────────────────────────────

@router.post("/trade/manual", dependencies=_AUTH)
async def trade_manual(request: Request, body: ManualTradeBody) -> dict[str, Any]:
    """Execute an AI-suggested trade. The risk gate may VETO or RESIZE it."""
    return await _engine(request).manual_trade(
        body.symbol, _dec(body.entry, "entry"), _dec(body.stop, "stop"), int(body.shares)
    )


@router.post("/trade/manual-order", dependencies=_AUTH)
async def trade_manual_order(request: Request, body: ManualOrderBody) -> dict[str, Any]:
    """Quick manual paper order. BUY routes through the U4/U5/U7 hard gate."""
    if body.side.upper().strip() not in {"BUY", "SELL"}:
        raise HTTPException(status_code=422, detail="side must be BUY or SELL")
    return await _engine(request).manual_order(
        body.symbol, body.side, int(body.qty), _dec(body.limit_price, "limit_price")
    )


# ── session-config overrides (U11 dashboard exception) ──────────────────────────

@router.get("/config")
async def get_config(request: Request) -> dict[str, Any]:
    """Current effective values of the four overridable session-config keys."""
    return _engine(request).effective_config()


@router.patch("/config", dependencies=_AUTH)
async def patch_config(request: Request, body: ConfigBody) -> dict[str, Any]:
    """Apply an audited session-config override (writes a risk_event audit row)."""
    result = await _engine(request).set_override(body.key, body.value)
    if not result.get("ok"):
        raise HTTPException(status_code=422, detail=result.get("message", "invalid override"))
    return result


# ── day controls ────────────────────────────────────────────────────────────────

@router.post("/control/flatten", dependencies=_AUTH)
async def control_flatten(request: Request) -> dict[str, Any]:
    """Cancel all orders and close all positions at market (emergency)."""
    result = await _engine(request).flatten_all()
    return {"success": result.get("ok", False), **result}


@router.post("/control/pause", dependencies=_AUTH)
async def control_pause(request: Request) -> dict[str, Any]:
    """Pause new entries; open positions stay monitored."""
    svc = _svc(request)
    if svc.halted:
        raise HTTPException(status_code=409, detail="Session is halted — cannot pause.")
    svc.pause()
    return {"ok": True, "status": "paused"}


@router.post("/control/resume", dependencies=_AUTH)
async def control_resume(request: Request) -> dict[str, Any]:
    """Re-enable new entries (blocked while risk-halted)."""
    svc = _svc(request)
    try:
        svc.resume()
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"ok": True, "status": "active"}


@router.post("/control/halt-day", dependencies=_AUTH)
async def control_halt_day(request: Request) -> dict[str, Any]:
    """End trading for the rest of the session (same effect as 3-strikes)."""
    return _engine(request).halt_day("manual_halt_day")


# ── journal ─────────────────────────────────────────────────────────────────────

@router.get("/journal/today")
async def journal_today(request: Request) -> dict[str, Any]:
    """All completed trades this session (newest first) with P&L / R-multiple."""
    trades = _engine(request).journal_today()
    return {"trades": trades, "count": len(trades)}


@router.get("/journal/session-summary")
async def journal_summary(request: Request) -> dict[str, Any]:
    """Win rate, averages, profit factor, best/worst for the session."""
    return _engine(request).session_summary()


@router.get("/journal/export")
async def journal_export(request: Request) -> StreamingResponse:
    """Download today's completed trades as CSV."""
    trades = _engine(request).journal_today()
    buf = io.StringIO()
    cols = ["symbol", "side", "entry_price", "exit_price", "shares", "pnl",
            "r_multiple", "exit_reason", "entry_ts", "exit_ts"]
    buf.write(",".join(cols) + "\n")
    for t in trades:
        buf.write(",".join(str(t.get(c, "")) for c in cols) + "\n")
    buf.seek(0)
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=rossbot_journal.csv"},
    )
