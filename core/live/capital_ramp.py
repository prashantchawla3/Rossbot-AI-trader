"""Staged capital ramp — limits position size during the first live trading days.

The ramp adds a hard cap ON TOP of the risk manager's approved shares. It is
deliberately simple (a config key, not an algorithm) because live tier changes
require explicit human review and client sign-off before promotion.

Tier progression:
  MICRO   → absolute max ``CAPITAL_RAMP_MICRO_SHARES`` (default 100 sh)
  STARTER → absolute max ``CAPITAL_RAMP_STARTER_SHARES`` (default 2000 sh)
  FULL    → no additional cap (risk manager sizing applies)

The tier is set at session startup from ``CAPITAL_RAMP_TIER`` config key.
It is NOT modified during a session (mirrors U11 — no mid-session parameter edits).
To promote a tier, update the config key in the DB BEFORE the next session.

spec §5/§6/Phase 6 capital ramp / ROSSBOT_PROJECT_PLAN.md Phase 6.
"""

from __future__ import annotations

import structlog

from core.config import ConfigService
from core.live.models import CapitalTier

log = structlog.get_logger(__name__)


class CapitalRamp:
    """Reads the current tier from config and applies the per-trade share cap.

    Usage::

        ramp = CapitalRamp(config)
        capped = ramp.apply(approved_shares=500)  # → 100 if MICRO, 500 if STARTER/FULL

    spec §5/§6/Phase 6.
    """

    def __init__(self, config: ConfigService) -> None:
        raw = config.get_str("CAPITAL_RAMP_TIER").upper()
        try:
            self._tier = CapitalTier(raw)
        except ValueError:
            log.warning("unknown CAPITAL_RAMP_TIER; defaulting to MICRO", raw=raw)
            self._tier = CapitalTier.MICRO

        self._micro_max = config.get_int("CAPITAL_RAMP_MICRO_SHARES")
        self._starter_max = config.get_int("CAPITAL_RAMP_STARTER_SHARES")

    @property
    def tier(self) -> CapitalTier:
        return self._tier

    def apply(self, approved_shares: int) -> int:
        """Return the share count after applying the ramp cap.

        :param approved_shares: Shares already approved by the risk manager.
        :returns: ``approved_shares`` clamped to the tier maximum (≤ approved_shares).
        """
        if self._tier is CapitalTier.MICRO:
            capped = min(approved_shares, self._micro_max)
        elif self._tier is CapitalTier.STARTER:
            capped = min(approved_shares, self._starter_max)
        else:
            capped = approved_shares  # FULL: no additional cap

        if capped < approved_shares:
            log.debug(
                "capital_ramp.capped",
                tier=self._tier,
                approved=approved_shares,
                capped=capped,
            )
        return capped

    def max_for_tier(self) -> int | None:
        """Maximum shares for the current tier, or None if FULL (uncapped)."""
        if self._tier is CapitalTier.MICRO:
            return self._micro_max
        if self._tier is CapitalTier.STARTER:
            return self._starter_max
        return None


__all__ = ["CapitalRamp"]
