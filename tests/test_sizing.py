"""Tests for core.risk.sizing — compute_size() position sizing engine.

Tests cover both sizing modes, all caps (cushion/icebreaker/starter/conviction/
DOW/market-state/liquidity/MAX_SIZE), and boundary conditions.
spec §5 (cushion), §6 (sizing), §8 (market state caps), U9 (liquidity).
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from adapters.providers import MarketState
from core.config import ConfigService, DEFAULTS, ValueType
from core.risk.models import RiskState
from core.risk.sizing import compute_size
from core.strategy.models import (
    EntryGateResult,
    EntrySignal,
    PatternType,
    PullbackContext,
)

# ── Helpers ───────────────────────────────────────────────────────────────────

_TS = datetime(2026, 6, 26, 13, 45, tzinfo=timezone.utc)

_WEDNESDAY = 2   # 0=Mon, 2=Wed, 4=Fri
_MONDAY = 0
_FRIDAY = 4


def _make_gate() -> EntryGateResult:
    return EntryGateResult(
        passes=True,
        e1_universe=True,
        e2_pullback=True,
        e3_crossing=True,
        e4_macd=True,
        e5_retrace=True,
        e6_l2=True,
        e7_spread=True,
        pullback_ctx=PullbackContext(
            pullback_count=1,
            pullback_low=Decimal("4.50"),
            surge_high=Decimal("5.50"),
            surge_start=Decimal("4.00"),
            retrace_ratio=Decimal("0.20"),
        ),
    )


def _make_signal(
    entry: str = "5.00",
    stop: str = "4.50",
    target: str = "6.00",
    conviction: str = "1.0",
    market_state: MarketState = MarketState.HOT,
) -> EntrySignal:
    return EntrySignal(
        symbol="TEST",
        ts=_TS,
        pattern=PatternType.MICRO_PULLBACK,
        conviction_score=Decimal(conviction),
        entry_price=Decimal(entry),
        stop_price=Decimal(stop),
        target_price=Decimal(target),
        gate=_make_gate(),
        market_state=market_state,
    )


def _cfg(**overrides: tuple[str, ValueType]) -> ConfigService:
    rows = {d.key: (d.value, d.value_type) for d in DEFAULTS}
    rows.update(overrides)
    return ConfigService(rows)


def _state(
    realized_pnl: str = "0",
    peak_pnl: str = "0",
) -> RiskState:
    return RiskState(
        realized_pnl=Decimal(realized_pnl),
        peak_pnl=Decimal(peak_pnl),
    )


# ── risk_formula mode ─────────────────────────────────────────────────────────

class TestRiskFormula:
    def test_typical_setup(self) -> None:
        # risk=0.50, PER_TRADE_RISK=1000 → raw=2000
        # day_pnl=0 → icebreaker=floor(10000×0.25)=2500; min(2000,2500)=2000
        # conviction=1.0; HOT, Wednesday → 2000
        signal = _make_signal(entry="5.00", stop="4.50", target="6.00")
        result = compute_size(signal, _state("0"), _cfg(), MarketState.HOT, _WEDNESDAY)
        assert result == 2000

    def test_narrow_stop_hits_icebreaker(self) -> None:
        # risk=0.10 → raw=10000; day_pnl=0 → icebreaker=2500 (binding)
        # conviction=1.0; HOT Wed → 2500
        signal = _make_signal(entry="5.00", stop="4.90", target="6.10")
        result = compute_size(signal, _state("0"), _cfg(), MarketState.HOT, _WEDNESDAY)
        assert result == 2500

    def test_cushion_built_allows_higher_size(self) -> None:
        # day_pnl=$2000 (past $1000 cushion threshold); risk=0.10 → raw=10000
        # No icebreaker/starter cap; conviction=1.0; HOT Wed; MAX_SIZE=10000 → 10000
        signal = _make_signal(entry="5.00", stop="4.90", target="6.10")
        result = compute_size(signal, _state("2000"), _cfg(), MarketState.HOT, _WEDNESDAY)
        assert result == 10000

    def test_wide_stop_low_raw(self) -> None:
        # risk=$5.00 → raw=floor(1000/5.00)=200
        # day_pnl=$2000 → no cushion cap; conviction=1.0; HOT Wed → 200
        signal = _make_signal(entry="10.00", stop="5.00", target="20.00")
        result = compute_size(signal, _state("2000"), _cfg(), MarketState.HOT, _WEDNESDAY)
        assert result == 200

    def test_degenerate_stop_returns_zero(self) -> None:
        # stop >= entry → risk <= 0 → return 0 (SIZING_ZERO)
        signal = _make_signal(entry="5.00", stop="5.00", target="7.00")
        result = compute_size(signal, _state("0"), _cfg(), MarketState.HOT, _WEDNESDAY)
        assert result == 0

    def test_stop_above_entry_returns_zero(self) -> None:
        signal = _make_signal(entry="5.00", stop="5.50", target="7.00")
        result = compute_size(signal, _state("0"), _cfg(), MarketState.HOT, _WEDNESDAY)
        assert result == 0


# ── flat_block mode ───────────────────────────────────────────────────────────

class TestFlatBlock:
    def _flat_cfg(self) -> ConfigService:
        return _cfg(SIZING_MODE=("flat_block", ValueType.STR))

    def test_flat_block_below_cushion_threshold(self) -> None:
        # day_pnl=$500 (positive but < $1000 threshold)
        # flat_block: realized_pnl < CUSHION_PNL_THRESHOLD → raw=STARTER_CAP=5000
        # day_pnl=500 > 0 → starter cap applies: min(5000, 5000)=5000
        # (no icebreaker since pnl > 0)
        # conviction=1.0; HOT Wed; MAX_SIZE → 5000
        signal = _make_signal()
        result = compute_size(signal, _state("500"), self._flat_cfg(), MarketState.HOT, _WEDNESDAY)
        assert result == 5000

    def test_flat_block_at_cushion_threshold(self) -> None:
        # day_pnl=$1000 → raw=MAX_SIZE=10000; no icebreaker; conviction=1.0; HOT → 10000
        signal = _make_signal()
        result = compute_size(signal, _state("1000"), self._flat_cfg(), MarketState.HOT, _WEDNESDAY)
        assert result == 10000

    def test_flat_block_negative_pnl_icebreaker(self) -> None:
        # day_pnl=-100 → icebreaker=2500; flat_block raw=STARTER_CAP=5000
        # day_pnl<=0 → min(5000, 2500)=2500
        signal = _make_signal()
        result = compute_size(signal, _state("-100"), self._flat_cfg(), MarketState.HOT, _WEDNESDAY)
        assert result == 2500


# ── Cushion / icebreaker caps ─────────────────────────────────────────────────

class TestCushionCaps:
    def test_negative_pnl_capped_at_icebreaker(self) -> None:
        # risk=0.10 → raw=10000; day_pnl=-50 → icebreaker=2500
        signal = _make_signal(entry="5.00", stop="4.90", target="6.10")
        result = compute_size(signal, _state("-50"), _cfg(), MarketState.HOT, _WEDNESDAY)
        assert result == 2500

    def test_zero_pnl_capped_at_icebreaker(self) -> None:
        # day_pnl=0 → icebreaker cap
        signal = _make_signal(entry="5.00", stop="4.90", target="6.10")
        result = compute_size(signal, _state("0"), _cfg(), MarketState.HOT, _WEDNESDAY)
        assert result == 2500

    def test_positive_pnl_below_threshold_caps_at_starter(self) -> None:
        # risk=0.05/sh → raw=20000; day_pnl=500 (pos, < 1000) → STARTER_CAP=5000
        signal = _make_signal(entry="5.00", stop="4.95", target="6.00")
        result = compute_size(signal, _state("500"), _cfg(), MarketState.HOT, _WEDNESDAY)
        assert result == 5000

    def test_past_threshold_no_starter_cap(self) -> None:
        # risk=0.10 → raw=10000; day_pnl=$1500 (>=$1000) → no cushion caps
        # conviction=1.0; HOT Wed; MAX_SIZE → 10000
        signal = _make_signal(entry="5.00", stop="4.90", target="6.10")
        result = compute_size(signal, _state("1500"), _cfg(), MarketState.HOT, _WEDNESDAY)
        assert result == 10000


# ── Conviction multiplier (spec §6) ──────────────────────────────────────────

class TestConvictionMultiplier:
    def test_full_conviction(self) -> None:
        # risk=0.10 → raw=10000; pnl=$2000 → no caps; conviction=1.0; HOT → 10000
        signal = _make_signal(entry="5.00", stop="4.90", target="6.10", conviction="1.0")
        result = compute_size(signal, _state("2000"), _cfg(), MarketState.HOT, _WEDNESDAY)
        assert result == 10000

    def test_quarter_conviction(self) -> None:
        # raw=10000; pnl=$2000; conviction=0.25 → floor(10000×0.25)=2500
        signal = _make_signal(entry="5.00", stop="4.90", target="6.10", conviction="0.25")
        result = compute_size(signal, _state("2000"), _cfg(), MarketState.HOT, _WEDNESDAY)
        assert result == 2500

    def test_half_conviction(self) -> None:
        # raw=2000; pnl=$2000; conviction=0.50 → floor(2000×0.50)=1000
        signal = _make_signal(entry="5.00", stop="4.50", target="6.00", conviction="0.50")
        result = compute_size(signal, _state("2000"), _cfg(), MarketState.HOT, _WEDNESDAY)
        assert result == 1000


# ── Day-of-week multipliers (spec §5) ────────────────────────────────────────

class TestDayOfWeek:
    def test_monday_half_size(self) -> None:
        # raw=2000; pnl=$2000; conviction=1.0; Monday → floor(2000×0.50)=1000
        signal = _make_signal(entry="5.00", stop="4.50", target="6.00")
        result = compute_size(signal, _state("2000"), _cfg(), MarketState.HOT, _MONDAY)
        assert result == 1000

    def test_friday_three_quarters(self) -> None:
        # raw=2000; pnl=$2000; conviction=1.0; Friday → floor(2000×0.75)=1500
        signal = _make_signal(entry="5.00", stop="4.50", target="6.00")
        result = compute_size(signal, _state("2000"), _cfg(), MarketState.HOT, _FRIDAY)
        assert result == 1500

    def test_wednesday_no_dow_mult(self) -> None:
        # Wednesday: no multiplier applied
        signal = _make_signal(entry="5.00", stop="4.50", target="6.00")
        result = compute_size(signal, _state("2000"), _cfg(), MarketState.HOT, _WEDNESDAY)
        assert result == 2000


# ── Market-state multipliers / caps (spec §8) ─────────────────────────────────

class TestMarketState:
    def test_hot_no_reduction(self) -> None:
        signal = _make_signal(entry="5.00", stop="4.50", target="6.00")
        result = compute_size(signal, _state("2000"), _cfg(), MarketState.HOT, _WEDNESDAY)
        assert result == 2000

    def test_cold_halves_size(self) -> None:
        # raw=2000; pnl=$2000; conviction=1.0; Wed; COLD → floor(2000×0.50)=1000
        signal = _make_signal(entry="5.00", stop="4.50", target="6.00")
        result = compute_size(signal, _state("2000"), _cfg(), MarketState.COLD, _WEDNESDAY)
        assert result == 1000

    def test_rehab_caps_at_rehab_cap(self) -> None:
        # raw=2000; pnl=$2000; conviction=1.0; Wed; REHAB → min(2000, REHAB_CAP=1000)=1000
        signal = _make_signal(entry="5.00", stop="4.50", target="6.00")
        result = compute_size(signal, _state("2000"), _cfg(), MarketState.REHAB, _WEDNESDAY)
        assert result == 1000

    def test_rehab_below_cap_not_reduced(self) -> None:
        # raw=500 (wide stop); REHAB_CAP=1000; min(500, 1000)=500
        signal = _make_signal(entry="5.00", stop="3.00", target="9.00")  # risk=2.00 → raw=500
        result = compute_size(signal, _state("2000"), _cfg(), MarketState.REHAB, _WEDNESDAY)
        assert result == 500


# ── Liquidity cap (U9) ────────────────────────────────────────────────────────

class TestLiquidityCap:
    def test_liquidity_cap_binds(self) -> None:
        # raw=2000; cap=500 → min(2000, 500)=500
        signal = _make_signal(entry="5.00", stop="4.50", target="6.00")
        result = compute_size(
            signal, _state("2000"), _cfg(), MarketState.HOT, _WEDNESDAY,
            liquidity_cap_shares=500,
        )
        assert result == 500

    def test_no_liquidity_cap_unconstrained(self) -> None:
        signal = _make_signal(entry="5.00", stop="4.50", target="6.00")
        result = compute_size(
            signal, _state("2000"), _cfg(), MarketState.HOT, _WEDNESDAY,
            liquidity_cap_shares=None,
        )
        assert result == 2000

    def test_zero_liquidity_cap_ignored(self) -> None:
        # A liquidity_cap of 0 should not clamp to 0 (0 means "unconstrained by data")
        signal = _make_signal(entry="5.00", stop="4.50", target="6.00")
        result = compute_size(
            signal, _state("2000"), _cfg(), MarketState.HOT, _WEDNESDAY,
            liquidity_cap_shares=0,
        )
        # 0 is falsy → ignored per spec; returns uncapped result
        assert result == 2000


# ── MAX_SIZE hard ceiling (C11) ───────────────────────────────────────────────

class TestMaxSizeCeiling:
    def test_never_exceeds_max_size(self) -> None:
        # Very narrow stop → huge raw; MAX_SIZE=10000 caps it
        signal = _make_signal(entry="5.00", stop="4.999", target="7.00")  # risk=0.001
        result = compute_size(signal, _state("2000"), _cfg(), MarketState.HOT, _WEDNESDAY)
        assert result == 10000
