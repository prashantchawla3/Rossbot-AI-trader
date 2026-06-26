"""Integration tests for core.risk.manager — RiskManager (the mandatory gate).

Tests the stateful RiskManager class: pre-trade evaluation, sizing, state
lifecycle (record_open / record_close / reset_session), live monitors.
spec §5/§6/§7/§8/§11 (U1–U15).
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from adapters.providers import MarketState
from core.config import ConfigService, DEFAULTS, ValueType
from core.risk import GiveBackLevel, RiskManager, VetoReason
from core.risk.models import RiskState
from core.strategy.models import (
    EntryGateResult,
    EntrySignal,
    PatternType,
    PositionSnapshot,
    PullbackContext,
)

# ── Helpers ───────────────────────────────────────────────────────────────────

# June 24, 2026 = Wednesday (day_of_week=2 → no DOW multiplier).
# 13:45 UTC = 9:45 AM EDT; well before 11:00 HARD_STOP_TIME.
_NOW_EARLY = datetime(2026, 6, 24, 13, 45, tzinfo=timezone.utc)
# 15:30 UTC = 11:30 AM EDT (past hard stop)
_NOW_PAST = datetime(2026, 6, 24, 15, 30, tzinfo=timezone.utc)
# 19:55 UTC = 15:55 EDT (EOD flatten time)
_NOW_EOD = datetime(2026, 6, 24, 19, 55, tzinfo=timezone.utc)

_EQUITY = Decimal("25000")


def _make_gate(tier_b: bool = True) -> EntryGateResult:
    return EntryGateResult(
        passes=tier_b,
        e1_universe=tier_b,
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
    tier_b: bool = True,
    conviction: str = "1.0",
    symbol: str = "TEST",
    market_state: MarketState = MarketState.HOT,
) -> EntrySignal:
    return EntrySignal(
        symbol=symbol,
        ts=_NOW_EARLY,
        pattern=PatternType.MICRO_PULLBACK,
        conviction_score=Decimal(conviction),
        entry_price=Decimal(entry),
        stop_price=Decimal(stop),
        target_price=Decimal(target),
        gate=_make_gate(tier_b),
        market_state=market_state,
    )


def _make_cfg(**overrides: tuple[str, ValueType]) -> ConfigService:
    rows = {d.key: (d.value, d.value_type) for d in DEFAULTS}
    # Raise MAX_TRADES_PER_DAY for tests that aren't testing PDT
    rows["MAX_TRADES_PER_DAY"] = ("100", ValueType.INT)
    rows.update(overrides)
    return ConfigService(rows)


def _make_manager(**cfg_overrides: tuple[str, ValueType]) -> RiskManager:
    return RiskManager(_make_cfg(**cfg_overrides))


def _make_position(entry: str = "5.00", stop: str = "4.50") -> PositionSnapshot:
    return PositionSnapshot(
        symbol="TEST",
        entry_price=Decimal(entry),
        current_stop=Decimal(stop),
        target_price=Decimal("6.00"),
        shares=2000,
        entry_ts=_NOW_EARLY,
        high_watermark=Decimal(entry),
    )


# ── evaluate(): happy path ────────────────────────────────────────────────────

class TestEvaluateHappyPath:
    def test_clean_state_approved_with_shares(self) -> None:
        mgr = _make_manager()
        result = mgr.evaluate(_make_signal(), _NOW_EARLY, _EQUITY)
        assert result.approved is True
        assert result.shares > 0
        assert result.vetoes == ()

    def test_returns_nonzero_shares(self) -> None:
        mgr = _make_manager()
        result = mgr.evaluate(_make_signal(), _NOW_EARLY, _EQUITY)
        # Default: risk=0.50, PER_TRADE=1000, raw=2000; pnl=0→icebreaker=2500 → 2000
        assert result.shares == 2000

    def test_cold_market_reduces_shares(self) -> None:
        mgr = _make_manager()
        # COLD: raw=2000, pnl=0 → icebreaker=2500 → min(2000,2500)=2000
        # Then conviction=1.0, no DOW, COLD → floor(2000×0.50)=1000
        signal = _make_signal(market_state=MarketState.COLD)
        result = mgr.evaluate(signal, _NOW_EARLY, _EQUITY)
        assert result.approved is True
        assert result.shares == 1000


# ── evaluate(): pre-trade vetoes ─────────────────────────────────────────────

class TestEvaluateVetoes:
    def test_halted_session_returns_halted_veto(self) -> None:
        mgr = _make_manager()
        mgr.halt_session("test")
        result = mgr.evaluate(_make_signal(), _NOW_EARLY, _EQUITY)
        assert result.approved is False
        assert VetoReason.HALTED in result.vetoes

    def test_u1_no_tier_b(self) -> None:
        mgr = _make_manager()
        result = mgr.evaluate(_make_signal(tier_b=False), _NOW_EARLY, _EQUITY)
        assert result.approved is False
        assert VetoReason.NO_FIVE_PILLAR in result.vetoes

    def test_rr_below_min(self) -> None:
        # entry=5.00, stop=4.50, target=5.50 → rr=1.0 < 2.0
        mgr = _make_manager()
        signal = _make_signal(target="5.50")
        result = mgr.evaluate(signal, _NOW_EARLY, _EQUITY)
        assert result.approved is False
        assert VetoReason.RR_BELOW_MIN in result.vetoes

    def test_past_hard_stop_time(self) -> None:
        mgr = _make_manager()
        result = mgr.evaluate(_make_signal(), _NOW_PAST, _EQUITY)
        assert result.approved is False
        assert VetoReason.HARD_STOP_TIME in result.vetoes

    def test_skip_catalyst(self) -> None:
        mgr = _make_manager()
        result = mgr.evaluate(_make_signal(), _NOW_EARLY, _EQUITY, catalyst_skip=True)
        assert result.approved is False
        assert VetoReason.SKIP_CATALYST in result.vetoes

    def test_sizing_zero_returns_sizing_zero_veto(self) -> None:
        # PER_TRADE_RISK=$1.00 with risk=$4.99/sh → floor(1.00/4.99)=0 → SIZING_ZERO.
        # rr=(10.00/4.99)≈2.0 passes the RR gate so sizing is reached.
        cfg = _make_cfg(PER_TRADE_RISK_DOLLARS=("1.00", ValueType.DECIMAL))
        mgr = RiskManager(cfg)
        signal = _make_signal(entry="5.00", stop="0.01", target="15.00")
        result = mgr.evaluate(signal, _NOW_EARLY, _EQUITY)
        assert result.approved is False
        assert VetoReason.SIZING_ZERO in result.vetoes


# ── record_open / record_close lifecycle ─────────────────────────────────────

class TestPositionLifecycle:
    def test_record_open_tracks_position(self) -> None:
        mgr = _make_manager()
        mgr.record_open("TEST", Decimal("5.00"))
        assert "TEST" in mgr.state.open_positions
        assert mgr.state.open_positions["TEST"] == Decimal("5.00")

    def test_record_open_increments_trades_today(self) -> None:
        mgr = _make_manager()
        assert mgr.state.trades_today == 0
        mgr.record_open("TEST", Decimal("5.00"))
        assert mgr.state.trades_today == 1

    def test_record_close_removes_from_open(self) -> None:
        mgr = _make_manager()
        mgr.record_open("TEST", Decimal("5.00"))
        mgr.record_close("TEST", Decimal("200"))
        assert "TEST" not in mgr.state.open_positions

    def test_record_close_win_updates_pnl(self) -> None:
        mgr = _make_manager()
        mgr.record_open("TEST", Decimal("5.00"))
        mgr.record_close("TEST", Decimal("500"))
        assert mgr.state.realized_pnl == Decimal("500")

    def test_record_close_loss_updates_pnl(self) -> None:
        mgr = _make_manager()
        mgr.record_open("TEST", Decimal("5.00"))
        mgr.record_close("TEST", Decimal("-200"))
        assert mgr.state.realized_pnl == Decimal("-200")

    def test_record_close_win_updates_peak(self) -> None:
        mgr = _make_manager()
        mgr.record_open("TEST", Decimal("5.00"))
        mgr.record_close("TEST", Decimal("1000"))
        assert mgr.state.peak_pnl == Decimal("1000")

    def test_peak_does_not_fall_on_loss(self) -> None:
        mgr = _make_manager()
        mgr.record_open("A", Decimal("5.00"))
        mgr.record_close("A", Decimal("1000"))   # peak=1000
        mgr.record_open("B", Decimal("5.00"))
        mgr.record_close("B", Decimal("-200"))   # pnl=800, but peak stays 1000
        assert mgr.state.peak_pnl == Decimal("1000")
        assert mgr.state.realized_pnl == Decimal("800")


# ── Three-strikes / halt ──────────────────────────────────────────────────────

class TestThreeStrikes:
    def test_consecutive_loss_increments_streak(self) -> None:
        mgr = _make_manager()
        mgr.record_open("A", Decimal("5")); mgr.record_close("A", Decimal("-100"))
        mgr.record_open("B", Decimal("5")); mgr.record_close("B", Decimal("-100"))
        assert mgr.state.consecutive_losses == 2
        assert mgr.state.halted is False

    def test_three_consecutive_losses_halt(self) -> None:
        mgr = _make_manager()
        for sym in ["A", "B", "C"]:
            mgr.record_open(sym, Decimal("5"))
            mgr.record_close(sym, Decimal("-100"))
        assert mgr.state.consecutive_losses == 3
        assert mgr.state.halted is True
        assert mgr.state.halt_reason == "three_strikes"

    def test_win_resets_consecutive_losses(self) -> None:
        mgr = _make_manager()
        mgr.record_open("A", Decimal("5")); mgr.record_close("A", Decimal("-100"))
        mgr.record_open("B", Decimal("5")); mgr.record_close("B", Decimal("-100"))
        mgr.record_open("C", Decimal("5")); mgr.record_close("C", Decimal("500"))  # WIN
        assert mgr.state.consecutive_losses == 0
        assert mgr.state.halted is False

    def test_four_losses_stays_halted(self) -> None:
        # Once halted at 3, a 4th loss doesn't un-halt
        mgr = _make_manager()
        for sym in ["A", "B", "C", "D"]:
            mgr.record_open(sym, Decimal("5"))
            mgr.record_close(sym, Decimal("-100"))
        assert mgr.state.halted is True


# ── reset_session ─────────────────────────────────────────────────────────────

class TestResetSession:
    def test_reset_clears_all_state(self) -> None:
        mgr = _make_manager()
        # Build up state
        for sym in ["A", "B", "C"]:
            mgr.record_open(sym, Decimal("5"))
            mgr.record_close(sym, Decimal("-100"))
        assert mgr.state.halted is True

        # Reset
        mgr.reset_session()
        assert mgr.state.realized_pnl == Decimal("0")
        assert mgr.state.peak_pnl == Decimal("0")
        assert mgr.state.consecutive_losses == 0
        assert mgr.state.trades_today == 0
        assert mgr.state.halted is False
        assert mgr.state.halt_reason is None
        assert mgr.state.open_positions == {}

    def test_after_reset_evaluate_approved(self) -> None:
        mgr = _make_manager()
        for sym in ["A", "B", "C"]:
            mgr.record_open(sym, Decimal("5"))
            mgr.record_close(sym, Decimal("-100"))
        mgr.reset_session()
        result = mgr.evaluate(_make_signal(), _NOW_EARLY, _EQUITY)
        assert result.approved is True


# ── Live monitors ─────────────────────────────────────────────────────────────

class TestLiveMonitors:
    def test_mental_stop_not_breached(self) -> None:
        mgr = _make_manager()
        pos = _make_position(stop="4.50")
        assert mgr.check_mental_stop(Decimal("4.51"), pos) is False

    def test_mental_stop_breached(self) -> None:
        mgr = _make_manager()
        pos = _make_position(stop="4.50")
        assert mgr.check_mental_stop(Decimal("4.50"), pos) is True

    def test_give_back_none_at_start(self) -> None:
        mgr = _make_manager()
        assert mgr.check_give_back() == GiveBackLevel.NONE

    def test_give_back_warn_after_peak_then_loss(self) -> None:
        mgr = _make_manager()
        mgr.record_open("A", Decimal("5"))
        mgr.record_close("A", Decimal("1000"))   # peak=1000
        mgr.record_open("B", Decimal("5"))
        mgr.record_close("B", Decimal("-300"))   # realized=700; give_back=0.30 >= 0.25
        assert mgr.check_give_back() == GiveBackLevel.WARN

    def test_give_back_halt_after_large_loss(self) -> None:
        mgr = _make_manager()
        mgr.record_open("A", Decimal("5"))
        mgr.record_close("A", Decimal("1000"))   # peak=1000
        mgr.record_open("B", Decimal("5"))
        mgr.record_close("B", Decimal("-600"))   # realized=400; give_back=0.60 >= 0.50
        assert mgr.check_give_back() == GiveBackLevel.HALT

    def test_check_daily_loss_not_triggered(self) -> None:
        mgr = _make_manager()
        assert mgr.check_daily_loss(_EQUITY) is False

    def test_check_daily_loss_triggered(self) -> None:
        mgr = _make_manager()
        mgr.record_open("A", Decimal("5"))
        mgr.record_close("A", Decimal("-1001"))  # past effective limit of 1000
        assert mgr.check_daily_loss(_EQUITY) is True

    def test_eod_flatten_before_time_false(self) -> None:
        mgr = _make_manager()
        assert mgr.should_flatten_eod(_NOW_EARLY) is False

    def test_eod_flatten_at_time_true(self) -> None:
        mgr = _make_manager()
        assert mgr.should_flatten_eod(_NOW_EOD) is True


# ── halt_session (kill-switch) ────────────────────────────────────────────────

class TestHaltSession:
    def test_halt_session_sets_halted(self) -> None:
        mgr = _make_manager()
        mgr.halt_session("daily_loss")
        assert mgr.state.halted is True
        assert mgr.state.halt_reason == "daily_loss"

    def test_evaluate_after_halt_returns_halted_veto(self) -> None:
        mgr = _make_manager()
        mgr.halt_session("manual_kill")
        result = mgr.evaluate(_make_signal(), _NOW_EARLY, _EQUITY)
        assert result.approved is False
        assert VetoReason.HALTED in result.vetoes


# ── Liquidity cap integration ─────────────────────────────────────────────────

class TestLiquidityCapIntegration:
    def test_liquidity_cap_applied_in_evaluate(self) -> None:
        mgr = _make_manager()
        # No cushion (pnl=0), risk=0.50 → raw=2000 → icebreaker=2500 → 2000
        # liquidity_cap=500 → min(2000, 500) = 500
        result = mgr.evaluate(_make_signal(), _NOW_EARLY, _EQUITY, liquidity_cap_shares=500)
        assert result.approved is True
        assert result.shares == 500
