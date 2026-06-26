"""Alpaca live/paper broker adapter — executes orders via alpaca-py TradingClient.

verified: alpaca-py 0.43.4, docs.alpaca.markets / alpaca.markets/sdks/python (2026-06)

Key SDK paths:
  TradingClient(api_key, secret_key, paper=False)
  LimitOrderRequest(symbol, qty, side, limit_price, time_in_force,
                    extended_hours, client_order_id)
  TimeInForce: DAY (extended-hours capable with extended_hours=True), IOC (RTH only)
  get_all_positions()  → list[Position]  (.symbol, .qty str, .avg_entry_price str)
  close_all_positions(cancel_orders=True) → cancel open orders + flatten all (kill-switch)
  get_account()        → TradeAccount  (.equity str, .buying_power str, .cash str,
                          .pattern_day_trader bool, .daytrade_count int,
                          .trading_blocked bool)
  get_asset(symbol)    → Asset  (.tradable bool, .status AssetStatus)
  get_order_by_id(id, GetOrderByIdRequest(by='client_order_id'))  → Order
  Paper base URL: https://paper-api.alpaca.markets (sdk handles via paper=True flag)

Idempotency: if the same client_order_id is submitted twice while the order is active,
Alpaca returns HTTP 422. We catch this and fetch the existing order instead of creating
a duplicate. This means a retry on disconnect CANNOT double-fill.

NOTES / LIMITATIONS (NEEDS-VERIFY on live broker):
- extended_hours=True is ONLY valid with time_in_force=DAY. IOC in pre-market is rejected
  by Alpaca → we switch to DAY when session is PREMARKET or AFTERHOURS.
- Alpaca's close_all_positions uses market orders internally. This is accepted ONLY for the
  emergency cancel_all_flatten kill-switch (U7 is relaxed for emergency-only operations).
  All normal entries and exits use limit orders (U7/U13).
- get_halt_status uses get_asset() which does NOT detect intraday LULD halts — that
  requires a real-time halt feed (Polygon/Databento). Flag shown in HaltStatus.reason.
- Market-data SIP feed requires Algo Trader Plus subscription ($99/mo as of 2026).
  Basic plan provides IEX only (free) which is INSUFFICIENT for scanning (REQUIRE_SIP=true).

spec Phase 6 plan / ROSSBOT_PROJECT_PLAN.md Phase 6.
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from datetime import datetime
from decimal import Decimal
from typing import Any

from adapters.base import (
    AccountState,
    AccountType,
    BrokerAdapter,
    HaltStatus,
    OrderAck,
    OrderRequest,
    Side,
)
from core.money import Money
from core.timeutils import Session, session_for

# ── Lazy-import helpers ──────────────────────────────────────────────────────


def _trading_client_cls() -> Any:
    from alpaca.trading.client import TradingClient  # lazy: optional vendor dep

    return TradingClient


def _limit_order_request_cls() -> Any:
    from alpaca.trading.requests import LimitOrderRequest  # lazy

    return LimitOrderRequest


def _get_order_by_id_request_cls() -> Any:
    from alpaca.trading.requests import GetOrderByIdRequest  # lazy

    return GetOrderByIdRequest


def _order_side() -> Any:
    from alpaca.trading.enums import OrderSide  # lazy

    return OrderSide


def _time_in_force() -> Any:
    from alpaca.trading.enums import TimeInForce  # lazy

    return TimeInForce


def _asset_status() -> Any:
    from alpaca.trading.enums import AssetStatus  # lazy

    return AssetStatus


# ── Money conversion ─────────────────────────────────────────────────────────


def _to_decimal(raw: str | float | None, default: str = "0") -> Decimal:
    """Convert Alpaca's string/float monetary values to Decimal (CLAUDE.md §10)."""
    if raw is None:
        return Decimal(default)
    return Decimal(str(raw))


# ── BrokerAdapter implementation ─────────────────────────────────────────────


