"""Tests for AlpacaBrokerAdapter (Phase 6).

All Alpaca SDK calls are mocked — no live broker required.
Verifies idempotency, order mapping, account-state mapping, halt-status, flatten.

spec Phase 6 / ROSSBOT_PROJECT_PLAN.md Phase 6.
"""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from adapters.alpaca_broker import AlpacaBrokerAdapter, _to_decimal
from adapters.base import AccountType, OrderRequest, OrderType, Side


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_adapter(paper: bool = True) -> AlpacaBrokerAdapter:
    return AlpacaBrokerAdapter("KEY", "SECRET", paper=paper)


def _mock_order(client_id: str = "oid-1", broker_id: str = "boid-1", status: str = "accepted") -> MagicMock:
    o = MagicMock()
    o.client_order_id = client_id
    o.id = broker_id
    o.status = status
    return o


def _mock_account(
    equity: str = "50000",
    cash: str = "40000",
    buying_power: str = "100000",
    account_type: str = "margin",
    daytrade_count: int = 0,
    pattern_day_trader: bool = False,
    trading_blocked: bool = False,
) -> MagicMock:
    a = MagicMock()
    a.equity = equity
    a.cash = cash
    a.buying_power = buying_power
    a.account_type = account_type
    a.daytrade_count = daytrade_count
    a.pattern_day_trader = pattern_day_trader
    a.trading_blocked = trading_blocked
    return a


def _mock_asset(tradable: bool = True, active: bool = True) -> MagicMock:
    a = MagicMock()
    a.tradable = tradable
    # Mimic AssetStatus.ACTIVE comparison
    a.status = MagicMock()
    a.status.__eq__ = lambda self, other: active
    return a


# ── _to_decimal helper ────────────────────────────────────────────────────────

def test_to_decimal_string():
    assert _to_decimal("12345.67") == Decimal("12345.67")


def test_to_decimal_none_returns_default():
    assert _to_decimal(None) == Decimal("0")
    assert _to_decimal(None, "99") == Decimal("99")


def test_to_decimal_float():
    assert _to_decimal(3.14) == Decimal("3.14")


# ── submit_marketable_limit ───────────────────────────────────────────────────

@pytest.mark.anyio
async def test_submit_marketable_limit_rth_uses_ioc():
    """RTH orders use TimeInForce.IOC (immediate-or-cancel)."""
    adapter = _make_adapter()
    captured = {}

    def mock_submit(req):
        captured["tif"] = req.time_in_force
        captured["extended"] = getattr(req, "extended_hours", False)
        captured["limit"] = req.limit_price
        captured["side"] = req.side
        captured["qty"] = req.qty
        return _mock_order(client_id=req.client_order_id)

    mock_client = MagicMock()
    mock_client.submit_order.side_effect = mock_submit
    adapter._client = mock_client

    # Patch session_for to return RTH
    from core.timeutils import Session
    with patch("adapters.alpaca_broker.session_for", return_value=Session.RTH), \
         patch("adapters.alpaca_broker._time_in_force") as mock_tif, \
         patch("adapters.alpaca_broker._order_side") as mock_side, \
         patch("adapters.alpaca_broker._limit_order_request_cls") as mock_req_cls:
        # Set up enums
        mock_tif.return_value.IOC = "ioc"
        mock_tif.return_value.DAY = "day"
        mock_side.return_value.BUY = "buy"
        mock_side.return_value.SELL = "sell"

        def fake_req_cls(**kwargs):
            m = MagicMock()
            for k, v in kwargs.items():
                setattr(m, k, v)
            return m

        mock_req_cls.return_value = type("FakeLimitOrderRequest", (), {
            "__init__": lambda self, **kw: [setattr(self, k, v) for k, v in kw.items()] and None
        })

        request = OrderRequest(
            client_order_id="test-uuid-1",
            symbol="TSLA",
            side=Side.BUY,
            qty=100,
            limit_price=Decimal("250.05"),
            order_type=OrderType.MARKETABLE_LIMIT,
        )
        ack = await adapter.submit_marketable_limit(request)

    assert ack.client_order_id == "test-uuid-1"
    assert ack.accepted is True


