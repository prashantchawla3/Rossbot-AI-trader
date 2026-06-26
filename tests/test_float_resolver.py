"""Float resolver tests (acceptance: "float resolver flags low-confidence")."""

from __future__ import annotations

from decimal import Decimal

from core.scanner.float_resolver import (
    FloatCandidate,
    FloatConfidence,
    resolve_float,
)


def fc(source: str, shares: int | None, *, free: bool = False) -> FloatCandidate:
    return FloatCandidate(source=source, shares=shares, is_free_float=free)


def test_no_sources_is_unknown() -> None:
    res = resolve_float([fc("edgar", None), fc("vendor", 0)])
    assert res.confidence is FloatConfidence.UNKNOWN
    assert res.float_shares is None
    assert res.acceptable_for_pillar2() is False


def test_free_float_validated_by_shares_out_is_high() -> None:
    res = resolve_float([fc("vendor", 8_000_000, free=True), fc("sec_edgar", 10_000_000)])
    assert res.confidence is FloatConfidence.HIGH
    assert res.float_shares == 8_000_000
    assert res.acceptable_for_pillar2() is True


def test_single_free_float_unvalidated_is_medium() -> None:
    res = resolve_float([fc("vendor", 8_000_000, free=True)])
    assert res.confidence is FloatConfidence.MEDIUM
    assert res.acceptable_for_pillar2() is True


def test_shares_out_only_is_medium_proxy() -> None:
    res = resolve_float([fc("sec_edgar", 12_000_000)])
    assert res.confidence is FloatConfidence.MEDIUM
    assert res.float_shares == 12_000_000  # conservative upper-bound proxy


def test_disagreeing_sources_flag_low_and_pick_conservative() -> None:
    # Two free-float sources disagree by > 5% → LOW, choose the larger (conservative).
    res = resolve_float(
        [fc("v1", 5_000_000, free=True), fc("v2", 9_000_000, free=True)],
        disagree_tolerance=Decimal("0.05"),
    )
    assert res.confidence is FloatConfidence.LOW
    assert res.float_shares == 9_000_000
    assert res.acceptable_for_pillar2() is False  # LOW must not pass Pillar 2


def test_free_float_exceeding_shares_out_is_low() -> None:
    # Float > shares outstanding is impossible → data error → LOW.
    res = resolve_float([fc("vendor", 20_000_000, free=True), fc("sec_edgar", 10_000_000)])
    assert res.confidence is FloatConfidence.LOW
    assert res.acceptable_for_pillar2() is False
