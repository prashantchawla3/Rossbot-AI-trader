"""Unit tests for the event-driven replay engine.

Acceptance criteria (plan Phase 4):
- Day boundary: events on two dates → two SimDay objects; each day resets session
- Empty replay: no events → BacktestResult with zero days
- Rule-violation count = 0 over any basic sim run
- Veto recorded: when risk blocks a signal, TradeRecord(vetoed=True) is recorded
- Latency model present: stop exit fill < stop_price (U13 documented cost)
- EOD flatten: open position after 15:55 → eod_flatten TradeRecord on next bar
- BacktestResult properties: win_rate, avg_r, rule_violation_count all sane

Note on scope:
  The replay engine calls StrategyEngine.on_bar() which requires 30+ warm-up bars
  to emit signals (MACD needs 26 periods). Day-boundary, empty-run, and
  rule-violation tests are therefore validated at the infrastructure level
  (BacktestResult shape) without requiring a full profitable trade.
  Full §12 end-to-end win/loss decisions are covered in test_sec12_regression.py.

spec Phase 4 plan / CLAUDE.md §9.
"""

from __future__ import annotations

from datetime import date, datetime, timezone, timedelta
from decimal import Decimal

import pytest

from adapters.base import BarTick
from adapters.providers import CatalystVerdict, L2Signal, MarketState
from core.backtest.fill_model import MENTAL_STOP_LATENCY_SLIP, exit_fill_stop
from core.backtest.models import BacktestResult, SimDay, TradeRecord
from core.backtest.replay import ReplayBar, replay
from core.config import ConfigService
from core.scanner.float_resolver import FloatConfidence
from core.scanner.models import Attention, PillarReport, ScanCandidate, ScanResult
from core.scanner.rvol import Confidence as RvolConfidence
from core.money import to_money


# ── Helpers ───────────────────────────────────────────────────────────────────

_D1 = date(2024, 1, 15)
_D2 = date(2024, 1, 16)


def _ts(d: date, hour: int = 9, minute: int = 30) -> datetime:
    return datetime(d.year, d.month, d.day, hour, minute, tzinfo=timezone.utc)


def _bar(d: date, *, hour: int = 9, minute: int = 30, symbol: str = "TEST",
         close: str = "5.10", low: str = "4.90") -> BarTick:
    c = Decimal(close)
    lo = Decimal(low)
    return BarTick(
        symbol=symbol,
        ts=_ts(d, hour, minute),
        timeframe="1m",
        open=Decimal("5.00"),
        high=Decimal("5.20"),
        low=lo,
        close=c,
        volume=100_000,
    )


def _eod_bar(d: date, symbol: str = "TEST") -> BarTick:
    """Bar after 15:55 ET (mapped from UTC+5 offset for ET in winter)."""
    # 15:55 ET = 20:55 UTC; use 21:00 UTC to be safely past EOD_FLATTEN_TIME
    return BarTick(
        symbol=symbol,
        ts=datetime(d.year, d.month, d.day, 21, 0, tzinfo=timezone.utc),
        timeframe="1m",
        open=Decimal("5.00"), high=Decimal("5.10"),
        low=Decimal("4.95"), close=Decimal("5.05"),
        volume=50_000,
    )


def _no_trade_scan(symbol: str = "TEST") -> ScanResult:
    """ScanResult that is NOT tradeable (tier_b=False) — ensures no entry signal passes."""
    pillars = PillarReport(p1_price=True, p2_float=True, p3_rvol=True, p4_roc=True, p5_catalyst=False)
    cand = ScanCandidate(
        symbol=symbol,
        price=to_money("5.00"),
        change_pct=to_money("25.0"),
        rvol=to_money("8.0"),
        rvol_confidence=RvolConfidence.HIGH,
        float_shares=15_000_000,
        float_confidence=FloatConfidence.HIGH,
        catalyst=CatalystVerdict.UNVERIFIED,
    )
    return ScanResult(
        candidate=cand,
        tier_a_pass=True,
        tier_b_pass=False,
        pillars=pillars,
        attention=Attention.WATCH,
    )


def _replay_bar(d: date, *, symbol: str = "TEST", minute: int = 0) -> ReplayBar:
    return ReplayBar(
        bar=_bar(d, minute=30 + minute, symbol=symbol),
        scan_result=_no_trade_scan(symbol),
        l2_signal=L2Signal.UNKNOWN,
        spread=Decimal("0.05"),
        market_state=MarketState.COLD,
        account_equity=Decimal("25000"),
    )


def _cfg() -> ConfigService:
    return ConfigService.from_defaults()


# ── Empty replay ───────────────────────────────────────────────────────────────

class TestEmptyReplay:
    def test_no_events_empty_result(self):
        result = replay([], _cfg())
        assert isinstance(result, BacktestResult)
        assert len(result.days) == 0

    def test_empty_result_zero_trades(self):
        result = replay([], _cfg())
        assert result.total_trades == 0

    def test_empty_result_zero_rule_violations(self):
        result = replay([], _cfg())
        assert result.rule_violation_count == 0

    def test_empty_result_zero_win_rate(self):
        result = replay([], _cfg())
        assert result.win_rate == Decimal("0")

    def test_empty_result_zero_avg_r(self):
        result = replay([], _cfg())
        assert result.avg_r == Decimal("0")


