"""Tests for core.risk.pre_trade — evaluate_pre_trade() veto gate.

Every veto rule has a pass + fail test.
spec §5, §11 (U1–U5, U15, §7, §13.11).
"""

from __future__ import annotations

from datetime import datetime, time, timezone
from decimal import Decimal

import pytest

from adapters.providers import MarketState
from core.config import ConfigService, DEFAULTS, ValueType
from core.risk.models import RiskState, VetoReason
from core.risk.pre_trade import evaluate_pre_trade
from core.strategy.models import (
    EntryGateResult,
    EntrySignal,
    PatternType,
    PullbackContext,
)

# ── Helpers ───────────────────────────────────────────────────────────────────

_TS = datetime(2026, 6, 26, 13, 45, tzinfo=timezone.utc)  # 9:45 AM EDT
_EQUITY = Decimal("25000")
_EARLY = time(9, 45)   # well before 11:00 HARD_STOP_TIME
_AFTER = time(11, 1)   # one minute after 11:00


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
        ts=_TS,
        pattern=PatternType.MICRO_PULLBACK,
        conviction_score=Decimal(conviction),
        entry_price=Decimal(entry),
        stop_price=Decimal(stop),
        target_price=Decimal(target),
        gate=_make_gate(tier_b),
        market_state=market_state,
    )


def _make_cfg(**overrides: tuple[str, ValueType]) -> ConfigService:
    """Build ConfigService from defaults, optionally overriding specific keys."""
    rows = {d.key: (d.value, d.value_type) for d in DEFAULTS}
    rows.update(overrides)
    return ConfigService(rows)


def _cfg() -> ConfigService:
    return ConfigService.from_defaults()


# ── U1: Five-Pillar / Tier-B (spec §11 U1) ───────────────────────────────────

class TestU1FivePillar:
    def test_tier_b_pass(self) -> None:
        signal = _make_signal(tier_b=True)
        result = evaluate_pre_trade(signal, RiskState(), _cfg(), _EARLY, _EQUITY)
        assert VetoReason.NO_FIVE_PILLAR not in result

    def test_tier_b_fail(self) -> None:
        signal = _make_signal(tier_b=False)
        result = evaluate_pre_trade(signal, RiskState(), _cfg(), _EARLY, _EQUITY)
        assert VetoReason.NO_FIVE_PILLAR in result


# ── 2:1 Reward:risk minimum (spec §5 RR_RATIO) ───────────────────────────────

class TestRRMinimum:
    def test_rr_exactly_two_passes(self) -> None:
        # entry=5.00, stop=4.50, target=6.00 → risk=0.50, reward=1.00, rr=2.0
        signal = _make_signal(entry="5.00", stop="4.50", target="6.00")
        result = evaluate_pre_trade(signal, RiskState(), _cfg(), _EARLY, _EQUITY)
        assert VetoReason.RR_BELOW_MIN not in result

    def test_rr_above_two_passes(self) -> None:
        # entry=5.00, stop=4.50, target=6.50 → rr=3.0
        signal = _make_signal(entry="5.00", stop="4.50", target="6.50")
        result = evaluate_pre_trade(signal, RiskState(), _cfg(), _EARLY, _EQUITY)
        assert VetoReason.RR_BELOW_MIN not in result

    def test_rr_below_two_vetoed(self) -> None:
        # entry=5.00, stop=4.50, target=5.50 → risk=0.50, reward=0.50, rr=1.0
        signal = _make_signal(entry="5.00", stop="4.50", target="5.50")
        result = evaluate_pre_trade(signal, RiskState(), _cfg(), _EARLY, _EQUITY)
        assert VetoReason.RR_BELOW_MIN in result


# ── U4: Max daily loss (spec §5 C2) ──────────────────────────────────────────

