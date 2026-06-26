"""Databento depth + tape adapter — full order book (spec §2A, plan Phase 1).

Databento exchange-direct Nasdaq TotalView-ITCH is the only retail-accessible source of true
full depth + tick tape on small caps. This adapter supplies **depth** (MBP-10) and **tape**
(trades); bars/quotes/news come from Alpaca (``adapters.alpaca``).

verified: github.com/databento/databento-python + databento.com/docs (databento 0.80.0, 2026-06)
- Clients: ``databento.Live(key)`` / ``databento.Historical(key)``; auth via ``DATABENTO_API_KEY``.
- Dataset: ``XNAS.ITCH`` (Nasdaq TotalView-ITCH, full depth).
- Schemas: ``mbp-10`` (10-level market-by-price), ``mbo`` (market-by-order), ``trades`` (tape).
- Pricing: metered/usage-based (per-GB or per-record by dataset+schema).

NEEDS-VERIFY before live (flagged per STANDING RULES A): the exact DBN record struct field
names and the live-iteration API can change between client minor versions. Confirm the current
``Mbp10Msg.levels`` (bid_px/ask_px/bid_sz/ask_sz) layout, the fixed-point price scale
(``FIXED_PRICE_SCALE``), and the Live iteration/callback API against the installed version
before enabling this in production. The mapping below uses Databento's documented conventions.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Sequence
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from adapters.base import BarTick, DepthTick, MarketDataAdapter, NewsItem, QuoteTick, Side, TapeTick

DATASET_TOTALVIEW = "XNAS.ITCH"
SCHEMA_DEPTH = "mbp-10"
SCHEMA_TAPE = "trades"
# Databento DBN prices are integer fixed-point at 1e-9 (nanodollars). NEEDS-VERIFY per version.
FIXED_PRICE_SCALE = Decimal("1e-9")
_DEPTH_LEVELS = 10


def _px(raw_int: int) -> Decimal:
    """Convert a DBN fixed-point integer price to a Decimal dollar amount."""
    return (Decimal(int(raw_int)) * FIXED_PRICE_SCALE).quantize(Decimal("0.0001"))


def _utc_from_ns(ts_ns: int) -> datetime:
    """DBN timestamps are UTC epoch nanoseconds."""
    return datetime.fromtimestamp(int(ts_ns) / 1_000_000_000, tz=UTC)


class DatabentoDepthTapeAdapter(MarketDataAdapter):
    """Full-depth + tape via Databento Live. Bars/quotes/news → use Alpaca."""

    def __init__(self, api_key: str | None = None, dataset: str = DATASET_TOTALVIEW) -> None:
        # api_key=None → SDK reads DATABENTO_API_KEY from the environment (verified).
        self.api_key = api_key
        self.dataset = dataset

    def _live(self) -> Any:
        import databento as dbn  # lazy: optional dependency

        return dbn.Live(self.api_key) if self.api_key else dbn.Live()

    async def _records(self, schema: str, symbols: Sequence[str]) -> AsyncIterator[Any]:
        """Bridge Databento's synchronous record iteration into an async iterator."""
        client = self._live()
        client.subscribe(
            dataset=self.dataset, schema=schema, symbols=list(symbols), stype_in="raw_symbol"
        )
        queue: asyncio.Queue[Any] = asyncio.Queue()

        def pump() -> None:
            client.start()
            for record in client:  # blocking iteration in a worker thread
                queue.put_nowait(record)

        runner = asyncio.create_task(asyncio.to_thread(pump))
        try:
            while True:
                yield await queue.get()
        finally:
            runner.cancel()

    async def subscribe_depth(self, symbols: Sequence[str]) -> AsyncIterator[DepthTick]:
        async for rec in self._records(SCHEMA_DEPTH, symbols):
            levels = getattr(rec, "levels", [])
            bids: list[tuple[Decimal, int]] = []
            asks: list[tuple[Decimal, int]] = []
            for lvl in levels[:_DEPTH_LEVELS]:
                bids.append((_px(lvl.bid_px), int(lvl.bid_sz)))
                asks.append((_px(lvl.ask_px), int(lvl.ask_sz)))
            yield DepthTick(
                symbol=str(getattr(rec, "symbol", "")),
                ts=_utc_from_ns(rec.ts_event),
                bids=bids,
                asks=asks,
            )

    async def subscribe_tape(self, symbols: Sequence[str]) -> AsyncIterator[TapeTick]:
        async for rec in self._records(SCHEMA_TAPE, symbols):
            # Databento trades schema: side = aggressor side char.
            # 'A' = ask aggressor (buyer lifted offer) = BUY (green print).
            # 'B' = bid aggressor (seller hit bid) = SELL (red print).
            # 'N' or absent = unknown. NEEDS-VERIFY field name per SDK version.
            raw_side = getattr(rec, "side", None)
            if raw_side == "A":
                side: Side | None = Side.BUY
            elif raw_side == "B":
                side = Side.SELL
            else:
                side = None
            yield TapeTick(
                symbol=str(getattr(rec, "symbol", "")),
                ts=_utc_from_ns(rec.ts_event),
                price=_px(rec.price),
                size=int(rec.size),
                side=side,
            )

    # ---- not provided by this adapter (use Alpaca) ----------------------
    def subscribe_bars(self, symbols: Sequence[str], timeframe: str) -> AsyncIterator[BarTick]:
        raise NotImplementedError(
            "Use adapters.alpaca for bars; Databento here supplies depth+tape."
        )

    async def get_quote(self, symbol: str) -> QuoteTick:
        raise NotImplementedError("Use adapters.alpaca for top-of-book quotes.")

    def news_stream(self, symbols: Sequence[str] | None = None) -> AsyncIterator[NewsItem]:
        raise NotImplementedError("Use adapters.alpaca for the news feed.")


__all__ = [
    "DATASET_TOTALVIEW",
    "SCHEMA_DEPTH",
    "SCHEMA_TAPE",
    "DatabentoDepthTapeAdapter",
]
