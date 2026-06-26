"""Data models for the L2 microstructure engine (spec §2A / §13.2).

All money is Decimal; no floats.  These are frozen dataclasses — pure value
objects that the detector functions operate on.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal


@dataclass(frozen=True)
class DepthSnapshot:
    """Depth-of-book state reduced to the fields the detectors need.

    Derived from a Databento MBP-10 record (XNAS.ITCH, 10-level market-by-price).
    Prices are Decimal dollars (converted from DBN fixed-point at 1e-9).
    spec §2A / §13.2.
    """

    ts: datetime
    best_bid: Decimal       # NBBO bid price
    best_bid_size: int      # shares on best bid
    best_ask: Decimal       # NBBO ask price
    best_ask_size: int      # shares on best ask
    total_bid_shares: int   # sum across all 10 bid levels
    total_ask_shares: int   # sum across all 10 ask levels


@dataclass(frozen=True)
class TapeAggregate:
    """Tape statistics over the rolling time window (L2_WINDOW_SECS).

    Computed by TapeAccumulator.aggregate().  Pure value object consumed by
    all detector functions.  spec §2A tape read / §13.2.
    """

    window_secs: int
    total_shares: int       # all prints in window
    buy_shares: int         # aggressor=ask side (buyer lifted offer) — green print
    sell_shares: int        # aggressor=bid side (seller hit bid) — red print
    price_first: Decimal    # first print price in window (Decimal("0") if empty)
    price_last: Decimal     # last print price in window
    prints: int             # number of individual tape events

    @property
    def price_advance_cents(self) -> Decimal:
        """Signed price movement in cents across the window (positive = up)."""
        return (self.price_last - self.price_first) * Decimal("100")

    @property
    def green_fraction(self) -> Decimal:
        """Fraction of volume that was buyer-aggressor (green).  0 if no data."""
        if self.total_shares == 0:
            return Decimal("0")
        return Decimal(self.buy_shares) / Decimal(self.total_shares)

    @property
    def is_empty(self) -> bool:
        return self.total_shares == 0 and self.prints == 0
