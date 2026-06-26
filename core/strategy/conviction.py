"""Conviction scorer — maps pattern/RVOL/float/attention/spread/retrace to [0.25, 1.0].

The score feeds position sizing in the Risk Manager (Phase 3):
  shares = floor(PER_TRADE_RISK / risk_per_share) × conviction_multiplier

spec §6 conviction_multiplier / §4 pattern ranks.
"""

from __future__ import annotations

from decimal import Decimal

from core.scanner.models import Attention
from core.strategy.models import PATTERN_RANK, PatternType

# Component weights (must sum to 1.0).
_W_PATTERN = Decimal("0.30")
_W_RVOL = Decimal("0.25")
_W_FLOAT = Decimal("0.15")
_W_ATTENTION = Decimal("0.15")
_W_SPREAD = Decimal("0.08")
_W_RETRACE = Decimal("0.07")

_ZERO = Decimal("0")
_ONE = Decimal("1.0")
_CONVICTION_MIN = Decimal("0.25")
_CONVICTION_MAX = Decimal("1.0")


def _pattern_score(pattern: PatternType) -> Decimal:
    """Map pattern rank to a 0–1 score.  R1 = 1.0, NONE ≈ 0.25."""
    rank = PATTERN_RANK[pattern]
    scores: dict[int, Decimal] = {
        1: Decimal("1.00"),   # micro_pullback
        2: Decimal("0.90"),   # abcd
        3: Decimal("0.80"),   # bull_flag / flat_top
        5: Decimal("0.70"),   # gap_and_go
        6: Decimal("0.65"),   # vwap_break
        7: Decimal("0.60"),   # halt_resumption
        10: Decimal("0.50"),  # red_to_green
        11: Decimal("0.50"),  # reverse_split_squeeze
        99: Decimal("0.25"),  # none
    }
    return scores.get(rank, Decimal("0.25"))


def _rvol_score(rvol: Decimal) -> Decimal:
    """Map RVOL to 0–1 score.  Tier B minimum is 5x; 100x+ = peak."""
    if rvol >= Decimal("100"):
        return Decimal("1.00")
    if rvol >= Decimal("80"):
        return Decimal("0.95")
    if rvol >= Decimal("50"):
        return Decimal("0.85")
    if rvol >= Decimal("30"):
        return Decimal("0.75")
    if rvol >= Decimal("10"):
        return Decimal("0.55")
    if rvol >= Decimal("5"):
        return Decimal("0.40")
    return _ZERO


def _float_score(float_shares: int | None) -> Decimal:
    """Map float tier to 0–1 score.  Smaller float = tighter squeeze = higher conviction."""
    if float_shares is None:
        return Decimal("0.50")  # unknown float: neutral (should have been blocked by E1)
    if float_shares < 1_000_000:
        return Decimal("1.00")
    if float_shares < 5_000_000:
        return Decimal("0.90")
    if float_shares < 10_000_000:
        return Decimal("0.75")
    if float_shares <= 20_000_000:
        return Decimal("0.60")
    return _ZERO  # > 20M float shouldn't pass Pillar 2


def _attention_score(attention: Attention) -> Decimal:
    """Map market-rank attention tier to 0–1 score.  spec §1 attention filter."""
    return {
        Attention.PRIME: Decimal("1.00"),
        Attention.WATCH: Decimal("0.75"),
        Attention.IGNORE: Decimal("0.40"),
    }[attention]


def _spread_score(spread: Decimal) -> Decimal:
    """Map spread to 0–1 score within the healthy band [0.03, 0.10].  spec §2 E7."""
    if spread <= Decimal("0.02") or spread > Decimal("0.10"):
        return _ZERO  # outside gate (shouldn't reach here post-E7)
    if spread <= Decimal("0.05"):
        return Decimal("1.00")  # ideal 3–5¢
    if spread <= Decimal("0.07"):
        return Decimal("0.85")
    return Decimal("0.70")  # 7–10¢: acceptable but widening slippage risk


def _retrace_score(retrace_ratio: Decimal) -> Decimal:
    """Map retrace depth to 0–1 score.  Shallower = higher conviction.  spec §2 E5 / C9."""
    if retrace_ratio <= Decimal("0.25"):
        return Decimal("1.00")  # full conviction (RETRACE_PREFERRED)
    if retrace_ratio <= Decimal("0.35"):
        return Decimal("0.75")
    if retrace_ratio <= Decimal("0.50"):
        return Decimal("0.50")  # within RETRACE_MAX but deep
    return _ZERO  # > 50% should have been blocked by E5


def score_conviction(
    pattern: PatternType,
    rvol: Decimal,
    float_shares: int | None,
    attention: Attention,
    spread: Decimal,
    retrace_ratio: Decimal,
    *,
    ema9: Decimal | None = None,
    current_price: Decimal | None = None,
    vwap: Decimal | None = None,
) -> Decimal:
    """Compute the [0.25, 1.0] conviction score.

    Weights: pattern 30%, RVOL 25%, float 15%, attention 15%, spread 8%,
    retrace 7%.  Bonuses: 9 EMA touch +0.05, VWAP reclaim +0.03.

    spec §6 conviction_multiplier = f(pattern_rank, rvol, float_tier,
                                      attention, spread).
    """
    composite = (
        _W_PATTERN * _pattern_score(pattern)
        + _W_RVOL * _rvol_score(rvol)
        + _W_FLOAT * _float_score(float_shares)
        + _W_ATTENTION * _attention_score(attention)
        + _W_SPREAD * _spread_score(spread)
        + _W_RETRACE * _retrace_score(retrace_ratio)
    )

    # Bonus: price ≈ 9 EMA (pullback touched 9 EMA).
    if ema9 is not None and current_price is not None:
        dist = abs(current_price - ema9) / max(ema9, Decimal("0.01"))
        if dist <= Decimal("0.02"):  # within 2%
            composite += Decimal("0.05")

    # Bonus: VWAP reclaim (close above VWAP).
    if vwap is not None and current_price is not None and current_price > vwap:
        composite += Decimal("0.03")

    return max(_CONVICTION_MIN, min(_CONVICTION_MAX, composite))


__all__ = ["score_conviction"]
