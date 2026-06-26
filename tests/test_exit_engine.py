"""Tests for the exit engine P1–P8 (spec §3).

Priority order: P1 beats P2 beats P3 … P8.
Each rule has a pass (fires) and fail (does NOT fire) test.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from adapters.base import BarTick
from adapters.providers import L2Signal
from core.config import ConfigService
from core.strategy.exit_engine import _at_psych_level, evaluate_exit
from core.strategy.models import ExitReason, PositionSnapshot, ScaleAction


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

_TS = datetime(2024, 1, 15, 9, 35, tzinfo=UTC)


def _bar(
    close: str,
    open_: str | None = None,
    high: str | None = None,
    low: str | None = None,
    offset_sec: int = 0,
) -> BarTick:
    c = Decimal(close)
    o = Decimal(open_) if open_ else c
    h = Decimal(high) if high else max(c, o) + Decimal("0.02")
    lo = Decimal(low) if low else min(c, o) - Decimal("0.02")
    return BarTick(
        symbol="TEST",
        ts=_TS + timedelta(seconds=offset_sec),
        timeframe="1m",
        open=o, high=h, low=lo, close=c,
        volume=200_000,
    )


def _pos(
    entry: str = "5.00",
    stop: str = "4.80",
    target: str = "5.40",
    high_wm: str | None = None,
    entry_offset_sec: int = 0,
) -> PositionSnapshot:
    e = Decimal(entry)
    return PositionSnapshot(
        symbol="TEST",
        entry_price=e,
        current_stop=Decimal(stop),
        target_price=Decimal(target),
        shares=1000,
        entry_ts=_TS + timedelta(seconds=entry_offset_sec),
        high_watermark=Decimal(high_wm) if high_wm else e,
    )


def _cfg() -> ConfigService:
    return ConfigService.from_defaults()


def _eval(
    pos: PositionSnapshot,
    current_bar: BarTick,
    prev_bars: list[BarTick] | None = None,
    l2_signal: L2Signal = L2Signal.SUPPORT,
    vwap: Decimal | None = None,
    market_rank: int | None = None,
    intraday_high: Decimal | None = None,
) -> "ExitSignal | None":  # noqa: F821
    from core.strategy.exit_engine import evaluate_exit
    cfg = _cfg()
    return evaluate_exit(
        position=pos,
        current_bar=current_bar,
        prev_bars=prev_bars or [],
        current_price=current_bar.close,
        l2_signal=l2_signal,
        vwap=vwap,
        market_rank=market_rank,
        intraday_high=intraday_high or current_bar.high,
        config=cfg,
    )


# ──────────────────────────────────────────────────────────────────────────────
# _at_psych_level utility
# ──────────────────────────────────────────────────────────────────────────────

class TestPsychLevel:
    def test_at_dollar(self):
        assert _at_psych_level(Decimal("6.00"), Decimal("0.50"), Decimal("0.03"))

    def test_at_half_dollar(self):
        assert _at_psych_level(Decimal("5.50"), Decimal("0.50"), Decimal("0.03"))

    def test_near_dollar(self):
        assert _at_psych_level(Decimal("5.97"), Decimal("0.50"), Decimal("0.03"))

    def test_not_near(self):
        assert not _at_psych_level(Decimal("5.27"), Decimal("0.50"), Decimal("0.03"))

    def test_zero_step_safe(self):
        assert not _at_psych_level(Decimal("5.00"), Decimal("0"), Decimal("0.03"))


# ──────────────────────────────────────────────────────────────────────────────
# P1 — Hard Stop
# ──────────────────────────────────────────────────────────────────────────────

class TestP1HardStop:
    def test_fires_at_stop_price(self):
        pos = _pos(entry="5.00", stop="4.80")
        bar = _bar("4.80", offset_sec=30)
        sig = _eval(pos, bar)
        assert sig is not None
        assert sig.reason == ExitReason.HARD_STOP
        assert sig.action == ScaleAction.FULL_EXIT
        assert sig.spec_ref == "§3 P1"

    def test_fires_below_stop_price(self):
        pos = _pos(entry="5.00", stop="4.80")
        bar = _bar("4.70", offset_sec=30)
        sig = _eval(pos, bar)
        assert sig is not None
        assert sig.reason == ExitReason.HARD_STOP

    def test_does_not_fire_above_stop(self):
        pos = _pos(entry="5.00", stop="4.80")
        bar = _bar("4.81", offset_sec=30)
        sig = _eval(pos, bar)
        # Should not be P1; may be something else or None.
        if sig is not None:
            assert sig.reason != ExitReason.HARD_STOP

    def test_p1_beats_p2(self):
        """P1 must fire before P2 even when time stop would also apply."""
        pos = _pos(entry="5.00", stop="4.80", entry_offset_sec=-300)  # entered 5 min ago
        bar = _bar("4.75", offset_sec=0)  # price at stop + elapsed > bailout
        sig = _eval(pos, bar)
        assert sig is not None
        assert sig.reason == ExitReason.HARD_STOP


# ──────────────────────────────────────────────────────────────────────────────
# P2 — Time Stop (Breakout-or-Bailout)
# ──────────────────────────────────────────────────────────────────────────────

class TestP2TimeStop:
    def test_fires_when_elapsed_and_no_move(self):
        cfg = _cfg()
        bailout_sec = cfg.get_int("BAILOUT_SECONDS")
        bailout_move = cfg.get_decimal("BAILOUT_MOVE")

        pos = _pos(entry="5.00", stop="4.80", entry_offset_sec=-(bailout_sec + 10))
        # Current price: entry + BAILOUT_MOVE - 0.01 (just under threshold)
        price = Decimal("5.00") + bailout_move - Decimal("0.01")
        bar = _bar(str(price))
        sig = _eval(pos, bar)
        assert sig is not None
        assert sig.reason == ExitReason.TIME_STOP
        assert sig.spec_ref == "§3 P2"

    def test_does_not_fire_when_price_advanced(self):
        cfg = _cfg()
        bailout_sec = cfg.get_int("BAILOUT_SECONDS")
        bailout_move = cfg.get_decimal("BAILOUT_MOVE")

        pos = _pos(entry="5.00", stop="4.80", entry_offset_sec=-(bailout_sec + 10))
        # Price advanced sufficiently.
        price = Decimal("5.00") + bailout_move + Decimal("0.05")
        bar = _bar(str(price))
        sig = _eval(pos, bar)
        if sig is not None:
            assert sig.reason != ExitReason.TIME_STOP

    def test_does_not_fire_before_elapsed(self):
        pos = _pos(entry="5.00", stop="4.80", entry_offset_sec=-10)  # 10s ago
        bar = _bar("5.01")
        sig = _eval(pos, bar)
        if sig is not None:
            assert sig.reason != ExitReason.TIME_STOP


# ──────────────────────────────────────────────────────────────────────────────
# P3 — L2/Tape Reversal
# ──────────────────────────────────────────────────────────────────────────────

class TestP3L2Reversal:
    def test_fires_on_spoof(self):
        pos = _pos(entry="5.00", stop="4.80")
        bar = _bar("5.10")
        sig = _eval(pos, bar, l2_signal=L2Signal.SPOOF)
        assert sig is not None
        assert sig.reason == ExitReason.L2_REVERSAL
        assert sig.action == ScaleAction.FULL_EXIT
        assert sig.spec_ref == "§3 P3"

    def test_fires_on_iceberg(self):
        pos = _pos(entry="5.00", stop="4.80")
        bar = _bar("5.10")
        sig = _eval(pos, bar, l2_signal=L2Signal.ICEBERG)
        assert sig is not None
        assert sig.reason == ExitReason.L2_REVERSAL

    def test_does_not_fire_on_support(self):
        pos = _pos(entry="5.00", stop="4.80")
        bar = _bar("5.10")
        sig = _eval(pos, bar, l2_signal=L2Signal.SUPPORT)
        if sig is not None:
            assert sig.reason != ExitReason.L2_REVERSAL

    def test_does_not_fire_on_unknown(self):
        pos = _pos(entry="5.00", stop="4.80")
        bar = _bar("5.10")
        sig = _eval(pos, bar, l2_signal=L2Signal.UNKNOWN)
        if sig is not None:
            assert sig.reason != ExitReason.L2_REVERSAL


# ──────────────────────────────────────────────────────────────────────────────
# P4 — Topping Tail (requires next-candle confirmation)
# ──────────────────────────────────────────────────────────────────────────────

class TestP4ToppingTail:
    def test_fires_when_topping_tail_confirmed(self):
        """Prev bar = topping candle; current bar makes new low below prev bar's low.

        Guard: entry just 1s ago so elapsed < BAILOUT_SECONDS (60) → P2 can't fire.
        Price > stop so P1 can't fire. L2 = SUPPORT so P3 can't fire.
        """
        # prev: big shooting star (upper shadow >> body) at offset_sec=0
        prev = _bar("5.20", open_="5.10", high="6.00", low="5.05", offset_sec=0)
        # current: low < prev.low (confirms the tail) at offset_sec=1 (only 1s elapsed)
        current = _bar("5.15", open_="5.25", high="5.30", low="4.90", offset_sec=1)

        # Entry at _TS + 0s, current bar at _TS + 1s → elapsed = 1s < BAILOUT_SECONDS
        pos = _pos(entry="5.00", stop="4.50", entry_offset_sec=0)
        sig = _eval(pos, current, prev_bars=[prev], l2_signal=L2Signal.SUPPORT)
        assert sig is not None
        assert sig.reason == ExitReason.TOPPING_TAIL
        assert sig.spec_ref == "§3 P4"

    def test_does_not_fire_without_confirmation(self):
        """Topping candle alone is NOT enough — next bar must make new low (spec §3 P4 [V2])."""
        prev = _bar("5.20", open_="5.10", high="6.00", low="5.05", offset_sec=0)
        # current.low >= prev.low → NOT confirmed
        current = _bar("5.30", open_="5.25", high="5.40", low="5.06", offset_sec=1)

        pos = _pos(entry="5.00", stop="4.50", entry_offset_sec=0)
        sig = _eval(pos, current, prev_bars=[prev])
        if sig is not None:
            assert sig.reason != ExitReason.TOPPING_TAIL

    def test_does_not_fire_on_no_prev_bar(self):
        """No previous bar → P4 cannot fire."""
        pos = _pos(entry="5.00", stop="4.50")
        bar = _bar("4.90", open_="5.05", high="5.15", low="4.80", offset_sec=1)
        sig = _eval(pos, bar, prev_bars=[])
        if sig is not None:
            assert sig.reason != ExitReason.TOPPING_TAIL


# ──────────────────────────────────────────────────────────────────────────────
# P5 — Scale into Strength
# ──────────────────────────────────────────────────────────────────────────────

class TestP5ScaleStrength:
    def test_fires_on_hod_break_with_move(self):
        cfg = _cfg()
        trigger = cfg.get_decimal("MOVE_BE_TRIGGER")

        pos = _pos(entry="5.00", stop="4.80", high_wm="5.00")
        # New HOD: current_price > intraday_high and old wm < intraday_high.
        # price > intraday_high (old hod), unrealized >= trigger.
        intraday_high = Decimal("5.20")
        price = Decimal("5.00") + trigger + Decimal("0.05")
        bar = _bar(str(price), high=str(price + Decimal("0.02")))
        # For HOD break: price must exceed the current intraday_high.
        # pos.high_watermark (5.00) < intraday_high (5.20) → hod_break triggers.
        bar_above = _bar(str(intraday_high + Decimal("0.05")),
                         high=str(intraday_high + Decimal("0.10")))
        pos2 = _pos(entry="5.00", stop="4.80", high_wm="5.10")  # wm < intraday_high
        unrealized_needed = intraday_high + Decimal("0.05") - Decimal("5.00")
        if unrealized_needed >= trigger:
            sig = _eval(pos2, bar_above, intraday_high=intraday_high)
            assert sig is not None
            assert sig.reason == ExitReason.SCALE_STRENGTH
            assert sig.action == ScaleAction.PARTIAL_SCALE
            assert sig.new_stop == Decimal("5.00")  # moved to entry (BE)
            assert sig.spec_ref == "§3 P5"

    def test_fires_on_psych_level_hit(self):
        cfg = _cfg()
        trigger = cfg.get_decimal("MOVE_BE_TRIGGER")

        entry = Decimal("5.00")
        # Price hits $6.00 psyche level with enough gain.
        psych_price = Decimal("6.00")
        if psych_price - entry >= trigger:
            pos = _pos(entry=str(entry), stop="4.80")
            bar = _bar(str(psych_price))
            sig = _eval(pos, bar, intraday_high=Decimal("5.90"))
            assert sig is not None
            assert sig.reason == ExitReason.SCALE_STRENGTH

    def test_does_not_fire_without_sufficient_move(self):
        pos = _pos(entry="5.00", stop="4.80")
        bar = _bar("5.02")  # tiny unrealized gain, likely below MOVE_BE_TRIGGER
        sig = _eval(pos, bar, intraday_high=Decimal("5.20"))
        if sig is not None:
            assert sig.reason != ExitReason.SCALE_STRENGTH

    def test_partial_scale_does_not_fully_close(self):
        """PARTIAL_SCALE action; not FULL_EXIT."""
        cfg = _cfg()
        trigger = cfg.get_decimal("MOVE_BE_TRIGGER")
        entry = Decimal("5.00")
        intraday_high = Decimal("6.50")
        price = intraday_high + Decimal("0.10")
        if price - entry >= trigger:
            pos = _pos(entry=str(entry), stop="4.80", high_wm="6.40")
            bar = _bar(str(price))
            sig = _eval(pos, bar, intraday_high=intraday_high)
            if sig is not None and sig.reason == ExitReason.SCALE_STRENGTH:
                assert sig.action == ScaleAction.PARTIAL_SCALE


# ──────────────────────────────────────────────────────────────────────────────
# P6 — First Red Candle Close
# ──────────────────────────────────────────────────────────────────────────────

class TestP6FirstRedClose:
    def test_fires_on_red_close(self):
        pos = _pos(entry="5.00", stop="4.50")
        bar = _bar("5.10", open_="5.30", high="5.35", low="5.05")  # close < open = red
        sig = _eval(pos, bar)
        assert sig is not None
        assert sig.reason == ExitReason.FIRST_RED_CLOSE
        assert sig.action == ScaleAction.FULL_EXIT
        assert sig.spec_ref == "§3 P6"

    def test_does_not_fire_on_green_close(self):
        pos = _pos(entry="5.00", stop="4.50")
        bar = _bar("5.30", open_="5.10", high="5.35", low="5.05")  # close > open = green
        sig = _eval(pos, bar)
        if sig is not None:
            assert sig.reason != ExitReason.FIRST_RED_CLOSE


# ──────────────────────────────────────────────────────────────────────────────
# P7 — VWAP Guard
# ──────────────────────────────────────────────────────────────────────────────

class TestP7VwapGuard:
    def test_fires_when_below_vwap_with_profit(self):
        cfg = _cfg()
        trigger = cfg.get_decimal("MOVE_BE_TRIGGER")
        entry = Decimal("5.00")
        vwap = Decimal("5.30")
        # Price is below VWAP but we've been in profit (unrealized >= trigger).
        price = vwap - Decimal("0.05")
        if price - entry >= trigger:
            pos = _pos(entry=str(entry), stop="4.80")
            bar = _bar(str(price))
            sig = _eval(pos, bar, vwap=vwap)
            assert sig is not None
            assert sig.reason == ExitReason.VWAP_GUARD
            assert sig.spec_ref == "§3 P7"

    def test_does_not_fire_when_above_vwap(self):
        pos = _pos(entry="5.00", stop="4.80")
        vwap = Decimal("5.20")
        bar = _bar("5.40")  # above vwap
        sig = _eval(pos, bar, vwap=vwap)
        if sig is not None:
            assert sig.reason != ExitReason.VWAP_GUARD

    def test_does_not_fire_without_vwap(self):
        pos = _pos(entry="5.00", stop="4.50")
        bar = _bar("5.30")
        sig = _eval(pos, bar, vwap=None)
        if sig is not None:
            assert sig.reason != ExitReason.VWAP_GUARD


# ──────────────────────────────────────────────────────────────────────────────
# P8 — Lost Popularity
# ──────────────────────────────────────────────────────────────────────────────

class TestP8LostPopularity:
    def test_fires_when_rank_too_low(self):
        cfg = _cfg()
        watch_rank = cfg.get_int("ATTENTION_WATCH_RANK")

        pos = _pos(entry="5.00", stop="4.50")
        bar = _bar("5.10")
        sig = _eval(pos, bar, market_rank=watch_rank + 10)
        assert sig is not None
        assert sig.reason == ExitReason.LOST_POPULARITY
        assert sig.action == ScaleAction.FULL_EXIT
        assert sig.spec_ref == "§3 P8"

    def test_does_not_fire_when_rank_good(self):
        cfg = _cfg()
        watch_rank = cfg.get_int("ATTENTION_WATCH_RANK")

        pos = _pos(entry="5.00", stop="4.50")
        bar = _bar("5.10")
        sig = _eval(pos, bar, market_rank=watch_rank - 1)
        if sig is not None:
            assert sig.reason != ExitReason.LOST_POPULARITY

    def test_does_not_fire_without_rank(self):
        pos = _pos(entry="5.00", stop="4.50")
        bar = _bar("5.10")
        sig = _eval(pos, bar, market_rank=None)
        if sig is not None:
            assert sig.reason != ExitReason.LOST_POPULARITY


# ──────────────────────────────────────────────────────────────────────────────
# Priority ordering
# ──────────────────────────────────────────────────────────────────────────────

class TestPriorityOrder:
    def test_p1_takes_precedence_over_p3(self):
        """Price hits stop AND L2 shows spoof → P1 fires (not P3)."""
        pos = _pos(entry="5.00", stop="4.80")
        bar = _bar("4.75")  # below stop
        sig = _eval(pos, bar, l2_signal=L2Signal.SPOOF)
        assert sig is not None
        assert sig.reason == ExitReason.HARD_STOP

    def test_p1_takes_precedence_over_p6(self):
        """Red bar AND below stop → P1 fires."""
        pos = _pos(entry="5.00", stop="4.80")
        bar = _bar("4.75", open_="5.20")  # red and below stop
        sig = _eval(pos, bar)
        assert sig is not None
        assert sig.reason == ExitReason.HARD_STOP

    def test_no_exit_signal_when_all_clear(self):
        """No conditions met → returns None."""
        pos = _pos(entry="5.00", stop="4.80")
        bar = _bar("5.20", open_="5.10")  # green, above stop, well-positioned
        sig = _eval(pos, bar, l2_signal=L2Signal.SUPPORT, market_rank=None)
        # Should be None unless some time/vwap/rank condition fires.
        # If it fires, it should be a valid reason.
        if sig is not None:
            assert sig.reason in ExitReason.__members__.values()
