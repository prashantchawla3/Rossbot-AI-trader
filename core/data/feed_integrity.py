"""Feed-integrity guards: SIP/consolidated requirement + staleness detection (Phase 1).

Two fail-safe gates on the data feed (CLAUDE.md §7.2, §10 "on any feed gap → do NOT trade"):

1. **SIP / consolidated guard.** A momentum scanner MUST run on the consolidated tape. IEX
   alone is ~2–4% of small-cap volume and single-venue feeds miss the move (plan Phase 1
   "must be SIP/consolidated — IEX-only is unusable"). ``require_consolidated_feed`` rejects
   IEX-only / single-venue / delayed feeds when ``REQUIRE_SIP`` is on.

2. **Staleness detector.** Tracks the last-seen timestamp per feed key and trips when the gap
   exceeds the threshold. An unseen key is treated as stale (no data ⇒ do not trade).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from enum import StrEnum


class FeedIntegrityError(RuntimeError):
    """Raised when the configured feed is unfit for scanning (e.g. IEX-only)."""


class FeedStaleError(RuntimeError):
    """Raised when a feed has gone stale beyond its threshold."""


class MarketFeed(StrEnum):
    """Known market-data feeds. Values match Alpaca's ``DataFeed`` enum where applicable.

    verified: alpaca.markets/sdks/python/api_reference/data/enums.html (2026-06) —
    DataFeed members IEX, SIP, DELAYED_SIP, OTC, BOATS, OVERNIGHT. SIP/OTC require a paid
    subscription; IEX is free.
    """

    SIP = "sip"  # consolidated full tape — the only feed valid for scanning
    IEX = "iex"  # single venue (~2–4% of small-cap volume) — REJECTED for scanning
    DELAYED_SIP = "delayed_sip"  # 15-min delayed — REJECTED for live scanning
    OTC = "otc"  # OTC/pink — single segment, not consolidated equities tape
    BOATS = "boats"  # Blue Ocean overnight
    OVERNIGHT = "overnight"


# Feeds acceptable as the scanning source: the consolidated, real-time tape only.
_CONSOLIDATED_REALTIME = frozenset({MarketFeed.SIP})


def require_consolidated_feed(feed: str | MarketFeed, *, require_sip: bool = True) -> None:
    """Raise ``FeedIntegrityError`` if ``feed`` is unfit for scanning.

    ``require_sip`` mirrors the ``REQUIRE_SIP`` config (default True). When True, only the
    consolidated real-time SIP tape is accepted; IEX-only, OTC-only, and delayed feeds are
    rejected. When False (explicit operator override, e.g. a dev box), the guard is a no-op
    but the caller is responsible for the consequences.
    """
    if not require_sip:
        return
    try:
        resolved = MarketFeed(str(feed).lower())
    except ValueError:
        raise FeedIntegrityError(
            f"unknown market-data feed {feed!r}; cannot certify for scanning"
        ) from None
    if resolved not in _CONSOLIDATED_REALTIME:
        raise FeedIntegrityError(
            f"feed {resolved.value!r} is not consolidated/real-time; scanning requires SIP "
            f"(IEX-only/OTC/delayed feeds miss small-cap momentum volume)"
        )


@dataclass
class StalenessDetector:
    """Per-key last-update tracker. A gap beyond ``default_threshold`` is stale.

    ``default_threshold`` comes from ``FEED_STALENESS_SECONDS`` config; per-key overrides are
    supported (depth/tape update sub-second; 10-sec bars allow a longer gap).
    """

    default_threshold: timedelta = timedelta(seconds=5)
    _last: dict[str, datetime] = field(default_factory=dict)
    _thresholds: dict[str, timedelta] = field(default_factory=dict)

    @classmethod
    def from_seconds(cls, seconds: Decimal | int) -> StalenessDetector:
        if isinstance(seconds, bool):
            raise TypeError("staleness seconds must be a number, not bool")
        return cls(default_threshold=timedelta(seconds=float(seconds)))

    def set_threshold(self, key: str, threshold: timedelta) -> None:
        self._thresholds[key] = threshold

    def record(self, key: str, ts: datetime) -> None:
        """Record the latest data timestamp for ``key``. Timestamps must be tz-aware."""
        if ts.tzinfo is None:
            raise ValueError("staleness timestamps must be tz-aware")
        prev = self._last.get(key)
        # Keep the most recent observation; never move the clock backwards.
        if prev is None or ts > prev:
            self._last[key] = ts

    def gap(self, key: str, now: datetime) -> timedelta | None:
        """Return the current gap for ``key``, or ``None`` if never recorded."""
        last = self._last.get(key)
        return None if last is None else now - last

    def is_stale(self, key: str, now: datetime) -> bool:
        """True if the feed is stale (gap over threshold) OR never seen (fail-safe)."""
        last = self._last.get(key)
        if last is None:
            return True  # no data ever ⇒ treat as stale ⇒ do not trade
        threshold = self._thresholds.get(key, self.default_threshold)
        return (now - last) > threshold

    def check(self, key: str, now: datetime) -> None:
        """Raise ``FeedStaleError`` if ``key`` is stale."""
        if self.is_stale(key, now):
            gap = self.gap(key, now)
            detail = "never received data" if gap is None else f"gap={gap}"
            raise FeedStaleError(f"feed {key!r} is stale ({detail}); fail-safe → do not trade")


__all__ = [
    "FeedIntegrityError",
    "FeedStaleError",
    "MarketFeed",
    "StalenessDetector",
    "require_consolidated_feed",
]
