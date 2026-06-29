"""Real-time Alpaca/Benzinga news WebSocket adapter.

Subscribes to all symbols ("*") via Alpaca's NewsDataStream and maintains an
in-memory per-symbol cache (deque, maxlen=10).  The alpaca-py ``DataStream.run()``
method calls ``asyncio.run()`` internally and is therefore unusable inside an
existing event loop.  We call the internal ``_run_forever()`` coroutine directly
so the stream runs as a native asyncio task inside the FastAPI lifespan.

On startup the cache is pre-populated via a REST backfill (NewsClient.get_news,
last 3 hours) so Pillar-5 can classify symbols immediately — the live WebSocket
only delivers news that arrives *after* the connection is established.

env vars: ALPACA_API_KEY, ALPACA_API_SECRET (same keys as paper trading).
"""

from __future__ import annotations

import asyncio
import logging
import os
from collections import defaultdict, deque
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

log = logging.getLogger(__name__)

_BACKFILL_HOURS = 3   # how far back to pull on startup
_BACKFILL_LIMIT = 200 # max articles fetched; Alpaca pages automatically up to this


@dataclass(frozen=True)
class NewsItem:
    """One article from the Alpaca/Benzinga news feed."""

    id: int
    headline: str
    summary: str
    source: str
    symbols: tuple[str, ...]
    created_at: datetime  # always UTC


# Callback signature: (symbol, item) — called for every new live item.
NewsCallback = Callable[[str, "NewsItem"], Awaitable[None]]


