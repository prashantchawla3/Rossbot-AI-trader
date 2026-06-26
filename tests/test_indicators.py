"""Indicators verified against hand-computed fixtures (acceptance: "indicator values verified
against a known fixture"). All math is Decimal — a float input is rejected.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from core.indicators import (
    EmaState,
    MacdPoint,
    MacdState,
    ema,
    macd,
    macd_positive,
    vwap,
)


def D(s: str) -> Decimal:
    return Decimal(s)


# ---- EMA -----------------------------------------------------------------
def test_ema_sma_seed_then_recurrence() -> None:
    # period=3, k=0.5; seed = SMA(1,2,3)=2; then EMA[i]=(p-prev)*0.5+prev.
    out = ema([D("1"), D("2"), D("3"), D("4"), D("5")], period=3)
    assert out[0] is None and out[1] is None
    assert out[2] == D("2")
    assert out[3] == D("3")
    assert out[4] == D("4")


def test_ema_state_matches_batch() -> None:
    state = EmaState(3)
    seq = [D("1"), D("2"), D("3"), D("4"), D("5")]
    assert [state.update(v) for v in seq] == ema(seq, 3)


def test_ema_rejects_float() -> None:
    with pytest.raises(TypeError):
        EmaState(3).update(1.5)  # type: ignore[arg-type]


# ---- VWAP ----------------------------------------------------------------
def test_vwap_two_bars() -> None:
    # tp = (H+L+C)/3; bar1 tp=10 vol=100, bar2 tp=11 vol=100 → (1000+1100)/200 = 10.5
    bars = [(D("10"), D("10"), D("10"), 100), (D("11"), D("11"), D("11"), 100)]
    assert vwap(bars) == D("10.5")


def test_vwap_zero_volume_is_none() -> None:
    assert vwap([(D("10"), D("10"), D("10"), 0)]) is None


# ---- MACD ----------------------------------------------------------------
def test_macd_constant_line_fixture() -> None:
    # closes 1..6 with fast=2, slow=3, signal=2 → MACD line is a constant 0.5 from idx2.
    closes = [D("1"), D("2"), D("3"), D("4"), D("5"), D("6")]
    pts = macd(closes, fast=2, slow=3, signal=2)
    assert pts[0] is None and pts[1] is None
    assert pts[2] is not None and pts[2].macd == D("0.5") and pts[2].signal is None
    last = pts[5]
    assert last is not None
    assert last.macd == D("0.5")
    assert last.signal == D("0.5")
    assert last.histogram == D("0")


def test_macd_state_matches_batch() -> None:
    closes = [D(str(i)) for i in range(1, 12)]
    state = MacdState(2, 3, 2)
    assert [state.update(c) for c in closes] == macd(closes, 2, 3, 2)


def test_macd_requires_fast_lt_slow() -> None:
    with pytest.raises(ValueError, match="fast < slow"):
        MacdState(26, 12, 9)


def test_macd_positive_gate() -> None:
    # E4: line > signal AND histogram >= 0.
    assert macd_positive(MacdPoint(macd=D("0.5"), signal=D("0.4"), histogram=D("0.1"))) is True
    # equal line/signal is NOT positive (boundary)
    assert macd_positive(MacdPoint(macd=D("0.5"), signal=D("0.5"), histogram=D("0"))) is False
    # negative histogram fails
    assert macd_positive(MacdPoint(macd=D("0.5"), signal=D("0.4"), histogram=D("-0.1"))) is False
    # un-seeded point fails closed (hard-block, spec §2 E4)
    assert macd_positive(None) is False