class TestDailyLossLimit:
    def test_no_loss_passes(self) -> None:
        state = RiskState(realized_pnl=Decimal("0"))
        result = evaluate_pre_trade(_make_signal(), state, _cfg(), _EARLY, _EQUITY)
        assert VetoReason.DAILY_LOSS_LIMIT not in result

    def test_small_loss_passes(self) -> None:
        # effective_limit = min(25000×0.10=2500, avg_win=1000, lockout=5000) = 1000
        state = RiskState(realized_pnl=Decimal("-999"))
        result = evaluate_pre_trade(_make_signal(), state, _cfg(), _EARLY, _EQUITY)
        assert VetoReason.DAILY_LOSS_LIMIT not in result

    def test_avg_win_binding_vetoed(self) -> None:
        # effective = min(2500, 1000, 5000) = 1000; realized=-1001 → fired
        state = RiskState(realized_pnl=Decimal("-1001"))
        result = evaluate_pre_trade(_make_signal(), state, _cfg(), _EARLY, _EQUITY)
        assert VetoReason.DAILY_LOSS_LIMIT in result

    def test_pct_binding_vetoed(self) -> None:
        # Small account: equity=500, 10%=50; avg_win=1000, lockout=5000
        # effective = min(50, 1000, 5000) = 50
        state = RiskState(realized_pnl=Decimal("-51"))
        result = evaluate_pre_trade(_make_signal(), state, _cfg(), _EARLY, Decimal("500"))
        assert VetoReason.DAILY_LOSS_LIMIT in result

    def test_broker_lockout_binding_vetoed(self) -> None:
        # High avg_win so lockout binds: AVG_WIN_DAY_PNL=100000, pct=10%×large_equity=10000
        # lockout=5000 → effective = min(10000, 100000, 5000) = 5000
        cfg = _make_cfg(AVG_WIN_DAY_PNL=("100000.00", ValueType.DECIMAL))
        state = RiskState(realized_pnl=Decimal("-5001"))
        result = evaluate_pre_trade(_make_signal(), state, cfg, _EARLY, Decimal("100000"))
        assert VetoReason.DAILY_LOSS_LIMIT in result


# ── U4: Give-back hard stop (spec §5 C3) ─────────────────────────────────────

class TestGiveBackHard:
    def test_no_peak_no_giveback(self) -> None:
        # peak=0 → give-back check skipped entirely
        state = RiskState(realized_pnl=Decimal("0"), peak_pnl=Decimal("0"))
        result = evaluate_pre_trade(_make_signal(), state, _cfg(), _EARLY, _EQUITY)
        assert VetoReason.GIVE_BACK_HARD not in result

    def test_below_give_back_hard_threshold_passes(self) -> None:
        # peak=2000, realized=1200; give_back=(2000-1200)/2000=0.40 < 0.50
        state = RiskState(realized_pnl=Decimal("1200"), peak_pnl=Decimal("2000"))
        result = evaluate_pre_trade(_make_signal(), state, _cfg(), _EARLY, _EQUITY)
        assert VetoReason.GIVE_BACK_HARD not in result

    def test_at_give_back_hard_threshold_vetoed(self) -> None:
        # peak=2000, realized=1000; give_back=0.50 = GIVE_BACK_HARD → veto
        state = RiskState(realized_pnl=Decimal("1000"), peak_pnl=Decimal("2000"))
        result = evaluate_pre_trade(_make_signal(), state, _cfg(), _EARLY, _EQUITY)
        assert VetoReason.GIVE_BACK_HARD in result

    def test_above_give_back_hard_vetoed(self) -> None:
        # peak=2000, realized=800; give_back=0.60 > 0.50 → veto
        state = RiskState(realized_pnl=Decimal("800"), peak_pnl=Decimal("2000"))
        result = evaluate_pre_trade(_make_signal(), state, _cfg(), _EARLY, _EQUITY)
        assert VetoReason.GIVE_BACK_HARD in result


# ── U5: Three-strikes halt + session halt (spec §11 U5) ──────────────────────

class TestThreeStrikes:
    def test_zero_losses_passes(self) -> None:
        state = RiskState(consecutive_losses=0)
        result = evaluate_pre_trade(_make_signal(), state, _cfg(), _EARLY, _EQUITY)
        assert VetoReason.THREE_STRIKES not in result

    def test_below_strikes_passes(self) -> None:
        state = RiskState(consecutive_losses=2)
        result = evaluate_pre_trade(_make_signal(), state, _cfg(), _EARLY, _EQUITY)
        assert VetoReason.THREE_STRIKES not in result

    def test_at_three_strikes_vetoed(self) -> None:
        state = RiskState(consecutive_losses=3)
        result = evaluate_pre_trade(_make_signal(), state, _cfg(), _EARLY, _EQUITY)
        assert VetoReason.THREE_STRIKES in result

    def test_halted_fast_path(self) -> None:
        state = RiskState(halted=True, halt_reason="three_strikes")
        result = evaluate_pre_trade(_make_signal(), state, _cfg(), _EARLY, _EQUITY)
        assert result == [VetoReason.HALTED]  # only this veto; fast-path exits early


# ── U2: Never average down (spec §11 U2) ─────────────────────────────────────