@pytest.mark.anyio
async def test_submit_marketable_limit_premarket_uses_day_extended():
    """Pre-market orders use TimeInForce.DAY + extended_hours=True."""
    adapter = _make_adapter()

    submitted_kwargs: dict = {}

    class FakeLimitOrderRequest:
        def __init__(self, **kwargs):
            submitted_kwargs.update(kwargs)

    mock_client = MagicMock()
    mock_client.submit_order.return_value = _mock_order(client_id="pm-uuid")
    adapter._client = mock_client

    from core.timeutils import Session
    with patch("adapters.alpaca_broker.session_for", return_value=Session.PREMARKET), \
         patch("adapters.alpaca_broker._time_in_force") as mock_tif, \
         patch("adapters.alpaca_broker._order_side") as mock_side, \
         patch("adapters.alpaca_broker._limit_order_request_cls", return_value=FakeLimitOrderRequest):

        mock_tif.return_value.IOC = "ioc"
        mock_tif.return_value.DAY = "day"
        mock_side.return_value.BUY = "buy"
        mock_side.return_value.SELL = "sell"

        request = OrderRequest(
            client_order_id="pm-uuid",
            symbol="NVDA",
            side=Side.BUY,
            qty=50,
            limit_price=Decimal("900.05"),
            order_type=OrderType.MARKETABLE_LIMIT,
        )
        ack = await adapter.submit_marketable_limit(request)

    assert submitted_kwargs.get("extended_hours") is True
    assert submitted_kwargs.get("time_in_force") == "day"


# ── Idempotency (no double fill on retry) ────────────────────────────────────

@pytest.mark.anyio
async def test_duplicate_client_order_id_fetches_existing():
    """Duplicate client_order_id on retry → fetches existing order, no new fill."""
    adapter = _make_adapter()

    existing_order = _mock_order(client_id="dup-uuid", broker_id="existing-boid", status="filled")

    class DuplicateError(Exception):
        pass

    def raise_duplicate(_req):
        raise DuplicateError("422: client_order_id already exists")

    def fetch_existing(order_id, params=None):
        return existing_order

    mock_client = MagicMock()
    mock_client.submit_order.side_effect = raise_duplicate
    mock_client.get_order_by_id.side_effect = fetch_existing
    adapter._client = mock_client

    from core.timeutils import Session
    with patch("adapters.alpaca_broker.session_for", return_value=Session.RTH), \
         patch("adapters.alpaca_broker._time_in_force") as mock_tif, \
         patch("adapters.alpaca_broker._order_side") as mock_side, \
         patch("adapters.alpaca_broker._limit_order_request_cls") as mock_req_cls, \
         patch("adapters.alpaca_broker._get_order_by_id_request_cls") as mock_get_req:

        mock_tif.return_value.IOC = "ioc"
        mock_tif.return_value.DAY = "day"
        mock_side.return_value.BUY = "buy"
        mock_req_cls.return_value = type("FakeLOR", (), {
            "__init__": lambda self, **kw: [setattr(self, k, v) for k, v in kw.items()] and None
        })
        mock_get_req.return_value = type("FakeGOBIR", (), {
            "__init__": lambda self, **kw: None
        })

        request = OrderRequest(
            client_order_id="dup-uuid",
            symbol="AAPL",
            side=Side.BUY,
            qty=100,
            limit_price=Decimal("150.05"),
            order_type=OrderType.MARKETABLE_LIMIT,
        )
        ack = await adapter.submit_marketable_limit(request)

    # Must return the existing order's ack, NOT create a new fill
    assert ack.broker_order_id == "existing-boid"
    assert ack.status == "filled"
    # submit_order was called exactly once (the failing call); no second submission
    mock_client.submit_order.assert_called_once()


