"""Tests for the conviction scorer (spec §6 / §4 pattern ranks)."""

from __future__ import annotations

from decimal import Decimal

import pytest

from core.scanner.models import Attention
from core.strategy.conviction import score_conviction
from core.strategy.models import PatternType


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

_DEFAULT = dict(
    pattern=PatternType.MICRO_PULLBACK,
    rvol=Decimal("15"),
    float_shares=5_000_000,
    attention=Attention.PRIME,
    spread=Decimal("0.04"),
    retrace_ratio=Decimal("0.20"),
)


def _score(**overrides) -> Decimal:
    kw = dict(_DEFAULT)
    kw.update(overrides)
    return score_conviction(**kw)


# ──────────────────────────────────────────────────────────────────────────────
# Clamp
# ──────────────────────────────────────────────────────────────────────────────

class TestConvictionClamp:
    def test_result_never_below_min(self):
        score = _score(
            pattern=PatternType.NONE,
            rvol=Decimal("1"),         # below Tier B minimum
            float_shares=30_000_000,   # too large
            attention=Attention.IGNORE,
            spread=Decimal("0.50"),    # too wide
            retrace_ratio=Decimal("0.80"),
        )
        assert score >= Decimal("0.25")

    def test_result_never_above_max(self):
        score = _score(
            pattern=PatternType.MICRO_PULLBACK,
            rvol=Decimal("200"),
            float_shares=500_000,
            attention=Attention.PRIME,
            spread=Decimal("0.04"),
            retrace_ratio=Decimal("0.10"),
            ema9=Decimal("5.00"),
            current_price=Decimal("5.02"),  # within 2% EMA → bonus
            vwap=Decimal("4.90"),           # price > vwap → bonus
        )
        assert score <= Decimal("1.0")


# ──────────────────────────────────────────────────────────────────────────────
# Pattern rank ordering
# ──────────────────────────────────────────────────────────────────────────────

class TestPatternRank:
    def test_micro_pullback_beats_abcd(self):
        s_mp = _score(pattern=PatternType.MICRO_PULLBACK)
        s_ab = _score(pattern=PatternType.ABCD)
        assert s_mp > s_ab

    def test_abcd_beats_bull_flag(self):
        s_ab = _score(pattern=PatternType.ABCD)
        s_bf = _score(pattern=PatternType.BULL_FLAG)
        assert s_ab > s_bf

    def test_none_gives_minimum_pattern_score(self):
        s_none = _score(pattern=PatternType.NONE)
        s_mp = _score(pattern=PatternType.MICRO_PULLBACK)
        assert s_none < s_mp

    def test_all_pattern_types_produce_valid_score(self):
        for pt in PatternType:
            score = _score(pattern=pt)
            assert Decimal("0.25") <= score <= Decimal("1.0"), f"Score {score} out of range for {pt}"


# ──────────────────────────────────────────────────────────────────────────────
# RVOL sensitivity
# ──────────────────────────────────────────────────────────────────────────────

class TestRvolSensitivity:
    def test_100x_beats_5x(self):
        high = _score(rvol=Decimal("100"))
        low = _score(rvol=Decimal("5"))
        assert high > low

    def test_below_5x_rvol_gives_low_contribution(self):
        score = _score(rvol=Decimal("3"))
        # RVOL below tier-B minimum → zero RVOL component.
        # Score should be lower than with rvol=5.
        score_5x = _score(rvol=Decimal("5"))
        assert score < score_5x


# ──────────────────────────────────────────────────────────────────────────────
# Float tier
# ──────────────────────────────────────────────────────────────────────────────

class TestFloatTier:
    def test_sub_1m_float_maximises_float_component(self):
        tiny = _score(float_shares=500_000)
        large = _score(float_shares=15_000_000)
        assert tiny > large

    def test_none_float_neutral(self):
        score = _score(float_shares=None)
        assert Decimal("0.25") <= score <= Decimal("1.0")

    def test_over_20m_float_drags_score(self):
        over = _score(float_shares=25_000_000)
        under = _score(float_shares=15_000_000)
        assert over < under


# ──────────────────────────────────────────────────────────────────────────────
# Attention tier
# ──────────────────────────────────────────────────────────────────────────────

class TestAttentionTier:
    def test_prime_beats_watch_beats_ignore(self):
        prime = _score(attention=Attention.PRIME)
        watch = _score(attention=Attention.WATCH)
        ignore = _score(attention=Attention.IGNORE)
        assert prime > watch > ignore


# ──────────────────────────────────────────────────────────────────────────────
# Spread
# ──────────────────────────────────────────────────────────────────────────────

class TestSpread:
    def test_ideal_spread_maximises_spread_component(self):
        ideal = _score(spread=Decimal("0.04"))
        wide = _score(spread=Decimal("0.09"))
        assert ideal > wide

    def test_too_wide_spread_zeroes_spread_component(self):
        over = _score(spread=Decimal("0.50"))
        ok = _score(spread=Decimal("0.05"))
        assert over < ok


# ──────────────────────────────────────────────────────────────────────────────
# Retrace depth
# ──────────────────────────────────────────────────────────────────────────────

class TestRetrace:
    def test_shallow_retrace_beats_deep(self):
        shallow = _score(retrace_ratio=Decimal("0.15"))
        deep = _score(retrace_ratio=Decimal("0.45"))
        assert shallow > deep


# ──────────────────────────────────────────────────────────────────────────────
# Bonuses
# ──────────────────────────────────────────────────────────────────────────────

class TestBonuses:
    def test_ema_touch_adds_bonus(self):
        base = _score()
        with_ema = _score(ema9=Decimal("5.00"), current_price=Decimal("5.01"))
        assert with_ema > base

    def test_vwap_reclaim_adds_bonus(self):
        base = _score()
        with_vwap = _score(vwap=Decimal("4.90"), current_price=Decimal("5.00"))
        assert with_vwap > base

    def test_both_bonuses_stack(self):
        base = _score()
        with_both = _score(
            ema9=Decimal("5.00"), current_price=Decimal("5.01"),
            vwap=Decimal("4.90"),
        )
        assert with_both > base
        # Both bonuses together should add ≥ 0.05 (EMA) + 0.03 (VWAP) = 0.08,
        # but clamped at 1.0.
        diff = with_both - base
        assert diff >= Decimal("0.05")
