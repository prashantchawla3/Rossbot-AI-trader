"""In-process dashboard state for the demo, in the EXACT shape the Next.js
dashboard expects (``dashboard/lib/types.ts``).

The production ``api.services.state_service.StateService`` is left untouched; this
holder is the demo's single source of truth and is read by the dashboard router
(``/api/state``) and pushed over the existing WebSocket (``/ws/live``) using the
``ConnectionManager.broadcast_json`` hook.

WS message envelope (matches ``useDashboardState`` reducer):
  {"type": "state_update", "payload": <DashboardState>}
  {"type": "signal",       "payload": <SignalEvent>}
  {"type": "risk_event",   "payload": <RiskEvent>}
"""

from __future__ import annotations

import asyncio
from collections import deque
from decimal import Decimal
from typing import Any, Awaitable, Callable

from core.timeutils import now_utc

BroadcastHook = Callable[[dict[str, Any]], Awaitable[None]]

_MAX_SIGNALS = 200
_MAX_RISK_EVENTS = 500


def _iso(dt: Any = None) -> str:
    return (dt or now_utc()).isoformat()


def _s(value: Decimal | int | float | str) -> str:
    """Money/number → string (frontend expects all monetary fields as strings)."""
    if isinstance(value, Decimal):
        return f"{value:.2f}"
    return str(value)


class DemoDashboardState:
    """Frontend-shaped live state, broadcast over WebSocket on every mutation."""

    def __init__(self, broadcast: BroadcastHook | None = None) -> None:
        self._lock = asyncio.Lock()
        self._broadcast = broadcast

        self._positions: list[dict[str, Any]] = []
        self._tier_a: list[dict[str, Any]] = []
        self._tier_b: list[dict[str, Any]] = []
        self._signals: deque[dict[str, Any]] = deque(maxlen=_MAX_SIGNALS)
        self._risk_events: deque[dict[str, Any]] = deque(maxlen=_MAX_RISK_EVENTS)

        self._risk: dict[str, Any] = _empty_risk()
        self._health: dict[str, Any] = _empty_health()

        self._signal_seq = 0
        self._event_seq = 0

    def set_broadcast(self, hook: BroadcastHook) -> None:
        self._broadcast = hook

    # ── builders (frontend shapes) ─────────────────────────────────────────────

    @staticmethod
    def make_position(
        symbol: str, shares: int, avg_price: Decimal, current_price: Decimal
    ) -> dict[str, Any]:
        unrealised = (current_price - avg_price) * Decimal(shares)
        return {
            "symbol": symbol,
            "shares": int(shares),
            "avg_price": _s(avg_price),
            "current_price": _s(current_price),
            "unrealised_pnl": _s(unrealised),
            "side": "long",
        }

    @staticmethod
    def make_watchlist_entry(
        symbol: str,
        tier: str,
        price: Decimal,
        rvol: Decimal | None,
        float_shares: int | None,
        catalyst: str | None,
        pillar_flags: dict[str, bool],
        *,
        change_pct: Decimal | None = None,
    ) -> dict[str, Any]:
        return {
            "symbol": symbol,
            "tier": tier,
            "price": _s(price),
            "rvol": _s(rvol) if rvol is not None else "—",
            "float_shares": float_shares,
            "catalyst": catalyst,
            "pillar_flags": pillar_flags,
            "change_pct": _s(change_pct) if change_pct is not None else None,
            "last_updated": _iso(),
        }

    def make_signal(
        self,
        symbol: str,
        action: str,
        event_type: str,
        detail: dict[str, Any],
        conviction: float | None = None,
    ) -> dict[str, Any]:
        self._signal_seq += 1
        return {
            "id": str(self._signal_seq),
            "ts": _iso(),
            "symbol": symbol,
            "event_type": event_type,
            "detail": detail,
            "conviction": conviction,
            "action": action,  # entry | exit | veto | info
        }

    def make_risk_event(
        self, event_type: str, severity: str, message: str, detail: dict[str, Any]
    ) -> dict[str, Any]:
        self._event_seq += 1
        return {
            "id": str(self._event_seq),
            "ts": _iso(),
            "event_type": event_type,
            "severity": severity,  # INFO | WARN | CRITICAL
            "message": message,
            "detail": detail,
        }

    # ── mutations ──────────────────────────────────────────────────────────────

    async def update_watchlists(
        self, tier_a: list[dict[str, Any]], tier_b: list[dict[str, Any]]
    ) -> None:
        async with self._lock:
            self._tier_a = list(tier_a)
            self._tier_b = list(tier_b)
        await self._broadcast_state()

    async def update_positions_and_risk(
        self, positions: list[dict[str, Any]], risk: dict[str, Any]
    ) -> None:
        async with self._lock:
            self._positions = list(positions)
            self._risk = dict(risk)
        await self._broadcast_state()

    async def update_health(self, health: dict[str, Any]) -> None:
        async with self._lock:
            self._health = dict(health)
        await self._broadcast_state()

    async def add_signal(self, signal: dict[str, Any]) -> None:
        async with self._lock:
            self._signals.appendleft(signal)
        await self._push("signal", signal)

    async def add_risk_event(self, event: dict[str, Any]) -> None:
        async with self._lock:
            self._risk_events.appendleft(event)
        await self._push("risk_event", event)

    def set_paused(self, paused: bool) -> None:
        self._risk["is_paused"] = paused

    # ── read path ──────────────────────────────────────────────────────────────

    def to_state(self) -> dict[str, Any]:
        return {
            "ts": _iso(),
            "positions": list(self._positions),
            "risk": dict(self._risk),
            "watchlist_tier_a": list(self._tier_a),
            "watchlist_tier_b": list(self._tier_b),
            "recent_signals": list(self._signals),
            "recent_risk_events": list(self._risk_events),
            "health": dict(self._health),
        }

    def signals(self, limit: int = 50) -> list[dict[str, Any]]:
        return list(self._signals)[:limit]

    def risk_events(self, limit: int = 50) -> list[dict[str, Any]]:
        return list(self._risk_events)[:limit]

    # ── broadcast helpers ──────────────────────────────────────────────────────

    async def _broadcast_state(self) -> None:
        await self._push("state_update", self.to_state())

    async def broadcast_state(self) -> None:
        await self._broadcast_state()

    async def _push(self, msg_type: str, payload: dict[str, Any]) -> None:
        if self._broadcast is None:
            return
        try:
            await self._broadcast({"type": msg_type, "payload": payload})
        except Exception:  # noqa: BLE001 — broadcast must never crash the engine
            pass


def _empty_risk() -> dict[str, Any]:
    return {
        "day_pnl": "0.00",
        "peak_pnl": "0.00",
        "max_daily_loss": "500.00",
        "give_back_warn": "0.25",
        "give_back_hard": "0.50",
        "consecutive_losses": 0,
        "is_halted": False,
        "halt_reason": None,
        "is_paused": False,
        "trades_today": 0,
        "wins_today": 0,
        "losses_today": 0,
    }


def _empty_health() -> dict[str, Any]:
    return {
        "feeds": [],
        "clock_drift_ms": 0.0,
        "avg_order_ack_ms": None,
        "ws_client_count": 0,
        "all_healthy": True,
        "checked_at": _iso(),
    }
