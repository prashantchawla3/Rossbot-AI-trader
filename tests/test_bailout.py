"""Tests for breakout-or-bailout (core/execution/bailout.py).

Acceptance criteria (spec §3 P2 / §13.5 / Phase 10):
  - Bailout fires when stalled (no move, no higher highs)
  - Bailout does NOT fire on slow-but-valid mover (higher highs with rising vol)
  - Bailout does NOT fire before BAILOUT_SECONDS
  - Bailout does NOT fire when unrealized >= BAILOUT_MOVE

spec §3 P2 / §13.5 / Phase 10.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from adapters.base import BarTick
from core.config import ConfigService, DEFAULTS
from core.execution.bailout import has_higher_high_on_rising_volume, is_bailout_condition
from core.money import Money


def _cfg(**overrides: str) -> ConfigService:
    m = {d.key: (d.value, d.value_type) for d in DEFAULTS}
    for k, v in overrides.items():
        m[k] = (v, m[k][1])
    return ConfigService(m)


def _bar(
    ts: datetime,
    high: str,
    volume: int,
    open: str = "10.00",
    low: str = "9.90",
    close: str = "10.10",
) -> BarTick:
    return BarTick(
        symbol="TEST",
        ts=ts,
        timeframe="1m",
        open=Money(open),
        high=Money(high),
        low=Money(low),
        close=Money(close),
        volume=volume,
    )


_T0 = datetime(2026, 1, 2, 9, 30, tzinfo=timezone.utc)
_ENTRY = Decimal("10.00")


def _dt(seconds: int) -> datetime:
    from datetime import timedelta
    return _T0 + timedelta(seconds=seconds)


class TestHasHigherHighOnRisingVolume:
    def test_empty_bars_returns_false(self):
        assert has_higher_high_on_rising_volume([], _ENTRY) is False

    def test_single_bar_returns_false(self):
        bars = [_bar(_T0, high="10.05", volume=1000)]
        assert has_higher_high_on_rising_volume(bars, _ENTRY) is False

    def test_higher_high_with_rising_volume_returns_true(self):
        bars = [
            _bar(_T0, high="10.05", volume=1000),
            _bar(_dt(60), high="10.10", volume=1200),  # new high + rising vol
        ]
        assert has_higher_high_on_rising_volume(bars, _ENTRY) is True

    def test_higher_high_with_equal_volume_returns_true(self):
        bars = [
            _bar(_T0, high="10.05", volume=1000),
            _bar(_dt(60), high="10.10", volume=1000),  # new high + equal vol
        ]
        assert has_higher_high_on_rising_volume(bars, _ENTRY) is True

    def test_higher_high_below_entry_does_not_count(self):
        # curr.high > prev.high but still below entry → no valid momentum
        bars = [
            _bar(_T0, high="9.95", volume=1000),
            _bar(_dt(60), high="9.98", volume=1200),
        ]
        assert has_higher_high_on_rising_volume(bars, _ENTRY) is False

    def test_higher_high_with_falling_volume_returns_false(self):
        bars = [
            _bar(_T0, high="10.05", volume=2000),
            _bar(_dt(60), high="10.10", volume=1500),  # new high BUT falling vol
        ]
        assert has_higher_high_on_rising_volume(bars, _ENTRY) is False

    def test_no_new_highs_returns_false(self):
        bars = [
            _bar(_T0, high="10.20", volume=1000),
            _bar(_dt(60), high="10.15", volume=1200),  # lower high
        ]
        assert has_higher_high_on_rising_volume(bars, _ENTRY) is False

    def test_detects_momentum_on_any_bar_pair(self):
        bars = [
            _bar(_T0, high="10.05", volume=2000),
            _bar(_dt(60), high="10.03", volume=1500),   # lower, falling
            _bar(_dt(120), high="10.20", volume=2500),  # new high + rising
        ]
        assert has_higher_high_on_rising_volume(bars, _ENTRY) is True


class TestIsBailoutCondition:

    def test_not_fired_before_window(self):
        # 30 s elapsed < BAILOUT_SECONDS=60
        assert not is_bailout_condition(
            entry_ts=_T0,
            entry_price=_ENTRY,
            current_price=Decimal("9.95"),
            bars_since_entry=[],
            now_ts=_dt(30),
            cfg=_cfg(),
        )

    def test_not_fired_when_advanced_enough(self):
        # Unrealized >= BAILOUT_MOVE=0.10
        assert not is_bailout_condition(
            entry_ts=_T0,
            entry_price=_ENTRY,
            current_price=Decimal("10.10"),
            bars_since_entry=[],
            now_ts=_dt(90),
            cfg=_cfg(),
        )

    def test_fired_when_stalled_no_momentum(self):
        # 90s elapsed, up only 0.05 (< 0.10), no higher highs
        bars = [
            _bar(_T0, high="10.05", volume=1000),
            _bar(_dt(60), high="10.04", volume=900),  # lower high, falling vol
        ]
        assert is_bailout_condition(
            entry_ts=_T0,
            entry_price=_ENTRY,
            current_price=Decimal("10.05"),
            bars_since_entry=bars,
            now_ts=_dt(90),
            cfg=_cfg(),
        )

    def test_not_fired_when_momentum_present(self):
        """Slow-but-valid mover: makes new highs with rising volume → do NOT bail."""
        bars = [
            _bar(_T0, high="10.05", volume=1000),
            _bar(_dt(60), high="10.12", volume=1500),  # new high + rising vol
        ]
        assert not is_bailout_condition(
            entry_ts=_T0,
            entry_price=_ENTRY,
            current_price=Decimal("10.05"),  # current price still low
            bars_since_entry=bars,
            now_ts=_dt(90),
            cfg=_cfg(),
        )

    def test_exactly_at_window_boundary_fires(self):
        # elapsed == BAILOUT_SECONDS → window expired
        assert is_bailout_condition(
            entry_ts=_T0,
            entry_price=_ENTRY,
            current_price=Decimal("10.05"),
            bars_since_entry=[],
            now_ts=_dt(60),
            cfg=_cfg(),
        )

    def test_configurable_window(self):
        # Raise BAILOUT_SECONDS to 120; 90s should not fire
        assert not is_bailout_condition(
            entry_ts=_T0,
            entry_price=_ENTRY,
            current_price=Decimal("9.95"),
            bars_since_entry=[],
            now_ts=_dt(90),
            cfg=_cfg(BAILOUT_SECONDS="120"),
        )

    def test_configurable_move(self):
        # Raise BAILOUT_MOVE to 0.50; unrealized=0.10 not enough
        assert is_bailout_condition(
            entry_ts=_T0,
            entry_price=_ENTRY,
            current_price=Decimal("10.10"),  # +0.10 < new threshold 0.50
            bars_since_entry=[],
            now_ts=_dt(90),
            cfg=_cfg(BAILOUT_MOVE="0.50"),
        )
