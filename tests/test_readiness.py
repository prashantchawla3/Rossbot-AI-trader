"""Tests for ReadinessChecker pre-market gate (Phase 6).

spec Phase 6 / ROSSBOT_PROJECT_PLAN.md Phase 6 hard-gates.
"""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from adapters.base import AccountState, AccountType
from core.backtest.models import SimDay
from core.backtest.sim_gate import SimulatorGate
from core.config import ConfigService, DEFAULTS, ValueType
from core.live.readiness import ReadinessChecker


# ── Fixtures ──────────────────────────────────────────────────────────────────

def _cfg(**overrides: str) -> ConfigService:
    rows = {d.key: (d.value, d.value_type) for d in DEFAULTS}
    for key, val in overrides.items():
        existing_type = next((d.value_type for d in DEFAULTS if d.key == key), ValueType.STR)
        rows[key] = (val, existing_type)
    return ConfigService(rows)


def _satisfied_gate(cfg: ConfigService) -> SimulatorGate:
    """Build a SimulatorGate that already satisfies U6."""
    gate = SimulatorGate(cfg)
    for i in range(cfg.get_int("SIM_GATE_DAYS")):
        gate.record_day(SimDay(
            date=__import__("datetime").date(2026, 1, i + 1),
            trades=[MagicMock(vetoed=False, net_pnl=Decimal("100"), rule_violation=False)],
        ))
    return gate


def _live_cfg(**overrides: str) -> ConfigService:
    base = {
        "LIVE_ENABLED": "true",
        "CAPITAL_RAMP_TIER": "MICRO",
        "READINESS_MIN_BUYING_POWER": "5000.00",
        "READINESS_MIN_EQUITY": "25000.00",
        "CLOCK_DRIFT_MAX_MS": "500",
    }
    base.update(overrides)
    return _cfg(**base)


def _good_account() -> AccountState:
    return AccountState(
        equity=Decimal("50000"),
        cash=Decimal("40000"),
        buying_power=Decimal("100000"),
        account_type=AccountType.MARGIN,
        day_trade_count=0,
        pdt_restricted=False,
    )


def _make_checker(cfg=None, gate=None, account=None, quote_ok=True):
    cfg = cfg or _live_cfg()
    gate = gate or _satisfied_gate(cfg)

    broker = AsyncMock()
    broker.account_state.return_value = account or _good_account()

    data = AsyncMock()
    if quote_ok:
        mock_quote = MagicMock()
        mock_quote.bid = Decimal("400.00")
        mock_quote.ask = Decimal("400.05")
        data.get_quote.return_value = mock_quote
    else:
        data.get_quote.side_effect = ConnectionError("feed offline")

    return ReadinessChecker(cfg, gate, broker, data)


# ── all_passed ────────────────────────────────────────────────────────────────

@pytest.mark.anyio
async def test_all_checks_pass():
    checker = _make_checker()
    with patch("core.live.readiness.asyncio.to_thread", new_callable=AsyncMock) as mock_thread:
        ntp_resp = MagicMock()
        ntp_resp.offset = 0.01  # 10ms drift — well within 500ms
        mock_thread.return_value = ntp_resp
        result = await checker.check_all()

    assert result.all_passed, result.summary()


# ── LIVE_ENABLED check ────────────────────────────────────────────────────────

@pytest.mark.anyio
async def test_live_enabled_false_fails():
    checker = _make_checker(cfg=_live_cfg(LIVE_ENABLED="false"))
    with patch("core.live.readiness.asyncio.to_thread", new_callable=AsyncMock) as mock_thread:
        ntp_resp = MagicMock(); ntp_resp.offset = 0.01
        mock_thread.return_value = ntp_resp
        result = await checker.check_all()

    assert not result.all_passed
    assert "LIVE_ENABLED" in result.failed_names()


# ── U6 gate ───────────────────────────────────────────────────────────────────

@pytest.mark.anyio
async def test_u6_gate_not_satisfied_fails():
    cfg = _live_cfg()
    # Empty gate (0 qualifying days)
    empty_gate = SimulatorGate(cfg)
    checker = _make_checker(cfg=cfg, gate=empty_gate)

    with patch("core.live.readiness.asyncio.to_thread", new_callable=AsyncMock) as mock_thread:
        ntp_resp = MagicMock(); ntp_resp.offset = 0.01
        mock_thread.return_value = ntp_resp
        result = await checker.check_all()

    assert not result.all_passed
    assert "U6_GATE" in result.failed_names()


# ── Account type ─────────────────────────────────────────────────────────────

@pytest.mark.anyio
async def test_account_type_unknown_fails():
    unknown_account = AccountState(
        equity=Decimal("50000"),
        cash=Decimal("40000"),
        buying_power=Decimal("100000"),
        account_type=AccountType.UNKNOWN,
        pdt_restricted=True,
    )
    checker = _make_checker(account=unknown_account)

    with patch("core.live.readiness.asyncio.to_thread", new_callable=AsyncMock) as mock_thread:
        ntp_resp = MagicMock(); ntp_resp.offset = 0.01
        mock_thread.return_value = ntp_resp
        result = await checker.check_all()

    assert not result.all_passed
    assert "ACCOUNT_TYPE" in result.failed_names()


