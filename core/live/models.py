"""Data-transfer objects for the Phase 6 live-trading layer.

spec Phase 6 / ROSSBOT_PROJECT_PLAN.md Phase 6.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


# ── Capital ramp ──────────────────────────────────────────────────────────────


class CapitalTier(StrEnum):
    """Staged capital ramp tiers (spec §5/§6/Phase 6).

    Progression: MICRO → STARTER → FULL (client-approved at each step).
    Never jump directly from MICRO to FULL.
    """

    MICRO = "MICRO"      # First live days; absolute tiny size (default 100 sh cap)
    STARTER = "STARTER"  # After MICRO validates, up to STARTER_CAP (default 2000 sh)
    FULL = "FULL"        # Full risk_formula sizing after proven sustained profitability


# ── Readiness checklist ───────────────────────────────────────────────────────


@dataclass(frozen=True)
class ReadinessItem:
    """One checklist item from the pre-market readiness check."""

    name: str
    passed: bool
    detail: str


@dataclass(frozen=True)
class ReadinessResult:
    """Full result of the pre-market readiness checklist."""

    items: tuple[ReadinessItem, ...]
    all_passed: bool = field(init=False)

    def __post_init__(self) -> None:
        # frozen dataclass: use object.__setattr__ to set the computed field
        object.__setattr__(self, "all_passed", all(i.passed for i in self.items))

    def failed_names(self) -> list[str]:
        return [i.name for i in self.items if not i.passed]

    def summary(self) -> str:
        total = len(self.items)
        passed = sum(1 for i in self.items if i.passed)
        if self.all_passed:
            return f"Readiness OK ({passed}/{total} checks passed)"
        failed = self.failed_names()
        return f"Readiness FAILED ({passed}/{total} passed). Blocked: {', '.join(failed)}"


# ── Position reconciliation ───────────────────────────────────────────────────


@dataclass(frozen=True)
class ReconcileResult:
    """Result of comparing broker positions vs. internal tracking state.

    matched: symbols present in both broker and internal state (correct).
    broker_only: broker has positions we are NOT tracking → ghost positions (alert).
    internal_only: we track positions the broker does NOT have → orphan state (correct).
    qty_mismatch: symbols where broker qty != internal qty (alert + correct).
    """

    matched: frozenset[str]
    broker_only: frozenset[str]
    internal_only: frozenset[str]
    qty_mismatch: frozenset[str]

    @property
    def clean(self) -> bool:
        """True when broker and internal state agree completely."""
        return not self.broker_only and not self.internal_only and not self.qty_mismatch

    def summary(self) -> str:
        if self.clean:
            return f"Reconcile OK: {len(self.matched)} position(s) matched"
        parts: list[str] = []
        if self.broker_only:
            parts.append(f"broker-only={set(self.broker_only)}")
        if self.internal_only:
            parts.append(f"internal-only={set(self.internal_only)}")
        if self.qty_mismatch:
            parts.append(f"qty-mismatch={set(self.qty_mismatch)}")
        return f"Reconcile DISCREPANCY: {'; '.join(parts)}"


__all__ = ["CapitalTier", "ReadinessItem", "ReadinessResult", "ReconcileResult"]