class AlpacaBrokerAdapter(BrokerAdapter):
    """BrokerAdapter backed by the Alpaca trading API (live or paper).

    ``paper=True`` routes to the Alpaca paper endpoint; ``paper=False`` (default) is live.
    The adapter enforces:
    - No native STOP orders (OrderType in adapters.base has no STOP member; U7/U13).
    - Idempotent submission: same client_order_id on retry fetches the existing order.
    - Extended-hours ordering: pre/post-market uses DAY+extended_hours; RTH uses IOC.

    Usage::

        adapter = AlpacaBrokerAdapter(api_key, secret_key, paper=True)
        ack = await adapter.submit_marketable_limit(request)

    spec Phase 6 / §10 limit-only / §13.4 mental-stop / §11 U7/U13.
    """

    def __init__(self, api_key: str, secret_key: str, *, paper: bool = True) -> None:
        self._api_key = api_key
        self._secret_key = secret_key
        self._paper = paper
        self._client: Any = None

    def _get_client(self) -> Any:
        if self._client is None:
            self._client = _trading_client_cls()(
                self._api_key, self._secret_key, paper=self._paper
            )
        return self._client

    # ── Order submission ──────────────────────────────────────────────────────

    async def submit_marketable_limit(self, request: OrderRequest) -> OrderAck:
        """Submit a marketable (or plain) limit order.

        Time-in-force adapts to session:
        - Pre-market / after-hours → DAY + extended_hours=True (IOC rejected by Alpaca).
        - RTH → IOC (immediate-or-cancel = true marketable behavior).

        Idempotency: a duplicate client_order_id returns the existing order's ack without
        creating a second fill. Safe to retry after a transient network error.
        spec §10 limit-only / §11 U7.
        """
        return await self._place_limit(
            symbol=request.symbol,
            qty=request.qty,
            side=request.side,
            limit_price=request.limit_price,
            client_order_id=request.client_order_id,
        )

    async def partial_sell(
        self,
        symbol: str,
        qty: int,
        limit_price: Money,
        *,
        client_order_id: str,
    ) -> OrderAck:
        """Sell ``qty`` shares of ``symbol`` at ``limit_price`` (scale-outs / exits).

        Uses the same limit-order path as submit_marketable_limit (U7).
        spec §3/§10.
        """
        return await self._place_limit(
            symbol=symbol,
            qty=qty,
            side=Side.SELL,
            limit_price=limit_price,
            client_order_id=client_order_id,
        )

    async def _place_limit(
        self,
        symbol: str,
        qty: int,
        side: Side,
        limit_price: Money,
        client_order_id: str,
    ) -> OrderAck:
        """Core limit-order submission shared by entry and exit paths."""
        now_utc = datetime.now(tz=__import__("datetime").timezone.utc)
        sess = session_for(now_utc)
        extended = sess in (Session.PREMARKET, Session.AFTERHOURS)

        OrderSide = _order_side()
        TimeInForce = _time_in_force()
        LimitOrderRequest = _limit_order_request_cls()

        alpaca_side = OrderSide.BUY if side is Side.BUY else OrderSide.SELL
        tif = TimeInForce.DAY if extended else TimeInForce.IOC

        req = LimitOrderRequest(
            symbol=symbol,
            qty=qty,
            side=alpaca_side,
            limit_price=float(limit_price),
            time_in_force=tif,
            extended_hours=extended,
            client_order_id=client_order_id,
        )

        try:
            order = await asyncio.to_thread(self._get_client().submit_order, req)
            return self._order_to_ack(order, client_order_id)
        except Exception as exc:  # noqa: BLE001
            # Idempotency: duplicate client_order_id while order is active → fetch existing.
            if self._is_duplicate_id_error(exc):
                return await self._fetch_existing_order_ack(client_order_id, exc)
            return OrderAck(
                client_order_id=client_order_id,
                broker_order_id=None,
                accepted=False,
                status="error",
                message=str(exc),
            )

    # ── Kill-switch ───────────────────────────────────────────────────────────

    async def cancel_all_flatten(self) -> Sequence[OrderAck]:
        """Cancel all open orders and close all positions (emergency kill-switch).

        Alpaca's close_all_positions uses market orders internally.  This is the ONLY
        place market orders are used, and only under emergency conditions (not normal
        trading). U7 is relaxed for the kill-switch per spec §11 U4/U5 intent.
        spec §11 kill-switch / CLAUDE.md §4 U4.
        """
        client = self._get_client()
        try:
            # cancel_orders=True cancels working orders first, then flattens via market close
            closed = await asyncio.to_thread(client.close_all_positions, cancel_orders=True)
        except Exception as exc:  # noqa: BLE001
            return [
                OrderAck(
                    client_order_id="kill_switch",
                    broker_order_id=None,
                    accepted=False,
                    status="error",
                    message=str(exc),
                )
            ]

        if not closed:
            return []

        acks: list[OrderAck] = []
        for item in closed:
            # close_all_positions returns Position objects or ClosePositionResponse
            sym = getattr(item, "symbol", getattr(item, "asset_id", "unknown"))
            acks.append(
                OrderAck(
                    client_order_id=f"flatten_{sym}",
                    broker_order_id=str(getattr(item, "id", "")),
                    accepted=True,
                    status="flatten_submitted",
                )
            )
        return acks

    # ── Account / asset state ─────────────────────────────────────────────────

    async def account_state(self) -> AccountState:
        """Return current account equity/buying-power/PDT state.

        Alpaca returns monetary values as strings; we convert to Decimal (CLAUDE.md §10).
        spec §13.11 PDT / cash-settlement.
        """
        client = self._get_client()
        try:
            acct = await asyncio.to_thread(client.get_account)
        except Exception as exc:  # noqa: BLE001
            # Fail-safe: return the most conservative defaults on any error
            return AccountState(
                equity=Decimal("0"),
                cash=Decimal("0"),
                buying_power=Decimal("0"),
                account_type=AccountType.UNKNOWN,
                day_trade_count=0,
                pdt_restricted=True,
                _error=str(exc),  # type: ignore[call-arg]
            )

        # Alpaca uses "margin" for margin accounts. "cash" = cash-only account.
        raw_type = str(getattr(acct, "account_type", "") or "").lower()
        if raw_type in ("margin", "reg_t_margin"):
            account_type = AccountType.MARGIN
        elif raw_type == "cash":
            account_type = AccountType.CASH
        else:
            account_type = AccountType.UNKNOWN  # fail-safe until confirmed

        equity = _to_decimal(getattr(acct, "equity", None))
        cash = _to_decimal(getattr(acct, "cash", None))
        buying_power = _to_decimal(getattr(acct, "buying_power", None))
        day_trade_count = int(getattr(acct, "daytrade_count", 0) or 0)
        pdt_restricted = bool(getattr(acct, "pattern_day_trader", True))
        trading_blocked = bool(getattr(acct, "trading_blocked", False))

        if trading_blocked:
            pdt_restricted = True

        return AccountState(
            equity=equity,
            cash=cash,
            buying_power=buying_power,
            account_type=account_type,
            day_trade_count=day_trade_count,
            pdt_restricted=pdt_restricted,
        )

    async def get_halt_status(self, symbol: str) -> HaltStatus:
        """Return halt status derived from Alpaca's asset endpoint.

        LIMITATION: Alpaca's asset.tradable does NOT reflect intraday LULD halts;
        it only changes for exchange-suspended or delisted assets. A real-time LULD
        halt feed (Databento or Polygon) is required for accurate intraday halts.
        Treat this as a best-effort check; fail-closed (halted=True) on any error.
        spec §12A halt logic (NEEDS-VERIFY with live LULD data feed).
        """
        client = self._get_client()
        try:
            asset = await asyncio.to_thread(client.get_asset, symbol)
            AssetStatus = _asset_status()
            tradable = bool(getattr(asset, "tradable", False))
            active = getattr(asset, "status", None) == AssetStatus.ACTIVE
            halted = not (tradable and active)
            return HaltStatus(
                symbol=symbol,
                halted=halted,
                reason=(
                    None
                    if not halted
                    else "non-tradable or inactive (LULD intraday not reflected here)"
                ),
            )
        except Exception as exc:  # noqa: BLE001
            # Fail-closed: unknown → treat as potentially halted
            return HaltStatus(symbol=symbol, halted=True, reason=f"error: {exc}")

    # ── Position reconciliation helper (not in ABC; Phase 6 addition) ─────────

    async def get_broker_positions(self) -> dict[str, int]:
        """Return {symbol: qty} of all open positions at the broker.

        Used by LiveSession.reconcile() to compare against internal state.
        spec Phase 6 reconciliation.
        """
        client = self._get_client()
        try:
            positions = await asyncio.to_thread(client.get_all_positions)
        except Exception:  # noqa: BLE001
            return {}  # treat as empty on error; reconcile will flag internal-only positions

        result: dict[str, int] = {}
        for p in positions:
            try:
                sym = str(p.symbol)
                qty = int(float(str(p.qty)))  # Alpaca returns qty as string float
                if qty > 0:
                    result[sym] = qty
            except (ValueError, AttributeError):
                continue
        return result

    # ── Internal helpers ──────────────────────────────────────────────────────

    @staticmethod
    def _order_to_ack(order: Any, client_order_id: str) -> OrderAck:
        status = str(getattr(order, "status", "unknown"))
        rejected = status in ("rejected", "expired", "canceled")
        return OrderAck(
            client_order_id=str(getattr(order, "client_order_id", client_order_id)),
            broker_order_id=str(getattr(order, "id", "")),
            accepted=not rejected,
            status=status,
        )

    @staticmethod
    def _is_duplicate_id_error(exc: Exception) -> bool:
        msg = str(exc).lower()
        return "already exist" in msg or "client_order_id" in msg or "422" in msg

    async def _fetch_existing_order_ack(
        self, client_order_id: str, original_exc: Exception
    ) -> OrderAck:
        """Fetch an existing order by client_order_id (idempotency recovery)."""
        GetOrderByIdRequest = _get_order_by_id_request_cls()
        try:
            order = await asyncio.to_thread(
                self._get_client().get_order_by_id,
                client_order_id,
                GetOrderByIdRequest(by="client_order_id"),
            )
            return self._order_to_ack(order, client_order_id)
        except Exception:  # noqa: BLE001
            return OrderAck(
                client_order_id=client_order_id,
                broker_order_id=None,
                accepted=False,
                status="duplicate_error",
                message=str(original_exc),
            )


__all__ = ["AlpacaBrokerAdapter"]
