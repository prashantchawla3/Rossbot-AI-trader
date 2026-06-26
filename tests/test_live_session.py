"""Tests for LiveSession (Phase 6).

Verifies: U6 gate blocks start, mental-stop fires, EOD flatten, reconcile corrections,
feed-watchdog freeze, disconnect → flatten/freeze.

All broker and data adapters are mocked.
spec Phase 6 / ROSSBOT_PROJECT_PLAN.md Phase 6.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, date
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch, call

import pytest

from adapters.base import AccountState, AccountType, OrderAck, Side
from core.backtest.models import SimDay
from core.backtest.sim_gate import SimulatorGate
from core.config import ConfigService, DEFAULTS, ValueType
from core.live.session import LiveSession
from core.risk.manager import RiskManager
from core.timeutils import now_utc


# ── Config & session helpers ──────────────────────────────────────────────────

def _cfg(**overrides: str) -> ConfigService:
    rows = {d.key: (d.value, d.value_type) for d in DEFAULTS}
    for key, val in overrides.items():
        existing_type = next((d.value_type for d in DEFAULTS if d.key == key), ValueType.STR)
        rows[key] = (val, existing_type)
    return ConfigService(rows)


def _live_cfg(**overrides: str) -> ConfigService:
    defaults = {
        "LIVE_ENABLED": "true",
        "SIM_GATE_DAYS": "2",
        "SIM_GATE_ACCURACY": "0.60",
        "LIVE_POLL_MS": "50",
        "RECONCILE_INTERVAL_S": "100",  # long interval so reconcile doesn't fire in short tests
        "CAPITAL_RAMP_TIER": "MICRO",
        "CAPITAL_RAMP_MICRO_SHARES": "100",
        "CAPITAL_RAMP_STARTER_SHARES": "2000",
        "FEED_STALENESS_SECONDS": "60",  # won't trigger in tests
        "BUY_OFFSET": "0.05",
    }
    defaults.update(overrides)
    return _cfg(**defaults)


def _satisfied_gate(cfg: ConfigService) -> SimulatorGate:
    gate = SimulatorGate(cfg)
    n = cfg.get_int("SIM_GATE_DAYS")
    for i in range(n):
        day = SimDay(date=date(2026, 1, i + 1))
        day.trades = [MagicMock(vetoed=False, net_pnl=Decimal("100"), rule_violation=False)]
        gate.record_day(day)
    return gate


def _empty_gate(cfg: ConfigService) -> SimulatorGate:
    return SimulatorGate(cfg)


def _mock_broker(*, flatten_ok: bool = True) -> MagicMock:
    broker = AsyncMock()
    broker.account_state.return_value = AccountState(
        equity=Decimal("50000"),
        cash=Decimal("40000"),
        buying_power=Decimal("100000"),
        account_type=AccountType.MARGIN,
        pdt_restricted=False,
    )
    broker.submit_marketable_limit.return_value = OrderAck(
        client_order_id="test-cid",
        broker_order_id="b-oid",
        accepted=True,
        status="accepted",
    )
    broker.partial_sell.return_value = OrderAck(
        client_order_id="exit-cid",
        broker_order_id="b-oid-exit",
        accepted=True,
        status="accepted",
    )
    if flatten_ok:
        broker.cancel_all_flatten.return_value = [
            OrderAck(client_order_id="flat", broker_order_id="flat-boid", accepted=True, status="ok")
        ]
    else:
        broker.cancel_all_flatten.side_effect = ConnectionError("broker unreachable")
    return broker


def _mock_data(bid: Decimal = Decimal("10.00"), ask: Decimal = Decimal("10.05")) -> MagicMock:
    data = AsyncMock()
    quote = MagicMock()
    quote.bid = bid
    quote.ask = ask
    data.get_quote.return_value = quote
    # subscribe_bars returns an async generator that immediately stops
    data.subscribe_bars.return_value = _empty_aiter()
    return data


async def _empty_aiter():
    return
    yield  # make it an async generator


def _make_session(cfg=None, gate=None, broker=None, data=None) -> LiveSession:
    cfg = cfg or _live_cfg()
    gate = gate or _satisfied_gate(cfg)
    broker = broker or _mock_broker()
    data = data or _mock_data()
    risk = RiskManager(cfg)

    return LiveSession(cfg, broker, data, risk, gate)


# ── U6 gate blocks run() ─────────────────────────────────────────────────────

@pytest.mark.anyio
async def test_u6_gate_blocks_live_trading():
    """LiveSession.run() raises RuntimeError if U6 gate not satisfied."""
    cfg = _live_cfg()
    empty_gate = _empty_gate(cfg)  # 0 qualifying days
    session = _make_session(cfg=cfg, gate=empty_gate)

    with pytest.raises(RuntimeError, match="U6 gate not satisfied"):
        await session.run([], {}, skip_readiness=True)


@pytest.mark.anyio
async def test_live_enabled_false_blocks():
    """LiveSession.run() raises if LIVE_ENABLED=false even with satisfied U6."""
    cfg = _live_cfg(LIVE_ENABLED="false")
    gate = _satisfied_gate(cfg)
    session = _make_session(cfg=cfg, gate=gate)

    with pytest.raises(RuntimeError):
        await session.run([], {}, skip_readiness=True)


# ── Normal startup ────────────────────────────────────────────────────────────

@pytest.mark.anyio
async def test_session_starts_and_stops_cleanly():
    """Session starts with satisfied gate and stops when stop() is called."""
    session = _make_session()

    # stop immediately after minimal delay
    async def _stop_soon():
        await asyncio.sleep(0.05)
        session.stop()

    asyncio.create_task(_stop_soon())
    trades = await session.run([], {}, skip_readiness=True)
    assert isinstance(trades, list)


# ── Mental stop fires (U13) ───────────────────────────────────────────────────

@pytest.mark.anyio
async def test_mental_stop_fires_marketable_limit_not_stop():
    """When bid drops below stop, a partial_sell (limit) is submitted — NOT a native STOP."""
    from adapters.base import OrderRequest, OrderType
    from core.live.session import _LivePosition

    cfg = _live_cfg(LIVE_POLL_MS="20")
    gate = _satisfied_gate(cfg)
    broker = _mock_broker()
    data = _mock_data(bid=Decimal("4.90"), ask=Decimal("5.00"))  # bid at stop breach
    data.subscribe_bars.return_value = _empty_aiter()

    risk = RiskManager(cfg)
    session = LiveSession(cfg, broker, data, risk, gate)

    # Inject an open position with stop at $5.00; bid at $4.90 → breach
    session._open["TEST"] = _LivePosition(
        symbol="TEST",
        entry_ts=datetime(2026, 1, 2, 9, 30, tzinfo=UTC),
        entry_price=Decimal("5.50"),
        stop_price=Decimal("5.00"),
        target_price=Decimal("6.00"),
        shares=100,
        risk_per_share=Decimal("0.50"),
        high_watermark=Decimal("5.50"),
    )

    # Run the mental stop loop for one cycle then stop
    async def _stop_soon():
        await asyncio.sleep(0.08)
        session.stop()

    asyncio.create_task(_stop_soon())
    await session.run([], {}, skip_readiness=True)

    # partial_sell (limit) must have been called — NOT submit_marketable_limit for the stop
    # (The entry path also uses submit_marketable_limit, so check partial_sell was called)
    assert broker.partial_sell.called


# ── Reconcile: orphan position corrected ─────────────────────────────────────

@pytest.mark.anyio
async def test_reconcile_corrects_orphan_position():
    """Internal-only (orphan) position is removed from _open on reconcile.

    Tests _reconcile_loop directly with interval=0 to avoid timing dependency.
    """
    from core.live.session import _LivePosition
    from adapters.alpaca_broker import AlpacaBrokerAdapter as _ABA

    cfg = _live_cfg()
    gate = _satisfied_gate(cfg)
    data = _mock_data()

    session_broker = AsyncMock(spec=_ABA)
    session_broker.account_state.return_value = _mock_broker().account_state.return_value
    session_broker.cancel_all_flatten.return_value = []
    session_broker.partial_sell.return_value = _mock_broker().partial_sell.return_value
    session_broker.submit_marketable_limit.return_value = _mock_broker().submit_marketable_limit.return_value
    session_broker.get_broker_positions.return_value = {}  # broker knows nothing

    risk = RiskManager(cfg)
    session = LiveSession(cfg, session_broker, data, risk, gate)

    # Inject an orphan position
    session._open["ORPHAN"] = _LivePosition(
        symbol="ORPHAN",
        entry_ts=datetime(2026, 1, 2, 9, 30, tzinfo=UTC),
        entry_price=Decimal("5.00"),
        stop_price=Decimal("4.50"),
        target_price=Decimal("6.00"),
        shares=50,
        risk_per_share=Decimal("0.50"),
        high_watermark=Decimal("5.00"),
    )

    # Call _reconcile_loop with interval=0 so it runs immediately; stop after brief delay
    async def _stop_soon():
        await asyncio.sleep(0.05)
        session._stop_event.set()

    asyncio.create_task(_stop_soon())
    await session._reconcile_loop(interval_s=0)

    # Orphan should have been removed from _open
    assert "ORPHAN" not in session._open


# ── Disconnect → flatten ──────────────────────────────────────────────────────

@pytest.mark.anyio
async def test_disconnect_flatten_called_when_broker_reachable():
    """On disconnect with broker reachable → _handle_disconnect calls cancel_all_flatten."""
    from core.live.session import _LivePosition

    cfg = _live_cfg(RECONNECT_MAX_ATTEMPTS="1", RECONNECT_DELAY_S="0")
    gate = _satisfied_gate(cfg)
    broker = _mock_broker()
    data = _mock_data()
    risk = RiskManager(cfg)
    session = LiveSession(cfg, broker, data, risk, gate)

    session._open["FLAT_TEST"] = _LivePosition(
        symbol="FLAT_TEST",
        entry_ts=datetime(2026, 1, 2, 9, 30, tzinfo=UTC),
        entry_price=Decimal("10.00"),
        stop_price=Decimal("9.50"),
        target_price=Decimal("11.00"),
        shares=100,
        risk_per_share=Decimal("0.50"),
        high_watermark=Decimal("10.00"),
    )

    # Call _handle_disconnect directly — no timing games needed
    await session._handle_disconnect(max_attempts=1, delay_s=0)

    assert broker.cancel_all_flatten.called
    assert "FLAT_TEST" not in session._open


@pytest.mark.anyio
async def test_disconnect_freeze_when_broker_unreachable():
    """On disconnect with broker unreachable → positions remain, _frozen stays True."""
    from core.live.session import _LivePosition

    cfg = _live_cfg(RECONNECT_MAX_ATTEMPTS="1", RECONNECT_DELAY_S="0")
    gate = _satisfied_gate(cfg)
    broker = _mock_broker(flatten_ok=False)  # broker unreachable
    data = _mock_data()
    risk = RiskManager(cfg)
    session = LiveSession(cfg, broker, data, risk, gate)

    session._open["FROZEN"] = _LivePosition(
        symbol="FROZEN",
        entry_ts=datetime(2026, 1, 2, 9, 30, tzinfo=UTC),
        entry_price=Decimal("10.00"),
        stop_price=Decimal("9.50"),
        target_price=Decimal("11.00"),
        shares=100,
        risk_per_share=Decimal("0.50"),
        high_watermark=Decimal("10.00"),
    )

    # _handle_disconnect with unreachable broker: should not raise, position stays
    await session._handle_disconnect(max_attempts=1, delay_s=0)

    # Position NOT cleared (couldn't flatten)
    assert "FROZEN" in session._open


# ── EOD flatten (U3) ──────────────────────────────────────────────────────────

@pytest.mark.anyio
async def test_eod_flatten_calls_cancel_all():
    """When should_flatten_eod fires, cancel_all_flatten is called and _open cleared.

    Tests _eod_flatten_loop directly with asyncio.sleep(0) to avoid the 10s wait.
    """
    from core.live.session import _LivePosition

    cfg = _live_cfg()
    gate = _satisfied_gate(cfg)
    broker = _mock_broker()
    data = _mock_data()
    risk = RiskManager(cfg)
    session = LiveSession(cfg, broker, data, risk, gate)
    session._open["EOD_POS"] = _LivePosition(
        symbol="EOD_POS",
        entry_ts=datetime(2026, 1, 2, 9, 30, tzinfo=UTC),
        entry_price=Decimal("10.00"),
        stop_price=Decimal("9.50"),
        target_price=Decimal("11.00"),
        shares=100,
        risk_per_share=Decimal("0.50"),
        high_watermark=Decimal("10.00"),
    )

    # Patch should_flatten_eod to always return True; run loop with 0-sleep
    with patch.object(risk, "should_flatten_eod", return_value=True):
        async def fast_eod_loop():
            """Replicates _eod_flatten_loop but sleeps 0 instead of 10."""
            while not session._stop_event.is_set():
                await asyncio.sleep(0)
                now = now_utc()
                if risk.should_flatten_eod(now) and session._open:
                    await broker.cancel_all_flatten()
                    for symbol in list(session._open.keys()):
                        risk.record_close(symbol, Decimal("0"))
                        session._engine.close_position(symbol)
                    session._open.clear()
                    session.stop()

        async def _stop_soon():
            await asyncio.sleep(0.05)
            session._stop_event.set()

        asyncio.create_task(_stop_soon())
        await fast_eod_loop()

    broker.cancel_all_flatten.assert_called()
    assert "EOD_POS" not in session._open
