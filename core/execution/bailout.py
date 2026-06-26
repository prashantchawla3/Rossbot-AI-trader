"""Breakout-or-bailout (time stop) pure functions (spec §3 P2 / §13.5, Phase 10).

Phase 10 hardens the existing P2 check (already in exit_engine.py) by adding
the "no higher-highs on rising volume" guard that prevents premature exit on
a slow-but-valid mover.

Spec §13.5:
  "unrealized < +0.10 at T+60s AND no higher-highs on rising volume → flatten"

The higher-high check filters the condition: if the stock IS grinding up with
increasing volume, it's slow-but-valid — do NOT bail out.  Only flatten when
it has stalled with NO sign of momentum.

Public functions:
  has_higher_high_on_rising_volume — pure: list[BarTick] × entry_price → bool
  is_bailout_condition             — pure: full time-stop gate

spec §3 P2 / §13.5 / Phase 10.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from adapters.base import BarTick
from core.config import ConfigService


def has_higher_high_on_rising_volume(
    bars_since_entry: list[BarTick],
    entry_price: Decimal,
) -> bool:
    """Return True if any consecutive bar pair shows a new high AND rising volume.

    "No higher-highs on rising volume" is the condition for the bailout to fire.
    If this function returns True, the position is still showing momentum and
    should NOT be bailed out yet.

    A higher high requires:
    1. curr.high > prev.high (new intraday high vs the prior bar)
    2. curr.high > entry_price (actually above where we entered)
    3. curr.volume >= prev.volume (rising or equal volume — confirming, not fading)

    spec §3 P2 / §13.5.
    """
    if len(bars_since_entry) < 2:
        return False

    for i in range(1, len(bars_since_entry)):
        prev = bars_since_entry[i - 1]
        curr = bars_since_entry[i]
        if (
            curr.high > prev.high
            and curr.high > entry_price
            and curr.volume >= prev.volume
        ):
            return True
    return False


def is_bailout_condition(
    entry_ts: datetime,
    entry_price: Decimal,
    current_price: Decimal,
    bars_since_entry: list[BarTick],
    now_ts: datetime,
    cfg: ConfigService,
) -> bool:
    """Return True when the position should be flattened via the time stop (P2).

    Gates (ALL must be true):
    1. elapsed >= BAILOUT_SECONDS since entry (window expired)
    2. unrealized < BAILOUT_MOVE (position has not moved enough)
    3. no higher-high on rising volume seen since entry (no proof of momentum)

    If (3) is False (momentum confirmed), return False even after the window,
    allowing slow-but-valid movers to run.

    spec §3 P2 / §13.5 / Phase 10.
    """
    bailout_secs = cfg.get_int("BAILOUT_SECONDS")
    bailout_move = cfg.get_decimal("BAILOUT_MOVE")

    elapsed = (now_ts - entry_ts).total_seconds()
    if elapsed < bailout_secs:
        return False  # still within window

    unrealized = current_price - entry_price
    if unrealized >= bailout_move:
        return False  # position already advanced enough

    # If we've seen higher highs on rising volume → momentum present → let it ride
    if has_higher_high_on_rising_volume(bars_since_entry, entry_price):
        return False

    return True  # stalled, no momentum proof → flatten
