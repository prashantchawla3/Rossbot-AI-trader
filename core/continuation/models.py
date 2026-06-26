"""Continuation engine domain models — spec §12B / §13.10.

All price/volume fields use Decimal (CLAUDE.md §10).
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum


class DoneReason(StrEnum):
    """Why a Day-2 continuation is considered over. spec §12B DONE_IF."""

    RVOL_FADED = "rvol_faded"          # today_rvol < 25% of prev_day_volume
    RETRACE_EXCEEDED = "retrace_exceeded"  # retrace > 50% of Day-1 move
    MACD_NEGATIVE_CROSS = "macd_negative_cross"  # MACD crossed below signal
    VWAP_BROKEN = "vwap_broken"         # broke and held below VWAP
    NOT_DONE = "not_done"               # none of the above — still tradeable


@dataclass(frozen=True)
class ContinuationContext:
    """All data needed to assess Day-2 tradability. spec §12B.

    ``day1_close_pct_of_high`` measures how well Day-1 "held" into the close.
    A value ≥ ``CONTINUATION_HOLD_PCT`` config threshold signals the stock held well.
    """

    symbol: str
    day1_open: Decimal
    day1_high: Decimal
    day1_close: Decimal
    prev_day_volume: int     # Day-1 total volume (for RVOL comparison)
    today_volume: int        # Day-2 volume so far
    today_low: Decimal       # Day-2 low so far (for retrace calc)
    current_price: Decimal
    current_vwap: Decimal
    macd_histogram: Decimal  # positive=rising momentum, negative=fading


@dataclass(frozen=True)
class EligibilityResult:
    """Whether this symbol qualifies for Day-2 continuation. spec §12B ELIGIBLE_DAY2."""

    eligible: bool
    day1_move_pct: Decimal
    held_close_pct: Decimal
    reason: str


@dataclass(frozen=True)
class Day2Settings:
    """Adjusted parameters for a Day-2 continuation trade. spec §12B ADJUSTMENTS.

    Forces 5-min timeframe and a reduced size fraction of the caller's max size.
    """

    timeframe: str = "5m"    # shift 1-min → 5-min (less choppy Day 2)
    size_fraction: Decimal = Decimal("0.50")   # reduced size
    avoid_gap_and_go: bool = True
    avoid_aggressive_hod: bool = True


__all__ = [
    "ContinuationContext",
    "Day2Settings",
    "DoneReason",
    "EligibilityResult",
]
