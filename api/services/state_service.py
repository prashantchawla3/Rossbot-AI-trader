"""In-memory state aggregator — bridges the trading engine to the dashboard API.

The StateService holds the current live snapshot:
  - Risk state (from RiskManager)
  - Watchlist (from Scanner output)
  - Recent signals + risk events (ring buffers)
  - Session flags (paused, date)

Phase 5: the trading engine registers itself via ``register_*()``.  The
dashboard API reads snapshot via ``get_state()``.  WebSocket broadcast is
triggered by ``push_update()`` which the caller provides via callback.
Phase 6 will wire the real engine; Phase 5 returns zero/empty state until then.

CLAUDE.md §3: strategy proposes, risk disposes, execution obeys.  StateService
is read-path only — it never sends orders or mutates risk rules.
"""

from __future__ import annotations

import asyncio
import logging
from collections import deque
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Callable, Coroutine

from api.schemas.dashboard import (
    DashboardStateOut,
    HealthOut,
    JournalEntry,
    OpenPosition,
    RiskEventOut,
    RiskStateOut,
    SessionJournal,
    SignalEvent,
    WatchlistEntry,
)
from core.risk.manager import RiskManager
from core.risk.models import GiveBackLevel, RiskState

log = logging.getLogger(__name__)

_MAX_SIGNALS = 200
_MAX_RISK_EVENTS = 500

# Callable type for the broadcast hook: async (data: dict) -> None
_BroadcastHook = Callable[[dict[str, Any]], Coroutine[Any, Any, None]]


