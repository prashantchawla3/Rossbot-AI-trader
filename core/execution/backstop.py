"""Optional hidden catastrophic backstop (spec §13.4, Phase 10).

The primary mental stop fires at the trade's planned pullback level (U13).
The catastrophic backstop is a SECOND, DEEPER internal mental stop placed
BACKSTOP_OFFSET below the entry price.  It fires the same way: the internal
monitor detects the breach and fires a marketable-limit sell.

NO native STOP order is ever routed (U13).  The backstop is entirely handled
by the same internal-monitor + marketable-limit mechanism as the primary stop.

When to use:
  BACKSTOP_ENABLED = true (off by default; opt-in per session)
  BACKSTOP_OFFSET  = 0.50 ($/sh below entry; spec §13.4 "far below mental level")

The backstop fires only if the primary mental stop somehow failed (e.g., the
position gapped down past the primary stop without triggering the monitor).
In normal conditions, the primary mental stop fires first.

spec §13.4 / Phase 10.
"""

from __future__ import annotations

from decimal import Decimal

from core.config import ConfigService


class CatastrophicBackstop:
    """Optional second internal mental stop far below the primary (spec §13.4).

    Usage::

        backstop = CatastrophicBackstop(cfg)
        level = backstop.level(entry_price)   # None if disabled
        if backstop.is_breached(bid, entry_price):
            # fire marketable-limit (same as primary stop)

    Never routes a native STOP order — uses the same mechanism as U13
    (internal monitor → marketable-limit).

    spec §13.4 / Phase 10.
    """

    def __init__(self, cfg: ConfigService) -> None:
        self._enabled: bool = cfg.get_bool("BACKSTOP_ENABLED")
        self._offset: Decimal = cfg.get_decimal("BACKSTOP_OFFSET")

    @property
    def enabled(self) -> bool:
        return self._enabled

    def level(self, entry_price: Decimal) -> Decimal | None:
        """Return the catastrophic stop price, or None if disabled.

        Level = entry_price - BACKSTOP_OFFSET.
        This is intentionally far below the primary mental stop so market-maker
        stop-hunts cannot reach it (spec §13.4 'hidden … far below').

        spec §13.4.
        """
        if not self._enabled:
            return None
        level = entry_price - self._offset
        return max(level, Decimal("0.01"))

    def is_breached(self, current_price: Decimal, entry_price: Decimal) -> bool:
        """Return True when current_price has hit or breached the catastrophic level.

        Caller MUST fire a marketable-limit sell immediately (same as primary stop).
        NEVER route a native STOP (U13).

        spec §13.4 / Phase 10.
        """
        if not self._enabled:
            return False
        lv = self.level(entry_price)
        return lv is not None and current_price <= lv