class NewsStreamAdapter:
    """WebSocket subscriber wrapping ``alpaca.data.live.news.NewsDataStream``.

    Lifecycle:
      await adapter.start()   # called from FastAPI lifespan startup
      …                       # runs indefinitely, reconnects with backoff
      await adapter.stop()    # called from FastAPI lifespan shutdown

    Thread-safety: all mutations happen inside the asyncio event loop; the
    ``asyncio.Lock`` guards the cache dict so ``get_recent_news`` and
    ``_store_item`` don't race.
    """

    def __init__(
        self,
        api_key: str | None = None,
        secret_key: str | None = None,
        cache_size: int = 10,
        backfill_hours: int = _BACKFILL_HOURS,
    ) -> None:
        self._api_key = api_key or os.environ.get("ALPACA_API_KEY", "")
        # Project uses ALPACA_SECRET_KEY (matches DemoConfig and adapters/alpaca.py).
        self._secret_key = secret_key or os.environ.get("ALPACA_SECRET_KEY", "")
        self._cache: dict[str, deque[NewsItem]] = defaultdict(
            lambda: deque(maxlen=cache_size)
        )
        self._lock = asyncio.Lock()
        self._task: asyncio.Task[None] | None = None
        self._stream: Any = None  # alpaca.data.live.news.NewsDataStream
        self._should_run = False
        self._backfill_hours = backfill_hours

        # Registered async callbacks fired for each new live item per-symbol.
        self._callbacks: list[NewsCallback] = []

    # ── public callback registration ──────────────────────────────────────────

    def add_news_callback(self, fn: NewsCallback) -> None:
        """Register an async callback invoked for each (symbol, NewsItem) pair."""
        self._callbacks.append(fn)

    # ── lifecycle ─────────────────────────────────────────────────────────────

    async def start(self) -> None:
        """Connect to the Alpaca news stream and begin processing messages.

        Two things happen concurrently:
        1. ``_backfill_cache()`` — REST call to pre-populate the last N hours of news
           so Pillar-5 can classify symbols immediately without waiting for live events.
        2. ``_run_loop()`` — WebSocket task that delivers new articles in real time.
        """
        if not self._api_key or not self._secret_key:
            log.warning(
                "news_stream.no_credentials — set ALPACA_API_KEY / ALPACA_SECRET_KEY "
                "in .env.  NewsStreamAdapter will remain idle."
            )
            return
        self._should_run = True

        # Backfill first (awaited so cache is populated before the first scan runs).
        await self._backfill_cache()

        # Then start the live stream task.
        self._task = asyncio.create_task(self._run_loop(), name="news_stream")
        log.info("news_stream.started")

    async def stop(self) -> None:
        """Gracefully stop the stream and cancel the background task."""
        self._should_run = False
        if self._stream is not None:
            try:
                await self._stream.stop_ws()
            except Exception:  # noqa: BLE001
                pass
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        log.info("news_stream.stopped")

    # ── REST backfill ─────────────────────────────────────────────────────────

    async def _backfill_cache(self) -> None:
        """Fetch recent historical news via REST and seed the in-memory cache.

        Uses ``asyncio.to_thread`` so the synchronous SDK call doesn't block the
        event loop.  Failures are logged and silently ignored — the live stream
        will populate the cache going forward.
        """
        try:
            count = await asyncio.to_thread(self._fetch_historical)
            log.info(
                "news_stream.backfilled count=%d lookback_hours=%d",
                count,
                self._backfill_hours,
            )
        except Exception:  # noqa: BLE001
            log.warning("news_stream.backfill_failed", exc_info=True)

    def _fetch_historical(self) -> int:
        """Synchronous REST fetch — runs in a thread pool via asyncio.to_thread."""
        from alpaca.data.historical.news import NewsClient  # lazy: sdk optional
        from alpaca.data.requests import NewsRequest

        start_dt = datetime.now(UTC) - timedelta(hours=self._backfill_hours)
        client = NewsClient(api_key=self._api_key, secret_key=self._secret_key)
        result = client.get_news(NewsRequest(start=start_dt, limit=_BACKFILL_LIMIT))
        articles = result.data.get("news", [])

        # Use a simple list (no asyncio.Lock) because we're in a thread;
        # the defaultdict/deque are populated before the async task starts.
        for article in articles:
            self._store_item_sync(article)
        return len(articles)

    def _store_item_sync(self, article: Any) -> None:
        """Parse a raw alpaca News object and insert into the cache (thread-safe via GIL)."""
        try:
            created = article.created_at
            if created.tzinfo is None:
                created = created.replace(tzinfo=UTC)
            else:
                created = created.astimezone(UTC)
            item = NewsItem(
                id=int(article.id),
                headline=str(article.headline or ""),
                summary=str(article.summary or ""),
                source=str(article.source or ""),
                symbols=tuple(str(s).upper() for s in (article.symbols or [])),
                created_at=created,
            )
            if item.symbols:
                for sym in item.symbols:
                    self._cache[sym].appendleft(item)
            else:
                self._cache["*"].appendleft(item)
        except Exception:  # noqa: BLE001
            log.debug("news_stream.backfill_parse_error", exc_info=True)

    # ── internal run loop with exponential backoff ─────────────────────────────

    async def _run_loop(self) -> None:
        """Outer retry loop.  Creates a fresh NewsDataStream on each reconnect."""
        from alpaca.data.live.news import NewsDataStream  # lazy: sdk optional

        backoff = 1.0
        while self._should_run:
            self._stream = NewsDataStream(
                api_key=self._api_key,
                secret_key=self._secret_key,
            )
            self._stream.subscribe_news(self._on_news, "*")
            try:
                # _run_forever() is the internal async entry-point.  The public
                # run() calls asyncio.run() which would conflict with our loop.
                await self._stream._run_forever()  # type: ignore[attr-defined]
                if self._should_run:
                    log.warning(
                        "news_stream.exited_unexpectedly reconnecting in %.0fs", backoff
                    )
                    await asyncio.sleep(backoff)
                    backoff = min(backoff * 2, 60.0)
                else:
                    break  # clean shutdown
            except asyncio.CancelledError:
                raise
            except Exception:
                log.warning(
                    "news_stream.error reconnecting in %.0fs", backoff, exc_info=True
                )
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 60.0)

    # ── live message handler ───────────────────────────────────────────────────

    async def _on_news(self, news: Any) -> None:
        """Handler registered with NewsDataStream.subscribe_news.

        ``news`` is an ``alpaca.data.models.news.News`` instance (parsed by the SDK).
        """
        try:
            created = news.created_at
            if created.tzinfo is None:
                created = created.replace(tzinfo=UTC)
            else:
                created = created.astimezone(UTC)

            item = NewsItem(
                id=int(news.id),
                headline=str(news.headline or ""),
                summary=str(news.summary or ""),
                source=str(news.source or ""),
                symbols=tuple(str(s).upper() for s in (news.symbols or [])),
                created_at=created,
            )
        except Exception:  # noqa: BLE001
            log.debug("news_stream.parse_error", exc_info=True)
            return

        log.debug(
            "news_stream.live id=%s symbols=%s headline=%r",
            item.id,
            item.symbols,
            item.headline[:80],
        )

        async with self._lock:
            if item.symbols:
                for sym in item.symbols:
                    self._cache[sym].appendleft(item)
            else:
                self._cache["*"].appendleft(item)

        # Fire registered callbacks for each symbol in this article.
        for sym in item.symbols or ("*",):
            for fn in self._callbacks:
                try:
                    await fn(sym, item)
                except Exception:  # noqa: BLE001
                    log.debug("news_stream.callback_error sym=%s", sym, exc_info=True)

    # ── query ─────────────────────────────────────────────────────────────────

    async def get_recent_news(
        self, symbol: str, lookback_minutes: int = 30
    ) -> list[NewsItem]:
        """Return cached news for ``symbol`` published within the last ``lookback_minutes``.

        Thread-safe (asyncio.Lock).  Returns an empty list when the stream is idle
        or no matching articles are cached.
        """
        cutoff = datetime.now(UTC).timestamp() - lookback_minutes * 60
        async with self._lock:
            bucket = list(self._cache.get(symbol.upper(), []))
        return [item for item in bucket if item.created_at.timestamp() >= cutoff]


__all__ = ["NewsItem", "NewsStreamAdapter"]