class TestAverageDown:
    def test_no_open_position_passes(self) -> None:
        state = RiskState()
        result = evaluate_pre_trade(_make_signal(), state, _cfg(), _EARLY, _EQUITY)
        assert VetoReason.AVERAGE_DOWN not in result

    def test_entry_above_open_not_averaging_down(self) -> None:
        # Scaling into strength: not a U2 violation
        state = RiskState(open_positions={"TEST": Decimal("4.50")})
        signal = _make_signal(entry="5.00", stop="4.50", target="6.00")
        result = evaluate_pre_trade(signal, state, _cfg(), _EARLY, _EQUITY)
        assert VetoReason.AVERAGE_DOWN not in result

    def test_entry_below_open_vetoed(self) -> None:
        # Open at 5.50, trying to buy at 5.00 → red position add → U2
        state = RiskState(open_positions={"TEST": Decimal("5.50")})
        signal = _make_signal(entry="5.00", stop="4.50", target="6.00")
        result = evaluate_pre_trade(signal, state, _cfg(), _EARLY, _EQUITY)
        assert VetoReason.AVERAGE_DOWN in result

    def test_different_symbol_not_blocked(self) -> None:
        # AAPL position doesn't block TEST
        state = RiskState(open_positions={"AAPL": Decimal("5.50")})
        signal = _make_signal(symbol="TEST")
        result = evaluate_pre_trade(signal, state, _cfg(), _EARLY, _EQUITY)
        assert VetoReason.AVERAGE_DOWN not in result


# ── §13.11: PDT / max-trades-per-day ─────────────────────────────────────────

class TestPDTLimit:
    def test_no_trades_passes(self) -> None:
        state = RiskState(trades_today=0)
        result = evaluate_pre_trade(_make_signal(), state, _cfg(), _EARLY, _EQUITY)
        assert VetoReason.PDT_LIMIT not in result

    def test_at_max_trades_vetoed(self) -> None:
        # MAX_TRADES_PER_DAY=1 (default); trades_today=1 → vetoed
        state = RiskState(trades_today=1)
        result = evaluate_pre_trade(_make_signal(), state, _cfg(), _EARLY, _EQUITY)
        assert VetoReason.PDT_LIMIT in result

    def test_higher_max_trades_passes(self) -> None:
        cfg = _make_cfg(MAX_TRADES_PER_DAY=("5", ValueType.INT))
        state = RiskState(trades_today=4)
        result = evaluate_pre_trade(_make_signal(), state, cfg, _EARLY, _EQUITY)
        assert VetoReason.PDT_LIMIT not in result


# ── U15: SKIP-list catalyst (spec §11 U15) ───────────────────────────────────

class TestSkipCatalyst:
    def test_normal_catalyst_passes(self) -> None:
        result = evaluate_pre_trade(
            _make_signal(), RiskState(), _cfg(), _EARLY, _EQUITY, catalyst_skip=False
        )
        assert VetoReason.SKIP_CATALYST not in result

    def test_skip_catalyst_vetoed(self) -> None:
        # U15: buyout/secondary/recycled-PR/pump → SKIP
        result = evaluate_pre_trade(
            _make_signal(), RiskState(), _cfg(), _EARLY, _EQUITY, catalyst_skip=True
        )
        assert VetoReason.SKIP_CATALYST in result


# ── §7: Hard stop time ────────────────────────────────────────────────────────

class TestHardStopTime:
    def test_before_hard_stop_passes(self) -> None:
        # 09:45 < 11:00 → ok
        result = evaluate_pre_trade(
            _make_signal(), RiskState(), _cfg(), time(9, 45), _EQUITY
        )
        assert VetoReason.HARD_STOP_TIME not in result

    def test_exactly_at_hard_stop_passes(self) -> None:
        # 11:00 is NOT past (gate is strictly > not >=)
        result = evaluate_pre_trade(
            _make_signal(), RiskState(), _cfg(), time(11, 0), _EQUITY
        )
        assert VetoReason.HARD_STOP_TIME not in result

    def test_one_minute_past_hard_stop_vetoed(self) -> None:
        # 11:01 > 11:00 → HARD_STOP_TIME
        result = evaluate_pre_trade(
            _make_signal(), RiskState(), _cfg(), time(11, 1), _EQUITY
        )
        assert VetoReason.HARD_STOP_TIME in result


# ── Clean-state acceptance test ───────────────────────────────────────────────

class TestAllPass:
    def test_clean_state_no_vetoes(self) -> None:
        """Perfect setup with clean state must have zero vetoes."""
        cfg = _make_cfg(MAX_TRADES_PER_DAY=("10", ValueType.INT))
        signal = _make_signal()
        state = RiskState()
        result = evaluate_pre_trade(signal, state, cfg, _EARLY, _EQUITY)
        assert result == [], f"Unexpected vetoes: {result}"
