"""Unit tests for U6 SimulatorGate.

Acceptance criteria (plan Phase 4 / spec §11 U6):
- Not satisfied initially (0 qualifying days)
- Satisfied after ≥10 consecutive qualifying days (≥60% accuracy each)
- Any below-threshold or zero-trade day resets the streak
- LIVE_ENABLED=false blocks live even when U6 satisfied
- LIVE_ENABLED=true allows live when satisfied
- Status summary reflects current state

spec §11 U6 / CLAUDE.md §4 U6.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

import pytest

from core.backtest.models import SimDay, TradeRecord
from core.backtest.sim_gate import SimulatorGate
from core.config import DEFAULTS, ConfigService, ValueType


# ── Helpers ───────────────────────────────────────────────────────────────────

def _cfg(overrides: dict[str, str] | None = None) -> ConfigService:
    rows = {d.key: (d.value, d.value_type) for d in DEFAULTS}
    for k, v in (overrides or {}).items():
        if k in rows:
            _, vt = rows[k]
            rows[k] = (v, vt)
    return ConfigService(rows)


def _cfg_live(live_enabled: bool = False, gate_days: int = 10) -> ConfigService:
    return _cfg({
        "LIVE_ENABLED": "true" if live_enabled else "false",
        "SIM_GATE_DAYS": str(gate_days),
        "SIM_GATE_ACCURACY": "0.60",
    })


def _trade(net_pnl: str, symbol: str = "X") -> TradeRecord:
    d = date(2024, 1, 15)
    ts = datetime(d.year, d.month, d.day, 9, 30)
    pnl = Decimal(net_pnl)
    entry = Decimal("5.00")
    exit_p = entry + pnl / Decimal("100")  # rough fill; exact values don't matter
    return TradeRecord(
        symbol=symbol,
        entry_ts=ts,
        exit_ts=ts,
        entry_price=entry,
        exit_price=max(exit_p, Decimal("0.01")),
        shares=100,
        gross_pnl=pnl + Decimal("1"),
        fees=Decimal("1"),
        net_pnl=pnl,
        r_multiple=Decimal("1.0") if pnl > Decimal("0") else Decimal("-1.0"),
        hold_seconds=300.0,
        exit_reason="scale_strength" if pnl > Decimal("0") else "hard_stop",
        risk_per_share=Decimal("0.50"),
    )


def _qualifying_day(d: date | None = None, wins: int = 3, losses: int = 1) -> SimDay:
    """Default: 3W / 1L = 75% accuracy — above 60% threshold."""
    day = SimDay(date=d or date(2024, 1, 15))
    for _ in range(wins):
        day.trades.append(_trade("50"))
    for _ in range(losses):
        day.trades.append(_trade("-30"))
    return day


def _failing_day(d: date | None = None) -> SimDay:
    """1W / 2L = 33% accuracy — below 60% threshold."""
    day = SimDay(date=d or date(2024, 1, 15))
    day.trades.append(_trade("50"))
    day.trades.append(_trade("-30"))
    day.trades.append(_trade("-30"))
    return day


def _zero_trade_day(d: date | None = None) -> SimDay:
    """No trades — accuracy = 0% — always fails gate."""
    return SimDay(date=d or date(2024, 1, 15))


# ── Initial state ──────────────────────────────────────────────────────────────

class TestInitialState:
    def test_not_satisfied_initially(self):
        gate = SimulatorGate(_cfg())
        assert not gate.satisfied

    def test_consecutive_days_zero_initially(self):
        gate = SimulatorGate(_cfg())
        assert gate.consecutive_qualifying_days == 0

    def test_live_not_allowed_initially(self):
        gate = SimulatorGate(_cfg_live(live_enabled=True))
        assert not gate.live_mode_allowed(_cfg_live(live_enabled=True))

    def test_status_not_met_initially(self):
        gate = SimulatorGate(_cfg())
        assert "NOT MET" in gate.status_summary


# ── Qualifying days accumulate ─────────────────────────────────────────────────

class TestAccumulation:
    def test_one_qualifying_day_not_satisfied(self):
        cfg = _cfg_live()
        gate = SimulatorGate(cfg)
        gate.record_day(_qualifying_day())
        assert not gate.satisfied

    def test_consecutive_count_increments(self):
        cfg = _cfg()
        gate = SimulatorGate(cfg)
        for i in range(5):
            gate.record_day(_qualifying_day(date(2024, 1, i + 1)))
        assert gate.consecutive_qualifying_days == 5

    def test_satisfied_after_ten_qualifying_days(self):
        cfg = _cfg_live()
        gate = SimulatorGate(cfg)
        for i in range(10):
            gate.record_day(_qualifying_day(date(2024, 1, i + 1)))
        assert gate.satisfied

    def test_satisfied_after_ten_with_gate_days_10(self):
        cfg = _cfg({"SIM_GATE_DAYS": "10", "SIM_GATE_ACCURACY": "0.60"})
        gate = SimulatorGate(cfg)
        for i in range(10):
            gate.record_day(_qualifying_day(date(2024, 1, i + 1)))
        assert gate.consecutive_qualifying_days >= 10
        assert gate.satisfied

    def test_nine_days_not_satisfied(self):
        cfg = _cfg_live()
        gate = SimulatorGate(cfg)
        for i in range(9):
            gate.record_day(_qualifying_day(date(2024, 1, i + 1)))
        assert not gate.satisfied


# ── Streak reset on failing day ────────────────────────────────────────────────

class TestStreakReset:
    def test_below_threshold_resets_streak(self):
        cfg = _cfg()
        gate = SimulatorGate(cfg)
        # Build 5 qualifying days
        for i in range(5):
            gate.record_day(_qualifying_day(date(2024, 1, i + 1)))
        assert gate.consecutive_qualifying_days == 5
        # Failing day resets
        gate.record_day(_failing_day(date(2024, 1, 10)))
        assert gate.consecutive_qualifying_days == 0
        assert not gate.satisfied

    def test_zero_trade_day_resets_streak(self):
        cfg = _cfg()
        gate = SimulatorGate(cfg)
        for i in range(7):
            gate.record_day(_qualifying_day(date(2024, 1, i + 1)))
        gate.record_day(_zero_trade_day(date(2024, 1, 10)))
        assert gate.consecutive_qualifying_days == 0

    def test_can_rebuild_after_reset(self):
        cfg = _cfg()
        gate = SimulatorGate(cfg)
        # 5 qualifying → fail → 10 more qualifying
        for i in range(5):
            gate.record_day(_qualifying_day(date(2024, 1, i + 1)))
        gate.record_day(_failing_day(date(2024, 1, 10)))
        for i in range(10):
            gate.record_day(_qualifying_day(date(2024, 2, i + 1)))
        assert gate.satisfied

    def test_reset_does_not_propagate_backwards(self):
        """After reset, further qualifying days count from zero."""
        cfg = _cfg()
        gate = SimulatorGate(cfg)
        for i in range(5):
            gate.record_day(_qualifying_day(date(2024, 1, i + 1)))
        gate.record_day(_failing_day(date(2024, 1, 10)))
        gate.record_day(_qualifying_day(date(2024, 1, 11)))
        assert gate.consecutive_qualifying_days == 1


# ── U6 live-mode gate ──────────────────────────────────────────────────────────

class TestLiveModeGate:
    def test_live_blocked_when_not_satisfied(self):
        cfg_live = _cfg_live(live_enabled=True)
        gate = SimulatorGate(cfg_live)
        gate.record_day(_qualifying_day())
        assert not gate.live_mode_allowed(cfg_live)

    def test_live_blocked_when_satisfied_but_live_disabled(self):
        """U6 satisfied but LIVE_ENABLED=false → still blocked."""
        cfg_off = _cfg_live(live_enabled=False)
        gate = SimulatorGate(cfg_off)
        for i in range(10):
            gate.record_day(_qualifying_day(date(2024, 1, i + 1)))
        assert gate.satisfied
        assert not gate.live_mode_allowed(cfg_off)

    def test_live_allowed_when_satisfied_and_live_enabled(self):
        """Both conditions: U6 satisfied AND LIVE_ENABLED=true."""
        cfg_on = _cfg_live(live_enabled=True)
        gate = SimulatorGate(cfg_on)
        for i in range(10):
            gate.record_day(_qualifying_day(date(2024, 1, i + 1)))
        assert gate.satisfied
        assert gate.live_mode_allowed(cfg_on)

    def test_live_disabled_by_default_config(self):
        """Default LIVE_ENABLED is 'false' — live mode must be explicitly enabled."""
        cfg_default = ConfigService.from_defaults()
        gate = SimulatorGate(cfg_default)
        for i in range(10):
            gate.record_day(_qualifying_day(date(2024, 1, i + 1)))
        assert gate.satisfied
        # Default config has LIVE_ENABLED=false
        assert not gate.live_mode_allowed(cfg_default)


# ── Custom gate thresholds ─────────────────────────────────────────────────────

class TestCustomThresholds:
    def test_custom_gate_days(self):
        """SIM_GATE_DAYS=5 satisfied after 5 days."""
        cfg = _cfg({"SIM_GATE_DAYS": "5", "SIM_GATE_ACCURACY": "0.60"})
        gate = SimulatorGate(cfg)
        for i in range(5):
            gate.record_day(_qualifying_day(date(2024, 1, i + 1)))
        assert gate.satisfied

    def test_custom_accuracy_threshold(self):
        """SIM_GATE_ACCURACY=0.80 means 75% accuracy fails."""
        cfg = _cfg({"SIM_GATE_DAYS": "5", "SIM_GATE_ACCURACY": "0.80"})
        gate = SimulatorGate(cfg)
        # _qualifying_day = 3W/1L = 75% — fails the 80% bar
        for i in range(5):
            gate.record_day(_qualifying_day(date(2024, 1, i + 1), wins=3, losses=1))
        # 75% < 80% threshold → none qualify
        assert not gate.satisfied

    def test_high_accuracy_qualifies(self):
        cfg = _cfg({"SIM_GATE_DAYS": "5", "SIM_GATE_ACCURACY": "0.80"})
        gate = SimulatorGate(cfg)
        for i in range(5):
            gate.record_day(_qualifying_day(date(2024, 1, i + 1), wins=9, losses=1))  # 90%
        assert gate.satisfied


# ── Status summary ─────────────────────────────────────────────────────────────

class TestStatusSummary:
    def test_not_met_summary(self):
        gate = SimulatorGate(_cfg())
        summary = gate.status_summary
        assert "NOT MET" in summary
        assert "0/" in summary

    def test_satisfied_summary(self):
        cfg = _cfg()
        gate = SimulatorGate(cfg)
        for i in range(10):
            gate.record_day(_qualifying_day(date(2024, 1, i + 1)))
        summary = gate.status_summary
        assert "SATISFIED" in summary

    def test_partial_progress_shown(self):
        cfg = _cfg()
        gate = SimulatorGate(cfg)
        for i in range(6):
            gate.record_day(_qualifying_day(date(2024, 1, i + 1)))
        summary = gate.status_summary
        assert "6/" in summary
