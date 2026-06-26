"""Bar-builder tests: bucket alignment, OHLCV correctness, odd-lot + pre-market inclusion."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from adapters.base import TapeTick
from core.data.bars import BarBuilder, bucket_start, build_bars, timeframe_seconds


def tape(sym: str, t: datetime, price: str, size: int) -> TapeTick:
    return TapeTick(symbol=sym, ts=t, price=Decimal(price), size=size)


def test_timeframe_seconds_supported() -> None:
    assert timeframe_seconds("10s") == 10
    assert timeframe_seconds("1m") == 60
    with pytest.raises(ValueError, match="unsupported timeframe"):
        timeframe_seconds("5m")


def test_bucket_alignment_10s_and_1m() -> None:
    t = datetime(2026, 6, 26, 13, 30, 17, tzinfo=UTC)  # 09:30:17 ET
    assert bucket_start(t, "10s") == datetime(2026, 6, 26, 13, 30, 10, tzinfo=UTC)
    assert bucket_start(t, "1m") == datetime(2026, 6, 26, 13, 30, 0, tzinfo=UTC)


def test_naive_timestamp_rejected() -> None:
    with pytest.raises(ValueError, match="tz-aware"):
        bucket_start(datetime(2026, 6, 26, 13, 30, 0), "1m")  # intentionally naive


def test_ohlcv_and_odd_lots_included() -> None:
    # One 1-min bucket; sizes include odd lots (<100). All prints count toward OHLC + volume.
    base = datetime(2026, 6, 26, 13, 30, 1, tzinfo=UTC)
    prints = [
        tape("AAA", base, "5.00", 50),  # odd lot — open
        tape("AAA", base.replace(second=10), "5.40", 100),  # high
        tape("AAA", base.replace(second=20), "4.90", 7),  # odd lot — low
        tape("AAA", base.replace(second=30), "5.10", 200),  # close
    ]
    bars = build_bars("AAA", "1m", prints)
    assert len(bars) == 1
    bar = bars[0]
    assert bar.open == Decimal("5.00")
    assert bar.high == Decimal("5.40")
    assert bar.low == Decimal("4.90")
    assert bar.close == Decimal("5.10")
    assert bar.volume == 50 + 100 + 7 + 200  # odd lots included


def test_premarket_bar_is_built() -> None:
    # 08:00 ET = 12:00 UTC — pre-market. The builder must NOT drop pre-market prints.
    pm = datetime(2026, 6, 26, 12, 0, 5, tzinfo=UTC)
    bars = build_bars("PRE", "1m", [tape("PRE", pm, "3.00", 100)])
    assert len(bars) == 1 and bars[0].volume == 100


def test_new_bucket_emits_previous_bar() -> None:
    b0 = datetime(2026, 6, 26, 13, 30, 5, tzinfo=UTC)
    b1 = datetime(2026, 6, 26, 13, 31, 5, tzinfo=UTC)
    builder = BarBuilder("AAA", "1m")
    assert builder.on_print(tape("AAA", b0, "5.00", 100)) is None
    emitted = builder.on_print(tape("AAA", b1, "6.00", 100))  # opens next bucket
    assert emitted is not None and emitted.close == Decimal("5.00")


def test_out_of_order_old_print_ignored() -> None:
    builder = BarBuilder("AAA", "1m")
    cur = datetime(2026, 6, 26, 13, 31, 5, tzinfo=UTC)
    old = datetime(2026, 6, 26, 13, 30, 5, tzinfo=UTC)
    builder.on_print(tape("AAA", cur, "6.00", 100))
    assert builder.on_print(tape("AAA", old, "5.00", 100)) is None  # ignored, no rewrite
    bar = builder.flush()
    assert bar is not None and bar.volume == 100  # old print did not contribute


def test_wrong_symbol_rejected() -> None:
    builder = BarBuilder("AAA", "1m")
    with pytest.raises(ValueError, match="fed to"):
        builder.on_print(tape("BBB", datetime(2026, 6, 26, 13, 30, 0, tzinfo=UTC), "1.00", 1))