# ── Buying power ──────────────────────────────────────────────────────────────

@pytest.mark.anyio
async def test_buying_power_below_minimum_fails():
    low_bp_account = AccountState(
        equity=Decimal("50000"),
        cash=Decimal("1000"),
        buying_power=Decimal("1000"),  # below 5000 minimum
        account_type=AccountType.MARGIN,
        pdt_restricted=False,
    )
    checker = _make_checker(account=low_bp_account)

    with patch("core.live.readiness.asyncio.to_thread", new_callable=AsyncMock) as mock_thread:
        ntp_resp = MagicMock(); ntp_resp.offset = 0.01
        mock_thread.return_value = ntp_resp
        result = await checker.check_all()

    assert not result.all_passed
    assert "BUYING_POWER" in result.failed_names()


# ── Clock drift ───────────────────────────────────────────────────────────────

@pytest.mark.anyio
async def test_clock_drift_too_high_fails():
    checker = _make_checker(cfg=_live_cfg(CLOCK_DRIFT_MAX_MS="500"))

    with patch("core.live.readiness.asyncio.to_thread", new_callable=AsyncMock) as mock_thread:
        ntp_resp = MagicMock()
        ntp_resp.offset = 1.0  # 1000ms = above 500ms threshold
        mock_thread.return_value = ntp_resp
        result = await checker.check_all()

    assert not result.all_passed
    assert "CLOCK_DRIFT" in result.failed_names()


@pytest.mark.anyio
async def test_clock_drift_ok():
    checker = _make_checker(cfg=_live_cfg(CLOCK_DRIFT_MAX_MS="500"))

    with patch("core.live.readiness.asyncio.to_thread", new_callable=AsyncMock) as mock_thread:
        ntp_resp = MagicMock()
        ntp_resp.offset = 0.1  # 100ms — within 500ms
        mock_thread.return_value = ntp_resp
        result = await checker.check_all()

    # Other checks might fail (not the focus here); just verify CLOCK_DRIFT passes
    clock_items = [i for i in result.items if i.name == "CLOCK_DRIFT"]
    assert clock_items[0].passed


# ── Data feed ─────────────────────────────────────────────────────────────────

@pytest.mark.anyio
async def test_data_feed_offline_fails():
    checker = _make_checker(quote_ok=False)

    with patch("core.live.readiness.asyncio.to_thread", new_callable=AsyncMock) as mock_thread:
        ntp_resp = MagicMock(); ntp_resp.offset = 0.01
        mock_thread.return_value = ntp_resp
        result = await checker.check_all()

    assert "DATA_FEED" in result.failed_names()


# ── Capital tier ──────────────────────────────────────────────────────────────

@pytest.mark.anyio
async def test_unknown_capital_tier_fails():
    checker = _make_checker(cfg=_live_cfg(CAPITAL_RAMP_TIER="INVALID"))

    with patch("core.live.readiness.asyncio.to_thread", new_callable=AsyncMock) as mock_thread:
        ntp_resp = MagicMock(); ntp_resp.offset = 0.01
        mock_thread.return_value = ntp_resp
        result = await checker.check_all()

    assert "CAPITAL_TIER" in result.failed_names()


# ── All checks run independently (no fail-fast) ───────────────────────────────

@pytest.mark.anyio
async def test_all_checks_run_even_if_first_fails():
    """All checks run even when LIVE_ENABLED fails — we want the full picture."""
    cfg = _live_cfg(
        LIVE_ENABLED="false",  # will fail
        CAPITAL_RAMP_TIER="INVALID",  # will also fail
    )
    empty_gate = SimulatorGate(cfg)  # U6 also fails
    checker = _make_checker(cfg=cfg, gate=empty_gate)

    with patch("core.live.readiness.asyncio.to_thread", new_callable=AsyncMock) as mock_thread:
        ntp_resp = MagicMock(); ntp_resp.offset = 0.01
        mock_thread.return_value = ntp_resp
        result = await checker.check_all()

    # Must have exactly 8 items (all checks ran)
    assert len(result.items) == 8
    failed = result.failed_names()
    assert "LIVE_ENABLED" in failed
    assert "U6_GATE" in failed
    assert "CAPITAL_TIER" in failed


# ── ReadinessResult ───────────────────────────────────────────────────────────

def test_readiness_result_all_passed():
    from core.live.models import ReadinessItem, ReadinessResult
    items = (
        ReadinessItem("A", True, "ok"),
        ReadinessItem("B", True, "ok"),
    )
    result = ReadinessResult(items=items)
    assert result.all_passed
    assert result.failed_names() == []
    assert "OK" in result.summary()


def test_readiness_result_some_failed():
    from core.live.models import ReadinessItem, ReadinessResult
    items = (
        ReadinessItem("A", True, "ok"),
        ReadinessItem("U6_GATE", False, "not met"),
    )
    result = ReadinessResult(items=items)
    assert not result.all_passed
    assert result.failed_names() == ["U6_GATE"]
    assert "FAILED" in result.summary()
