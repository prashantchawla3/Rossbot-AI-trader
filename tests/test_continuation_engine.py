"""Tests for core.continuation — multi-day continuation engine. spec §12B / §13.10.

Acceptance criteria:
  - Day-1 < 100% → not eligible.
  - Day-1 ≥ 100% but closed poorly (< 70% of high) → not eligible.
  - RVOL < 25% of prior day volume → DoneReason.RVOL_FADED.
  - Retrace > 50% of Day-1 move → DoneReason.RETRACE_EXCEEDED.
  - MACD histogram negative → DoneReason.MACD_NEGATIVE_CROSS.
  - Price below VWAP → DoneReason.VWAP_BROKEN.
  - All done-conditions clear → DoneReason.NOT_DONE.
  - get_day2_settings returns 5-min timeframe + 50% size.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from core.config import ConfigService
from core.continuation.engine import (
    check_continuation_done,
    evaluate_day2_eligibility,
    get_day2_settings,
)
from core.continuation.models import ContinuationContext, DoneReason


# ── Helpers ───────────────────────────────────────────────────────────────────


def _cfg() -> ConfigService:
    return ConfigService.from_defaults()


def _ctx(
    day1_open: str = "5.00",
    day1_high: str = "12.00",  # +140% move
    day1_close: str = "10.00",  # held 83% of high
    prev_volume: int = 10_000_000,
    today_volume: int = 4_000_000,
    today_low: str = "9.50",
    current_price: str = "10.20",
    current_vwap: str = "9.80",
    macd_histogram: str = "0.05",
) -> ContinuationContext:
    return ContinuationContext(
        symbol="MLGO",
        day1_open=Decimal(day1_open),
        day1_high=Decimal(day1_high),
        day1_close=Decimal(day1_close),
        prev_day_volume=prev_volume,
        today_volume=today_volume,
        today_low=Decimal(today_low),
        current_price=Decimal(current_price),
        current_vwap=Decimal(current_vwap),
        macd_histogram=Decimal(macd_histogram),
    )


# ── Eligibility ───────────────────────────────────────────────────────────────


class TestDay2Eligibility:
    def test_eligible_when_day1_100pct_and_held(self) -> None:
        result = evaluate_day2_eligibility(_ctx(), _cfg())
        assert result.eligible is True
        assert result.day1_move_pct >= Decimal("100")

    def test_not_eligible_when_day1_move_below_100pct(self) -> None:
        # Day-1: $5 → $9.50 = +90%, below threshold
        result = evaluate_day2_eligibility(_ctx(day1_high="9.50"), _cfg())
        assert result.eligible is False
        assert "90" in result.reason or "move" in result.reason.lower()

    def test_not_eligible_when_close_below_hold_pct(self) -> None:
        # Day-1: $5 → $12, but closed at $7.50 = 62.5% of high (< 70%)
        result = evaluate_day2_eligibility(_ctx(day1_close="7.50"), _cfg())
        assert result.eligible is False
        assert "held" in result.reason.lower() or "close" in result.reason.lower()

    def test_not_eligible_when_day1_open_zero(self) -> None:
        result = evaluate_day2_eligibility(_ctx(day1_open="0"), _cfg())
        assert result.eligible is False

    def test_exactly_at_100pct_eligible(self) -> None:
        # Day-1: $5 → $10 = +100%, close at $8.00 = 80% of high
        result = evaluate_day2_eligibility(
            _ctx(day1_open="5.00", day1_high="10.00", day1_close="8.00"), _cfg()
        )
        assert result.eligible is True


# ── Done-conditions ───────────────────────────────────────────────────────────


class TestContinuationDoneConditions:
    def test_all_clear_not_done(self) -> None:
        result = check_continuation_done(_ctx(), _cfg())
        assert result == DoneReason.NOT_DONE

    def test_rvol_faded(self) -> None:
        """RVOL < 25% of prev_day_volume → RVOL_FADED."""
        ctx = _ctx(prev_volume=10_000_000, today_volume=2_000_000)  # 20% of prior
        result = check_continuation_done(ctx, _cfg())
        assert result == DoneReason.RVOL_FADED

    def test_rvol_exactly_at_threshold_not_done(self) -> None:
        """RVOL exactly 25% → NOT_DONE (boundary: strict <)."""
        ctx = _ctx(prev_volume=10_000_000, today_volume=2_500_000)
        result = check_continuation_done(ctx, _cfg())
        assert result != DoneReason.RVOL_FADED

    def test_retrace_exceeded(self) -> None:
        """Retrace > 50% of Day-1 move ($5→$12 = $7 move; low at $8.40 = $3.60 retrace = 51%) → DONE."""
        ctx = _ctx(
            day1_open="5.00", day1_high="12.00",
            today_low="8.40",   # retrace = 12-8.40 = 3.60 / 7.00 move = 51.4%
        )
        result = check_continuation_done(ctx, _cfg())
        assert result == DoneReason.RETRACE_EXCEEDED

    def test_retrace_at_50pct_not_done(self) -> None:
        """Retrace exactly 50% → NOT_DONE (strict >)."""
        # $5→$12 move = $7; 50% = $3.50; low = $12 - $3.50 = $8.50
        ctx = _ctx(day1_open="5.00", day1_high="12.00", today_low="8.50")
        result = check_continuation_done(ctx, _cfg())
        assert result != DoneReason.RETRACE_EXCEEDED

    def test_macd_negative_cross(self) -> None:
        """MACD histogram < 0 → MACD_NEGATIVE_CROSS."""
        ctx = _ctx(macd_histogram="-0.01")
        result = check_continuation_done(ctx, _cfg())
        assert result == DoneReason.MACD_NEGATIVE_CROSS

    def test_macd_zero_not_done(self) -> None:
        """MACD = 0 → not a negative cross."""
        ctx = _ctx(macd_histogram="0.00")
        result = check_continuation_done(ctx, _cfg())
        assert result != DoneReason.MACD_NEGATIVE_CROSS

    def test_vwap_broken(self) -> None:
        """Price < VWAP → VWAP_BROKEN."""
        ctx = _ctx(current_price="9.00", current_vwap="9.80")
        result = check_continuation_done(ctx, _cfg())
        assert result == DoneReason.VWAP_BROKEN

    def test_price_above_vwap_not_broken(self) -> None:
        ctx = _ctx(current_price="10.20", current_vwap="9.80")
        result = check_continuation_done(ctx, _cfg())
        assert result != DoneReason.VWAP_BROKEN

    def test_done_priority_rvol_first(self) -> None:
        """When multiple done-conditions fire, RVOL_FADED checked first."""
        ctx = _ctx(
            prev_volume=10_000_000, today_volume=100_000,  # RVOL_FADED
            macd_histogram="-0.10",                         # also MACD cross
        )
        result = check_continuation_done(ctx, _cfg())
        assert result == DoneReason.RVOL_FADED


# ── Day-2 settings ────────────────────────────────────────────────────────────


class TestDay2Settings:
    def test_default_settings(self) -> None:
        settings = get_day2_settings(_cfg())
        assert settings.timeframe == "5m"
        assert settings.size_fraction == Decimal("0.50")
        assert settings.avoid_gap_and_go is True
        assert settings.avoid_aggressive_hod is True
