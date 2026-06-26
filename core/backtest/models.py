"""Backtest domain models — trade records, sim-day summaries, results.

All money fields: Decimal. Float is forbidden (CLAUDE.md §10).
spec Phase 4 plan / ROSSBOT_PROJECT_PLAN.md §Phase 4.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal


@dataclass
class TradeRecord:
    """One completed round-trip trade in a backtest or sim run.

    ``vetoed=True`` means the Risk Manager blocked the entry; no capital was deployed.
    ``rule_violation=True`` means a U1–U15 rule was breached; must never appear in prod.
    """

    symbol: str
    entry_ts: datetime
    exit_ts: datetime
    entry_price: Decimal        # actual fill price after slippage
    exit_price: Decimal         # actual fill price after slippage
    shares: int
    gross_pnl: Decimal          # (exit_price − entry_price) × shares
    fees: Decimal               # ECN + regulatory (always ≥ 0)
    net_pnl: Decimal            # gross_pnl − fees
    r_multiple: Decimal         # net_pnl / (risk_per_share × shares); 0 if shares=0
    hold_seconds: float
    exit_reason: str            # ExitReason value or "vetoed"/"eod_flatten"
    risk_per_share: Decimal

    # Veto tracking (correctly blocked entries are NOT rule violations)
    vetoed: bool = False
    veto_reasons: tuple[str, ...] = ()

    # Any U1–U15 breach that slipped through = a bug; must be 0 in prod
    rule_violation: bool = False
    rule_violation_detail: str = ""


@dataclass
class SimDay:
    """Per-day summary for a sim or backtest run."""

    date: date
    trades: list[TradeRecord] = field(default_factory=list)
    peak_pnl: Decimal = field(default_factory=lambda: Decimal("0"))
    end_pnl: Decimal = field(default_factory=lambda: Decimal("0"))
    max_drawdown: Decimal = field(default_factory=lambda: Decimal("0"))  # always ≥ 0
    give_back_pct: Decimal = field(default_factory=lambda: Decimal("0"))

    @property
    def day_trades(self) -> int:
        """Completed trades (excluding vetoed entries)."""
        return len([t for t in self.trades if not t.vetoed])

    @property
    def wins(self) -> int:
        return len([t for t in self.trades if not t.vetoed and t.net_pnl > Decimal("0")])

    @property
    def losses(self) -> int:
        return len([t for t in self.trades if not t.vetoed and t.net_pnl <= Decimal("0")])

    @property
    def accuracy(self) -> Decimal:
        if self.day_trades == 0:
            return Decimal("0")
        return Decimal(str(self.wins)) / Decimal(str(self.day_trades))

    @property
    def rule_violations(self) -> int:
        return len([t for t in self.trades if t.rule_violation])


@dataclass
class BacktestResult:
    """Aggregated result of a multi-day backtest or sim run."""

    days: list[SimDay] = field(default_factory=list)

    @property
    def total_trades(self) -> int:
        return sum(d.day_trades for d in self.days)

    @property
    def wins(self) -> int:
        return sum(d.wins for d in self.days)

    @property
    def losses(self) -> int:
        return sum(d.losses for d in self.days)

    @property
    def win_rate(self) -> Decimal:
        if self.total_trades == 0:
            return Decimal("0")
        return Decimal(str(self.wins)) / Decimal(str(self.total_trades))

    @property
    def avg_r(self) -> Decimal:
        valid = [t.r_multiple for d in self.days for t in d.trades if not t.vetoed]
        if not valid:
            return Decimal("0")
        return sum(valid) / Decimal(str(len(valid)))

    @property
    def avg_hold_seconds(self) -> float:
        valid = [t.hold_seconds for d in self.days for t in d.trades if not t.vetoed]
        if not valid:
            return 0.0
        return sum(valid) / len(valid)

    @property
    def max_daily_drawdown(self) -> Decimal:
        if not self.days:
            return Decimal("0")
        return max(d.max_drawdown for d in self.days)

    @property
    def rule_violation_count(self) -> int:
        return sum(d.rule_violations for d in self.days)

    @property
    def consecutive_green_days(self) -> int:
        """Trailing consecutive profitable sim days."""
        count = 0
        for d in reversed(self.days):
            if d.end_pnl > Decimal("0"):
                count += 1
            else:
                break
        return count


__all__ = ["BacktestResult", "SimDay", "TradeRecord"]
