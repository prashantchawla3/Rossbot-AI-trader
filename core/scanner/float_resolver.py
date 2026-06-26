"""Float / share-count resolver (spec §13.1 — Pillar-2 dependency).

Float is the hardest field in the universe filter and a wrong value directly corrupts
Pillar 2. There is no clean real-time *free-float* API, so we reconcile multiple sources and
attach a confidence flag; **a bad/uncertain float must NOT silently pass Pillar 2** (plan
Phase 1, CLAUDE.md §7.1).

Sources (wired in ``adapters/``):
- **Vendor fundamentals** (Massive/Polygon, FMP, Finnhub) — may expose true *free float* and/or
  shares outstanding.
- **SEC EDGAR** (``data.sec.gov``) — gives **shares outstanding, NOT free float**
  (``dei:EntityCommonStockSharesOutstanding``). Shares outstanding is an *upper bound* on
  float, so it is a conservative proxy for the ``≤ 20M`` ceiling test.

This module is pure reconciliation logic over already-fetched ``FloatCandidate`` values; the
HTTP clients live in ``adapters/edgar.py`` and the reference-data adapter.

Reconciliation policy (documented for determinism):
1. Drop non-positive / missing counts.
2. None left ⇒ ``UNKNOWN`` (float unknown ⇒ Pillar 2 fails).
3. Prefer true free-float sources; fall back to shares-outstanding as a conservative proxy.
4. If the primary sources disagree by more than ``disagree_tolerance`` ⇒ ``LOW`` and pick the
   **larger** value (conservative: least likely to wrongly pass a ≤ceiling gate).
5. A free-float value that exceeds shares outstanding is logically impossible ⇒ ``LOW``.
6. Free float cross-validated by shares outstanding ⇒ ``HIGH``; single free-float w/o
   validation ⇒ ``MEDIUM``; shares-outstanding-only (no true float) ⇒ ``MEDIUM`` proxy.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from enum import StrEnum

DEFAULT_DISAGREE_TOLERANCE = Decimal("0.05")  # 5%


class FloatConfidence(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    UNKNOWN = "unknown"


# Confidences that may satisfy Pillar 2 (MEDIUM is the conservative shares-outstanding proxy).
PILLAR2_ACCEPTABLE = frozenset({FloatConfidence.HIGH, FloatConfidence.MEDIUM})


@dataclass(frozen=True)
class FloatCandidate:
    """One sourced share count. ``is_free_float`` distinguishes true float from shares-out."""

    source: str
    shares: int | None
    is_free_float: bool = False
    as_of: date | None = None


@dataclass(frozen=True)
class FloatResult:
    float_shares: int | None
    source: str
    confidence: FloatConfidence
    reason: str
    candidates: tuple[FloatCandidate, ...] = field(default_factory=tuple)

    def acceptable_for_pillar2(self) -> bool:
        return self.float_shares is not None and self.confidence in PILLAR2_ACCEPTABLE


def _spread(values: Sequence[int]) -> Decimal:
    lo, hi = min(values), max(values)
    if lo <= 0:
        return Decimal("Infinity")
    return (Decimal(hi) - Decimal(lo)) / Decimal(lo)


def resolve_float(
    candidates: Sequence[FloatCandidate],
    *,
    disagree_tolerance: Decimal = DEFAULT_DISAGREE_TOLERANCE,
) -> FloatResult:
    """Reconcile share-count candidates into a single float estimate + confidence."""
    valid = [c for c in candidates if c.shares is not None and c.shares > 0]
    tup = tuple(candidates)
    if not valid:
        return FloatResult(
            None, "none", FloatConfidence.UNKNOWN, "no usable share-count source", tup
        )

    free = [c for c in valid if c.is_free_float]
    shares_out = [c for c in valid if not c.is_free_float]
    primary = free if free else shares_out
    primary_vals = [c.shares for c in primary if c.shares is not None]

    # 4) disagreement among the primary sources → LOW, pick the conservative (larger) value.
    if len(primary_vals) > 1 and _spread(primary_vals) > disagree_tolerance:
        chosen = max(primary_vals)
        src = "+".join(sorted({c.source for c in primary}))
        return FloatResult(
            chosen,
            src,
            FloatConfidence.LOW,
            f"primary sources disagree > {disagree_tolerance:%}; using conservative max",
            tup,
        )

    if free:
        chosen = max(c.shares for c in free if c.shares is not None)
        src = "+".join(sorted({c.source for c in free}))
        so_max = max((c.shares for c in shares_out if c.shares is not None), default=None)
        if so_max is not None:
            # 5) float must be ≤ shares outstanding (allow tolerance for timing skew).
            if chosen > int(Decimal(so_max) * (Decimal(1) + disagree_tolerance)):
                return FloatResult(
                    chosen,
                    src,
                    FloatConfidence.LOW,
                    f"free float {chosen} exceeds shares outstanding {so_max} — data error",
                    tup,
                )
            # 6) cross-validated free float.
            return FloatResult(
                chosen, src, FloatConfidence.HIGH, "free float validated by shares-out", tup
            )
        return FloatResult(
            chosen, src, FloatConfidence.MEDIUM, "single free-float source, unvalidated", tup
        )

    # shares-outstanding only: conservative upper-bound proxy for float.
    chosen = max(primary_vals)
    src = "+".join(sorted({c.source for c in shares_out}))
    return FloatResult(
        chosen,
        src,
        FloatConfidence.MEDIUM,
        "shares-outstanding proxy (no true free-float source); upper bound on float",
        tup,
    )


__all__ = [
    "DEFAULT_DISAGREE_TOLERANCE",
    "PILLAR2_ACCEPTABLE",
    "FloatCandidate",
    "FloatConfidence",
    "FloatResult",
    "resolve_float",
]
