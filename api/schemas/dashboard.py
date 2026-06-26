"""Pydantic response schemas for the Phase 5 dashboard API.

All money fields use Decimal (never float) per CLAUDE.md §10.
Timestamps are UTC; ET is derived at display time in the dashboard.
spec Phase 5 (dashboard), §5 (risk state), §11 (U11 — no param editing).
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict


class _Out(BaseModel):
    model_config = ConfigDict(frozen=True)


# ── Positions ──────────────────────────────────────────────────────────────────

class OpenPosition(_Out):
    symbol: str
    entry_price: Decimal
    current_price: Decimal
    shares: int
    unrealized_pnl: Decimal
    side: Literal["long"] = "long"


# ── Risk state ─────────────────────────────────────────────────────────────────

class RiskStateOut(_Out):
    """Daily risk state snapshot.  spec §5/§6."""

    realized_pnl: Decimal
    peak_pnl: Decimal
    consecutive_losses: int
    trades_today: int
    halted: bool
    halt_reason: str | None
    give_back_level: Literal["none", "warn", "halt"]
    open_positions: list[OpenPosition]
    daily_loss_limit: Decimal


# ── Watchlist ──────────────────────────────────────────────────────────────────

class WatchlistEntry(_Out):
    """One symbol in the Tier-A or Tier-B scanner output.  spec §1/§9."""

    symbol: str
    price: Decimal
    rvol: float
    roc_pct: float
    float_shares: int | None
    catalyst_verified: bool
    tier: Literal["A", "B"]
    last_updated: datetime


# ── Signals ────────────────────────────────────────────────────────────────────

class SignalEvent(_Out):
    """Entry / exit / veto signal from the strategy engine.  spec §2/§3/§5."""

    id: int
    ts: datetime
    symbol: str
    event_type: Literal["entry", "exit", "veto"]
    pattern: str | None
    conviction: float | None
    veto_reasons: list[str]
    approved: bool
    spec_ref: str


# ── Risk events ────────────────────────────────────────────────────────────────

class RiskEventOut(_Out):
    """Auditable risk event row (mirrors ``risk_events`` DB table).  spec §5/§11."""

    id: int
    ts: datetime
    symbol: str | None
    event_type: str
    reason: str
    spec_ref: str
    detail: str | None


# ── Health ─────────────────────────────────────────────────────────────────────

class FeedHealth(_Out):
    """Liveness status for a single named data feed.  spec Phase 5."""

    name: str
    last_tick: datetime | None
    staleness_s: float
    alive: bool


class HealthOut(_Out):
    """Aggregated health status for all monitored components.  spec Phase 5."""

    feeds: list[FeedHealth]
    clock_drift_ms: float
    order_ack_latency_ms: float | None
    all_healthy: bool
    ws_clients: int
    as_of: datetime


# ── Journal ────────────────────────────────────────────────────────────────────

class JournalEntry(_Out):
    """One completed trade in the post-session journal.  spec Phase 5."""

    symbol: str
    side: str
    entry_price: Decimal
    exit_price: Decimal | None
    shares: int
    pnl: Decimal
    r_multiple: float | None
    pattern: str | None
    entry_ts: datetime
    exit_ts: datetime | None
    exit_reason: str | None
    spec_ref: str


class SessionJournal(_Out):
    """Post-session trade journal / report.  Mirrors Ross's review discipline."""

    date: str
    realized_pnl: Decimal
    peak_pnl: Decimal
    trades: list[JournalEntry]
    wins: int
    losses: int
    win_rate: float | None
    max_consecutive_losses: int
    rule_violations: int


# ── Full dashboard state ───────────────────────────────────────────────────────

class DashboardStateOut(_Out):
    """Complete dashboard state; pushed over WebSocket and served by GET /state."""

    risk: RiskStateOut
    watchlist: list[WatchlistEntry]
    recent_signals: list[SignalEvent]
    recent_risk_events: list[RiskEventOut]
    health: HealthOut
    session_paused: bool
    session_date: str
    server_ts: datetime


# ── WebSocket envelope ─────────────────────────────────────────────────────────

class WsMessage(BaseModel):
    """WebSocket message envelope sent to connected clients."""

    model_config = ConfigDict(frozen=True)

    type: str  # "state_update" | "risk_event" | "health_update" | "alert" | "pong"
    payload: dict[str, Any]


# ── Control responses ──────────────────────────────────────────────────────────

class ControlResult(_Out):
    ok: bool
    message: str


__all__ = [
    "ControlResult",
    "DashboardStateOut",
    "FeedHealth",
    "HealthOut",
    "JournalEntry",
    "OpenPosition",
    "RiskEventOut",
    "RiskStateOut",
    "SessionJournal",
    "SignalEvent",
    "WatchlistEntry",
    "WsMessage",
]
