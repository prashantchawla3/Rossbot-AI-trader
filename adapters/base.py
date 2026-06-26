"""Broker + market-data adapter ABCs and their data-transfer objects.

Hard invariants encoded in the contract:
- ``OrderType`` has NO ``stop``/``market`` member — a native STOP/MARKET order is
  unrepresentable (U7/U13 by construction). The only write path is ``submit_marketable_limit``.
- All money fields use ``core.money.Money`` (Decimal; floats rejected at validation).
- Streaming methods return ``AsyncIterator`` (asyncio feed handling, plan tech-stack).

ABCs cannot be instantiated (acceptance: "adapter ABCs can't be instantiated").
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator, Sequence
from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from core.money import Money
from pydantic import BaseModel, ConfigDict


class Side(StrEnum):
    BUY = "buy"
    SELL = "sell"


class OrderType(StrEnum):
    """Permitted order types ONLY. No STOP, no MARKET — ever (U7/U13)."""

    LIMIT = "limit"
    MARKETABLE_LIMIT = "marketable_limit"


class AccountType(StrEnum):
    UNKNOWN = "unknown"  # fail-safe default until confirmed at boot (§13.11)
    CASH = "cash"
    MARGIN = "margin"


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True)


# --------------------------------------------------------------------------------------
# DTOs
# --------------------------------------------------------------------------------------
class OrderRequest(_Frozen):
    """A request to place a limit-style order. ``client_order_id`` is the idempotency key."""

    client_order_id: str
    symbol: str
    side: Side
    qty: int
    limit_price: Money
    order_type: OrderType = OrderType.MARKETABLE_LIMIT


class OrderAck(_Frozen):
    """Broker acknowledgement of an order request."""

    client_order_id: str
    broker_order_id: str | None
    accepted: bool
    status: str
    message: str | None = None


class AccountState(_Frozen):
    """Snapshot of broker account state (gates PDT/cash rules at boot — §13.11)."""

    equity: Money
    cash: Money
    buying_power: Money
    account_type: AccountType = AccountType.UNKNOWN
    day_trade_count: int = 0
    pdt_restricted: bool = True  # fail-safe: assume restricted until proven otherwise


class HaltStatus(_Frozen):
    """LULD/halt state for a symbol (§12A)."""

    symbol: str
    halted: bool
    reason: str | None = None
    resume_price: Decimal | None = None


class QuoteTick(_Frozen):
    symbol: str
    ts: datetime
    bid: Money
    ask: Money
    bid_size: int
    ask_size: int


class BarTick(_Frozen):
    symbol: str
    ts: datetime
    timeframe: str
    open: Money
    high: Money
    low: Money
    close: Money
    volume: int


class TapeTick(_Frozen):
    symbol: str
    ts: datetime
    price: Money
    size: int
    side: Side | None = None


class DepthTick(_Frozen):
    symbol: str
    ts: datetime
    bids: list[tuple[Money, int]]
    asks: list[tuple[Money, int]]


class NewsItem(_Frozen):
    symbol: str | None
    ts: datetime
    headline: str
    source: str
    body: str | None = None


# --------------------------------------------------------------------------------------
# Broker contract
# --------------------------------------------------------------------------------------
class BrokerAdapter(ABC):
    """Execution-side contract. The ONLY write path is marketable/partial limit orders.

    There is intentionally no ``submit_stop`` / ``submit_market`` method: mental stops are
    emulated by the risk layer firing ``submit_marketable_limit`` on breach (U13, §13.4).
    """

    @abstractmethod
    async def submit_marketable_limit(self, request: OrderRequest) -> OrderAck:
        """Submit a marketable (or plain) limit order. Idempotent on client_order_id."""

    @abstractmethod
    async def partial_sell(
        self, symbol: str, qty: int, limit_price: Money, *, client_order_id: str
    ) -> OrderAck:
        """Sell part of a position via a limit order (scale-outs, spec §3/§10)."""

    @abstractmethod
    async def cancel_all_flatten(self) -> Sequence[OrderAck]:
        """Kill-switch: cancel all working orders and flatten all positions (Ctrl+Z)."""

    @abstractmethod
    async def account_state(self) -> AccountState:
        """Return current account equity/buying-power/PDT state."""

    @abstractmethod
    async def get_halt_status(self, symbol: str) -> HaltStatus:
        """Return current LULD/halt status for a symbol."""


# --------------------------------------------------------------------------------------
# Market-data contract
# --------------------------------------------------------------------------------------
class MarketDataAdapter(ABC):
    """Market-data contract: depth, tape, bars, quotes, news. SIP/consolidated required."""

    @abstractmethod
    def subscribe_depth(self, symbols: Sequence[str]) -> AsyncIterator[DepthTick]:
        """Stream full depth-of-book snapshots (§2A)."""

    @abstractmethod
    def subscribe_tape(self, symbols: Sequence[str]) -> AsyncIterator[TapeTick]:
        """Stream tick time-&-sales prints (§2A)."""

    @abstractmethod
    def subscribe_bars(self, symbols: Sequence[str], timeframe: str) -> AsyncIterator[BarTick]:
        """Stream OHLCV bars at the given timeframe (e.g. '10s', '1m')."""

    @abstractmethod
    async def get_quote(self, symbol: str) -> QuoteTick:
        """Return the latest top-of-book quote."""

    @abstractmethod
    def news_stream(self, symbols: Sequence[str] | None = None) -> AsyncIterator[NewsItem]:
        """Stream breaking-news headlines (Pillar 5 catalyst feed)."""
