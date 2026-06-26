"""RollingMarketStateProvider — replaces StubMarketStateProvider (spec §8/§13.9, Phase 9).

Maintains a rolling ring-buffer of DaySnapshots (one per trading day).
On classify(), computes features from the window and delegates to the pure
classifier.  REHAB mode overrides all feature logic when active.

REHAB entry:  caller calls set_rehab(True) after an outlier loss (spec §8).
REHAB exit:   caller calls set_rehab(False) when cushion is rebuilt (spec §8).

Fail-safe invariant (CLAUDE.md §4 / spec §13.9):
  Insufficient window (< MS_MIN_WINDOW_DAYS) → COLD.
  Missing features → COLD.
  On any exception → COLD.

spec §8 / §13.9.
"""

from __future__ import annotations

import structlog

from adapters.market_state.classifier import classify_market_state
from adapters.market_state.features import compute_features
from adapters.market_state.models import DaySnapshot
from adapters.providers import MarketState, MarketStateProvider
from core.config import ConfigService

log = structlog.get_logger(__name__)


class RollingMarketStateProvider(MarketStateProvider):
    """Rolling-feature market-state classifier (HOT/COLD/REHAB).

    Usage::

        provider = RollingMarketStateProvider(cfg, window_days=5)
        provider.record_day(today_snapshot)     # called once per trading day
        state = await provider.classify()        # called before each bar loop

    REHAB is set externally (by the risk manager on outlier loss)::

        provider.set_rehab(True)    # enter REHAB
        provider.set_rehab(False)   # exit REHAB (once cushion rebuilt)

    spec §8 / §13.9.
    """

    def __init__(self, cfg: ConfigService) -> None:
        self._cfg = cfg
        self._window: list[DaySnapshot] = []
        self._rehab: bool = False

    # ── Public API ─────────────────────────────────────────────────────────────

    def record_day(self, snapshot: DaySnapshot) -> None:
        """Append today's breadth snapshot; prune to the rolling window.

        Call once per trading day (at market close or before next open).
        spec §13.9.
        """
        self._window.append(snapshot)
        max_days = self._cfg.get_int("MS_HOT_WINDOW_DAYS")
        if len(self._window) > max_days:
            self._window.pop(0)
        log.debug(
            "market_state.snapshot_recorded",
            day=str(snapshot.day),
            window_size=len(self._window),
        )

    def set_rehab(self, active: bool) -> None:
        """Enter or exit REHAB mode (spec §8 outlier-loss recovery).

        REHAB caps sizing at MARKET_STATE_REHAB_CAP and disables EX1/EX2.
        Exit only when 50 %% of drawdown recovered AND multi-day cushion rebuilt
        (caller's responsibility to track that condition).
        spec §8.
        """
        prev = self._rehab
        self._rehab = active
        if prev != active:
            log.info("market_state.rehab_changed", active=active)

    @property
    def in_rehab(self) -> bool:
        """True when REHAB mode is active."""
        return self._rehab

    @property
    def window_size(self) -> int:
        """Number of days currently in the rolling buffer."""
        return len(self._window)

    async def classify(self) -> MarketState:
        """Return the current market regime.  Bias COLD on any uncertainty.

        REHAB → always MarketState.REHAB (overrides feature logic).
        HOT → all three hot signals present, zero cold signals.
        COLD → default (any cold signal, missing data, or insufficient window).
        spec §8 / §13.9.
        """
        if self._rehab:
            return MarketState.REHAB

        try:
            features = compute_features(list(self._window))
            state = classify_market_state(features, self._cfg)
        except Exception:  # noqa: BLE001
            log.exception("market_state.classify_error_fallback_cold")
            state = MarketState.COLD

        log.debug(
            "market_state.classified",
            state=state,
            window=len(self._window),
        )
        return state
