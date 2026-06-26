"""Attention / "obvious" scorer (spec §1 / §13.3, Phase 9).

score_attention() returns a float [0, 1] for how "obvious" a symbol is.
This is ALWAYS a weight (conviction factor), NEVER a hard entry gate.

Proxy per spec §13.3:
  - %-gain rank ≤ 3 (PRIME) / ≤ 10 (WATCH) / else IGNORE   → rank component
  - RVOL percentile (RVOL vs ATTENTION_RVOL_SCALE)           → rvol component

Combined: rank 60 %% + rvol 40 %% (weights chosen to favour rank as primary signal).

The existing Attention enum (core/scanner/models.py) and the 15 %%-weighted
conviction component already consume this signal at Phase 2.  Phase 9 makes the
scorer its own pure function so the provider can call it directly too.

spec §1 (attention filter) / §13.3 / Phase 9.
"""

from __future__ import annotations

from decimal import Decimal

from core.config import ConfigService

# Rank-tier weights (matching spec §1 PRIME/WATCH/IGNORE ranks)
_PRIME_SCORE = 1.0
_WATCH_SCORE = 0.6
_IGNORE_SCORE = 0.2


def score_attention(
    rank_by_pct_gain: int,
    rvol: Decimal,
    cfg: ConfigService,
) -> float:
    """Return an attention weight in [0, 1].  Never a hard gate (spec §13.3).

    :param rank_by_pct_gain: 1-based market rank by %%gain (1 = top gainer).
    :param rvol:             Symbol's relative volume (e.g., 5.0 = 500 %% of avg).
    :param cfg:              ConfigService for ATTENTION_PRIME_RANK / WATCH_RANK /
                             ATTENTION_RVOL_SCALE.

    spec §1 attention filter / §13.3 obvious-factor.
    """
    prime_rank = cfg.get_int("ATTENTION_PRIME_RANK")   # default 3
    watch_rank = cfg.get_int("ATTENTION_WATCH_RANK")   # default 10
    rvol_scale = cfg.get_decimal("ATTENTION_RVOL_SCALE")  # default 100.0

    # ── Rank component ────────────────────────────────────────────────────────
    if rank_by_pct_gain <= prime_rank:
        rank_score = _PRIME_SCORE
    elif rank_by_pct_gain <= watch_rank:
        rank_score = _WATCH_SCORE
    else:
        rank_score = _IGNORE_SCORE

    # ── RVOL component (capped at 1.0) ────────────────────────────────────────
    if rvol_scale > Decimal("0"):
        rvol_score = min(float(rvol) / float(rvol_scale), 1.0)
    else:
        rvol_score = 0.0

    # ── Composite (rank 60 %%, rvol 40 %%) ────────────────────────────────────
    return round(0.6 * rank_score + 0.4 * rvol_score, 4)
