"""RVOL engine — relative volume vs a rolling daily-volume baseline (spec §1 PILLAR_3, §9).

RVOL = today's volume ÷ the average daily volume over the trailing baseline window
(default 50 trading days, ``RVOL_BASELINE_DAYS``). Pillar 3 requires RVOL ≥ 5.0.

Confidence: with fewer than ``RVOL_MIN_HISTORY_DAYS`` baseline days the average is noisy, so
the result is flagged ``LOW`` and must NOT silently satisfy Pillar 3 (fail-safe).

Intraday note: this computes the **day-over-day** ratio. ``current_volume`` is whatever volume
has accumulated so far today; to compare like-for-like intraday, pass ``expected_fraction`` =
the fraction of an average day's volume normally done by this time, which scales the baseline
down (e.g. 0.25 ⇒ "a quarter of the day is typically done by now"). Omit it for an EOD ratio.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

RVOL_BASELINE_DAYS_DEFAULT = 50
RVOL_MIN_HISTORY_DAYS_DEFAULT = 20


class Confidence(StrEnum):
    HIGH = "high"
    LOW = "low"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class RvolResult:
    rvol: Decimal | None
    baseline_avg_volume: Decimal | None
    history_days: int
    confidence: Confidence
    reason: str

    def passes(self, threshold: Decimal) -> bool:
        """Pillar-3 gate: only a confident, sufficient RVOL passes (fail-safe on LOW/UNKNOWN)."""
        return (
            self.rvol is not None and self.confidence is Confidence.HIGH and self.rvol >= threshold
        )


def rolling_baseline(daily_volumes: Sequence[int], window: int) -> Decimal | None:
    """Mean of the most recent ``window`` daily volumes (excludes the current day).

    ``daily_volumes`` is the trailing history, most-recent last, NOT including today.
    Returns ``None`` if there is no usable history.
    """
    usable = [v for v in daily_volumes[-window:] if v >= 0]
    if not usable:
        return None
    total = sum(usable)
    if total <= 0:
        return None
    return Decimal(total) / Decimal(len(usable))


class RvolEngine:
    """Stateful RVOL calculator with an optional per-symbol baseline cache."""

    def __init__(
        self,
        baseline_days: int = RVOL_BASELINE_DAYS_DEFAULT,
        min_history_days: int = RVOL_MIN_HISTORY_DAYS_DEFAULT,
    ) -> None:
        if baseline_days < 1:
            raise ValueError("baseline_days must be >= 1")
        self.baseline_days = baseline_days
        self.min_history_days = min_history_days
        self._baselines: dict[str, tuple[Decimal | None, int]] = {}

    def update_baseline(self, symbol: str, daily_volumes: Sequence[int]) -> None:
        """Cache the trailing baseline for ``symbol`` (history excludes today)."""
        avg = rolling_baseline(daily_volumes, self.baseline_days)
        n = len([v for v in daily_volumes[-self.baseline_days :] if v >= 0])
        self._baselines[symbol] = (avg, n)

    def rvol_for(
        self, symbol: str, current_volume: int, expected_fraction: Decimal | None = None
    ) -> RvolResult:
        """RVOL for ``symbol`` using its cached baseline. Unknown symbol ⇒ UNKNOWN."""
        if symbol not in self._baselines:
            return RvolResult(
                None, None, 0, Confidence.UNKNOWN, f"no baseline cached for {symbol!r}"
            )
        avg, n = self._baselines[symbol]
        return self._compute(avg, n, current_volume, expected_fraction)

    def compute(
        self,
        current_volume: int,
        daily_volumes: Sequence[int],
        expected_fraction: Decimal | None = None,
    ) -> RvolResult:
        """RVOL from an explicit history (stateless)."""
        avg = rolling_baseline(daily_volumes, self.baseline_days)
        n = len([v for v in daily_volumes[-self.baseline_days :] if v >= 0])
        return self._compute(avg, n, current_volume, expected_fraction)

    def _compute(
        self,
        avg: Decimal | None,
        history_days: int,
        current_volume: int,
        expected_fraction: Decimal | None,
    ) -> RvolResult:
        if isinstance(current_volume, bool) or not isinstance(current_volume, int):
            raise TypeError("current_volume must be a plain int")
        if current_volume < 0:
            raise ValueError("current_volume must be >= 0")
        if avg is None or avg <= 0:
            return RvolResult(
                None, avg, history_days, Confidence.UNKNOWN, "no usable baseline volume"
            )

        denom = avg
        if expected_fraction is not None:
            if isinstance(expected_fraction, bool) or not isinstance(expected_fraction, Decimal):
                raise TypeError("expected_fraction must be a Decimal")
            if not (Decimal(0) < expected_fraction <= Decimal(1)):
                raise ValueError("expected_fraction must be in (0, 1]")
            denom = avg * expected_fraction

        rvol = Decimal(current_volume) / denom
        if history_days < self.min_history_days:
            return RvolResult(
                rvol,
                avg,
                history_days,
                Confidence.LOW,
                f"only {history_days} baseline days (< {self.min_history_days}); low confidence",
            )
        return RvolResult(rvol, avg, history_days, Confidence.HIGH, "ok")


__all__ = [
    "Confidence",
    "RvolEngine",
    "RvolResult",
    "rolling_baseline",
]
