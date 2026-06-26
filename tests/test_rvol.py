"""RVOL engine tests: baseline, ratio, and low-confidence on thin history."""

from __future__ import annotations

from decimal import Decimal

import pytest
from core.scanner.rvol import Confidence, RvolEngine, rolling_baseline


def test_rolling_baseline_mean() -> None:
    assert rolling_baseline([100, 200, 300], window=50) == Decimal("200")
    assert rolling_baseline([], window=50) is None
    assert rolling_baseline([0, 0], window=50) is None  # no usable volume


def test_rvol_high_confidence_passes_pillar3() -> None:
    eng = RvolEngine(baseline_days=50, min_history_days=20)
    hist = [1_000_000] * 30  # 30 days ≥ min_history
    res = eng.compute(current_volume=5_000_000, daily_volumes=hist)
    assert res.confidence is Confidence.HIGH
    assert res.rvol == Decimal("5")
    assert res.passes(Decimal("5.0")) is True


def test_rvol_thin_history_is_low_confidence() -> None:
    eng = RvolEngine(baseline_days=50, min_history_days=20)
    res = eng.compute(current_volume=5_000_000, daily_volumes=[1_000_000] * 5)  # only 5 days
    assert res.confidence is Confidence.LOW
    # Even with rvol >= threshold, low confidence must NOT pass Pillar 3 (fail-safe).
    assert res.passes(Decimal("5.0")) is False


def test_rvol_no_baseline_is_unknown() -> None:
    eng = RvolEngine()
    res = eng.compute(current_volume=1_000_000, daily_volumes=[])
    assert res.confidence is Confidence.UNKNOWN
    assert res.rvol is None
    assert res.passes(Decimal("5.0")) is False


def test_rvol_cache_and_unknown_symbol() -> None:
    eng = RvolEngine(min_history_days=1)
    eng.update_baseline("AAA", [2_000_000] * 50)
    res = eng.rvol_for("AAA", current_volume=4_000_000)
    assert res.rvol == Decimal("2")
    assert eng.rvol_for("ZZZ", 1).confidence is Confidence.UNKNOWN


def test_rvol_intraday_projection() -> None:
    eng = RvolEngine(min_history_days=1)
    # half the day's avg volume done, but only a quarter of the day elapsed ⇒ 2x pace.
    res = eng.compute(
        current_volume=500_000,
        daily_volumes=[1_000_000] * 50,
        expected_fraction=Decimal("0.25"),
    )
    assert res.rvol == Decimal("2")


def test_rvol_rejects_float_volume() -> None:
    eng = RvolEngine()
    with pytest.raises(TypeError):
        eng.compute(current_volume=1.5, daily_volumes=[1_000_000] * 50)  # type: ignore[arg-type]
