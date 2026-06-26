"""Tests for core.compliance — PDT guard, wash-sale tracker, SSR, startup gate. spec §13.11.

Acceptance criteria:
  - PDT: round-trip count enforces MAX_TRADES_PER_DAY; cash accounts cap at 1.
  - Wash-sale: flags re-entry within 30 days of a loss; ignores winners.
  - SSR: fires at ≥10% down from prior close; zero effect on longs.
  - LULD bands: correct %% for each price tier.
  - Startup gate: blocks UNKNOWN account type; blocks zero buying power;
                  cash → MAX_TRADES capped at 1; margin check warns if equity low.

NOTE: PDT rule eliminated June 4, 2026 (FINRA Rule 4210 amendment).
The $25k minimum requirement is NO LONGER ACTIVE. MAX_TRADES_PER_DAY from config
is the conservative guard. Tests reflect the CURRENT regulatory framework.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pytest

from adapters.base import AccountState, AccountType
from core.compliance.pdt import PDTGuard
from core.compliance.ssr import is_ssr_active, luld_band_pct, luld_bands
from core.compliance.startup_gate import evaluate_startup_compliance
from core.compliance.wash_sale import WashSaleTracker
from core.config import ConfigService


# ── Helpers ───────────────────────────────────────────────────────────────────


def _cfg(max_trades: int = 3) -> ConfigService:
    svc = ConfigService.from_defaults()
    svc._rows["MAX_TRADES_PER_DAY"] = (str(max_trades), svc._rows["MAX_TRADES_PER_DAY"][1])
    return svc


def _acct(
    acct_type: AccountType = AccountType.MARGIN,
    equity: str = "50000",
    buying_power: str = "50000",
) -> AccountState:
    return AccountState(
        equity=Decimal(equity),
        cash=Decimal(equity),
        buying_power=Decimal(buying_power),
        account_type=acct_type,
        day_trade_count=0,
        pdt_restricted=False,
    )


_TODAY = date(2026, 6, 26)


# ── PDTGuard ─────────────────────────────────────────────────────────────────


class TestPDTGuard:
    def test_first_round_trip_allowed(self) -> None:
        guard = PDTGuard()
        cfg = _cfg(max_trades=3)
        ok, _ = guard.can_trade(cfg, AccountType.MARGIN)
        assert ok is True

    def test_max_trades_enforced(self) -> None:
        """After MAX_TRADES_PER_DAY round-trips, trading is blocked."""
        guard = PDTGuard()
        cfg = _cfg(max_trades=3)
        # Simulate 3 completed round-trips
        for i in range(3):
            guard.record_open(f"SYM{i}", 100)
            guard.record_close(f"SYM{i}", 100)
        ok, reason = guard.can_trade(cfg, AccountType.MARGIN)
        assert ok is False
        assert "3/3" in reason

    def test_cash_account_capped_at_1(self) -> None:
        """Cash account: T+1 restriction caps MAX_TRADES at 1 regardless of config."""
        guard = PDTGuard()
        cfg = _cfg(max_trades=3)  # config says 3 but cash overrides
        guard.record_open("AAPL", 100)
        guard.record_close("AAPL", 100)
        ok, reason = guard.can_trade(cfg, AccountType.CASH)
        assert ok is False
        assert "CASH" in reason or "cash" in reason.lower()

    def test_partial_close_no_round_trip(self) -> None:
        """Partial close of 200-share position by 50 shares — round-trip NOT counted."""
        guard = PDTGuard()
        cfg = _cfg(max_trades=3)
        guard.record_open("MLGO", 200)
        guard.record_close("MLGO", 50)  # 150 shares still open
        assert guard.round_trips_today == 0
        ok, _ = guard.can_trade(cfg, AccountType.MARGIN)
        assert ok is True

    def test_full_close_increments_round_trip(self) -> None:
        guard = PDTGuard()
        guard.record_open("XYZ", 100)
        guard.record_close("XYZ", 100)
        assert guard.round_trips_today == 1

    def test_reset_clears_state(self) -> None:
        guard = PDTGuard()
        cfg = _cfg(max_trades=1)
        guard.record_open("A", 100)
        guard.record_close("A", 100)
        guard.reset_session()
        ok, _ = guard.can_trade(cfg, AccountType.MARGIN)
        assert ok is True

    def test_no_blocking_before_max_hit(self) -> None:
        """Two round-trips with max_trades=3 → still allowed."""
        guard = PDTGuard()
        cfg = _cfg(max_trades=3)
        for i in range(2):
            guard.record_open(f"S{i}", 100)
            guard.record_close(f"S{i}", 100)
        ok, _ = guard.can_trade(cfg, AccountType.MARGIN)
        assert ok is True


# ── WashSaleTracker ───────────────────────────────────────────────────────────


class TestWashSaleTracker:
    def test_no_risk_when_no_history(self) -> None:
        tracker = WashSaleTracker()
        at_risk, _ = tracker.check_wash_sale_risk("AAPL", _TODAY)
        assert at_risk is False

    def test_winner_not_recorded(self) -> None:
        tracker = WashSaleTracker()
        tracker.record_loss("AAPL", _TODAY - timedelta(days=5), Decimal("500.00"))  # WIN
        at_risk, _ = tracker.check_wash_sale_risk("AAPL", _TODAY)
        assert at_risk is False

    def test_loss_within_30_days_flags_risk(self) -> None:
        tracker = WashSaleTracker()
        loss_date = _TODAY - timedelta(days=15)
        tracker.record_loss("SLXN", loss_date, Decimal("-250.00"))
        at_risk, msg = tracker.check_wash_sale_risk("SLXN", _TODAY)
        assert at_risk is True
        assert "SLXN" in msg
        assert "15" in msg  # 15 days ago

    def test_loss_older_than_30_days_no_risk(self) -> None:
        tracker = WashSaleTracker()
        loss_date = _TODAY - timedelta(days=31)
        tracker.record_loss("MLGO", loss_date, Decimal("-100.00"))
        at_risk, _ = tracker.check_wash_sale_risk("MLGO", _TODAY)
        assert at_risk is False

    def test_same_day_loss_and_reentry_flags(self) -> None:
        """Intraday loss + re-entry on same day = wash-sale risk (IRS ruling)."""
        tracker = WashSaleTracker()
        tracker.record_loss("CTRM", _TODAY, Decimal("-50.00"))
        at_risk, _ = tracker.check_wash_sale_risk("CTRM", _TODAY)
        assert at_risk is True

    def test_different_symbol_no_risk(self) -> None:
        tracker = WashSaleTracker()
        tracker.record_loss("AAPL", _TODAY - timedelta(days=5), Decimal("-100.00"))
        at_risk, _ = tracker.check_wash_sale_risk("GOOG", _TODAY)
        assert at_risk is False

    def test_case_insensitive(self) -> None:
        tracker = WashSaleTracker()
        tracker.record_loss("aapl", _TODAY - timedelta(days=10), Decimal("-200.00"))
        at_risk, _ = tracker.check_wash_sale_risk("AAPL", _TODAY)
        assert at_risk is True

    def test_purge_clears_old_records(self) -> None:
        tracker = WashSaleTracker()
        tracker.record_loss("XYZ", _TODAY - timedelta(days=35), Decimal("-100.00"))
        tracker.purge_before(_TODAY)
        at_risk, _ = tracker.check_wash_sale_risk("XYZ", _TODAY)
        assert at_risk is False


# ── SSR & LULD ────────────────────────────────────────────────────────────────


class TestSSR:
    def test_ssr_fires_at_exactly_10pct_down(self) -> None:
        prior = Decimal("10.00")
        current = Decimal("9.00")  # exactly -10%
        assert is_ssr_active(current, prior) is True

    def test_ssr_fires_when_more_than_10pct_down(self) -> None:
        assert is_ssr_active(Decimal("8.00"), Decimal("10.00")) is True

    def test_ssr_does_not_fire_when_less_than_10pct_down(self) -> None:
        assert is_ssr_active(Decimal("9.10"), Decimal("10.00")) is False

    def test_ssr_does_not_fire_when_up(self) -> None:
        assert is_ssr_active(Decimal("11.00"), Decimal("10.00")) is False

    def test_ssr_zero_prior_close_returns_false(self) -> None:
        """Avoid div-by-zero with missing prior close."""
        assert is_ssr_active(Decimal("5.00"), Decimal("0")) is False


class TestLULDBands:
    def test_tier2_above_3_dollars(self) -> None:
        """Most NMS stocks ≥$3 have ±5% bands."""
        pct = luld_band_pct(Decimal("10.00"))
        assert pct == Decimal("5")

    def test_tier2_0_75_to_3_dollars(self) -> None:
        """$0.75–$3.00: ±20% band."""
        pct = luld_band_pct(Decimal("2.00"))
        assert pct == Decimal("20")

    def test_below_0_75_dollars(self) -> None:
        """Below $0.75: ±75% band."""
        pct = luld_band_pct(Decimal("0.50"))
        assert pct == Decimal("75")

    def test_near_close_doubles_band_for_sub_3(self) -> None:
        """Last 25 min: bands double for stocks ≤$3."""
        pct_normal = luld_band_pct(Decimal("2.00"))
        pct_close = luld_band_pct(Decimal("2.00"), near_close=True)
        assert pct_close == pct_normal * 2

    def test_near_close_no_change_for_above_3(self) -> None:
        """Last 25 min: no change for stocks > $3 (only ≤$3 doubles)."""
        pct_normal = luld_band_pct(Decimal("10.00"))
        pct_close = luld_band_pct(Decimal("10.00"), near_close=True)
        assert pct_close == pct_normal

    def test_luld_bands_symmetrical(self) -> None:
        price = Decimal("5.00")
        lower, upper = luld_bands(price)
        assert lower == Decimal("4.75")  # 5% below $5.00
        assert upper == Decimal("5.25")  # 5% above $5.00


# ── StartupComplianceGate ────────────────────────────────────────────────────


class TestStartupComplianceGate:
    def test_margin_with_sufficient_equity_passes(self) -> None:
        result = evaluate_startup_compliance(
            _acct(AccountType.MARGIN, equity="50000", buying_power="50000"),
            _cfg(),
        )
        assert result.passed is True
        assert result.effective_max_trades == 3

    def test_unknown_account_type_fails(self) -> None:
        result = evaluate_startup_compliance(
            _acct(AccountType.UNKNOWN, buying_power="10000"),
            _cfg(),
        )
        assert result.passed is False
        assert any("UNKNOWN" in r for r in result.reasons)

    def test_zero_buying_power_fails(self) -> None:
        result = evaluate_startup_compliance(
            _acct(AccountType.MARGIN, buying_power="0"),
            _cfg(),
        )
        assert result.passed is False
        assert any("BUYING_POWER" in r for r in result.reasons)

    def test_negative_buying_power_fails(self) -> None:
        result = evaluate_startup_compliance(
            _acct(AccountType.MARGIN, buying_power="-500"),
            _cfg(),
        )
        assert result.passed is False

    def test_cash_account_caps_max_trades_at_1(self) -> None:
        """Cash account: T+1 → effective_max_trades = 1 regardless of config."""
        result = evaluate_startup_compliance(
            _acct(AccountType.CASH, buying_power="10000"),
            _cfg(max_trades=3),
        )
        assert result.passed is True
        assert result.effective_max_trades == 1
        assert any("CASH" in w.upper() for w in result.warnings)

    def test_margin_low_equity_warns_not_blocks(self) -> None:
        """Margin account with equity < READINESS_MIN_EQUITY gets a warning, not a block.

        PDT rule eliminated 2026-06-04; $25k is no longer a hard regulatory gate.
        The warning remains as a capital safety floor check.
        """
        result = evaluate_startup_compliance(
            _acct(AccountType.MARGIN, equity="10000", buying_power="10000"),
            _cfg(),
        )
        # Should PASS (not a hard block post PDT elimination)
        assert result.passed is True
        # But should carry a warning about capital floor
        assert any("equity" in w.lower() or "READINESS" in w for w in result.warnings)

    def test_result_includes_account_type_and_equity(self) -> None:
        result = evaluate_startup_compliance(
            _acct(AccountType.MARGIN, equity="75000", buying_power="75000"),
            _cfg(),
        )
        assert result.account_type == AccountType.MARGIN
        assert result.equity == Decimal("75000")
