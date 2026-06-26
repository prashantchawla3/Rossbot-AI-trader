"""DepthBook: rolling ring-buffer of depth snapshots per symbol (spec §2A).

Consumes DepthTick events (from Databento MBP-10) and stores the last
L2_DEPTH_SNAPSHOTS snapshots as DepthSnapshot frozen objects.

Thread-safety: single-threaded async use only (asyncio event loop).
"""

from __future__ import annotations

from collections import deque
from decimal import Decimal

from adapters.base import DepthTick
from adapters.l2.models import DepthSnapshot

_ZERO = Decimal("0")


class DepthBook:
    """Stateful rolling buffer of depth snapshots for one symbol.

    spec §2A — the live session calls ``add()`` on every MBP-10 tick;
    detectors call ``snapshots()`` to read the current state.
    """

    def __init__(self, max_snapshots: int = 20) -> None:
        if max_snapshots < 2:
            raise ValueError("max_snapshots must be >= 2 for spoof detection")
        self._max = max_snapshots
        self._buf: deque[DepthSnapshot] = deque(maxlen=max_snapshots)

    def add(self, tick: DepthTick) -> None:
        """Ingest a new depth tick and append a reduced DepthSnapshot."""
        if not tick.bids or not tick.asks:
            # Incomplete book tick — skip (fail-safe; no trade on bad data)
            return

        best_bid_price, best_bid_size = tick.bids[0]
        best_ask_price, best_ask_size = tick.asks[0]

        total_bid = sum(sz for _, sz in tick.bids)
        total_ask = sum(sz for _, sz in tick.asks)

        self._buf.append(
            DepthSnapshot(
                ts=tick.ts,
                best_bid=Decimal(str(best_bid_price)),
                best_bid_size=int(best_bid_size),
                best_ask=Decimal(str(best_ask_price)),
                best_ask_size=int(best_ask_size),
                total_bid_shares=int(total_bid),
                total_ask_shares=int(total_ask),
            )
        )

    def snapshots(self) -> list[DepthSnapshot]:
        """Return snapshots ordered oldest → newest."""
        return list(self._buf)

    def current(self) -> DepthSnapshot | None:
        """Return the most recent snapshot, or None if no data yet."""
        return self._buf[-1] if self._buf else None

    def clear(self) -> None:
        self._buf.clear()

    def __len__(self) -> int:
        return len(self._buf)
