"""Two-tier scanner — Tier A wide net → Tier B Five-Pillars gate (spec §1, §9).

Tier A surfaces a wide watchlist (surveillance); Tier B is the strict trade trigger. **No
trade fires until Tier B passes** (U1). All thresholds come from config (never literals).

Boundary convention: thresholds are **inclusive** (``>=`` / ``<=``), normalizing the trivial
§1-vs-§9 ``>``/``≥`` mismatch to §1's inclusive form (PROGRESS contradiction #5) so a value
sitting exactly on a threshold behaves deterministically.

Float fail-safe (CLAUDE.md §7.1): Tier B's Pillar 2 passes only when the float is **known**
with acceptable confidence AND ≤ the hard ceiling. Tier A (surveillance) tolerates an unknown
float so the name can still be watched — but it can never become tradeable without Tier B.
"""

from __future__ import annotations

from decimal import Decimal

from adapters.providers import CatalystVerdict

from core.config import ConfigService
from core.scanner.float_resolver import PILLAR2_ACCEPTABLE
from core.scanner.models import Attention, PillarReport, ScanCandidate, ScanResult
from core.scanner.rvol import Confidence as RvolConfidence


class TwoTierScanner:
    """Stateless evaluator: ``ScanCandidate`` → ``ScanResult`` using config thresholds."""

    def __init__(self, config: ConfigService) -> None:
        c = config
        # Tier A wide net (§1 TIER_A / §9 GAP_SCAN).
        self.tier_a_gap_min = c.get_decimal("TIER_A_GAP_MIN")
        self.tier_a_rvol_min = c.get_decimal("TIER_A_RVOL_MIN")
        self.tier_a_float_ceiling = c.get_int("TIER_A_FLOAT_CEILING")
        self.tier_a_price_min = c.get_decimal("TIER_A_PRICE_MIN")
        self.tier_a_price_max = c.get_decimal("TIER_A_PRICE_MAX")
        # Tier B Five Pillars (§1).
        self.price_min = c.get_decimal("PRICE_MIN")
        self.price_max = c.get_decimal("PRICE_MAX")
        self.float_ceiling = c.get_int("FLOAT_HARD_CEILING")
        self.rvol_min = c.get_decimal("RVOL_MIN")
        self.roc_min = c.get_decimal("ROC_MIN")
        # Attention (§1).
        self.prime_rank = c.get_int("ATTENTION_PRIME_RANK")
        self.watch_rank = c.get_int("ATTENTION_WATCH_RANK")

    # ---- Tier A ----------------------------------------------------------
    def _tier_a(self, cand: ScanCandidate, reasons: list[str]) -> bool:
        ok = True
        if not (self.tier_a_price_min <= cand.price <= self.tier_a_price_max):
            ok = False
            band = f"[{self.tier_a_price_min},{self.tier_a_price_max}]"
            reasons.append(f"tierA price {cand.price} outside {band}")
        # gap OR change ≥ floor.
        move = max(cand.gap_pct, cand.change_pct)
        if move < self.tier_a_gap_min:
            ok = False
            reasons.append(f"tierA move {move}% < {self.tier_a_gap_min}%")
        if cand.rvol is None or cand.rvol < self.tier_a_rvol_min:
            ok = False
            reasons.append(f"tierA rvol {cand.rvol} < {self.tier_a_rvol_min}")
        # Float: unknown is tolerated for surveillance; a known float must be ≤ ceiling.
        if cand.float_shares is not None and cand.float_shares > self.tier_a_float_ceiling:
            ok = False
            reasons.append(f"tierA float {cand.float_shares} > {self.tier_a_float_ceiling}")
        return ok

    # ---- Tier B Five Pillars --------------------------------------------
    def _pillars(self, cand: ScanCandidate, reasons: list[str]) -> PillarReport:
        # P1 price band (inclusive).
        p1 = self.price_min <= cand.price <= self.price_max
        if not p1:
            reasons.append(f"P1 price {cand.price} outside [{self.price_min},{self.price_max}]")

        # P2 float: must be KNOWN + acceptable confidence + ≤ ceiling (fail-safe on uncertainty).
        p2 = (
            cand.float_shares is not None
            and cand.float_confidence in PILLAR2_ACCEPTABLE
            and cand.float_shares <= self.float_ceiling
        )
        if not p2:
            reasons.append(
                f"P2 float fail (shares={cand.float_shares}, conf={cand.float_confidence}, "
                f"ceiling={self.float_ceiling})"
            )

        # P3 RVOL: present + HIGH confidence + ≥ min (fail-safe on LOW/UNKNOWN).
        p3 = (
            cand.rvol is not None
            and cand.rvol_confidence is RvolConfidence.HIGH
            and cand.rvol >= self.rvol_min
        )
        if not p3:
            reasons.append(
                f"P3 rvol fail (rvol={cand.rvol}, conf={cand.rvol_confidence}, min={self.rvol_min})"
            )

        # P4 ROC.
        p4 = cand.change_pct >= self.roc_min
        if not p4:
            reasons.append(f"P4 ROC {cand.change_pct}% < {self.roc_min}%")

        # P5 catalyst: only a VERIFIED catalyst passes; UNVERIFIED/SKIP fail (U15).
        p5 = cand.catalyst is CatalystVerdict.VERIFIED
        if not p5:
            reasons.append(f"P5 catalyst {cand.catalyst} (need VERIFIED)")

        return PillarReport(p1_price=p1, p2_float=p2, p3_rvol=p3, p4_roc=p4, p5_catalyst=p5)

    # ---- attention -------------------------------------------------------
    def _attention(self, cand: ScanCandidate) -> Attention:
        rank = cand.market_rank
        if rank is None:
            return Attention.IGNORE
        if rank <= self.prime_rank:
            return Attention.PRIME
        if rank <= self.watch_rank:
            return Attention.WATCH
        return Attention.IGNORE

    # ---- public ----------------------------------------------------------
    def evaluate(self, cand: ScanCandidate) -> ScanResult:
        reasons: list[str] = []
        tier_a = self._tier_a(cand, reasons)
        pillars = self._pillars(cand, reasons)
        tier_b = pillars.all_pass
        return ScanResult(
            candidate=cand,
            tier_a_pass=tier_a,
            tier_b_pass=tier_b,
            pillars=pillars,
            attention=self._attention(cand),
            reasons=tuple(reasons),
        )

    def scan(self, candidates: list[ScanCandidate]) -> list[ScanResult]:
        """Evaluate a batch, ranked by ROC descending (highest mover first)."""
        results = [self.evaluate(c) for c in candidates]
        results.sort(key=lambda r: r.candidate.change_pct, reverse=True)
        return results

    def watchlist(self, candidates: list[ScanCandidate]) -> list[ScanResult]:
        """Tier-A surveillance set (everything on the wide net)."""
        return [r for r in self.scan(candidates) if r.tier_a_pass]

    def tradeable(self, candidates: list[ScanCandidate]) -> list[ScanResult]:
        """Tier-B trade triggers only (Five Pillars passed)."""
        return [r for r in self.scan(candidates) if r.tier_b_pass]


# Convention constant: top-gainers floor price (spec §9 TOP_GAINERS_SCAN: price > $0.50).
TOP_GAINER_MIN_PRICE = Decimal("0.50")

__all__ = ["TOP_GAINER_MIN_PRICE", "TwoTierScanner"]
