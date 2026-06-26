"""Tests for CatastrophicBackstop (core/execution/backstop.py).

Acceptance criteria (spec §13.4 / Phase 10):
  - Backstop fires when price reaches catastrophic level
  - Backstop does NOT fire when disabled (BACKSTOP_ENABLED=false)
  - Backstop level is BACKSTOP_OFFSET below entry price
  - Backstop does NOT fire when price is above the level
  - Never routes a native STOP (U13 — structural test)

spec §13.4 / Phase 10.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from core.config import ConfigService, DEFAULTS
from core.execution.backstop import CatastrophicBackstop


def _cfg(**overrides: str) -> ConfigService:
    m = {d.key: (d.value, d.value_type) for d in DEFAULTS}
    for k, v in overrides.items():
        m[k] = (v, m[k][1])
    return ConfigService(m)


class TestCatastrophicBackstop:
    # ── Disabled (default) ───────────────────────────────────────────────────

    def test_disabled_by_default(self):
        bs = CatastrophicBackstop(_cfg())
        assert bs.enabled is False

    def test_level_none_when_disabled(self):
        bs = CatastrophicBackstop(_cfg())
        assert bs.level(Decimal("10.00")) is None

    def test_never_fires_when_disabled(self):
        bs = CatastrophicBackstop(_cfg())
        # Even if price is catastrophically low
        assert not bs.is_breached(Decimal("0.01"), Decimal("10.00"))

    # ── Enabled ──────────────────────────────────────────────────────────────

    def test_enabled_when_configured(self):
        bs = CatastrophicBackstop(_cfg(BACKSTOP_ENABLED="true"))
        assert bs.enabled is True

    def test_level_is_entry_minus_offset(self):
        bs = CatastrophicBackstop(_cfg(BACKSTOP_ENABLED="true", BACKSTOP_OFFSET="0.50"))
        level = bs.level(Decimal("10.00"))
        assert level == Decimal("9.50")

    def test_fires_at_exact_level(self):
        bs = CatastrophicBackstop(_cfg(BACKSTOP_ENABLED="true", BACKSTOP_OFFSET="0.50"))
        assert bs.is_breached(Decimal("9.50"), Decimal("10.00"))

    def test_fires_below_level(self):
        bs = CatastrophicBackstop(_cfg(BACKSTOP_ENABLED="true", BACKSTOP_OFFSET="0.50"))
        assert bs.is_breached(Decimal("9.40"), Decimal("10.00"))

    def test_not_fires_above_level(self):
        bs = CatastrophicBackstop(_cfg(BACKSTOP_ENABLED="true", BACKSTOP_OFFSET="0.50"))
        assert not bs.is_breached(Decimal("9.60"), Decimal("10.00"))

    def test_level_not_negative_on_tiny_entry(self):
        # entry=0.40, offset=0.50 → would go to -0.10; clamped to 0.01
        bs = CatastrophicBackstop(_cfg(BACKSTOP_ENABLED="true", BACKSTOP_OFFSET="0.50"))
        level = bs.level(Decimal("0.40"))
        assert level is not None
        assert level >= Decimal("0.01")

    def test_offset_configurable(self):
        bs = CatastrophicBackstop(_cfg(BACKSTOP_ENABLED="true", BACKSTOP_OFFSET="1.00"))
        level = bs.level(Decimal("10.00"))
        assert level == Decimal("9.00")

    def test_does_not_fire_at_primary_stop_level(self):
        # Backstop is FAR below primary stop — primary stops at -$0.20, backstop at -$0.50
        # Price just hit the primary mental stop level ($9.80) but backstop is at $9.50
        bs = CatastrophicBackstop(_cfg(BACKSTOP_ENABLED="true", BACKSTOP_OFFSET="0.50"))
        assert not bs.is_breached(Decimal("9.80"), Decimal("10.00"))

    # ── U13 structural: no native STOP ever ──────────────────────────────────

    def test_no_native_stop_in_base_adapter(self):
        """Structural: OrderType enum has no STOP member (U13 by construction)."""
        from adapters.base import OrderType
        assert not hasattr(OrderType, "STOP")
        assert not hasattr(OrderType, "STOP_LIMIT")
        assert not hasattr(OrderType, "MARKET")

    def test_no_native_stop_in_order_request(self):
        """OrderRequest can only hold LIMIT or MARKETABLE_LIMIT (U13 by construction)."""
        from adapters.base import OrderRequest, OrderType, Side
        from core.money import Money
        req = OrderRequest(
            client_order_id="test",
            symbol="AAPL",
            side=Side.SELL,
            qty=100,
            limit_price=Money("10.00"),
            order_type=OrderType.MARKETABLE_LIMIT,
        )
        assert req.order_type in {OrderType.LIMIT, OrderType.MARKETABLE_LIMIT}
