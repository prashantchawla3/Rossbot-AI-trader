"""Tests for the attention scorer (adapters/market_state/attention.py).

Acceptance criteria (spec §1 / §13.3):
  - PRIME rank → highest score
  - WATCH rank → mid score
  - IGNORE rank → lowest score
  - RVOL boosts score continuously
  - Score is always a weight [0, 1], never a hard gate

spec §1 / §13.3 / Phase 9.
"""

from __future__ import annotations

from decimal import Decimal

from adapters.market_state.attention import score_attention
from core.config import ConfigService, DEFAULTS


def _cfg() -> ConfigService:
    return ConfigService({d.key: (d.value, d.value_type) for d in DEFAULTS})


class TestScoreAttention:
    def test_prime_rank_no_rvol(self):
        score = score_attention(1, Decimal("0"), _cfg())
        # rank=1 <= PRIME_RANK(3) → rank_score=1.0; rvol_score=0.0 → 0.6
        assert score == pytest.approx(0.6, abs=0.001)

    def test_watch_rank_no_rvol(self):
        score = score_attention(5, Decimal("0"), _cfg())
        # rank=5 between 3 and 10 → rank_score=0.6 → weight 0.6*0.6=0.36
        assert score == pytest.approx(0.36, abs=0.001)

    def test_ignore_rank_no_rvol(self):
        score = score_attention(50, Decimal("0"), _cfg())
        # rank=50 > 10 → rank_score=0.2; rvol=0 → 0.6*0.2=0.12
        assert score == pytest.approx(0.12, abs=0.001)

    def test_prime_rank_max_rvol(self):
        score = score_attention(1, Decimal("100"), _cfg())
        # rank_score=1.0, rvol_score=1.0 → 0.6 + 0.4 = 1.0
        assert score == pytest.approx(1.0, abs=0.001)

    def test_rvol_capped_at_one(self):
        score = score_attention(1, Decimal("200"), _cfg())
        # rvol=200 > scale(100) → rvol_score capped at 1.0 → still 1.0
        assert score == pytest.approx(1.0, abs=0.001)

    def test_prime_at_boundary(self):
        score = score_attention(3, Decimal("0"), _cfg())  # rank=3 == PRIME_RANK
        assert score == pytest.approx(0.6, abs=0.001)

    def test_watch_at_boundary(self):
        score = score_attention(10, Decimal("0"), _cfg())  # rank=10 == WATCH_RANK
        assert score == pytest.approx(0.36, abs=0.001)

    def test_ignore_beyond_watch(self):
        score = score_attention(11, Decimal("0"), _cfg())  # rank=11 > WATCH
        assert score == pytest.approx(0.12, abs=0.001)

    def test_rvol_50_half_score(self):
        score = score_attention(11, Decimal("50"), _cfg())
        # rank_score=0.2 (ignore), rvol_score=0.5 → 0.6*0.2 + 0.4*0.5 = 0.12+0.20=0.32
        assert score == pytest.approx(0.32, abs=0.001)

    def test_score_never_exceeds_one(self):
        for rank in [1, 5, 11]:
            for rvol_val in ["0", "50", "100", "200"]:
                score = score_attention(rank, Decimal(rvol_val), _cfg())
                assert 0.0 <= score <= 1.0

    def test_prime_outranks_watch_same_rvol(self):
        prime = score_attention(1, Decimal("20"), _cfg())
        watch = score_attention(5, Decimal("20"), _cfg())
        assert prime > watch

    def test_watch_outranks_ignore_same_rvol(self):
        watch = score_attention(5, Decimal("20"), _cfg())
        ignore = score_attention(50, Decimal("20"), _cfg())
        assert watch > ignore

    def test_higher_rvol_raises_score_within_tier(self):
        low = score_attention(5, Decimal("10"), _cfg())
        high = score_attention(5, Decimal("80"), _cfg())
        assert high > low


import pytest
