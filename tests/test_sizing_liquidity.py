"""Tests for Phase 12 sizing/liquidity hardening. spec §13.6 / U9.

Acceptance criteria:
  - compute_adv_liquidity_cap: 1% of ADV cap applied correctly.
  - compute_depth_cap: top-N levels × LIQUIDITY_CAP_FRACTION applied.
  - TRNR/ESTR oversize scenario: large uncapped size is correctly clamped.
  - Zero/empty depth → cap returns 0 (caller vetoes).
  - compute_size integration: liquidity_cap_shares clamps the final result.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from core.config import ConfigService
from core.risk.sizing import compute_adv_liquidity_cap, compute_depth_cap


# ── Helpers ───────────────────────────────────────────────────────────────────


def _cfg() -> ConfigService:
    return ConfigService.from_defaults()


# ── ADV cap ──────────────────────────────────────────────────────────────────


class TestADVLiquidityCap:
    def test_1_pct_of_1m_adv(self) -> None:
        """1% of 1,000,000 ADV = 10,000 shares."""
        cap = compute_adv_liquidity_cap(1_000_000, _cfg())
        assert cap == 10_000

    def test_1_pct_of_500k_adv(self) -> None:
        """1% of 500,000 ADV = 5,000 shares."""
        cap = compute_adv_liquidity_cap(500_000, _cfg())
        assert cap == 5_000

    def test_zero_adv_returns_zero(self) -> None:
        cap = compute_adv_liquidity_cap(0, _cfg())
        assert cap == 0

    def test_negative_adv_returns_zero(self) -> None:
        cap = compute_adv_liquidity_cap(-1_000, _cfg())
        assert cap == 0

    def test_small_adv_returns_at_least_1(self) -> None:
        """Any positive ADV always returns at least 1 share."""
        cap = compute_adv_liquidity_cap(50, _cfg())
        assert cap >= 1

    def test_trnr_estr_scenario_capped(self) -> None:
        """TRNR: 3M ADV but naive sizing wants 9,000 shares (0.3%) — must be ≤ 1% cap (30k).

        1% of 3M = 30,000; 9,000 < 30,000 so no ADV cap fires here.
        Test that the cap doesn't over-restrict reasonable sizes.
        """
        cap = compute_adv_liquidity_cap(3_000_000, _cfg())
        assert cap == 30_000
        # A 9,000-share order is well within cap
        assert 9_000 < cap

    def test_estr_style_low_adv(self) -> None:
        """ESTR: 200k ADV; even 1% = 2,000 shares. Oversize (9,000) would be clamped."""
        cap = compute_adv_liquidity_cap(200_000, _cfg())
        assert cap == 2_000
        oversize_attempt = 9_000
        capped = min(oversize_attempt, cap)
        assert capped == 2_000


# ── Depth cap ─────────────────────────────────────────────────────────────────


class TestDepthCap:
    def test_top_3_levels_10pct(self) -> None:
        """3 levels × various sizes; LIQUIDITY_CAP_FRACTION=0.10."""
        depth_asks = [
            (Decimal("5.10"), 10_000),
            (Decimal("5.11"), 8_000),
            (Decimal("5.12"), 6_000),
            (Decimal("5.15"), 20_000),  # 4th level excluded
        ]
        cap = compute_depth_cap(depth_asks, _cfg())
        # top 3 = 24,000; 10% = 2,400
        assert cap == 2_400

    def test_empty_depth_returns_zero(self) -> None:
        cap = compute_depth_cap([], _cfg())
        assert cap == 0

    def test_depth_with_zero_size_levels(self) -> None:
        depth_asks = [
            (Decimal("5.10"), 0),
            (Decimal("5.11"), 0),
        ]
        cap = compute_depth_cap(depth_asks, _cfg())
        assert cap == 0

    def test_thin_book_caps_aggressively(self) -> None:
        """Thin book: 3 levels with 1,000 shares total; 10% = 100 shares."""
        depth_asks = [
            (Decimal("10.00"), 400),
            (Decimal("10.05"), 300),
            (Decimal("10.10"), 300),
        ]
        cap = compute_depth_cap(depth_asks, _cfg())
        assert cap == 100  # 1000 * 0.10

    def test_fewer_levels_than_config(self) -> None:
        """Only 1 level available when config wants 3 — uses what's there."""
        depth_asks = [(Decimal("5.00"), 5_000)]
        cap = compute_depth_cap(depth_asks, _cfg())
        assert cap == 500  # 5000 * 0.10
