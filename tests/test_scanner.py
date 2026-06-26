"""Two-tier scanner tests — synthetic tickers at every Five-Pillars / Tier-A boundary."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest
from adapters.providers import CatalystVerdict
from core.config import ConfigService
from core.scanner.float_resolver import FloatConfidence
from core.scanner.models import Attention, ScanCandidate
from core.scanner.rvol import Confidence as RvolConfidence
from core.scanner.scanner import TwoTierScanner


@pytest.fixture
def scanner() -> TwoTierScanner:
    return TwoTierScanner(ConfigService.from_defaults())


def cand(**over: Any) -> ScanCandidate:
    """A fully Tier-B-passing candidate; override one field to probe a boundary."""
    base: dict[str, Any] = dict(
        symbol="AAA",
        price=Decimal("5.00"),
        change_pct=Decimal("12.0"),
        gap_pct=Decimal("8.0"),
        volume=10_000_000,
        rvol=Decimal("8.0"),
        rvol_confidence=RvolConfidence.HIGH,
        float_shares=8_000_000,
        float_confidence=FloatConfidence.HIGH,
        catalyst=CatalystVerdict.VERIFIED,
        market_rank=1,
    )
    base.update(over)
    return ScanCandidate(**base)


def test_full_pass_is_tradeable(scanner: TwoTierScanner) -> None:
    res = scanner.evaluate(cand())
    assert res.pillars.all_pass is True
    assert res.tier_b_pass is True and res.tradeable is True
    assert res.attention is Attention.PRIME


# ---- P1 price band (inclusive [2, 20]) ----
@pytest.mark.parametrize(
    ("price", "ok"),
    [("2.00", True), ("1.99", False), ("20.00", True), ("20.01", False)],
)
def test_p1_price_boundaries(scanner: TwoTierScanner, price: str, ok: bool) -> None:
    assert scanner.evaluate(cand(price=Decimal(price))).pillars.p1_price is ok


# ---- P2 float (≤ 20M, known + acceptable confidence) ----
def test_p2_float_boundary(scanner: TwoTierScanner) -> None:
    assert scanner.evaluate(cand(float_shares=20_000_000)).pillars.p2_float is True
    assert scanner.evaluate(cand(float_shares=20_000_001)).pillars.p2_float is False


def test_p2_float_unknown_or_low_conf_fails(scanner: TwoTierScanner) -> None:
    assert scanner.evaluate(cand(float_shares=None)).pillars.p2_float is False
    low = cand(float_shares=8_000_000, float_confidence=FloatConfidence.LOW)
    assert scanner.evaluate(low).pillars.p2_float is False


# ---- P3 RVOL (≥ 5, HIGH confidence) ----
@pytest.mark.parametrize(("rvol", "ok"), [("5.0", True), ("4.99", False)])
def test_p3_rvol_boundary(scanner: TwoTierScanner, rvol: str, ok: bool) -> None:
    assert scanner.evaluate(cand(rvol=Decimal(rvol))).pillars.p3_rvol is ok


def test_p3_rvol_low_conf_or_none_fails(scanner: TwoTierScanner) -> None:
    low = cand(rvol=Decimal("8.0"), rvol_confidence=RvolConfidence.LOW)
    assert scanner.evaluate(low).pillars.p3_rvol is False
    assert (
        scanner.evaluate(cand(rvol=None, rvol_confidence=RvolConfidence.UNKNOWN)).pillars.p3_rvol
        is False
    )


# ---- P4 ROC (≥ 10%) ----
@pytest.mark.parametrize(("roc", "ok"), [("10.0", True), ("9.99", False), ("10.01", True)])
def test_p4_roc_boundary(scanner: TwoTierScanner, roc: str, ok: bool) -> None:
    assert scanner.evaluate(cand(change_pct=Decimal(roc))).pillars.p4_roc is ok


# ---- P5 catalyst (VERIFIED only) ----
@pytest.mark.parametrize(
    ("verdict", "ok"),
    [
        (CatalystVerdict.VERIFIED, True),
        (CatalystVerdict.UNVERIFIED, False),
        (CatalystVerdict.SKIP, False),
    ],
)
def test_p5_catalyst(scanner: TwoTierScanner, verdict: CatalystVerdict, ok: bool) -> None:
    assert scanner.evaluate(cand(catalyst=verdict)).pillars.p5_catalyst is ok


# ---- Tier A wide net (surveillance) ----
def test_tier_a_unknown_float_surveils_but_not_tradeable(scanner: TwoTierScanner) -> None:
    # Unknown float: Tier A tolerates it (surveillance), Tier B Pillar 2 rejects it (no trade).
    c = cand(float_shares=None, float_confidence=FloatConfidence.UNKNOWN)
    res = scanner.evaluate(c)
    assert res.tier_a_pass is True
    assert res.tier_b_pass is False and res.tradeable is False


@pytest.mark.parametrize(
    ("change", "gap", "ok"), [("4.0", "0", True), ("3.99", "0", False), ("0", "4.0", True)]
)
def test_tier_a_move_gap_or_change(
    scanner: TwoTierScanner, change: str, gap: str, ok: bool
) -> None:
    c = cand(change_pct=Decimal(change), gap_pct=Decimal(gap))
    assert scanner.evaluate(c).tier_a_pass is ok


def test_tier_a_rvol_floor(scanner: TwoTierScanner) -> None:
    assert scanner.evaluate(cand(rvol=Decimal("2.0"))).tier_a_pass is True
    res = scanner.evaluate(cand(rvol=Decimal("1.99")))
    assert res.tier_a_pass is False


# ---- attention ranking ----
@pytest.mark.parametrize(
    ("rank", "expected"),
    [
        (1, Attention.PRIME),
        (3, Attention.PRIME),
        (4, Attention.WATCH),
        (10, Attention.WATCH),
        (11, Attention.IGNORE),
        (None, Attention.IGNORE),
    ],
)
def test_attention(scanner: TwoTierScanner, rank: int | None, expected: Attention) -> None:
    assert scanner.evaluate(cand(market_rank=rank)).attention is expected


# ---- batch behavior ----
def test_scan_sorts_by_roc_desc(scanner: TwoTierScanner) -> None:
    cands = [
        cand(symbol="LO", change_pct=Decimal("11")),
        cand(symbol="HI", change_pct=Decimal("40")),
    ]
    ordered = scanner.scan(cands)
    assert [r.candidate.symbol for r in ordered] == ["HI", "LO"]


def test_tradeable_and_watchlist_filters(scanner: TwoTierScanner) -> None:
    good = cand(symbol="GOOD")
    surveil = cand(symbol="WATCH", float_shares=None, float_confidence=FloatConfidence.UNKNOWN)
    fail = cand(symbol="FAIL", change_pct=Decimal("1.0"), gap_pct=Decimal("1.0"))
    results = [good, surveil, fail]
    assert {r.candidate.symbol for r in scanner.tradeable(results)} == {"GOOD"}
    assert {r.candidate.symbol for r in scanner.watchlist(results)} == {"GOOD", "WATCH"}
