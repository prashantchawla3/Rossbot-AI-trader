"""Unit tests for L2 microstructure detector pure functions (spec §2A / §13.2).

Acceptance criteria from the Phase 8 spec:
  - Spoof (vanishing bid, no prints) → SPOOF, not SUPPORT
  - Iceberg (GMBL/NIXX: executed >> displayed, price flat) → ICEBERG
  - Absorption then break → ABSORB_BREAK (E6 fires)
  - CADL bid-pull trap → SPOOF (not treated as guaranteed support)
  - Real floor (stable large bid + prints) → SUPPORT (E6 satisfied)

All functions are pure; no I/O, no config service needed — params are plain ints.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from adapters.l2.detectors import (
    detect_absorb_break,
    detect_iceberg,
    detect_real_floor,
    detect_spoof,
)
from adapters.l2.models import DepthSnapshot, TapeAggregate

# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

_T0 = datetime(2026, 1, 15, 9, 30, 0, tzinfo=UTC)


def _ts(offset_s: float = 0.0) -> datetime:
    return _T0 + timedelta(seconds=offset_s)


def _snap(
    *,
    ts: datetime = _T0,
    best_bid: str = "5.00",
    best_bid_size: int = 500,
    best_ask: str = "5.01",
    best_ask_size: int = 200,
    total_bid: int = 5000,
    total_ask: int = 2000,
) -> DepthSnapshot:
    return DepthSnapshot(
        ts=ts,
        best_bid=Decimal(best_bid),
        best_bid_size=best_bid_size,
        best_ask=Decimal(best_ask),
        best_ask_size=best_ask_size,
        total_bid_shares=total_bid,
        total_ask_shares=total_ask,
    )


def _agg(
    *,
    total: int = 0,
    buys: int = 0,
    sells: int = 0,
    price_first: str = "5.00",
    price_last: str = "5.00",
    prints: int = 0,
    window: int = 30,
) -> TapeAggregate:
    return TapeAggregate(
        window_secs=window,
        total_shares=total,
        buy_shares=buys,
        sell_shares=sells,
        price_first=Decimal(price_first),
        price_last=Decimal(price_last),
        prints=prints,
    )


# ─────────────────────────────────────────────────────────────────────────────
# detect_spoof
# ─────────────────────────────────────────────────────────────────────────────

class TestDetectSpoof:
    """spec §2A EX4/EX6 — large bid vanishes without confirming prints → SPOOF."""

    _PARAMS = dict(
        spoof_bid_min_shares=20_000,
        spoof_decay_secs=5,
        spoof_min_prints=100,
    )

    def test_classic_spoof_vanishing_bid_no_prints(self) -> None:
        """Large bid at t=0, gone at t=3 (< 5s), tape is silent → SPOOF."""
        snaps = [
            _snap(ts=_ts(0), best_bid_size=25_000),  # large bid appears
            _snap(ts=_ts(1), best_bid_size=24_000),
            _snap(ts=_ts(2), best_bid_size=22_000),
            _snap(ts=_ts(3), best_bid_size=500),     # pulled
        ]
        agg = _agg(total=50, prints=10)  # few prints — not real buying
        assert detect_spoof(snaps, agg, **self._PARAMS) is True

    def test_cadl_bid_pull_trap(self) -> None:
        """CADL (EX6): HFT yanks bids instantly → SPOOF, not guaranteed support."""
        snaps = [
            _snap(ts=_ts(0), best_bid_size=30_000),  # HFT large bid
            _snap(ts=_ts(0.5), best_bid_size=0),     # yanked in 0.5s
        ]
        agg = _agg(total=0, prints=0)
        assert detect_spoof(snaps, agg, **self._PARAMS) is True

    def test_no_spoof_bid_never_large(self) -> None:
        """Normal small bid — never reaches spoof threshold → not spoof."""
        snaps = [
            _snap(ts=_ts(0), best_bid_size=5_000),
            _snap(ts=_ts(3), best_bid_size=500),
        ]
        agg = _agg(total=50, prints=5)
        assert detect_spoof(snaps, agg, **self._PARAMS) is False

    def test_no_spoof_bid_still_present(self) -> None:
        """Large bid still substantially there (> 20%) → not a pull → not spoof."""
        snaps = [
            _snap(ts=_ts(0), best_bid_size=25_000),
            _snap(ts=_ts(2), best_bid_size=22_000),  # 88% still there
        ]
        agg = _agg(total=50, prints=5)
        assert detect_spoof(snaps, agg, **self._PARAMS) is False

    def test_no_spoof_prints_confirm_real(self) -> None:
        """Large bid vanished BUT lots of tape prints → real buyer filled, not spoof."""
        snaps = [
            _snap(ts=_ts(0), best_bid_size=25_000),
            _snap(ts=_ts(3), best_bid_size=300),  # bid gone — but tape printed heavily
        ]
        agg = _agg(total=500, prints=200)  # heavy tape activity
        assert detect_spoof(snaps, agg, **self._PARAMS) is False

    def test_no_spoof_bid_decay_too_slow(self) -> None:
        """Bid faded slowly (> spoof_decay_secs) — genuine fade, not a pull."""
        snaps = [
            _snap(ts=_ts(0), best_bid_size=25_000),
            _snap(ts=_ts(10), best_bid_size=300),  # took 10s > 5s decay threshold
        ]
        agg = _agg(total=30, prints=5)
        assert detect_spoof(snaps, agg, **self._PARAMS) is False

    def test_single_snapshot_insufficient(self) -> None:
        """Only one snapshot — not enough history to detect a pull."""
        snaps = [_snap(ts=_ts(0), best_bid_size=25_000)]
        agg = _agg(total=0, prints=0)
        assert detect_spoof(snaps, agg, **self._PARAMS) is False


# ─────────────────────────────────────────────────────────────────────────────
# detect_iceberg
# ─────────────────────────────────────────────────────────────────────────────

class TestDetectIceberg:
    """spec §2A GMBL/NIXX — executed >> displayed, price flat → ICEBERG (U14)."""

    _PARAMS = dict(
        absorbed_min=5_000,
        display_max=600,
        advance_max_cents=2,
    )

    def test_gmbl_style_iceberg(self) -> None:
        """10k shares bought, ask shows 200, price flat → ICEBERG.  spec §2A GMBL."""
        agg = _agg(total=10_000, buys=10_000, price_first="7.00", price_last="7.00", prints=50)
        snap = _snap(best_ask_size=200)
        assert detect_iceberg(agg, snap, **self._PARAMS) is True

    def test_nixx_style_iceberg(self) -> None:
        """NIXX-style: 7k shares absorbed, ask shows 400, price moved only 1 cent."""
        agg = _agg(total=7_000, buys=7_000, price_first="3.50", price_last="3.51", prints=40)
        snap = _snap(best_ask_size=400)
        assert detect_iceberg(agg, snap, **self._PARAMS) is True

    def test_no_iceberg_insufficient_volume(self) -> None:
        """Not enough volume executed to trigger iceberg suspicion."""
        agg = _agg(total=1_000, buys=1_000, price_first="5.00", price_last="5.00", prints=10)
        snap = _snap(best_ask_size=200)
        assert detect_iceberg(agg, snap, **self._PARAMS) is False

    def test_no_iceberg_large_displayed_ask(self) -> None:
        """Ask size is large (10k shown) — not a hidden seller."""
        agg = _agg(total=10_000, price_first="5.00", price_last="5.00", prints=50)
        snap = _snap(best_ask_size=10_000)
        assert detect_iceberg(agg, snap, **self._PARAMS) is False

    def test_no_iceberg_price_advanced(self) -> None:
        """Large volume AND price did advance — not iceberg, real breakout."""
        agg = _agg(total=10_000, buys=10_000, price_first="5.00", price_last="5.10", prints=50)
        snap = _snap(best_ask_size=200)
        assert detect_iceberg(agg, snap, **self._PARAMS) is False

    def test_no_iceberg_empty_tape(self) -> None:
        """No tape data — not iceberg (no evidence either way → UNKNOWN upstream)."""
        agg = _agg(total=0, prints=0)
        snap = _snap(best_ask_size=200)
        assert detect_iceberg(agg, snap, **self._PARAMS) is False

    def test_boundary_exactly_at_advance_threshold(self) -> None:
        """Advance of exactly 2 cents (boundary) — still counts as iceberg (≤ threshold)."""
        agg = _agg(total=6_000, buys=6_000, price_first="5.00", price_last="5.02", prints=30)
        snap = _snap(best_ask_size=300)
        assert detect_iceberg(agg, snap, **self._PARAMS) is True

    def test_no_iceberg_advance_just_over_threshold(self) -> None:
        """Advance of 3 cents — just over threshold → not iceberg."""
        agg = _agg(total=6_000, buys=6_000, price_first="5.00", price_last="5.03", prints=30)
        snap = _snap(best_ask_size=300)
        assert detect_iceberg(agg, snap, **self._PARAMS) is False


# ─────────────────────────────────────────────────────────────────────────────
# detect_real_floor
# ─────────────────────────────────────────────────────────────────────────────

class TestDetectRealFloor:
    """spec §2A real floor — stacked bids + print confirmation → SUPPORT (E6)."""

    _PARAMS = dict(
        floor_bid_min_shares=10_000,
        floor_min_prints=200,
        floor_min_stable_snaps=2,
    )

    def test_real_floor_classic(self) -> None:
        """Large stable bid + heavy prints → SUPPORT."""
        snaps = [
            _snap(ts=_ts(0), best_bid_size=15_000),
            _snap(ts=_ts(5), best_bid_size=14_000),
            _snap(ts=_ts(10), best_bid_size=13_500),
        ]
        agg = _agg(total=500, prints=250)
        assert detect_real_floor(snaps, agg, **self._PARAMS) is True

    def test_no_floor_bid_too_small(self) -> None:
        """Bid is below the floor threshold — not a real floor."""
        snaps = [
            _snap(ts=_ts(0), best_bid_size=3_000),
            _snap(ts=_ts(5), best_bid_size=2_500),
        ]
        agg = _agg(total=500, prints=250)
        assert detect_real_floor(snaps, agg, **self._PARAMS) is False

    def test_no_floor_insufficient_prints(self) -> None:
        """Large bid but tape is quiet — no prints confirmation → not support."""
        snaps = [
            _snap(ts=_ts(0), best_bid_size=15_000),
            _snap(ts=_ts(5), best_bid_size=14_000),
        ]
        agg = _agg(total=50, prints=20)  # below FLOOR_MIN_PRINTS
        assert detect_real_floor(snaps, agg, **self._PARAMS) is False

    def test_no_floor_bid_unstable(self) -> None:
        """Large bid appeared once but then vanished — not stable enough."""
        snaps = [
            _snap(ts=_ts(0), best_bid_size=15_000),
            _snap(ts=_ts(5), best_bid_size=100),   # disappeared → unstable
        ]
        agg = _agg(total=500, prints=250)
        assert detect_real_floor(snaps, agg, **self._PARAMS) is False

    def test_no_floor_empty_snapshots(self) -> None:
        assert detect_real_floor([], _agg(total=500, prints=250), **self._PARAMS) is False

    def test_floor_requires_prints_confirmation(self) -> None:
        """Large stable bid without prints → spec §13.2 prints-confirmation required."""
        snaps = [
            _snap(ts=_ts(0), best_bid_size=12_000),
            _snap(ts=_ts(5), best_bid_size=11_500),
        ]
        agg = _agg(total=0, prints=0)  # no prints
        assert detect_real_floor(snaps, agg, **self._PARAMS) is False


# ─────────────────────────────────────────────────────────────────────────────
# detect_absorb_break
# ─────────────────────────────────────────────────────────────────────────────

class TestDetectAbsorbBreak:
    """spec §2A absorbed-then-break trigger (E6) — visible ask absorbed → pop."""

    _PARAMS = dict(
        absorb_ask_min_shares=5_000,
        absorb_tape_min_shares=3_000,
        absorb_break_min_cents=5,
    )

    def test_absorb_break_classic(self) -> None:
        """Large ask visible early, absorbed by tape, price broke through → E6."""
        snaps = [
            _snap(ts=_ts(0), best_ask="5.00", best_ask_size=15_000),
            _snap(ts=_ts(5), best_ask="5.00", best_ask_size=8_000),  # ticking down
            _snap(ts=_ts(10), best_ask="5.00", best_ask_size=2_000),
            _snap(ts=_ts(15), best_ask="5.07", best_ask_size=500),   # broke through
        ]
        agg = _agg(total=5_000, prints=80, price_first="5.00", price_last="5.07")
        assert detect_absorb_break(snaps, agg, **self._PARAMS) is True

    def test_absorb_break_block_ticking_down(self) -> None:
        """'20k, 19k, 18k... boom' — spec §2A exact pattern."""
        snaps = [
            _snap(ts=_ts(0), best_ask="4.00", best_ask_size=20_000),
            _snap(ts=_ts(2), best_ask="4.00", best_ask_size=18_000),
            _snap(ts=_ts(4), best_ask="4.00", best_ask_size=16_000),
            _snap(ts=_ts(6), best_ask="4.08", best_ask_size=400),    # break
        ]
        agg = _agg(total=4_000, prints=100)
        assert detect_absorb_break(snaps, agg, **self._PARAMS) is True

    def test_no_absorb_break_ask_never_large(self) -> None:
        """No visible large seller — condition 1 fails."""
        snaps = [
            _snap(ts=_ts(0), best_ask="5.00", best_ask_size=500),
            _snap(ts=_ts(5), best_ask="5.05", best_ask_size=200),
        ] * 2
        agg = _agg(total=4_000, prints=100)
        assert detect_absorb_break(snaps, agg, **self._PARAMS) is False

    def test_no_absorb_break_insufficient_tape(self) -> None:
        """Large ask visible but tape too thin — seller not absorbed yet."""
        snaps = [
            _snap(ts=_ts(0), best_ask="5.00", best_ask_size=10_000),
            _snap(ts=_ts(5), best_ask="5.00", best_ask_size=8_000),
            _snap(ts=_ts(10), best_ask="5.06", best_ask_size=300),
        ]
        agg = _agg(total=500, prints=20)  # below ABSORB_TAPE_MIN
        assert detect_absorb_break(snaps, agg, **self._PARAMS) is False

    def test_no_absorb_break_price_not_advanced(self) -> None:
        """Ask reduced but price didn't break through — no break."""
        snaps = [
            _snap(ts=_ts(0), best_ask="5.00", best_ask_size=10_000),
            _snap(ts=_ts(5), best_ask="5.00", best_ask_size=8_000),
            _snap(ts=_ts(10), best_ask="5.02", best_ask_size=300),   # only 2c advance
        ]
        agg = _agg(total=4_000, prints=100)
        assert detect_absorb_break(snaps, agg, **self._PARAMS) is False

    def test_no_absorb_break_too_few_snapshots(self) -> None:
        """Fewer than 3 snapshots — insufficient history."""
        snaps = [
            _snap(ts=_ts(0), best_ask="5.00", best_ask_size=10_000),
            _snap(ts=_ts(5), best_ask="5.08", best_ask_size=200),
        ]
        agg = _agg(total=4_000, prints=100)
        assert detect_absorb_break(snaps, agg, **self._PARAMS) is False


# ─────────────────────────────────────────────────────────────────────────────
# TapeAggregate helpers
# ─────────────────────────────────────────────────────────────────────────────

class TestTapeAggregate:
    def test_price_advance_cents_positive(self) -> None:
        agg = _agg(price_first="5.00", price_last="5.10")
        assert agg.price_advance_cents == Decimal("10")

    def test_price_advance_cents_negative(self) -> None:
        agg = _agg(price_first="5.10", price_last="5.00")
        assert agg.price_advance_cents == Decimal("-10")

    def test_green_fraction(self) -> None:
        agg = _agg(total=1000, buys=750, sells=250)
        assert agg.green_fraction == Decimal("0.75")

    def test_green_fraction_zero_when_empty(self) -> None:
        agg = _agg(total=0)
        assert agg.green_fraction == Decimal("0")

    def test_is_empty(self) -> None:
        assert _agg(total=0, prints=0).is_empty is True
        assert _agg(total=1, prints=1).is_empty is False
