"""Sub-scanner tests (spec §9)."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from core.scanner.models import ScanCandidate
from core.scanner.subscanners import (
    continuation,
    halt_scan,
    hod_momentum,
    low_float_top_gainer,
    reverse_split_ipo,
    running_up,
    top_gainers,
)


def c(symbol: str, **over: Any) -> ScanCandidate:
    base: dict[str, Any] = dict(symbol=symbol, price=Decimal("5.00"), change_pct=Decimal("10.0"))
    base.update(over)
    return ScanCandidate(**base)


def test_top_gainers_filters_penny_and_sorts() -> None:
    cands = [
        c("PENNY", price=Decimal("0.40"), change_pct=Decimal("99")),
        c("MID", change_pct=Decimal("20")),
        c("TOP", change_pct=Decimal("50")),
    ]
    out = top_gainers(cands)
    assert [x.symbol for x in out] == ["TOP", "MID"]  # PENNY (<= $0.50) excluded


def test_low_float_top_gainer() -> None:
    cands = [
        c("LOWFLOAT", float_shares=2_000_000, change_pct=Decimal("30")),
        c("BIGFLOAT", float_shares=9_000_000, change_pct=Decimal("40")),
        c("UNKNOWN", float_shares=None),
    ]
    out = low_float_top_gainer(cands, float_ceiling=5_000_000, price_max=Decimal("20"))
    assert [x.symbol for x in out] == ["LOWFLOAT"]  # only KNOWN float < 5M


def test_hod_momentum() -> None:
    out = hod_momentum([c("HOD", at_hod=True), c("NOT", at_hod=False)])
    assert [x.symbol for x in out] == ["HOD"]


def test_running_up_below_hod() -> None:
    cands = [
        c("SURGE", at_hod=False, surge_pct_window=Decimal("6")),
        c("ATHOD", at_hod=True, surge_pct_window=Decimal("9")),  # at HOD → excluded
        c("SLOW", at_hod=False, surge_pct_window=Decimal("2")),  # below threshold
    ]
    out = running_up(cands, surge_pct=Decimal("5"))
    assert [x.symbol for x in out] == ["SURGE"]


def test_halt_scan() -> None:
    assert [x.symbol for x in halt_scan([c("H", is_halted=True), c("N")])] == ["H"]


def test_reverse_split_ipo() -> None:
    cands = [c("RS", recent_reverse_split=True), c("IPO", recent_ipo=True), c("NONE")]
    assert {x.symbol for x in reverse_split_ipo(cands)} == {"RS", "IPO"}


def test_continuation() -> None:
    out = continuation([c("PRIOR", was_prior_mover=True), c("NEW")])
    assert [x.symbol for x in out] == ["PRIOR"]