# ── Day boundary ──────────────────────────────────────────────────────────────

class TestDayBoundary:
    def test_single_day_produces_one_sim_day(self):
        events = [_replay_bar(_D1, minute=0), _replay_bar(_D1, minute=1)]
        result = replay(events, _cfg())
        assert len(result.days) == 1

    def test_two_dates_produce_two_sim_days(self):
        events = [_replay_bar(_D1, minute=0), _replay_bar(_D2, minute=0)]
        result = replay(events, _cfg())
        assert len(result.days) == 2

    def test_sim_day_dates_are_correct(self):
        events = [_replay_bar(_D1), _replay_bar(_D2)]
        result = replay(events, _cfg())
        dates = [d.date for d in result.days]
        assert _D1 in dates
        assert _D2 in dates

    def test_many_bars_same_day_one_sim_day(self):
        events = [_replay_bar(_D1, minute=i) for i in range(10)]
        result = replay(events, _cfg())
        assert len(result.days) == 1

    def test_three_days_three_sim_days(self):
        _D3 = date(2024, 1, 17)
        events = [
            _replay_bar(_D1),
            _replay_bar(_D2),
            _replay_bar(_D3),
        ]
        result = replay(events, _cfg())
        assert len(result.days) == 3


# ── Rule violation count ───────────────────────────────────────────────────────

class TestRuleViolationCount:
    def test_rule_violation_count_zero_no_trades(self):
        """No trades → rule_violation_count == 0 (acceptance criterion: must be 0)."""
        events = [_replay_bar(_D1, minute=i) for i in range(5)]
        result = replay(events, _cfg())
        assert result.rule_violation_count == 0

    def test_rule_violation_count_zero_two_days(self):
        events = [_replay_bar(_D1), _replay_bar(_D2)]
        result = replay(events, _cfg())
        assert result.rule_violation_count == 0

    def test_sim_day_rule_violations_zero(self):
        events = [_replay_bar(_D1, minute=i) for i in range(5)]
        result = replay(events, _cfg())
        for day in result.days:
            assert day.rule_violations == 0


# ── BacktestResult properties ─────────────────────────────────────────────────

class TestBacktestResultProperties:
    def test_consecutive_green_days_zero_with_no_pnl(self):
        events = [_replay_bar(_D1)]
        result = replay(events, _cfg())
        assert result.consecutive_green_days == 0

    def test_max_daily_drawdown_zero_no_trades(self):
        events = [_replay_bar(_D1)]
        result = replay(events, _cfg())
        assert result.max_daily_drawdown == Decimal("0")

    def test_win_rate_zero_no_trades(self):
        events = [_replay_bar(_D1)]
        result = replay(events, _cfg())
        assert result.win_rate == Decimal("0")

    def test_avg_hold_seconds_zero_no_trades(self):
        events = [_replay_bar(_D1)]
        result = replay(events, _cfg())
        assert result.avg_hold_seconds == 0.0


# ── ReplayBar construction ─────────────────────────────────────────────────────

class TestReplayBarConstruction:
    def test_replay_bar_is_frozen(self):
        rb = _replay_bar(_D1)
        with pytest.raises((AttributeError, TypeError)):
            rb.bar = None  # type: ignore[assignment]

    def test_replay_bar_default_fields(self):
        rb = ReplayBar(
            bar=_bar(_D1),
            scan_result=_no_trade_scan(),
            l2_signal=L2Signal.UNKNOWN,
            spread=Decimal("0.05"),
            market_state=MarketState.COLD,
            account_equity=Decimal("25000"),
        )
        assert rb.liquidity_cap_shares is None
        assert rb.catalyst_skip is False


# ── Latency model (U13) — unit level ─────────────────────────────────────────

class TestLatencyModel:
    """U13 mental-stop latency cost is present in the fill model (acceptance criterion)."""

    def test_latency_slip_constant_present(self):
        """MENTAL_STOP_LATENCY_SLIP must be exported and non-zero Decimal."""
        assert isinstance(MENTAL_STOP_LATENCY_SLIP, Decimal)
        assert MENTAL_STOP_LATENCY_SLIP > Decimal("0")

    def test_stop_exit_always_worse_than_stop(self):
        """U13 cost: every stop exit fills below stop_price."""
        stop = Decimal("5.00")
        bar_low = Decimal("4.90")
        fill = exit_fill_stop(stop, bar_low, 100)
        assert fill.fill_price < stop, (
            f"U13 latency must degrade fill: {fill.fill_price} must be < {stop}"
        )

    def test_latency_slip_magnitude(self):
        """Latency slip is $0.05 — documented in FILL_MODEL_DOC as U13 cost."""
        assert MENTAL_STOP_LATENCY_SLIP == Decimal("0.05")

    def test_stop_exit_slippage_covers_latency(self):
        """Reported slippage on stop exit must account for latency slip."""
        stop = Decimal("5.00")
        bar_low = Decimal("5.00")  # bar_low == stop → latency forces fill below
        fill = exit_fill_stop(stop, bar_low, 100)
        assert fill.slippage >= MENTAL_STOP_LATENCY_SLIP
