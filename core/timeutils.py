"""UTC / Eastern-Time helpers and market-session boundaries.

CLAUDE.md §10: "Time is ET, market-aware; handle pre-market, RTH, halts, and DST correctly."
All persisted timestamps are tz-aware UTC; ET is *derived* for display and session logic.
DST is handled by ``zoneinfo`` (America/New_York), not by fixed offsets.
"""

from __future__ import annotations

from datetime import UTC, datetime, time
from enum import StrEnum
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")

# Regular trading hours (ET). Pre-market begins well before; spec §7 scans from 07:00 ET.
RTH_OPEN = time(9, 30)
RTH_CLOSE = time(16, 0)
PREMARKET_OPEN = time(4, 0)
_SATURDAY = 5  # datetime.weekday(): Mon=0 .. Sat=5, Sun=6


class Session(StrEnum):
    """Coarse market session for a given instant (US equities)."""

    CLOSED = "CLOSED"
    PREMARKET = "PREMARKET"
    RTH = "RTH"
    AFTERHOURS = "AFTERHOURS"


def now_utc() -> datetime:
    """Current tz-aware time in UTC. The single clock source for the system."""
    return datetime.now(tz=UTC)


def to_utc(dt: datetime) -> datetime:
    """Normalize any datetime to tz-aware UTC. Naive input is rejected (fail-safe)."""
    if dt.tzinfo is None:
        raise ValueError("naive datetime is not allowed; all times must be tz-aware")
    return dt.astimezone(UTC)


def to_et(dt: datetime) -> datetime:
    """Convert any tz-aware datetime to Eastern Time (DST-correct)."""
    if dt.tzinfo is None:
        raise ValueError("naive datetime is not allowed; all times must be tz-aware")
    return dt.astimezone(ET)


def et_time(dt: datetime) -> time:
    """Wall-clock ET time-of-day for ``dt`` (for §7 time-of-day rules)."""
    return to_et(dt).timetz().replace(tzinfo=None)


def session_for(dt: datetime) -> Session:
    """Classify the US-equities session for ``dt``.

    Weekend = CLOSED. Exchange holidays are NOT modeled here (deferred to a calendar
    in a later phase); a holiday will read as a normal weekday session.
    """
    et = to_et(dt)
    if et.weekday() >= _SATURDAY:  # Sat/Sun
        return Session.CLOSED
    t = et.time()
    if t < PREMARKET_OPEN:
        return Session.CLOSED
    if t < RTH_OPEN:
        return Session.PREMARKET
    if t < RTH_CLOSE:
        return Session.RTH
    return Session.AFTERHOURS
