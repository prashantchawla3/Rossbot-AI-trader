"""Alpaca market-data adapter — bars / quotes / tape / news (plan Phase 1 default).

Alpaca provides the consolidated **SIP** tape, top-of-book quotes, trades, and news, plus the
best paper API. It has **no native depth-of-book** — full depth comes from Databento
(``adapters.databento``); ``subscribe_depth`` here raises and points there.

verified: alpaca.markets/sdks/python (alpaca-py 0.43.4, 2026-06)
- Historical bars: alpaca.data.historical.StockHistoricalDataClient.get_stock_bars(StockBarsRequest)
- Live stream: alpaca.data.live.StockDataStream(key, secret, feed=DataFeed.SIP);
  .subscribe_bars/_quotes/_trades(handler, *symbols); .run()
- Feeds: alpaca.data.enums.DataFeed {IEX, SIP, DELAYED_SIP, OTC, BOATS, OVERNIGHT};
  SIP requires a paid subscription, IEX is free. We REQUIRE SIP for scanning.
- Paper base URL: https://paper-api.alpaca.markets

The SDK is an optional dependency (``rossbot[vendors]``); it is imported lazily so importing
this module without the SDK installed fails only when an adapter is actually constructed.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Sequence
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from core.data.feed_integrity import require_consolidated_feed

from adapters.base import BarTick, DepthTick, MarketDataAdapter, NewsItem, QuoteTick, TapeTick

PAPER_BASE_URL = "https://paper-api.alpaca.markets"


def _utc(ts: Any) -> datetime:
    """Normalize a vendor timestamp to tz-aware UTC."""
    if isinstance(ts, datetime):
        return ts.astimezone(UTC) if ts.tzinfo else ts.replace(tzinfo=UTC)
    raise TypeError(f"unexpected timestamp type from vendor: {type(ts).__name__}")


class AlpacaMarketDataAdapter(MarketDataAdapter):
    """MarketDataAdapter over alpaca-py. Depth is delegated to Databento.

    ``feed`` defaults to ``"sip"`` and is validated against the SIP/consolidated requirement at
    construction (a momentum scanner on IEX-only would miss the move).
    """

    def __init__(
        self,
        api_key: str,
        secret_key: str,
        *,
        feed: str = "sip",
        require_sip: bool = True,
    ) -> None:
        require_consolidated_feed(feed, require_sip=require_sip)
        self.api_key = api_key
        self.secret_key = secret_key
        self.feed = feed
        self._stream: Any = None  # lazily built StockDataStream

    # ---- lazy SDK wiring -------------------------------------------------
    def _data_feed(self) -> Any:
        from alpaca.data.enums import DataFeed  # lazy: optional dependency

        return DataFeed(self.feed)

    def _live_stream(self) -> Any:
        if self._stream is None:
            from alpaca.data.live import StockDataStream  # lazy: optional dependency

            self._stream = StockDataStream(self.api_key, self.secret_key, feed=self._data_feed())
        return self._stream

    def _hist_client(self) -> Any:
        from alpaca.data.historical import StockHistoricalDataClient  # lazy

        return StockHistoricalDataClient(self.api_key, self.secret_key)

    # ---- streaming via a queue bridge -----------------------------------
    async def _stream_subscribe(self, kind: str, symbols: Sequence[str]) -> AsyncIterator[Any]:
        """Bridge Alpaca's callback handlers into an async iterator via a queue."""
        stream = self._live_stream()
        queue: asyncio.Queue[Any] = asyncio.Queue()

        async def handler(item: Any) -> None:
            await queue.put(item)

        subscribe = getattr(stream, f"subscribe_{kind}")
        subscribe(handler, *symbols)
        runner = asyncio.create_task(asyncio.to_thread(stream.run))
        try:
            while True:
                yield await queue.get()
        finally:
            runner.cancel()

    async def subscribe_bars(
        self, symbols: Sequence[str], timeframe: str
    ) -> AsyncIterator[BarTick]:
        # Alpaca streams 1-min bars; 10-sec bars are built from the tape (core.data.bars).
        async for b in self._stream_subscribe("bars", symbols):
            yield BarTick(
                symbol=b.symbol,
                ts=_utc(b.timestamp),
                timeframe=timeframe,
                open=Decimal(str(b.open)),
                high=Decimal(str(b.high)),
                low=Decimal(str(b.low)),
                close=Decimal(str(b.close)),
                volume=int(b.volume),
            )

    async def subscribe_tape(self, symbols: Sequence[str]) -> AsyncIterator[TapeTick]:
        async for t in self._stream_subscribe("trades", symbols):
            yield TapeTick(
                symbol=t.symbol, ts=_utc(t.timestamp), price=Decimal(str(t.price)), size=int(t.size)
            )

    async def subscribe_quotes(self, symbols: Sequence[str]) -> AsyncIterator[QuoteTick]:
        async for q in self._stream_subscribe("quotes", symbols):
            yield QuoteTick(
                symbol=q.symbol,
                ts=_utc(q.timestamp),
                bid=Decimal(str(q.bid_price)),
                ask=Decimal(str(q.ask_price)),
                bid_size=int(q.bid_size),
                ask_size=int(q.ask_size),
            )

    def subscribe_depth(self, symbols: Sequence[str]) -> AsyncIterator[DepthTick]:
        raise NotImplementedError(
            "Alpaca has no native depth-of-book; use adapters.databento for full depth (§2A)."
        )

    async def get_quote(self, symbol: str) -> QuoteTick:
        from alpaca.data.requests import StockLatestQuoteRequest  # lazy

        client = self._hist_client()
        req = StockLatestQuoteRequest(symbol_or_symbols=symbol, feed=self._data_feed())
        result = await asyncio.to_thread(client.get_stock_latest_quote, req)
        q = result[symbol]
        return QuoteTick(
            symbol=symbol,
            ts=_utc(q.timestamp),
            bid=Decimal(str(q.bid_price)),
            ask=Decimal(str(q.ask_price)),
            bid_size=int(q.bid_size),
            ask_size=int(q.ask_size),
        )

    async def news_stream(self, symbols: Sequence[str] | None = None) -> AsyncIterator[NewsItem]:
        from alpaca.data.live.news import NewsDataStream  # lazy

        stream = NewsDataStream(self.api_key, self.secret_key)
        queue: asyncio.Queue[Any] = asyncio.Queue()

        async def handler(item: Any) -> None:
            await queue.put(item)

        stream.subscribe_news(handler, *(symbols or ["*"]))
        runner = asyncio.create_task(asyncio.to_thread(stream.run))
        try:
            while True:
                n = await queue.get()
                syms = list(getattr(n, "symbols", []) or [])
                yield NewsItem(
                    symbol=syms[0] if syms else None,
                    ts=_utc(n.created_at),
                    headline=str(n.headline),
                    source=str(getattr(n, "source", "alpaca")),
                    body=getattr(n, "summary", None),
                )
        finally:
            runner.cancel()


__all__ = ["PAPER_BASE_URL", "AlpacaMarketDataAdapter"]
