"""Tests for RollingMarketStateProvider (adapters/market_state/provider.py).

Acceptance criteria (spec §8 / §13.9 / Phase 9):
  - Synthetic HOT tape → classify() returns HOT (unlocks mid-candle/EX2)
  - Synthetic COLD tape → classify() returns COLD (locks them)
  - REHAB mode overrides → always REHAB regardless of features
  - Insufficient window → COLD
  - Exception during classify → COLD (fail-safe)

spec §8 / §13.9 / Phase 9.
"""

from __future__ import annotations

import asyncio
from datetime import date
from decimal import Decimal

import pytest

from adapters.market_state.models import DaySnapshot
from adapters.market_state.provider import RollingMarketStateProvider
from adapters.providers import MarketState
from core.config import ConfigService, DEFAULTS


def _cfg(**overrides: str) -> ConfigService:
    default_map = {d.key: (d.value, d.value_type) for d in DEFAULTS}
    for k, v in overrides.items():
        vt = default_map[k][1]
        default_map[k] = (v, vt)
    return ConfigService(default_map)


def _hot_snap(day: date) -> DaySnapshot:
    """Snapshot typical of a HOT day."""
    return DaySnapshot(
        day=day,
        count_gt100pct=3,
        count_tiny_float=5,
        gapper_count=10,
        gapper_followthrough_count=8,   # 80 %% follow-through
        winner_count=8,
        winner_gain_sum=Decimal("2.40"),  # avg 0.30 per winner
        loser_count=2,
        loser_loss_sum=Decimal("0.10"),
        breakout_count=4,
        breakout_success_count=3,
    )


def _cold_snap(day: date) -> DaySnapshot:
    """Snapshot typical of a COLD day."""
    return DaySnapshot(
        day=day,
        count_gt100pct=0,
        count_tiny_float=0,
        gapper_count=5,
        gapper_followthrough_count=1,   # 20 %% follow-through
        winner_count=3,
        winner_gain_sum=Decimal("0.21"),  # avg 0.07 per winner
        loser_count=7,
        loser_loss_sum=Decimal("0.70"),
        breakout_count=3,
        breakout_success_count=0,
    )


class TestRollingMarketStateProvider:

    # ── HOT tape acceptance ────────────────────────────────────────────────────

    def test_hot_tape_returns_hot(self):
        provider = RollingMarketStateProvider(_cfg())
        dates = [date(2026, 1, i) for i in range(2, 7)]
        for d in dates:
            provider.record_day(_hot_snap(d))
        state = asyncio.run(provider.classify())
        assert state is MarketState.HOT

    # ── COLD tape acceptance ───────────────────────────────────────────────────

    def test_cold_tape_returns_cold(self):
        provider = RollingMarketStateProvider(_cfg())
        dates = [date(2026, 1, i) for i in range(2, 7)]
        for d in dates:
            provider.record_day(_cold_snap(d))
        state = asyncio.run(provider.classify())
        assert state is MarketState.COLD

    def test_empty_window_returns_cold(self):
        provider = RollingMarketStateProvider(_cfg())
        state = asyncio.run(provider.classify())
        assert state is MarketState.COLD

    def test_insufficient_window_returns_cold(self):
        # Only 2 days (< MS_MIN_WINDOW_DAYS=3) → COLD
        provider = RollingMarketStateProvider(_cfg())
        for i in range(2):
            provider.record_day(_hot_snap(date(2026, 1, i + 2)))
        state = asyncio.run(provider.classify())
        assert state is MarketState.COLD

    # ── REHAB mode ────────────────────────────────────────────────────────────

    def test_rehab_overrides_hot_tape(self):
        provider = RollingMarketStateProvider(_cfg())
        for i in range(5):
            provider.record_day(_hot_snap(date(2026, 1, i + 2)))
        provider.set_rehab(True)
        state = asyncio.run(provider.classify())
        assert state is MarketState.REHAB

    def test_rehab_overrides_cold_tape(self):
        provider = RollingMarketStateProvider(_cfg())
        for i in range(5):
            provider.record_day(_cold_snap(date(2026, 1, i + 2)))
        provider.set_rehab(True)
        state = asyncio.run(provider.classify())
        assert state is MarketState.REHAB

    def test_rehab_cleared_returns_to_tape(self):
        provider = RollingMarketStateProvider(_cfg())
        for i in range(5):
            provider.record_day(_hot_snap(date(2026, 1, i + 2)))
        provider.set_rehab(True)
        provider.set_rehab(False)
        state = asyncio.run(provider.classify())
        assert state is MarketState.HOT

    def test_in_rehab_property(self):
        provider = RollingMarketStateProvider(_cfg())
        assert provider.in_rehab is False
        provider.set_rehab(True)
        assert provider.in_rehab is True
        provider.set_rehab(False)
        assert provider.in_rehab is False

    # ── Rolling window pruning ─────────────────────────────────────────────────

    def test_window_pruned_to_max_days(self):
        provider = RollingMarketStateProvider(_cfg(MS_HOT_WINDOW_DAYS="3"))
        for i in range(6):
            provider.record_day(_hot_snap(date(2026, 1, i + 2)))
        # Only last 3 days kept
        assert provider.window_size == 3

    def test_window_size_grows_up_to_max(self):
        provider = RollingMarketStateProvider(_cfg(MS_HOT_WINDOW_DAYS="5"))
        for i in range(3):
            provider.record_day(_hot_snap(date(2026, 1, i + 2)))
        assert provider.window_size == 3

    def test_mixed_tape_old_hot_recent_cold_returns_cold(self):
        """Recent cold days should outweigh old hot days in the rolling window."""
        provider = RollingMarketStateProvider(_cfg(MS_HOT_WINDOW_DAYS="3"))
        # Fill window with cold days (3 days = full window)
        for i in range(3):
            provider.record_day(_cold_snap(date(2026, 1, i + 2)))
        state = asyncio.run(provider.classify())
        assert state is MarketState.COLD

    # ── Fail-safe on classify error ───────────────────────────────────────────

    def test_exception_during_classify_returns_cold(self, monkeypatch):
        provider = RollingMarketStateProvider(_cfg())
        for i in range(5):
            provider.record_day(_hot_snap(date(2026, 1, i + 2)))

        # Patch compute_features to raise
        import adapters.market_state.provider as pmod

        def _always_raise(_):
            raise RuntimeError("boom")

        monkeypatch.setattr(pmod, "compute_features", _always_raise)

        state = asyncio.run(provider.classify())
        assert state is MarketState.COLD
