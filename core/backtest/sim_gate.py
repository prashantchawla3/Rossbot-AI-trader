"""U6 Simulator Gate — hard-blocks live trading until ≥10 consecutive sim days @ ≥60% accuracy.

spec §11 U6 / CLAUDE.md §4 U6 / ROSSBOT_PROJECT_PLAN.md Phase 4.
"""

from __future__ import annotations

from decimal import Decimal

from core.backtest.models import SimDay
from core.config import ConfigService


class SimulatorGate:
    """Tracks consecutive qualifying sim days and enforces the U6 live-trading gate.

    A "qualifying day" = accuracy ≥ SIM_GATE_ACCURACY (default 60%) AND ≥ 1 real trade.
    Any below-threshold day or zero-trade day RESETS the streak.

    Usage::

        gate = SimulatorGate(config)
        gate.record_day(sim_day)  # call after each simulated trading day
        if gate.live_mode_allowed(config):
            ...  # U6 satisfied; LIVE_ENABLED must also be True in DB config

    spec §11 U6.
    """

    def __init__(self, config: ConfigService) -> None:
        self._cfg = config
        self._qualifying_days: list[SimDay] = []

    def record_day(self, day: SimDay) -> None:
        """Record a completed sim day.  Resets the streak on any failing day.

        A zero-trade day is treated as failing (no evidence of accuracy).
        spec §11 U6.
        """
        threshold = self._cfg.get_decimal("SIM_GATE_ACCURACY")
        qualifies = day.day_trades > 0 and day.accuracy >= threshold
        if not qualifies:
            self._qualifying_days.clear()
        self._qualifying_days.append(day)
        # Trim streak to last N days only (avoids unbounded accumulation)
        required = self._cfg.get_int("SIM_GATE_DAYS")
        self._qualifying_days = self._qualifying_days[-required:]

    @property
    def consecutive_qualifying_days(self) -> int:
        """Number of trailing consecutive qualifying days (≥ threshold accuracy)."""
        threshold = self._cfg.get_decimal("SIM_GATE_ACCURACY")
        count = 0
        for d in reversed(self._qualifying_days):
            if d.day_trades > 0 and d.accuracy >= threshold:
                count += 1
            else:
                break
        return count

    @property
    def satisfied(self) -> bool:
        """True when U6 bar has been met (≥10 consecutive qualifying days).

        spec §11 U6 — "≥10 consecutive sim days @ ≥60% accuracy before live".
        """
        return self.consecutive_qualifying_days >= self._cfg.get_int("SIM_GATE_DAYS")

    def live_mode_allowed(self, cfg: ConfigService) -> bool:
        """Hard gate: BOTH U6 satisfied AND LIVE_ENABLED=true in config.

        LIVE_ENABLED must be set manually in the config table after the client
        reviews the sim results. Neither condition alone is sufficient.
        spec §11 U6 / CLAUDE.md §4 U6.
        """
        return self.satisfied and cfg.get_bool("LIVE_ENABLED")

    @property
    def status_summary(self) -> str:
        """Human-readable U6 status string for logging / monitoring."""
        required = self._cfg.get_int("SIM_GATE_DAYS")
        threshold = self._cfg.get_decimal("SIM_GATE_ACCURACY")
        days = self.consecutive_qualifying_days
        if self.satisfied:
            q_days = [d for d in self._qualifying_days if d.day_trades > 0]
            avg_acc = (
                sum(d.accuracy for d in q_days) / Decimal(str(len(q_days)))
                if q_days else Decimal("0")
            )
            return (
                f"U6 SATISFIED: {days}/{required} days, "
                f"avg accuracy {avg_acc:.0%} (threshold {threshold:.0%})"
            )
        return (
            f"U6 NOT MET: {days}/{required} qualifying days "
            f"(each must have ≥{threshold:.0%} accuracy)"
        )


__all__ = ["SimulatorGate"]
