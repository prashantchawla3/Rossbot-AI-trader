"""Scanner domain DTOs — the normalized per-symbol snapshot + scan results (spec §1, §9).

A ``ScanCandidate`` is the vendor-agnostic snapshot the scanner evaluates; upstream (the
ingest layer + RVOL/float/catalyst providers) fills it. All ``Decimal`` fields use the
float-rejecting ``core.money.Money`` type so a float can never enter the scan path.
"""

from __future__ import annotations

from decimal import Decimal
from enum import StrEnum

from adapters.providers import CatalystVerdict
from pydantic import BaseModel, ConfigDict

from core.money import Money
from core.scanner.float_resolver import FloatConfidence
from core.scanner.rvol import Confidence as RvolConfidence


class Attention(StrEnum):
    """Ranking by market %-gain rank (spec §1 attention filter)."""

    PRIME = "PRIME"
    WATCH = "WATCH"
    IGNORE = "IGNORE"


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True)


class ScanCandidate(_Frozen):
    """Normalized snapshot for one symbol at one instant.

    ``change_pct`` and ``gap_pct`` are percentages (e.g. ``12.5`` = +12.5%), computed upstream
    from prev close. ``rvol`` / ``float_shares`` carry their resolver confidence so the gate can
    fail-safe on uncertainty.
    """

    symbol: str
    price: Money
    change_pct: Money  # ROC % vs prev close (Pillar 4 / top-gainers)
    gap_pct: Money = Decimal("0")  # pre-market gap % (Tier A)
    volume: int = 0  # cumulative shares today (sweet-spot ranking / liquidity)

    rvol: Money | None = None
    rvol_confidence: RvolConfidence = RvolConfidence.UNKNOWN

    float_shares: int | None = None
    float_confidence: FloatConfidence = FloatConfidence.UNKNOWN

    catalyst: CatalystVerdict = CatalystVerdict.UNVERIFIED  # fail-closed default (Pillar 5)

    market_rank: int | None = None  # rank by %-gain across the market (1 = top); None ⇒ unknown

    # ---- sub-scanner support fields (optional; default to the conservative value) ----
    at_hod: bool = False  # printing a new intraday high (HOD momentum)
    surge_pct_window: Money | None = None  # %% move over the running-up window (below HOD)
    is_halted: bool = False  # in/exiting an LULD halt
    recent_reverse_split: bool = False
    recent_ipo: bool = False
    was_prior_mover: bool = False  # big mover in the prior ~2 weeks (continuation)


class PillarReport(_Frozen):
    """Five-Pillars pass/fail breakdown (spec §1)."""

    p1_price: bool
    p2_float: bool
    p3_rvol: bool
    p4_roc: bool
    p5_catalyst: bool

    @property
    def all_pass(self) -> bool:
        return self.p1_price and self.p2_float and self.p3_rvol and self.p4_roc and self.p5_catalyst


class ScanResult(_Frozen):
    """Outcome of evaluating one candidate through both tiers."""

    candidate: ScanCandidate
    tier_a_pass: bool
    tier_b_pass: bool
    pillars: PillarReport
    attention: Attention
    reasons: tuple[str, ...] = ()

    @property
    def tradeable(self) -> bool:
        """Only a Tier-B (Five-Pillars) pass is tradeable; Tier-A is surveillance only (U1)."""
        return self.tier_b_pass


__all__ = [
    "Attention",
    "PillarReport",
    "ScanCandidate",
    "ScanResult",
]
