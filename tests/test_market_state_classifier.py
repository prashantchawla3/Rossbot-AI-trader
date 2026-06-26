"""Tests for the market-state classifier (adapters/market_state/classifier.py).

Acceptance criteria (spec §8 / §13.9):
  - Synthetic HOT tape → HOT state (unlocks mid-candle / EX2)
  - Synthetic COLD tape → COLD state (locks them)
  - Uncertain / insufficient data → COLD (bias §13.9)

spec §8 / §13.9 / Phase 9.
"""

from __future__ import annotations

from decimal import Decimal

from adapters.market_state.classifier import classify_market_state
from adapters.market_state.models import MarketStateFeatures
from adapters.providers import MarketState
from core.config import ConfigService, DEFAULTS, ValueType


def _cfg(**overrides: str) -> ConfigService:
    default_map = {d.key: (d.value, d.value_type) for d in DEFAULTS}
    for k, v in overrides.items():
        vt = default_map[k][1]
        default_map[k] = (v, vt)
    return ConfigService(default_map)


def _feat(
    *,
    days: int = 5,
    gft: str | None = None,
    avg_green: str | None = None,
    count_gt100: int = 0,
) -> MarketStateFeatures:
    return MarketStateFeatures(
        days_in_window=days,
        gapper_follow_through=Decimal(gft) if gft else None,
        avg_green_size=Decimal(avg_green) if avg_green else None,
        count_gt100pct=count_gt100,
    )


class TestClassifyMarketState:
    # ── HOT acceptance ────────────────────────────────────────────────────────

    def test_hot_all_signals_present(self):
        feat = _feat(days=5, gft="0.70", avg_green="0.30", count_gt100=3)
        assert classify_market_state(feat, _cfg()) is MarketState.HOT

    def test_hot_exactly_at_thresholds(self):
        # Exactly at boundaries: gft=0.60, avg_green=0.25, count=2
        feat = _feat(days=3, gft="0.60", avg_green="0.25", count_gt100=2)
        assert classify_market_state(feat, _cfg()) is MarketState.HOT

    # ── COLD acceptance ───────────────────────────────────────────────────────

    def test_cold_insufficient_window(self):
        feat = _feat(days=2, gft="0.70", avg_green="0.30", count_gt100=3)
        assert classify_market_state(feat, _cfg()) is MarketState.COLD

    def test_cold_zero_window(self):
        feat = MarketStateFeatures(days_in_window=0)
        assert classify_market_state(feat, _cfg()) is MarketState.COLD

    def test_cold_low_follow_through(self):
        feat = _feat(days=5, gft="0.30", avg_green="0.30", count_gt100=3)
        assert classify_market_state(feat, _cfg()) is MarketState.COLD

    def test_cold_low_avg_green(self):
        feat = _feat(days=5, gft="0.70", avg_green="0.08", count_gt100=3)
        assert classify_market_state(feat, _cfg()) is MarketState.COLD

    def test_cold_zero_big_movers(self):
        feat = _feat(days=5, gft="0.70", avg_green="0.30", count_gt100=0)
        assert classify_market_state(feat, _cfg()) is MarketState.COLD

    # ── Uncertain → COLD (bias spec §13.9) ───────────────────────────────────

    def test_cold_missing_follow_through(self):
        feat = _feat(days=5, gft=None, avg_green="0.30", count_gt100=3)
        assert classify_market_state(feat, _cfg()) is MarketState.COLD

    def test_cold_missing_avg_green(self):
        feat = _feat(days=5, gft="0.70", avg_green=None, count_gt100=3)
        assert classify_market_state(feat, _cfg()) is MarketState.COLD

    def test_cold_missing_all_data(self):
        feat = MarketStateFeatures(days_in_window=5)
        assert classify_market_state(feat, _cfg()) is MarketState.COLD

    def test_cold_two_hot_one_cold_still_cold(self):
        # 2/3 hot signals but gft is in cold zone → COLD
        feat = _feat(days=5, gft="0.30", avg_green="0.30", count_gt100=3)
        assert classify_market_state(feat, _cfg()) is MarketState.COLD

    def test_cold_is_default_when_all_neutral(self):
        """Middle-zone data (no HOT, no COLD signals) → COLD (default bias)."""
        # gft=0.45 between 0.35 and 0.60; avg_green=0.15 between 0.10 and 0.25;
        # count_gt100=1 between 0 and 2 → all neutral → hot_signals=0 → not HOT → COLD
        feat = _feat(days=5, gft="0.45", avg_green="0.15", count_gt100=1)
        assert classify_market_state(feat, _cfg()) is MarketState.COLD

    # ── Configurable thresholds ───────────────────────────────────────────────

    def test_hot_threshold_big_movers_configurable(self):
        # Raise threshold to 5; count=3 no longer qualifies
        feat = _feat(days=5, gft="0.70", avg_green="0.30", count_gt100=3)
        assert classify_market_state(feat, _cfg(MS_HOT_BIG_MOVERS_MIN="5")) is MarketState.COLD

    def test_hot_requires_min_window_configurable(self):
        # Raise min-window to 5; 4 days insufficient
        feat = _feat(days=4, gft="0.70", avg_green="0.30", count_gt100=3)
        assert classify_market_state(feat, _cfg(MS_MIN_WINDOW_DAYS="5")) is MarketState.COLD