class StateService:
    """Single source of truth for the dashboard's live state.

    One instance is created at app startup and stored in ``app.state.svc``.
    Thread-safety: all mutations run inside ``asyncio`` (single-threaded event loop).
    """

    def __init__(self) -> None:
        self._lock = asyncio.Lock()

        # Optional references — wired in by Phase 6 / paper engine
        self._risk_manager: RiskManager | None = None
        self._broker_cancel: Callable[[], Coroutine[Any, Any, None]] | None = None

        # Ring buffers for the log views
        self._signals: deque[SignalEvent] = deque(maxlen=_MAX_SIGNALS)
        self._risk_events: deque[RiskEventOut] = deque(maxlen=_MAX_RISK_EVENTS)

        # Watchlist (replaced wholesale on each scanner cycle)
        self._watchlist: list[WatchlistEntry] = []

        # Session flags
        self._paused: bool = False
        self._session_date: str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        # Health snapshot (updated by HealthService background task)
        self._health: HealthOut = _empty_health()

        # Journal (post-session, populated by paper/live engine)
        self._journal_entries: list[JournalEntry] = []

        # Broadcast hook — set by main.py after ws_manager is created
        self._broadcast: _BroadcastHook | None = None

        # Signal + event counters for stable IDs
        self._signal_id: int = 0
        self._event_id: int = 0

        # Current prices for open positions (symbol → price)
        self._current_prices: dict[str, Decimal] = {}

    # ── Wiring ────────────────────────────────────────────────────────────────

    def register_risk_manager(self, rm: RiskManager) -> None:
        self._risk_manager = rm
        log.info("state_service.risk_manager_registered")

    def register_broker_cancel(
        self,
        cancel_fn: Callable[[], Coroutine[Any, Any, None]],
    ) -> None:
        """Register the broker's cancel-all-flatten coroutine (U13/kill-switch)."""
        self._broker_cancel = cancel_fn
        log.info("state_service.broker_cancel_registered")

    def set_broadcast_hook(self, hook: _BroadcastHook) -> None:
        self._broadcast = hook

    # ── State mutations (called by trading engine) ────────────────────────────

    async def update_watchlist(self, entries: list[WatchlistEntry]) -> None:
        async with self._lock:
            self._watchlist = list(entries)
        await self._push("watchlist_update", {"watchlist": [e.model_dump(mode="json") for e in entries]})

    async def add_signal(self, signal: SignalEvent) -> None:
        async with self._lock:
            self._signals.appendleft(signal)
        await self._push("signal", signal.model_dump(mode="json"))

    async def add_risk_event(self, event: RiskEventOut) -> None:
        async with self._lock:
            self._risk_events.appendleft(event)
        await self._push("risk_event", event.model_dump(mode="json"))

    async def update_current_price(self, symbol: str, price: Decimal) -> None:
        async with self._lock:
            self._current_prices[symbol] = price

    async def update_health(self, health: HealthOut) -> None:
        async with self._lock:
            self._health = health
        await self._push("health_update", health.model_dump(mode="json"))

    async def add_journal_entry(self, entry: JournalEntry) -> None:
        async with self._lock:
            self._journal_entries.append(entry)

    def reset_session(self, date: str | None = None) -> None:
        self._session_date = date or datetime.now(timezone.utc).strftime("%Y-%m-%d")
        self._signals.clear()
        self._risk_events.clear()
        self._watchlist = []
        self._paused = False
        self._journal_entries = []
        self._current_prices = {}

    def next_signal_id(self) -> int:
        self._signal_id += 1
        return self._signal_id

    def next_event_id(self) -> int:
        self._event_id += 1
        return self._event_id

    # ── Control actions (called by /controls router) ──────────────────────────

    async def halt_session(self, reason: str = "manual_kill_switch") -> None:
        """Halt the risk manager + optionally cancel all broker positions."""
        if self._risk_manager is not None:
            self._risk_manager.halt_session(reason)
            log.warning("state_service.halt reason=%s", reason)
        if self._broker_cancel is not None:
            try:
                await self._broker_cancel()
                log.warning("state_service.broker_cancel_called")
            except Exception:
                log.exception("state_service.broker_cancel_failed")
        # Fire a state-update broadcast immediately
        state = self.get_state()
        await self._push("state_update", state.model_dump(mode="json"))

    def pause(self) -> None:
        self._paused = True
        log.info("state_service.paused")

    def resume(self) -> None:
        # Only allow resume if risk manager isn't in a halted state
        if self._risk_manager is not None and self._risk_manager.state.halted:
            raise RuntimeError("Cannot resume: risk manager halted (requires session reset)")
        self._paused = False
        log.info("state_service.resumed")

    # ── Read path ─────────────────────────────────────────────────────────────

    def get_state(self) -> DashboardStateOut:
        risk_state = self._build_risk_state()
        return DashboardStateOut(
            risk=risk_state,
            watchlist=list(self._watchlist),
            recent_signals=list(self._signals)[:50],
            recent_risk_events=list(self._risk_events)[:50],
            health=self._health,
            session_paused=self._paused,
            session_date=self._session_date,
            server_ts=datetime.now(timezone.utc),
        )

    def get_journal(self) -> SessionJournal:
        entries = list(self._journal_entries)
        wins = sum(1 for e in entries if e.pnl > 0)
        losses = sum(1 for e in entries if e.pnl <= 0)
        total = len(entries)
        risk_state = self._build_risk_state()
        return SessionJournal(
            date=self._session_date,
            realized_pnl=risk_state.realized_pnl,
            peak_pnl=risk_state.peak_pnl,
            trades=entries,
            wins=wins,
            losses=losses,
            win_rate=(wins / total) if total > 0 else None,
            max_consecutive_losses=risk_state.consecutive_losses,
            rule_violations=0,  # populated by Phase 6 engine
        )

    @property
    def paused(self) -> bool:
        return self._paused

    @property
    def halted(self) -> bool:
        if self._risk_manager is None:
            return False
        return self._risk_manager.state.halted

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _build_risk_state(self) -> RiskStateOut:
        if self._risk_manager is None:
            return _empty_risk_state()
        rs: RiskState = self._risk_manager.state

        positions = [
            OpenPosition(
                symbol=sym,
                entry_price=entry_px,
                current_price=self._current_prices.get(sym, entry_px),
                shares=0,  # Phase 6 will supply share count per position
                unrealized_pnl=Decimal("0"),
            )
            for sym, entry_px in rs.open_positions.items()
        ]

        give_back: GiveBackLevel = self._risk_manager.check_give_back()

        return RiskStateOut(
            realized_pnl=rs.realized_pnl,
            peak_pnl=rs.peak_pnl,
            consecutive_losses=rs.consecutive_losses,
            trades_today=rs.trades_today,
            halted=rs.halted,
            halt_reason=rs.halt_reason,
            give_back_level=str(give_back),
            open_positions=positions,
            daily_loss_limit=Decimal("5000"),  # Phase 6 wires real BROKER_HARD_LOCKOUT
        )

    async def _push(self, event_type: str, payload: dict[str, Any]) -> None:
        if self._broadcast is not None:
            try:
                await self._broadcast({"type": event_type, "payload": payload})
            except Exception:  # noqa: BLE001
                log.exception("state_service.broadcast_failed type=%s", event_type)


# ── Zero-state helpers ─────────────────────────────────────────────────────────

def _empty_risk_state() -> RiskStateOut:
    return RiskStateOut(
        realized_pnl=Decimal("0"),
        peak_pnl=Decimal("0"),
        consecutive_losses=0,
        trades_today=0,
        halted=False,
        halt_reason=None,
        give_back_level="none",
        open_positions=[],
        daily_loss_limit=Decimal("5000"),
    )


def _empty_health() -> HealthOut:
    return HealthOut(
        feeds=[],
        clock_drift_ms=0.0,
        order_ack_latency_ms=None,
        all_healthy=True,
        ws_clients=0,
        as_of=datetime.now(timezone.utc),
    )
