"""Tests for market-state feature computation (adapters/market_state/features.py).

spec §8 / §13.9 / Phase 9.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from adapters.market_state.features import compute_features
from adapters.market_state.models import DaySnapshot, MarketStateFeatures


def _snap(
    *,
    day: date = date(2026, 1, 2),
    count_gt100pct: int = 0,
    count_tiny_float: int = 0,
    gapper_count: int = 0,
    gapper_followthrough_count: int = 0,
    winner_count: int = 0,
    winner_gain_sum: str = "0",
    loser_count: int = 0,
    loser_loss_sum: str = "0",
    breakout_count: int = 0,
    breakout_success_count: int = 0,
) -> DaySnapshot:
    return DaySnapshot(
        day=day,
        count_gt100pct=count_gt100pct,
        count_tiny_float=count_tiny_float,
        gapper_count=gapper_count,
        gapper_followthrough_count=gapper_followthrough_count,
        winner_count=winner_count,
        winner_gain_sum=Decimal(winner_gain_sum),
        loser_count=loser_count,
        loser_loss_sum=Decimal(loser_loss_sum),
        breakout_count=breakout_count,
        breakout_success_count=breakout_success_count,
    )


class TestComputeFeatures:
    def test_empty_window_returns_zero_days(self):
        feat = compute_features([])
        assert feat.days_in_window == 0

    def test_empty_window_all_none(self):
        feat = compute_features([])
        assert feat.gapper_follow_through is None
        assert feat.breakout_success_rate is None
        assert feat.avg_green_size is None
        assert feat.avg_red_size is None
        assert feat.count_gt100pct == 0

    def test_single_day_basic(self):
        snap = _snap(count_gt100pct=3, count_tiny_float=2)
        feat = compute_features([snap])
        assert feat.days_in_window == 1
        assert feat.count_gt100pct == 3
        assert feat.count_tiny_float == 2

    def test_gapper_follow_through_rate(self):
        snap = _snap(gapper_count=10, gapper_followthrough_count=7)
        feat = compute_features([snap])
        assert feat.gapper_follow_through == Decimal("7") / Decimal("10")

    def test_gapper_follow_through_none_when_no_gappers(self):
        snap = _snap(gapper_count=0, gapper_followthrough_count=0)
        feat = compute_features([snap])
        assert feat.gapper_follow_through is None

    def test_avg_green_size(self):
        snap = _snap(winner_count=4, winner_gain_sum="1.20")
        feat = compute_features([snap])
        assert feat.avg_green_size == Decimal("1.20") / Decimal("4")

    def test_avg_green_size_none_when_no_winners(self):
        snap = _snap(winner_count=0)
        feat = compute_features([snap])
        assert feat.avg_green_size is None

    def test_avg_red_size(self):
        snap = _snap(loser_count=2, loser_loss_sum="0.16")
        feat = compute_features([snap])
        assert feat.avg_red_size == Decimal("0.16") / Decimal("2")

    def test_breakout_success_rate(self):
        snap = _snap(breakout_count=5, breakout_success_count=3)
        feat = compute_features([snap])
        assert feat.breakout_success_rate == Decimal("3") / Decimal("5")

    def test_breakout_success_rate_none_when_no_entries(self):
        snap = _snap(breakout_count=0)
        feat = compute_features([snap])
        assert feat.breakout_success_rate is None

    def test_aggregates_across_multiple_days(self):
        snaps = [
            _snap(day=date(2026, 1, 1), count_gt100pct=2, gapper_count=5, gapper_followthrough_count=3),
            _snap(day=date(2026, 1, 2), count_gt100pct=1, gapper_count=3, gapper_followthrough_count=2),
        ]
        feat = compute_features(snaps)
        assert feat.days_in_window == 2
        assert feat.count_gt100pct == 3
        # total ft: 5/8
        assert feat.gapper_follow_through == Decimal("5") / Decimal("8")

    def test_winner_gain_summed_across_days(self):
        snaps = [
            _snap(winner_count=2, winner_gain_sum="0.50"),
            _snap(winner_count=2, winner_gain_sum="0.70"),
        ]
        feat = compute_features(snaps)
        # total gain: 1.20 / 4 = 0.30
        assert feat.avg_green_size == Decimal("1.20") / Decimal("4")
