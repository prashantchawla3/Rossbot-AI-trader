"""Pure feature-engineering for the market-state classifier (spec §13.9, Phase 9).

compute_features(snapshots) aggregates N DaySnapshots into MarketStateFeatures.
All computation is pure (no I/O, no mutations).

spec §8 / §13.9.
"""

from __future__ import annotations

from decimal import Decimal

from adapters.market_state.models import DaySnapshot, MarketStateFeatures

_ZERO = Decimal("0")


def compute_features(snapshots: list[DaySnapshot]) -> MarketStateFeatures:
    """Aggregate a rolling window of DaySnapshots into MarketStateFeatures.

    Called by RollingMarketStateProvider each time classify() is invoked.
    Returns COLD-safe (all None) features when window is empty.

    spec §8 / §13.9.
    """
    if not snapshots:
        return MarketStateFeatures(days_in_window=0)

    total_gappers = sum(s.gapper_count for s in snapshots)
    total_followthrough = sum(s.gapper_followthrough_count for s in snapshots)
    total_breakouts = sum(s.breakout_count for s in snapshots)
    total_successes = sum(s.breakout_success_count for s in snapshots)
    total_winners = sum(s.winner_count for s in snapshots)
    total_losers = sum(s.loser_count for s in snapshots)
    total_winner_gain = sum((s.winner_gain_sum for s in snapshots), _ZERO)
    total_loser_loss = sum((s.loser_loss_sum for s in snapshots), _ZERO)

    gapper_ft: Decimal | None = None
    if total_gappers > 0:
        gapper_ft = Decimal(total_followthrough) / Decimal(total_gappers)

    breakout_rate: Decimal | None = None
    if total_breakouts > 0:
        breakout_rate = Decimal(total_successes) / Decimal(total_breakouts)

    avg_green: Decimal | None = None
    if total_winners > 0:
        avg_green = total_winner_gain / Decimal(total_winners)

    avg_red: Decimal | None = None
    if total_losers > 0:
        avg_red = total_loser_loss / Decimal(total_losers)

    return MarketStateFeatures(
        days_in_window=len(snapshots),
        gapper_follow_through=gapper_ft,
        breakout_success_rate=breakout_rate,
        avg_green_size=avg_green,
        avg_red_size=avg_red,
        count_gt100pct=sum(s.count_gt100pct for s in snapshots),
        count_tiny_float=sum(s.count_tiny_float for s in snapshots),
    )
