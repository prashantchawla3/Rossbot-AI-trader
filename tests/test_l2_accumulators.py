"""Unit tests for DepthBook and TapeAccumulator (spec §2A / §13.2, Phase 8)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from adapters.base import DepthTick, Side, TapeTick
from adapters.l2.depth_book import DepthBook
from adapters.l2.tape_window import TapeAccumulator

_T0 = datetime(2026, 1, 15, 9, 30, 0, tzinfo=UTC)


def _ts(s: float = 0.0) -> datetime:
    return _T0 + timedelta(seconds=s)


def _depth(bid_size: int = 1000, ask_size: int = 500, ts_s: float = 0.0) -> DepthTick:
    return DepthTick(
        symbol="TEST",
        ts=_ts(ts_s),
        bids=[(Decimal("5.00"), bid_size)],
        asks=[(Decimal("5.01"), ask_size)],
    )


def _tape(price: str = "5.00", size: int = 100, ts_s: float = 0.0, side=Side.BUY) -> TapeTick:
    return TapeTick(symbol="TEST", ts=_ts(ts_s), price=Decimal(price), size=size, side=side)


# ─────────────────────────────────────────────────────────────────────────────
# DepthBook
# ─────────────────────────────────────────────────────────────────────────────

class TestDepthBook:
    def test_empty_on_init(self) -> None:
        b = DepthBook(max_snapshots=5)
        assert b.current() is None
        assert b.snapshots() == []
        assert len(b) == 0

    def test_add_single_snapshot(self) -> None:
        b = DepthBook()
        b.add(_depth(bid_size=2000))
        assert len(b) == 1
        s = b.current()
        assert s is not None
        assert s.best_bid_size == 2000
        assert s.best_ask_size == 500

    def test_ring_buffer_max_snapshots(self) -> None:
        b = DepthBook(max_snapshots=3)
        for i in range(5):
            b.add(_depth(bid_size=1000 + i * 100, ts_s=float(i)))
        assert len(b) == 3
        snaps = b.snapshots()
        # oldest should be the 3rd insert (i=2)
        assert snaps[0].best_bid_size == 1200
        assert snaps[-1].best_bid_size == 1400

    def test_snapshots_ordered_oldest_to_newest(self) -> None:
        b = DepthBook()
        for i in range(4):
            b.add(_depth(bid_size=100 * (i + 1), ts_s=float(i)))
        snaps = b.snapshots()
        sizes = [s.best_bid_size for s in snaps]
        assert sizes == sorted(sizes)

    def test_skips_empty_tick(self) -> None:
        b = DepthBook()
        tick = DepthTick(symbol="X", ts=_T0, bids=[], asks=[])
        b.add(tick)
        assert len(b) == 0

    def test_total_shares_summed_across_levels(self) -> None:
        tick = DepthTick(
            symbol="X",
            ts=_T0,
            bids=[(Decimal("5.00"), 1000), (Decimal("4.99"), 500)],
            asks=[(Decimal("5.01"), 300), (Decimal("5.02"), 200)],
        )
        b = DepthBook()
        b.add(tick)
        s = b.current()
        assert s is not None
        assert s.total_bid_shares == 1500
        assert s.total_ask_shares == 500

    def test_clear(self) -> None:
        b = DepthBook()
        b.add(_depth())
        b.clear()
        assert len(b) == 0
        assert b.current() is None

    def test_min_snapshots_validation(self) -> None:
        import pytest
        with pytest.raises(ValueError):
            DepthBook(max_snapshots=1)


# ─────────────────────────────────────────────────────────────────────────────
# TapeAccumulator
# ─────────────────────────────────────────────────────────────────────────────

class TestTapeAccumulator:
    def test_empty_aggregate(self) -> None:
        ta = TapeAccumulator(window_secs=30)
        agg = ta.aggregate(now=_T0)
        assert agg.is_empty
        assert agg.total_shares == 0
        assert agg.prints == 0

    def test_buy_side_counted(self) -> None:
        ta = TapeAccumulator(window_secs=30)
        ta.add(_tape(size=500, side=Side.BUY))
        agg = ta.aggregate(now=_ts(1))
        assert agg.total_shares == 500
        assert agg.buy_shares == 500
        assert agg.sell_shares == 0

    def test_sell_side_counted(self) -> None:
        ta = TapeAccumulator(window_secs=30)
        ta.add(_tape(size=300, side=Side.SELL))
        agg = ta.aggregate(now=_ts(1))
        assert agg.sell_shares == 300
        assert agg.buy_shares == 0

    def test_window_eviction(self) -> None:
        """Prints older than window_secs should be evicted."""
        ta = TapeAccumulator(window_secs=10)
        ta.add(_tape(size=100, ts_s=0.0))   # will be evicted
        ta.add(_tape(size=200, ts_s=5.0))   # will be evicted
        ta.add(_tape(size=400, ts_s=25.0))  # stays (15s before now)
        ta.add(_tape(size=300, ts_s=30.0))  # stays (right at now)
        agg = ta.aggregate(now=_ts(35.0))
        assert agg.total_shares == 700
        assert agg.prints == 2

    def test_price_advance_tracked(self) -> None:
        ta = TapeAccumulator(window_secs=30)
        ta.add(_tape(price="5.00", size=100))
        ta.add(_tape(price="5.05", size=100))
        ta.add(_tape(price="5.10", size=100))
        agg = ta.aggregate(now=_ts(5))
        assert agg.price_first == Decimal("5.00")
        assert agg.price_last == Decimal("5.10")
        assert agg.price_advance_cents == Decimal("10")

    def test_tick_test_side_inference_up(self) -> None:
        """Price rising → infer BUY for unknown-side print."""
        ta = TapeAccumulator(window_secs=30)
        ta.add(_tape(price="5.00", size=100, side=None))
        ta.add(_tape(price="5.02", size=200, side=None))  # higher price → BUY
        agg = ta.aggregate(now=_ts(5))
        assert agg.buy_shares == 200  # second print inferred as BUY

    def test_tick_test_side_inference_down(self) -> None:
        ta = TapeAccumulator(window_secs=30)
        ta.add(_tape(price="5.05", size=100, side=None))
        ta.add(_tape(price="5.03", size=150, side=None))  # lower price → SELL
        agg = ta.aggregate(now=_ts(5))
        assert agg.sell_shares == 150

    def test_shares_near_price(self) -> None:
        ta = TapeAccumulator(window_secs=60)
        ta.add(_tape(price="5.00", size=200))
        ta.add(_tape(price="5.01", size=300))
        ta.add(_tape(price="5.10", size=1000))  # far away
        near = ta.shares_near_price(Decimal("5.00"), tolerance=Decimal("0.02"))
        assert near == 500  # 200 + 300

    def test_clear(self) -> None:
        ta = TapeAccumulator(window_secs=30)
        ta.add(_tape(size=500))
        ta.clear()
        agg = ta.aggregate(now=_ts(5))
        assert agg.is_empty

    def test_window_secs_validation(self) -> None:
        import pytest
        with pytest.raises(ValueError):
            TapeAccumulator(window_secs=0)
