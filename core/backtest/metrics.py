"""Compute and format backtest metrics from a BacktestResult.

Metrics required by plan Phase 4:
  per-trade R, win rate, avg hold, give-back, max DD, rule-violation count (must be 0).

All values: Decimal. Float is forbidden (CLAUDE.md §10).
spec Phase 4 plan.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from core.backtest.models import BacktestResult


@dataclass(frozen=True)
class BacktestMetrics:
    """Human-readable metrics summary. All money in Decimal, never float."""

    total_trades: int
    win_rate: Decimal           # fraction [0, 1]
    avg_r: Decimal              # average R-multiple (net_pnl / initial risk $)
    avg_hold_minutes: Decimal   # average hold time in minutes
    max_daily_drawdown: Decimal # worst single-day drawdown in $
    total_net_pnl: Decimal      # cumulative net PnL across all days
    total_fees: Decimal         # cumulative ECN + regulatory fees
    rule_violation_count: int   # MUST be 0 in production runs
    sim_gate_qualifying_days: int  # days with ≥60% accuracy (for U6)
    consecutive_green_days: int    # trailing profitable days


def compute_metrics(result: BacktestResult, *, accuracy_threshold: Decimal = Decimal("0.60")) -> BacktestMetrics:
    """Derive all key Phase 4 metrics from a BacktestResult.

    ``rule_violation_count`` must be 0 before any production use.
    spec Phase 4 plan / CLAUDE.md §9.
    """
    all_trades = [t for d in result.days for t in d.trades if not t.vetoed]

    total_pnl = sum((t.net_pnl for t in all_trades), Decimal("0"))
    total_fees = sum((t.fees for t in all_trades), Decimal("0"))

    avg_hold_secs = result.avg_hold_seconds
    avg_hold_minutes = Decimal(str(round(avg_hold_secs / 60, 1)))

    qualifying_days = sum(
        1
        for d in result.days
        if d.day_trades > 0 and d.accuracy >= accuracy_threshold
    )

    return BacktestMetrics(
        total_trades=result.total_trades,
        win_rate=result.win_rate,
        avg_r=result.avg_r,
        avg_hold_minutes=avg_hold_minutes,
        max_daily_drawdown=result.max_daily_drawdown,
        total_net_pnl=total_pnl,
        total_fees=total_fees,
        rule_violation_count=result.rule_violation_count,
        sim_gate_qualifying_days=qualifying_days,
        consecutive_green_days=result.consecutive_green_days,
    )


__all__ = ["BacktestMetrics", "compute_metrics"]
