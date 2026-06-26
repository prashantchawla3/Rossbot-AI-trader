"""Tests for core.risk.monitors — all five pure monitor functions.

spec §3 P1 (mental stop), §5 (give-back / daily loss), §7 (time), U3, U13.
"""

from __future__ import annotations

from datetime import time
from decimal import Decimal

import pytest

from core.config import ConfigService
from core.risk.models import GiveBackLevel
from core.risk.monitors import (
    evaluate_give_back,
    is_daily_loss_limit,
    is_mental_stop_breached,
    is_past_hard_stop_time,
    should_flatten_eod,
)


def _cfg() -> ConfigService:
    return ConfigService.from_defaults()


# ── U13: Mental stop (spec §3 P1 / U13) ──────────────────────────────────────

class TestMentalStop:
    def test_price_above_stop_not_breached(self) -> None:
        assert is_mental_stop_breached(Decimal("5.01"), Decimal("4.50")) is False

    def test_price_exactly_at_stop_breached(self) -> None:
        # <= triggers (at the stop price IS a breach)
        assert is_mental_stop_breached(Decimal("4.50"), Decimal("4.50")) is True

    def test_price_below_stop_breached(self) -> None:
        assert is_mental_stop_breached(Decimal("4.40"), Decimal("4.50")) is True

    def test_price_far_above_stop(self) -> None:
        assert is_mental_stop_breached(Decimal("10.00"), Decimal("4.50")) is False

    def test_tiny_difference_not_breached(self) -> None:
        assert is_mental_stop_breached(Decimal("4.51"), Decimal("4.50")) is False


# ── C3: Give-back stop (spec §5) ─────────────────────────────────────────────

class TestEvaluateGiveBack:
    def test_no_peak_returns_none(self) -> None:
        # peak=0 → no give-back possible
        assert evaluate_give_back(Decimal("0"), Decimal("0"), _cfg()) == GiveBackLevel.NONE

    def test_negative_peak_returns_none(self) -> None:
        assert evaluate_give_back(Decimal("-100"), Decimal("-200"), _cfg()) == GiveBackLevel.NONE

    def test_zero_give_back_is_none(self) -> None:
        # realized=peak → 0% give-back
        assert evaluate_give_back(Decimal("1000"), Decimal("1000"), _cfg()) == GiveBackLevel.NONE

    def test_below_warn_threshold_is_none(self) -> None:
        # peak=1000, realized=810 → give_back=(1000-810)/1000=0.19 < 0.25 (GIVE_BACK_WARN)
        assert evaluate_give_back(Decimal("810"), Decimal("1000"), _cfg()) == GiveBackLevel.NONE

    def test_at_warn_threshold_is_warn(self) -> None:
        # peak=1000, realized=750 → give_back=0.25 >= GIVE_BACK_WARN=0.25
        assert evaluate_give_back(Decimal("750"), Decimal("1000"), _cfg()) == GiveBackLevel.WARN

    def test_above_warn_below_halt_is_warn(self) -> None:
        # peak=1000, realized=600 → give_back=0.40; 0.25<=0.40<0.50
        assert evaluate_give_back(Decimal("600"), Decimal("1000"), _cfg()) == GiveBackLevel.WARN

    def test_at_halt_threshold_is_halt(self) -> None:
        # peak=1000, realized=500 → give_back=0.50 = GIVE_BACK_HARD
        assert evaluate_give_back(Decimal("500"), Decimal("1000"), _cfg()) == GiveBackLevel.HALT

    def test_above_halt_threshold_is_halt(self) -> None:
        # peak=1000, realized=300 → give_back=0.70 > 0.50
        assert evaluate_give_back(Decimal("300"), Decimal("1000"), _cfg()) == GiveBackLevel.HALT

    def test_negative_realized_with_positive_peak_is_halt(self) -> None:
        # peak=1000, realized=-200 → give_back=(1000-(-200))/1000=1.20 > 0.50
        assert evaluate_give_back(Decimal("-200"), Decimal("1000"), _cfg()) == GiveBackLevel.HALT


# ── U4: Daily loss limit (spec §5 C2) ────────────────────────────────────────

class TestDailyLossLimit:
    def test_zero_loss_not_triggered(self) -> None:
        # realized=0; effective_limit=min(2500, 1000, 5000)=1000; 0 > -1000 → False
        assert is_daily_loss_limit(Decimal("0"), Decimal("25000"), Decimal("1000"), _cfg()) is False

    def test_small_loss_not_triggered(self) -> None:
        # realized=-500; -500 > -1000 → False
        assert is_daily_loss_limit(Decimal("-500"), Decimal("25000"), Decimal("1000"), _cfg()) is False

    def test_exactly_at_limit_triggered(self) -> None:
        # realized=-1000; -1000 <= -1000 → True
        assert is_daily_loss_limit(Decimal("-1000"), Decimal("25000"), Decimal("1000"), _cfg()) is True

    def test_beyond_limit_triggered(self) -> None:
        # realized=-2000; effective=1000; -2000 <= -1000 → True
        assert is_daily_loss_limit(Decimal("-2000"), Decimal("25000"), Decimal("1000"), _cfg()) is True

    def test_pct_component_is_binding(self) -> None:
        # Small equity: equity=500, pct=0.10 → 50; avg_win=10000, lockout=5000
        # effective = min(50, 10000, 5000) = 50
        assert is_daily_loss_limit(
            Decimal("-51"), Decimal("500"), Decimal("10000"), _cfg()
        ) is True

    def test_broker_lockout_is_binding(self) -> None:
        # Large equity, high avg_win: equity=200000, pct → 20000; avg_win=100000; lockout=5000
        # effective = min(20000, 100000, 5000) = 5000
        assert is_daily_loss_limit(
            Decimal("-5001"), Decimal("200000"), Decimal("100000"), _cfg()
        ) is True

    def test_broker_lockout_not_reached(self) -> None:
        # same setup but loss < lockout
        assert is_daily_loss_limit(
            Decimal("-4999"), Decimal("200000"), Decimal("100000"), _cfg()
        ) is False


# ── U3: EOD flatten (spec §11 U3) ────────────────────────────────────────────

class TestShouldFlattenEod:
    def test_before_flatten_time_false(self) -> None:
        # EOD_FLATTEN_TIME default = 15:55; 15:54 < 15:55 → False
        assert should_flatten_eod(time(15, 54), _cfg()) is False

    def test_exactly_at_flatten_time_true(self) -> None:
        # 15:55 >= 15:55 → True
        assert should_flatten_eod(time(15, 55), _cfg()) is True

    def test_after_flatten_time_true(self) -> None:
        # 16:00 >= 15:55 → True
        assert should_flatten_eod(time(16, 0), _cfg()) is True

    def test_morning_false(self) -> None:
        assert should_flatten_eod(time(9, 30), _cfg()) is False


# ── §7: Hard stop time ────────────────────────────────────────────────────────

class TestIsPassHardStopTime:
    def test_before_hard_stop_false(self) -> None:
        # HARD_STOP_TIME default = 11:00; 10:59 < 11:00 → False
        assert is_past_hard_stop_time(time(10, 59), _cfg()) is False

    def test_exactly_at_hard_stop_false(self) -> None:
        # Strictly ">", not ">=" — 11:00 is NOT past
        assert is_past_hard_stop_time(time(11, 0), _cfg()) is False

    def test_one_minute_past_hard_stop_true(self) -> None:
        assert is_past_hard_stop_time(time(11, 1), _cfg()) is True

    def test_well_past_hard_stop_true(self) -> None:
        assert is_past_hard_stop_time(time(14, 0), _cfg()) is True
