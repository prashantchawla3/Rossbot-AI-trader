"""Pure market-state classifier: MarketStateFeatures → MarketState (spec §8/§13.9, Phase 9).

Decision rule (spec §13.9 — bias COLD on uncertainty):
  HOT requires ALL THREE positive signals and ZERO negative signals.
  Any single cold or missing feature tips the classification to COLD.
  Insufficient data (< MS_MIN_WINDOW_DAYS) → COLD unconditionally.

This is intentionally conservative: a false-COLD slows the bot (smaller size,
candle-close entry, EX1/EX2 disabled) which is safe.  A false-HOT enables
jackknife losses (spec §13.9).

spec §8 / §13.9.
"""

from __future__ import annotations

from adapters.market_state.models import MarketStateFeatures
from adapters.providers import MarketState
from core.config import ConfigService


def classify_market_state(
    features: MarketStateFeatures,
    cfg: ConfigService,
) -> MarketState:
    """Return HOT, COLD, or COLD-on-uncertainty.  Never returns REHAB (caller manages that).

    HOT gate (all three must fire, zero cold signals):
      1. count_gt100pct >= MS_HOT_BIG_MOVERS_MIN   (multiple 100%%+ names)
      2. gapper_follow_through >= MS_HOT_FOLLOW_THROUGH_MIN   (winners hold)
      3. avg_green_size >= MS_HOT_AVG_GREEN_MIN   (sizable moves)

    COLD signals (any one tips to COLD):
      - gapper_follow_through <= MS_COLD_FOLLOW_THROUGH_MAX   (faders)
      - avg_green_size <= MS_COLD_AVG_GREEN_MAX   (tiny moves)
      - count_gt100pct == 0   (no big movers)
      - gapper_follow_through is None   (no data → conservative)
      - avg_green_size is None   (no data → conservative)

    spec §8 / §13.9.
    """
    min_days = cfg.get_int("MS_MIN_WINDOW_DAYS")
    if features.days_in_window < min_days:
        # Insufficient rolling history → COLD (bias §13.9)
        return MarketState.COLD

    hot_big_movers_min = cfg.get_int("MS_HOT_BIG_MOVERS_MIN")
    hot_ft_min = cfg.get_decimal("MS_HOT_FOLLOW_THROUGH_MIN")
    hot_green_min = cfg.get_decimal("MS_HOT_AVG_GREEN_MIN")
    cold_ft_max = cfg.get_decimal("MS_COLD_FOLLOW_THROUGH_MAX")
    cold_green_max = cfg.get_decimal("MS_COLD_AVG_GREEN_MAX")

    # ── Count HOT and COLD signals ─────────────────────────────────────────────
    hot_signals = 0
    cold_signals = 0

    # Signal 1: big movers count
    if features.count_gt100pct >= hot_big_movers_min:
        hot_signals += 1
    elif features.count_gt100pct == 0:
        cold_signals += 1

    # Signal 2: gapper follow-through rate
    if features.gapper_follow_through is None:
        cold_signals += 1  # missing data → COLD bias
    elif features.gapper_follow_through >= hot_ft_min:
        hot_signals += 1
    elif features.gapper_follow_through <= cold_ft_max:
        cold_signals += 1

    # Signal 3: avg winner size
    if features.avg_green_size is None:
        cold_signals += 1  # missing data → COLD bias
    elif features.avg_green_size >= hot_green_min:
        hot_signals += 1
    elif features.avg_green_size <= cold_green_max:
        cold_signals += 1

    # ── Decision (bias COLD, §13.9) ───────────────────────────────────────────
    # HOT: needs all 3 hot signals AND zero cold signals
    if hot_signals == 3 and cold_signals == 0:
        return MarketState.HOT

    return MarketState.COLD
