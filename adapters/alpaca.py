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
from datetime import UTC, datetime, timedelta
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

    # ---- demo polling helpers (REST historical client) -------------------
    async def get_snapshot(self, symbols: Sequence[str]) -> dict[str, dict[str, Any]]:
        """Batch snapshot: {symbol: {price, prev_close, change_pct, volume}}.

        Used by the scanner's Tier-A wide net. ``change_pct`` is daily close vs the
        previous daily close (%). Missing symbols are simply omitted (fail-safe).
        spec §1 TIER_A wide net.
        """
        from alpaca.data.requests import StockSnapshotRequest  # lazy

        client = self._hist_client()
        req = StockSnapshotRequest(symbol_or_symbols=list(symbols), feed=self._data_feed())
        try:
            snaps = await asyncio.to_thread(client.get_stock_snapshot, req)
        except Exception:  # noqa: BLE001 — partial-universe failure must not crash scan
            return {}

        out: dict[str, dict[str, Any]] = {}
        for sym, snap in (snaps or {}).items():
            if snap is None:
                continue
            daily = getattr(snap, "daily_bar", None)
            prev = getattr(snap, "previous_daily_bar", None)
            trade = getattr(snap, "latest_trade", None)
            minute = getattr(snap, "minute_bar", None)
            price = None
            if trade is not None and getattr(trade, "price", None) is not None:
                price = Decimal(str(trade.price))
            elif daily is not None and getattr(daily, "close", None) is not None:
                price = Decimal(str(daily.close))
            elif minute is not None and getattr(minute, "close", None) is not None:
                price = Decimal(str(minute.close))
            if price is None:
                continue
            prev_close = (
                Decimal(str(prev.close))
                if prev is not None and getattr(prev, "close", None) is not None
                else None
            )
            change_pct = Decimal("0")
            if prev_close and prev_close > 0:
                change_pct = (price - prev_close) / prev_close * Decimal("100")
            volume = int(getattr(daily, "volume", 0) or 0) if daily is not None else 0
            out[str(sym)] = {
                "price": price,
                "prev_close": prev_close,
                "change_pct": change_pct,
                "volume": volume,
            }
        return out

    async def get_bars(
        self, symbol: str, timeframe: str = "1Min", limit: int = 50
    ) -> list[BarTick]:
        """Return the most recent ``limit`` historical bars (oldest→newest) for ``symbol``.

        A ``start`` window is REQUIRED on Alpaca's historical REST API: omitting it makes the
        IEX free feed return an EMPTY set (verified 2026-06 — daily bars without ``start`` →
        0 rows → RVOL never computes → Pillar-3 never passes). The window is sized by
        timeframe and ``limit``, then we slice the tail so the *newest* bars are returned even
        when the window (sized to span a weekend/holiday) holds more than ``limit`` bars.
        spec §1 Pillar-3 (RVOL) / §2 (MACD on recent bars).
        """
        from alpaca.data.requests import StockBarsRequest  # lazy
        from alpaca.data.timeframe import TimeFrame, TimeFrameUnit  # lazy

        tf_map = {
            "1Min": TimeFrame(1, TimeFrameUnit.Minute),
            "1min": TimeFrame(1, TimeFrameUnit.Minute),
            "5Min": TimeFrame(5, TimeFrameUnit.Minute),
            "1Day": TimeFrame(1, TimeFrameUnit.Day),
            "1day": TimeFrame(1, TimeFrameUnit.Day),
        }
        tf = tf_map.get(timeframe, TimeFrame(1, TimeFrameUnit.Minute))

        # Lookback window. Daily bars need ~1.5 calendar days per trading day (weekends +
        # holidays), so size generously off ``limit``; intraday bars need only a few days to
        # reach back across a weekend to the last live session.
        is_daily = timeframe.lower() == "1day"
        lookback = timedelta(days=limit * 2 + 14) if is_daily else timedelta(days=5)
        end = datetime.now(UTC)
        start = end - lookback

        client = self._hist_client()
        req = StockBarsRequest(
            symbol_or_symbols=symbol,
            timeframe=tf,
            start=start,
            end=end,
            feed=self._data_feed(),
        )
        try:
            result = await asyncio.to_thread(client.get_stock_bars, req)
        except Exception:  # noqa: BLE001
            return []

        rows = (getattr(result, "data", {}) or {}).get(symbol, [])
        # Keep only the newest ``limit`` bars (Alpaca returns oldest→newest for the window).
        if limit and len(rows) > limit:
            rows = rows[-limit:]
        bars: list[BarTick] = []
        for b in rows:
            bars.append(
                BarTick(
                    symbol=symbol,
                    ts=_utc(b.timestamp),
                    timeframe=timeframe,
                    open=Decimal(str(b.open)),
                    high=Decimal(str(b.high)),
                    low=Decimal(str(b.low)),
                    close=Decimal(str(b.close)),
                    volume=int(b.volume),
                )
            )
        return bars

    async def get_rvol(self, symbol: str, *, current_volume: int | None = None) -> Decimal | None:
        """Relative volume = today's volume / avg of prior ~50 daily volumes.

        Computed from daily bars. Returns None if insufficient history. Intraday
        ``current_volume`` (from a snapshot) may be passed; otherwise the latest
        daily bar's volume is used. spec §1 Pillar-3 / §13.
        """
        bars = await self.get_bars(symbol, timeframe="1Day", limit=51)
        if len(bars) < 6:  # need a few days to be meaningful
            return None
        history = bars[:-1]  # exclude today
        today_vol = current_volume if current_volume is not None else bars[-1].volume
        vols = [b.volume for b in history if b.volume > 0]
        if not vols:
            return None
        avg = sum(vols) / len(vols)
        if avg <= 0:
            return None
        return (Decimal(today_vol) / Decimal(str(avg))).quantize(Decimal("0.01"))

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
