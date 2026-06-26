"""Tests for the E1–E7 entry AND-gate (spec §2).

Each gate has:
  - a PASS case (returns True / gate passes)
  - a FAIL case (returns False / gate vetoes)

Plus: full gate integration tests for combined pass and specific veto.

Note: find_pullback_context requires n >= surge_min_candles + pullback_max_candles + 1 = 2+3+1=6.
All bar sequences in tests must meet this minimum.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from adapters.base import BarTick
from adapters.providers import CatalystVerdict, L2Signal, MarketState
from core.config import DEFAULTS, ConfigService, EntryTrigger, ValueType
from core.indicators import MacdPoint, macd_positive
from core.money import to_money
from core.scanner.float_resolver import FloatConfidence
from core.scanner.models import Attention, PillarReport, ScanCandidate, ScanResult
from core.scanner.rvol import Confidence as RvolConfidence
from core.strategy.entry_gate import (
    evaluate_entry_gate,
    find_pullback_context,
    is_green_candle,
    is_red_candle,
)
from core.strategy.models import EntryGateResult, PullbackContext


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

_TS0 = datetime(2024, 1, 15, 9, 30, tzinfo=UTC)


def _bar(
    close: str,
    open_: str | None = None,
    high: str | None = None,
    low: str | None = None,
    volume: int = 100_000,
    symbol: str = "TEST",
    offset_min: int = 0,
) -> BarTick:
    c = Decimal(close)
    o = Decimal(open_) if open_ else c
    h = Decimal(high) if high else max(c, o) + Decimal("0.02")
    lo = Decimal(low) if low else min(c, o) - Decimal("0.02")
    ts = _TS0 + timedelta(minutes=offset_min)
    return BarTick(symbol=symbol, ts=ts, timeframe="1m", open=o, high=h, low=lo, close=c, volume=volume)


def _green(price: str, prev: str | None = None, **kw) -> BarTick:
    """Green bar: close > open."""
    p = Decimal(prev) if prev else Decimal(price) - Decimal("0.30")
    return _bar(close=price, open_=str(p), **kw)


def _red(price: str, prev: str | None = None, **kw) -> BarTick:
    """Red bar: close < open."""
    p = Decimal(prev) if prev else Decimal(price) + Decimal("0.30")
    return _bar(close=price, open_=str(p), **kw)


def _make_config() -> ConfigService:
    return ConfigService.from_defaults()


def _make_scan_result(tier_b: bool = True) -> ScanResult:
    cand = ScanCandidate(
        symbol="TEST",
        price=to_money("5.00"),
        change_pct=to_money("50.0"),
        rvol=to_money("10.0"),
        rvol_confidence=RvolConfidence.HIGH,
        float_shares=5_000_000,
        float_confidence=FloatConfidence.HIGH,
        catalyst=CatalystVerdict.VERIFIED if tier_b else CatalystVerdict.UNVERIFIED,
        market_rank=2,
    )
    pillars = PillarReport(
        p1_price=tier_b,
        p2_float=tier_b,
        p3_rvol=tier_b,
        p4_roc=tier_b,
        p5_catalyst=tier_b,
    )
    return ScanResult(
        candidate=cand,
        tier_a_pass=True,
        tier_b_pass=tier_b,
        pillars=pillars,
        attention=Attention.PRIME,
    )


def _surge_then_pullback_then_signal(
    surge_open: str = "5.00",
    surge_steps: int = 4,        # ≥4 keeps total bars ≥ 6 (find_pullback_context minimum = 6)
    pullback_count: int = 1,
    signal_close: str = "7.10",  # must exceed pullback bar's high (~7.02) so E3 passes
    surge_step: str = "0.50",
    pullback_step: str = "0.20",
) -> list[BarTick]:
    """Build: N green surge bars → M red pullback bars → 1 green signal bar.

    find_pullback_context minimum = surge_min(2) + pullback_max(3) + 1 = 6.
    With surge_steps=4, pullback_count=1: 4+1+1=6 bars, exactly meeting the minimum.
    """
    bars: list[BarTick] = []
    base = Decimal(surge_open)
    step = Decimal(surge_step)
    # Surge bars (green)
    for i in range(surge_steps):
        o = base + i * step
        c = o + step
        bars.append(_bar(close=str(c), open_=str(o), high=str(c + Decimal("0.05")),
                         low=str(o - Decimal("0.02")), offset_min=i))
    # Pullback (red, light volume)
    last_close = bars[-1].close
    pb_step = Decimal(pullback_step)
    for j in range(pullback_count):
        o = last_close - j * pb_step
        c = o - pb_step
        bars.append(_bar(close=str(c), open_=str(o), high=str(o + Decimal("0.02")),
                         low=str(c - Decimal("0.02")), volume=30_000,
                         offset_min=surge_steps + j))
    # Signal bar: green, close above last pullback bar's high
    last_pb = bars[-1]
    c = Decimal(signal_close)
    o = last_pb.close
    bars.append(_bar(close=str(c), open_=str(o), high=str(c + Decimal("0.05")),
                     low=str(o - Decimal("0.02")), volume=300_000,
                     offset_min=surge_steps + pullback_count))
    return bars


def _macd_positive() -> MacdPoint:
    return MacdPoint(macd=Decimal("0.05"), signal=Decimal("0.03"), histogram=Decimal("0.02"))


def _macd_negative() -> MacdPoint:
    return MacdPoint(macd=Decimal("-0.05"), signal=Decimal("0.03"), histogram=Decimal("-0.08"))


# ──────────────────────────────────────────────────────────────────────────────
# Unit tests: candle direction helpers
# ──────────────────────────────────────────────────────────────────────────────

class TestCandleDirection:
    def test_green_candle(self):
        bar = _green("5.50", prev="5.00")
        assert is_green_candle(bar)
        assert not is_red_candle(bar)

    def test_red_candle(self):
        bar = _red("5.00", prev="5.50")
        assert is_red_candle(bar)
        assert not is_green_candle(bar)

    def test_doji_is_neither(self):
        bar = _bar("5.00", open_="5.00")
        assert not is_green_candle(bar)
        assert not is_red_candle(bar)


# ──────────────────────────────────────────────────────────────────────────────
# Unit tests: find_pullback_context
# ──────────────────────────────────────────────────────────────────────────────

class TestFindPullbackContext:
    def test_valid_single_pullback(self):
        # 4 surge + 1 pullback + 1 signal = 6 bars (meets minimum of 6)
        bars = _surge_then_pullback_then_signal(surge_steps=4, pullback_count=1)
        assert len(bars) == 6
        ctx = find_pullback_context(bars, Decimal("0.50"))
        assert ctx is not None
        assert ctx.pullback_count == 1
        assert ctx.retrace_ratio <= Decimal("0.50")

    def test_valid_two_pullback_bars(self):
        # 3 surge + 2 pullback + 1 signal = 6 bars
        bars = _surge_then_pullback_then_signal(surge_steps=3, pullback_count=2)
        assert len(bars) == 6
        ctx = find_pullback_context(bars, Decimal("0.50"))
        assert ctx is not None
        assert ctx.pullback_count == 2

    def test_valid_three_pullback_bars(self):
        # 3 surge + 3 pullback + 1 signal = 7 bars
        bars = _surge_then_pullback_then_signal(surge_steps=3, pullback_count=3)
        assert len(bars) == 7
        ctx = find_pullback_context(bars, Decimal("0.50"))
        assert ctx is not None
        assert ctx.pullback_count == 3

    def test_no_pullback_returns_none(self):
        # 7 all-green bars → no red pullback → chasing vertical
        bars = [_green(str(Decimal("5.00") + i * Decimal("0.30")), offset_min=i)
                for i in range(7)]
        ctx = find_pullback_context(bars, Decimal("0.50"))
        assert ctx is None

    def test_too_few_bars_returns_none(self):
        # Only 3 bars total (below minimum of 6)
        bars = _surge_then_pullback_then_signal(surge_steps=1, pullback_count=1)
        assert len(bars) == 3
        ctx = find_pullback_context(bars[:3], Decimal("0.50"))
        assert ctx is None

    def test_retrace_ratio_computed_correctly(self):
        bars = _surge_then_pullback_then_signal(
            surge_open="10.00", surge_steps=4, pullback_count=1, signal_close="12.50"
        )
        ctx = find_pullback_context(bars, Decimal("0.50"))
        assert ctx is not None
        assert Decimal("0") < ctx.retrace_ratio <= Decimal("0.50")

    def test_too_deep_retrace_still_returned_e5_vetoes(self):
        """find_pullback_context returns context even if retrace > RETRACE_MAX; E5 vetoes.

        4 surge bars + 1 very deep pullback + 1 signal = 6 bars (minimum met).
        """
        bars: list[BarTick] = []
        # 4 surge bars: 5.00→5.80→6.60→7.40→8.20 (lows ~4.78+)
        for i in range(4):
            o = Decimal("5.00") + i * Decimal("0.80")
            c = o + Decimal("0.80")
            bars.append(_bar(close=str(c), open_=str(o), high=str(c + Decimal("0.05")),
                             low=str(o - Decimal("0.02")), offset_min=i))
        # Deep pullback (retraces >80% of the move)
        bars.append(_bar("5.20", open_="9.00", high="9.05", low="5.15", offset_min=4))
        # Signal bar
        bars.append(_green("5.80", prev="5.20", offset_min=5))

        assert len(bars) == 6
        ctx = find_pullback_context(bars, Decimal("0.50"))
        assert ctx is not None
        assert ctx.retrace_ratio > Decimal("0.50"), (
            f"Expected retrace > 0.50 but got {ctx.retrace_ratio}"
        )


# ──────────────────────────────────────────────────────────────────────────────
# Unit tests: individual gates
# ──────────────────────────────────────────────────────────────────────────────

class TestGateE4Macd:
    def test_positive_macd_passes(self):
        assert macd_positive(_macd_positive()) is True

    def test_negative_macd_blocks(self):
        assert macd_positive(_macd_negative()) is False

    def test_none_macd_blocks(self):
        assert macd_positive(None) is False


class TestGateE7Spread:
    def test_ideal_spread_passes(self):
        cfg = _make_config()
        spread = Decimal("0.05")
        assert spread >= cfg.get_decimal("SPREAD_MIN")
        assert spread <= cfg.get_decimal("SPREAD_MAX")

    def test_too_narrow_spread_fails(self):
        cfg = _make_config()
        spread = Decimal("0.01")
        assert spread < cfg.get_decimal("SPREAD_MIN")

    def test_too_wide_spread_fails(self):
        cfg = _make_config()
        spread = Decimal("0.15")
        assert spread > cfg.get_decimal("SPREAD_MAX")


# ──────────────────────────────────────────────────────────────────────────────
# Integration: full evaluate_entry_gate
# ──────────────────────────────────────────────────────────────────────────────

class TestEvaluateEntryGatePasses:
    def test_all_gates_pass(self):
        bars = _surge_then_pullback_then_signal()  # surge_steps=4 → 6 bars
        cfg = _make_config()
        scan = _make_scan_result(tier_b=True)
        result = evaluate_entry_gate(
            scan_result=scan,
            bars_1m=bars,
            macd_point=_macd_positive(),
            l2_signal=L2Signal.SUPPORT,
            spread=Decimal("0.05"),
            vwap=None,
            ema9=None,
            market_state=MarketState.COLD,
            config=cfg,
        )
        assert result.passes, f"Expected pass; reasons: {result.reasons}"
        assert result.e1_universe
        assert result.e2_pullback
        assert result.e3_crossing
        assert result.e4_macd
        assert result.e5_retrace
        assert result.e6_l2
        assert result.e7_spread
        assert result.pullback_ctx is not None

    def test_absorb_break_also_passes_e6(self):
        bars = _surge_then_pullback_then_signal()
        cfg = _make_config()
        result = evaluate_entry_gate(
            scan_result=_make_scan_result(tier_b=True),
            bars_1m=bars,
            macd_point=_macd_positive(),
            l2_signal=L2Signal.ABSORB_BREAK,
            spread=Decimal("0.04"),
            vwap=None,
            ema9=None,
            market_state=MarketState.COLD,
            config=cfg,
        )
        assert result.e6_l2
        assert result.passes


class TestEvaluateEntryGateVeto:
    def _run(self, **kwargs) -> EntryGateResult:
        bars = kwargs.pop("bars", _surge_then_pullback_then_signal())
        cfg = _make_config()
        defaults = dict(
            scan_result=_make_scan_result(tier_b=True),
            bars_1m=bars,
            macd_point=_macd_positive(),
            l2_signal=L2Signal.SUPPORT,
            spread=Decimal("0.05"),
            vwap=None,
            ema9=None,
            market_state=MarketState.COLD,
            config=cfg,
        )
        defaults.update(kwargs)
        return evaluate_entry_gate(**defaults)

    def test_e1_fails_when_tier_b_false(self):
        result = self._run(scan_result=_make_scan_result(tier_b=False))
        assert not result.e1_universe
        assert not result.passes

    def test_e2_fails_no_pullback_vertical(self):
        # 7 all-green bars → no pullback
        all_green = [_green(str(Decimal("5.00") + i * Decimal("0.30")), offset_min=i)
                     for i in range(7)]
        result = self._run(bars=all_green)
        assert not result.e2_pullback
        assert not result.passes

    def test_e3_fails_when_signal_bar_below_prior_high(self):
        bars = _surge_then_pullback_then_signal()  # 6 bars
        prev_bar = bars[-2]  # last pullback bar (red)
        # Signal bar: close is just 1c above pullback close but HIGH is below pullback bar's high.
        # E3 (candle_close): signal.close > prior.high → fails because close < prior.high
        signal = _bar(
            close=str(prev_bar.close + Decimal("0.01")),
            open_=str(prev_bar.close),
            high=str(prev_bar.high - Decimal("0.05")),   # high below pullback bar's high
            low=str(prev_bar.close - Decimal("0.02")),
            offset_min=10,
        )
        bars[-1] = signal
        result = self._run(bars=bars)
        assert not result.e3_crossing
        assert not result.passes

    def test_e4_hard_blocks_on_red_macd(self):
        result = self._run(macd_point=_macd_negative())
        assert not result.e4_macd
        assert not result.passes

    def test_e4_hard_blocks_on_none_macd(self):
        result = self._run(macd_point=None)
        assert not result.e4_macd
        assert not result.passes

    def test_e5_fails_on_too_deep_retrace(self):
        # 4 surge bars + 1 very deep pullback + 1 signal = 6 bars
        bars: list[BarTick] = []
        for i in range(4):
            o = Decimal("5.00") + i * Decimal("0.80")
            c = o + Decimal("0.80")
            bars.append(_bar(close=str(c), open_=str(o), high=str(c + Decimal("0.05")),
                             low=str(o - Decimal("0.02")), offset_min=i))
        # Pullback to 5.20 from a surge_high of ~8.85 → retrace ≈ 88%
        bars.append(_bar("5.20", open_="9.00", high="9.05", low="5.15", offset_min=4))
        bars.append(_green("5.80", prev="5.20", offset_min=5))

        result = self._run(bars=bars)
        assert not result.e5_retrace
        assert not result.passes

    def test_e6_fails_on_unknown_l2(self):
        # Stub default = UNKNOWN = fail closed (spec §13.2)
        result = self._run(l2_signal=L2Signal.UNKNOWN)
        assert not result.e6_l2
        assert not result.passes

    def test_e6_fails_on_iceberg(self):
        # GMBL fixture: hidden seller (iceberg) at key level
        result = self._run(l2_signal=L2Signal.ICEBERG)
        assert not result.e6_l2
        assert not result.passes

    def test_e6_fails_on_spoof(self):
        result = self._run(l2_signal=L2Signal.SPOOF)
        assert not result.e6_l2
        assert not result.passes

    def test_e7_fails_on_one_cent_spread(self):
        result = self._run(spread=Decimal("0.01"))
        assert not result.e7_spread
        assert not result.passes

    def test_e7_fails_on_wide_spread(self):
        result = self._run(spread=Decimal("0.20"))
        assert not result.e7_spread
        assert not result.passes


class TestMidCandleTrigger:
    def test_mid_candle_requires_hot_market(self):
        """Mid-candle is only used when market_state = HOT; forced to candle_close otherwise."""
        rows = {d.key: (d.value, d.value_type) for d in DEFAULTS}
        rows["ENTRY_TRIGGER"] = (EntryTrigger.MID_CANDLE.value, ValueType.STR)
        cfg = ConfigService(rows)
        bars = _surge_then_pullback_then_signal()
        scan = _make_scan_result()

        result_cold = evaluate_entry_gate(
            scan_result=scan,
            bars_1m=bars,
            macd_point=_macd_positive(),
            l2_signal=L2Signal.SUPPORT,
            spread=Decimal("0.05"),
            vwap=None,
            ema9=None,
            market_state=MarketState.COLD,
            config=cfg,
        )
        # COLD market → mid_candle forced to candle_close (spec C12)
        assert result_cold.entry_trigger == EntryTrigger.CANDLE_CLOSE

        result_hot = evaluate_entry_gate(
            scan_result=scan,
            bars_1m=bars,
            macd_point=_macd_positive(),
            l2_signal=L2Signal.SUPPORT,
            spread=Decimal("0.05"),
            vwap=None,
            ema9=None,
            market_state=MarketState.HOT,
            config=cfg,
        )
        # HOT market → mid_candle allowed (spec C12)
        assert result_hot.entry_trigger == EntryTrigger.MID_CANDLE