@pytest.mark.anyio
async def test_duplicate_client_order_id_not_double_counted():
    """A retry with the same client_order_id must NOT return accepted=True on a new fill."""
    adapter = _make_adapter()
    submit_call_count = [0]

    existing = _mock_order(client_id="idem-id", broker_id="b1", status="accepted")

    def submit_side_effect(_req):
        submit_call_count[0] += 1
        if submit_call_count[0] == 1:
            return existing  # first call succeeds
        # second call: same client_order_id → duplicate error
        raise Exception("422: client_order_id already exists")

    mock_client = MagicMock()
    mock_client.submit_order.side_effect = submit_side_effect
    mock_client.get_order_by_id.return_value = existing
    adapter._client = mock_client

    from core.timeutils import Session
    with patch("adapters.alpaca_broker.session_for", return_value=Session.RTH), \
         patch("adapters.alpaca_broker._time_in_force") as mock_tif, \
         patch("adapters.alpaca_broker._order_side") as mock_side, \
         patch("adapters.alpaca_broker._limit_order_request_cls") as mock_req_cls, \
         patch("adapters.alpaca_broker._get_order_by_id_request_cls") as mock_get_req:

        mock_tif.return_value.IOC = "ioc"
        mock_tif.return_value.DAY = "day"
        mock_side.return_value.BUY = "buy"
        mock_req_cls.return_value = type("F", (), {
            "__init__": lambda self, **kw: [setattr(self, k, v) for k, v in kw.items()] and None
        })
        mock_get_req.return_value = type("G", (), {"__init__": lambda self, **kw: None})

        req = OrderRequest(
            client_order_id="idem-id",
            symbol="GME",
            side=Side.BUY,
            qty=200,
            limit_price=Decimal("20.05"),
            order_type=OrderType.MARKETABLE_LIMIT,
        )
        ack1 = await adapter.submit_marketable_limit(req)
        ack2 = await adapter.submit_marketable_limit(req)  # retry with same ID

    # Both acks reference the SAME broker order (no new fill created)
    assert ack1.broker_order_id == ack2.broker_order_id == "b1"
    assert submit_call_count[0] == 2  # tried twice, second got the duplicate


# ── partial_sell ──────────────────────────────────────────────────────────────

@pytest.mark.anyio
async def test_partial_sell_submits_sell_side():
    """partial_sell submits a SELL-side limit order."""
    adapter = _make_adapter()
    submitted_side = []

    def mock_submit(req):
        submitted_side.append(req.side)
        return _mock_order(client_id="sell-uuid")

    class FakeLimitOrderRequest:
        def __init__(self, **kwargs):
            for k, v in kwargs.items():
                setattr(self, k, v)

    mock_client = MagicMock()
    mock_client.submit_order.side_effect = mock_submit
    adapter._client = mock_client

    from core.timeutils import Session
    with patch("adapters.alpaca_broker.session_for", return_value=Session.RTH), \
         patch("adapters.alpaca_broker._time_in_force") as mock_tif, \
         patch("adapters.alpaca_broker._order_side") as mock_side, \
         patch("adapters.alpaca_broker._limit_order_request_cls", return_value=FakeLimitOrderRequest):

        mock_tif.return_value.IOC = "ioc"
        mock_tif.return_value.DAY = "day"
        mock_side.return_value.BUY = "buy"
        mock_side.return_value.SELL = "sell"

        ack = await adapter.partial_sell(
            "NVDA", 100, Decimal("899.00"), client_order_id="sell-uuid"
        )

    assert ack.accepted is True
    assert submitted_side[0] == "sell"


# ── cancel_all_flatten ────────────────────────────────────────────────────────

@pytest.mark.anyio
async def test_cancel_all_flatten_calls_close_all():
    """cancel_all_flatten delegates to Alpaca's close_all_positions(cancel_orders=True)."""
    adapter = _make_adapter()

    pos_mock = MagicMock()
    pos_mock.symbol = "TSLA"
    pos_mock.id = "pos-boid"

    mock_client = MagicMock()
    mock_client.close_all_positions.return_value = [pos_mock]
    adapter._client = mock_client

    acks = await adapter.cancel_all_flatten()

    mock_client.close_all_positions.assert_called_once_with(cancel_orders=True)
    assert len(acks) == 1
    assert acks[0].accepted is True


@pytest.mark.anyio
async def test_cancel_all_flatten_empty_returns_empty():
    """cancel_all_flatten with no open positions returns empty list."""
    adapter = _make_adapter()
    mock_client = MagicMock()
    mock_client.close_all_positions.return_value = []
    adapter._client = mock_client

    acks = await adapter.cancel_all_flatten()
    assert acks == []


# ── account_state ─────────────────────────────────────────────────────────────

