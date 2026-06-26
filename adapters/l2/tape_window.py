"""TapeAccumulator: rolling time-window of tape prints per symbol (spec §2A).

Consumes TapeTick events (from Databento trades schema) and exposes a
TapeAggregate summary over the last L2_WINDOW_SECS seconds.

Side inference (when TapeTick.side is None):
  Uses the tick test: if price > prior price → buyer aggressor (green);
  if price < prior price → seller aggressor (red); equal → same as prior.
  This is an approximation; the Databento trades schema provides explicit
  side ('A' = ask aggressor = BUY, 'B' = bid aggressor = SELL) when available.

Thread-safety: single-threaded async use only.
"""

from __future__ import annotations

from collections import deque
from datetime import datetime
from decimal import Decimal

from adapters.base import Side, TapeTick
from adapters.l2.models import TapeAggregate

_ZERO = Decimal("0")
_HUNDRED = Decimal("100")


class _Print:
    """Internal record for one tape event."""

    __slots__ = ("ts", "price", "size", "side")

    def __init__(self, ts: datetime, price: Decimal, size: int, side: Side | None) -> None:
        self.ts = ts
        self.price = price
        self.size = size
        self.side = side


class TapeAccumulator:
    """Stateful rolling window of tape prints for one symbol.

    spec §2A — the live session calls ``add()`` on every trades tick;
    detectors call ``aggregate(now)`` to read the window summary.
    """

    def __init__(self, window_secs: int = 30) -> None:
        if window_secs <= 0:
            raise ValueError("window_secs must be positive")
        self._window_secs = window_secs
        self._buf: deque[_Print] = deque()
        self._last_inferred_side: Side | None = None

    def add(self, tick: TapeTick) -> None:
        """Ingest a tape print.  Side inferred via tick test when not provided."""
        side = tick.side
        if side is None:
            side = self._infer_side(tick.price)
        self._last_inferred_side = side
        self._buf.append(_Print(tick.ts, Decimal(str(tick.price)), int(tick.size), side))

    def _infer_side(self, price: Decimal) -> Side | None:
        """Tick test: compare to prior print price."""
        if not self._buf:
            return None
        prev_price = self._buf[-1].price
        if price > prev_price:
            return Side.BUY
        if price < prev_price:
            return Side.SELL
        # Same price: repeat last known inferred side
        return self._last_inferred_side

    def _evict(self, now: datetime) -> None:
        """Remove prints older than window_secs from the front of the deque."""
        cutoff_ts = now.timestamp() - self._window_secs
        while self._buf and self._buf[0].ts.timestamp() < cutoff_ts:
            self._buf.popleft()

    def aggregate(self, now: datetime | None = None) -> TapeAggregate:
        """Compute window statistics.  If now is None, uses the latest print ts."""
        if now is None:
            now = self._buf[-1].ts if self._buf else None
        if now is not None:
            self._evict(now)

        if not self._buf:
            return TapeAggregate(
                window_secs=self._window_secs,
                total_shares=0,
                buy_shares=0,
                sell_shares=0,
                price_first=_ZERO,
                price_last=_ZERO,
                prints=0,
            )

        total = 0
        buys = 0
        sells = 0
        for p in self._buf:
            total += p.size
            if p.side is Side.BUY:
                buys += p.size
            elif p.side is Side.SELL:
                sells += p.size

        return TapeAggregate(
            window_secs=self._window_secs,
            total_shares=total,
            buy_shares=buys,
            sell_shares=sells,
            price_first=self._buf[0].price,
            price_last=self._buf[-1].price,
            prints=len(self._buf),
        )

    def shares_near_price(self, price: Decimal, tolerance: Decimal) -> int:
        """Total shares executed within ±tolerance of a given price level."""
        lo = price - tolerance
        hi = price + tolerance
        return sum(p.size for p in self._buf if lo <= p.price <= hi)

    def clear(self) -> None:
        self._buf.clear()
        self._last_inferred_side = None

    def __len__(self) -> int:
        return len(self._buf)
