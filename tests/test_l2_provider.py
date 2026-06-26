"""Integration tests for L2MicrostructureProvider (spec §2A / §13.2, Phase 8).

Tests wire up DepthBook + TapeAccumulator through the full provider to verify
the end-to-end signal path — from raw ticks to L2Signal output.

Acceptance criteria (Phase 8 spec):
  A. Spoof (vanishing bid, no prints) → SPOOF, not SUPPORT
  B. Iceberg (GMBL/NIXX-style) → ICEBERG
  C. Absorption-then-break → ABSORB_BREAK (E6 fires)
  D. CADL bid-pull trap → SPOOF (not treated as guaranteed support)
  E. No data for symbol → UNKNOWN (fail closed, §13.2)
  F. Real floor (stable bid + prints) → SUPPORT (E6 satisfied)
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from adapters.base import DepthTick, Side, TapeTick
from adapters.l2.provider import L2MicrostructureProvider
from adapters.providers import L2Signal
from core.config import ConfigService

# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────

_T0 = datetime(2026, 1, 15, 9, 30, 0, tzinfo=UTC)
_SYM = "GMBL"


def _ts(offset_s: float = 0.0) -> datetime:
    return _T0 + timedelta(seconds=offset_s)


def _mk_provider(overrides: dict | None = None) -> L2MicrostructureProvider:
    """Build a provider with test-tuned thresholds via config overrides."""
    cfg = ConfigService.from_defaults()
    if overrides:
        rows = {k: (cfg._rows[k][1],) for k in cfg._rows}  # preserve types
        # Apply overrides as raw strings
        merged = dict(cfg._rows)
        for key, val in overrides.items():
            if key in merged:
                raw_type = merged[key][1]
                merged[key] = (str(val), raw_type)
        cfg = ConfigService(merged)
    return L2MicrostructureProvider(cfg)


def _depth_tick(
    *,
    ts: datetime = _T0,
    symbol: str = _SYM,
    bid: str = "5.00",
    bid_size: int = 500,
    ask: str = "5.01",
    ask_size: int = 200,
) -> DepthTick:
    bid_p = Decimal(bid)
    ask_p = Decimal(ask)
    return DepthTick(
        symbol=symbol,
        ts=ts,
        bids=[(bid_p, bid_size)],
        asks=[(ask_p, ask_size)],
    )


def _tape_tick(
    *,
    ts: datetime = _T0,
    symbol: str = _SYM,
    price: str = "5.00",
    size: int = 100,
    side: Side | None = Side.BUY,
) -> TapeTick:
    return TapeTick(
        symbol=symbol,
        ts=ts,
        price=Decimal(price),
        size=size,
        side=side,
    )


def run(coro):  # type: ignore[no-untyped-def]
    return asyncio.run(coro)


# ─────────────────────────────────────────────────────────────────────────────
# A. Unknown when no data
# ─────────────────────────────────────────────────────────────────────────────

def test_unknown_no_data_for_symbol() -> None:
    """Acceptance E: no data → UNKNOWN (fail closed, spec §13.2)."""
    p = _mk_provider()
    assert run(p.evaluate(_SYM)) is L2Signal.UNKNOWN


def test_unknown_only_depth_no_tape() -> None:
    """Depth data alone is insufficient — tape needed for confirmation."""
    p = _mk_provider()
    p.on_depth(_depth_tick(bid_size=20_000))
    assert run(p.evaluate(_SYM)) is L2Signal.UNKNOWN


def test_unknown_only_tape_no_depth() -> None:
    """Tape data alone is insufficient — depth book needed."""
    p = _mk_provider()
    p.on_tape(_tape_tick(size=5_000))
    assert run(p.evaluate(_SYM)) is L2Signal.UNKNOWN


# ─────────────────────────────────────────────────────────────────────────────
# B. Iceberg (GMBL / NIXX fixture)
# ─────────────────────────────────────────────────────────────────────────────

def test_iceberg_gmbl_style() -> None:
    """Acceptance B: massive buying, price flat, small displayed ask → ICEBERG.

    Models the GMBL fixture: anticipated $7 break with hidden seller (U14).
    10k shares bought, ask shows 200, price didn't advance.
    """
    p = _mk_provider({
        "ICEBERG_ABSORBED_MIN": 5000,
        "ICEBERG_DISPLAY_MAX": 600,
        "ICEBERG_ADVANCE_MAX_CENTS": 2,
        # Ensure spoof threshold is NOT triggered
        "SPOOF_BID_MIN_SHARES": 50_000,
    })
    # Stable small ask (hidden seller)
    p.on_depth(_depth_tick(ts=_ts(0), ask_size=200))
    p.on_depth(_depth_tick(ts=_ts(5), ask_size=200))

    # Heavy buying with no price advance (iceberg being filled)
    for i in range(100):
        p.on_tape(_tape_tick(ts=_ts(i * 0.2), size=100, price="7.00", side=Side.BUY))

    assert run(p.evaluate(_SYM)) is L2Signal.ICEBERG


def test_iceberg_nixx_fast_bailout() -> None:
    """NIXX fixture: iceberg seller → correct fast bailout (small advance only)."""
    p = _mk_provider({
        "ICEBERG_ABSORBED_MIN": 5000,
        "ICEBERG_DISPLAY_MAX": 600,
        "ICEBERG_ADVANCE_MAX_CENTS": 2,
        "SPOOF_BID_MIN_SHARES": 50_000,
    })
    p.on_depth(_depth_tick(ts=_ts(0), ask_size=400))
    p.on_depth(_depth_tick(ts=_ts(5), ask_size=350))
    # 7k shares at $3.50, price moved only 1 cent
    for i in range(70):
        p.on_tape(_tape_tick(ts=_ts(i * 0.3), size=100, price="3.50" if i < 65 else "3.51"))
    assert run(p.evaluate(_SYM)) is L2Signal.ICEBERG


# ─────────────────────────────────────────────────────────────────────────────
# A / D. Spoof (vanishing bid) and CADL bid-pull
# ─────────────────────────────────────────────────────────────────────────────

def test_spoof_vanishing_bid_no_prints() -> None:
    """Acceptance A: large bid appears then vanishes within decay window, no prints → SPOOF."""
    p = _mk_provider({
        "SPOOF_BID_MIN_SHARES": 20_000,
        "SPOOF_DECAY_SECS": 5,
        "SPOOF_MIN_PRINTS": 100,
        "ICEBERG_ABSORBED_MIN": 99_999,  # disable iceberg to isolate spoof
    })
    # Large bid at t=0
    p.on_depth(_depth_tick(ts=_ts(0), bid_size=25_000))
    p.on_depth(_depth_tick(ts=_ts(1), bid_size=24_000))
    p.on_depth(_depth_tick(ts=_ts(2), bid_size=22_000))
    p.on_depth(_depth_tick(ts=_ts(3), bid_size=300))  # pulled

    # Tape is silent (no real buying)
    p.on_tape(_tape_tick(ts=_ts(1), size=30))
    p.on_tape(_tape_tick(ts=_ts(2), size=20))

    assert run(p.evaluate(_SYM)) is L2Signal.SPOOF


def test_cadl_bid_pull_not_treated_as_support() -> None:
    """Acceptance D: CADL bid-pull trap (EX6) → SPOOF, never SUPPORT."""
    p = _mk_provider({
        "SPOOF_BID_MIN_SHARES": 20_000,
        "SPOOF_DECAY_SECS": 5,
        "SPOOF_MIN_PRINTS": 100,
        "ICEBERG_ABSORBED_MIN": 99_999,
    })
    # HFT drops large bid then yanks it in <1s
    p.on_depth(_depth_tick(ts=_ts(0), bid_size=30_000))
    p.on_depth(_depth_tick(ts=_ts(0.5), bid_size=0))

    p.on_tape(_tape_tick(ts=_ts(0.1), size=10))  # almost no prints

    assert run(p.evaluate(_SYM)) is L2Signal.SPOOF


# ─────────────────────────────────────────────────────────────────────────────
# C. Absorption → Break (E6 fires)
# ─────────────────────────────────────────────────────────────────────────────

def test_absorb_break_e6_fires() -> None:
    """Acceptance C: visible ask absorbed by tape, price breaks through → ABSORB_BREAK."""
    p = _mk_provider({
        "ABSORB_ASK_MIN_SHARES": 5_000,
        "ABSORB_TAPE_MIN_SHARES": 3_000,
        "ABSORB_BREAK_MIN_CENTS": 5,
        "SPOOF_BID_MIN_SHARES": 99_999,  # disable spoof
        "ICEBERG_ABSORBED_MIN": 99_999,  # disable iceberg
        "FLOOR_BID_MIN_SHARES": 99_999,  # disable floor
    })
    # Early: large visible ask (the seller)
    p.on_depth(_depth_tick(ts=_ts(0), ask="5.00", ask_size=15_000))
    p.on_depth(_depth_tick(ts=_ts(5), ask="5.00", ask_size=10_000))
    # Middle: seller being absorbed
    p.on_depth(_depth_tick(ts=_ts(10), ask="5.00", ask_size=5_000))
    # Late: ask gone, price broke through
    p.on_depth(_depth_tick(ts=_ts(15), ask="5.08", ask_size=300))

    # Tape shows heavy execution against the seller
    for i in range(40):
        p.on_tape(_tape_tick(ts=_ts(i * 0.3), size=100, price="5.00"))

    assert run(p.evaluate(_SYM)) is L2Signal.ABSORB_BREAK


# ─────────────────────────────────────────────────────────────────────────────
# F. Real floor → SUPPORT
# ─────────────────────────────────────────────────────────────────────────────

def test_real_floor_support() -> None:
    """Acceptance F: large stable bid absorbs selling, tape confirms → SUPPORT."""
    p = _mk_provider({
        "FLOOR_BID_MIN_SHARES": 10_000,
        "FLOOR_MIN_PRINTS": 200,
        "FLOOR_MIN_STABLE_SNAPS": 2,
        "SPOOF_BID_MIN_SHARES": 99_999,  # disable spoof
        "ICEBERG_ABSORBED_MIN": 99_999,  # disable iceberg
        "ABSORB_ASK_MIN_SHARES": 99_999,  # disable absorb-break
    })
    # Stable large bid over multiple snapshots
    p.on_depth(_depth_tick(ts=_ts(0), bid_size=14_000))
    p.on_depth(_depth_tick(ts=_ts(5), bid_size=13_500))
    p.on_depth(_depth_tick(ts=_ts(10), bid_size=13_000))

    # Tape confirms: sellers hitting the floor, bid holding
    for i in range(30):
        p.on_tape(_tape_tick(ts=_ts(i * 0.5), size=20, side=Side.SELL))

    assert run(p.evaluate(_SYM)) is L2Signal.SUPPORT


# ─────────────────────────────────────────────────────────────────────────────
# Priority ordering
# ─────────────────────────────────────────────────────────────────────────────

def test_iceberg_beats_floor() -> None:
    """When both ICEBERG and FLOOR conditions hold, ICEBERG wins (more dangerous)."""
    p = _mk_provider({
        "ICEBERG_ABSORBED_MIN": 1_000,    # low threshold → easy to trigger
        "ICEBERG_DISPLAY_MAX": 600,
        "ICEBERG_ADVANCE_MAX_CENTS": 2,
        "FLOOR_BID_MIN_SHARES": 1,        # floor threshold very low → also triggers
        "FLOOR_MIN_PRINTS": 1,
        "FLOOR_MIN_STABLE_SNAPS": 1,
        "SPOOF_BID_MIN_SHARES": 99_999,
        "ABSORB_ASK_MIN_SHARES": 99_999,
    })
    p.on_depth(_depth_tick(ts=_ts(0), bid_size=5_000, ask_size=200))
    for i in range(20):
        p.on_tape(_tape_tick(ts=_ts(i * 0.5), size=100, price="5.00", side=Side.BUY))
    # Iceberg condition met AND floor condition met → ICEBERG wins
    result = run(p.evaluate(_SYM))
    assert result is L2Signal.ICEBERG


def test_spoof_beats_iceberg() -> None:
    """SPOOF wins over ICEBERG in priority."""
    p = _mk_provider({
        "SPOOF_BID_MIN_SHARES": 5_000,    # low → easy to trigger
        "SPOOF_DECAY_SECS": 60,           # allow slow decay
        "SPOOF_MIN_PRINTS": 100_000,      # impossible to meet → always spoof
        "ICEBERG_ABSORBED_MIN": 1_000,    # low → easy to trigger
        "ICEBERG_DISPLAY_MAX": 9_999_999,
        "ICEBERG_ADVANCE_MAX_CENTS": 9_999,
        "ABSORB_ASK_MIN_SHARES": 99_999,
        "FLOOR_BID_MIN_SHARES": 99_999,
    })
    # Large bid that vanishes
    p.on_depth(_depth_tick(ts=_ts(0), bid_size=25_000))
    p.on_depth(_depth_tick(ts=_ts(3), bid_size=100))
    p.on_tape(_tape_tick(ts=_ts(1), size=50))

    assert run(p.evaluate(_SYM)) is L2Signal.SPOOF


# ─────────────────────────────────────────────────────────────────────────────
# Reset
# ─────────────────────────────────────────────────────────────────────────────

def test_reset_clears_state() -> None:
    """reset() removes all accumulated state so evaluate() returns UNKNOWN again."""
    p = _mk_provider({
        "FLOOR_BID_MIN_SHARES": 1,
        "FLOOR_MIN_PRINTS": 1,
        "FLOOR_MIN_STABLE_SNAPS": 1,
        "SPOOF_BID_MIN_SHARES": 99_999,
        "ICEBERG_ABSORBED_MIN": 99_999,
        "ABSORB_ASK_MIN_SHARES": 99_999,
    })
    p.on_depth(_depth_tick(bid_size=50_000))
    p.on_tape(_tape_tick(size=10_000))

    # Sanity: should have a signal before reset
    assert run(p.evaluate(_SYM)) is not L2Signal.UNKNOWN

    p.reset(_SYM)
    assert run(p.evaluate(_SYM)) is L2Signal.UNKNOWN