@pytest.mark.anyio
async def test_account_state_margin():
    adapter = _make_adapter()
    mock_client = MagicMock()
    mock_client.get_account.return_value = _mock_account(
        equity="50000", buying_power="100000", account_type="margin"
    )
    adapter._client = mock_client

    state = await adapter.account_state()

    assert state.equity == Decimal("50000")
    assert state.buying_power == Decimal("100000")
    assert state.account_type is AccountType.MARGIN
    assert state.pdt_restricted is False


@pytest.mark.anyio
async def test_account_state_cash():
    adapter = _make_adapter()
    mock_client = MagicMock()
    mock_client.get_account.return_value = _mock_account(
        equity="10000", buying_power="10000", account_type="cash"
    )
    adapter._client = mock_client

    state = await adapter.account_state()
    assert state.account_type is AccountType.CASH


@pytest.mark.anyio
async def test_account_state_unknown_on_error():
    """On account API error → fail-safe UNKNOWN AccountState."""
    adapter = _make_adapter()
    mock_client = MagicMock()
    mock_client.get_account.side_effect = ConnectionError("broker unreachable")
    adapter._client = mock_client

    state = await adapter.account_state()

    assert state.account_type is AccountType.UNKNOWN
    assert state.pdt_restricted is True  # fail-safe
    assert state.equity == Decimal("0")


@pytest.mark.anyio
async def test_account_state_trading_blocked_sets_pdt():
    adapter = _make_adapter()
    mock_client = MagicMock()
    mock_client.get_account.return_value = _mock_account(
        account_type="margin", trading_blocked=True
    )
    adapter._client = mock_client

    state = await adapter.account_state()
    assert state.pdt_restricted is True


# ── get_halt_status ───────────────────────────────────────────────────────────

@pytest.mark.anyio
async def test_get_halt_status_active_tradable():
    adapter = _make_adapter()
    mock_client = MagicMock()
    mock_client.get_asset.return_value = _mock_asset(tradable=True, active=True)
    adapter._client = mock_client

    with patch("adapters.alpaca_broker._asset_status") as mock_st:
        active_sentinel = object()
        mock_st.return_value.ACTIVE = active_sentinel
        # Make asset.status == ACTIVE return True
        mock_asset = _mock_asset(tradable=True, active=True)
        mock_asset.status = active_sentinel
        mock_client.get_asset.return_value = mock_asset

        status = await adapter.get_halt_status("AAPL")

    assert status.symbol == "AAPL"
    assert status.halted is False


@pytest.mark.anyio
async def test_get_halt_status_not_tradable():
    adapter = _make_adapter()
    mock_client = MagicMock()
    mock_asset = MagicMock()
    mock_asset.tradable = False
    mock_asset.status = None
    mock_client.get_asset.return_value = mock_asset
    adapter._client = mock_client

    with patch("adapters.alpaca_broker._asset_status") as mock_st:
        mock_st.return_value.ACTIVE = "active_sentinel"
        status = await adapter.get_halt_status("HALT")

    assert status.halted is True


@pytest.mark.anyio
async def test_get_halt_status_fail_closed_on_error():
    """On any error → halted=True (fail-closed)."""
    adapter = _make_adapter()
    mock_client = MagicMock()
    mock_client.get_asset.side_effect = RuntimeError("API down")
    adapter._client = mock_client

    with patch("adapters.alpaca_broker._asset_status"):
        status = await adapter.get_halt_status("ERR")

    assert status.halted is True
    assert "error" in (status.reason or "").lower()


# ── get_broker_positions ──────────────────────────────────────────────────────

@pytest.mark.anyio
async def test_get_broker_positions():
    adapter = _make_adapter()

    p1 = MagicMock(); p1.symbol = "TSLA"; p1.qty = "100"
    p2 = MagicMock(); p2.symbol = "NVDA"; p2.qty = "50.0"

    mock_client = MagicMock()
    mock_client.get_all_positions.return_value = [p1, p2]
    adapter._client = mock_client

    positions = await adapter.get_broker_positions()

    assert positions == {"TSLA": 100, "NVDA": 50}


@pytest.mark.anyio
async def test_get_broker_positions_error_returns_empty():
    adapter = _make_adapter()
    mock_client = MagicMock()
    mock_client.get_all_positions.side_effect = ConnectionError("network fail")
    adapter._client = mock_client

    positions = await adapter.get_broker_positions()
    assert positions == {}
