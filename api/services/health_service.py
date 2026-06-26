"""Health monitors — feed liveness, clock drift, order-ack latency, depth staleness.

spec Phase 5: "Health monitors: feed liveness, clock drift, order-ack latency,
depth-stream staleness."

Usage: call ``record_tick(feed_name)`` on every received market-data event.
The background task in ``api/main.py`` calls ``build_health_snapshot()`` every
``HEALTH_POLL_SECONDS`` and pushes it to the StateService.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Any

import ntplib  # type: ignore[import-untyped]  # already in pyproject.toml

from api.schemas.dashboard import FeedHealth, HealthOut

log = logging.getLogger(__name__)

_FEED_STALE_S = float(os.environ.get("FEED_STALE_SECONDS", "30"))
_CLOCK_DRIFT_WARN_MS = float(os.environ.get("CLOCK_DRIFT_WARN_MS", "500"))
_NTP_SERVER = os.environ.get("NTP_SERVER", "pool.ntp.org")
_HEALTH_POLL_S = float(os.environ.get("HEALTH_POLL_SECONDS", "15"))

_NTP_EXECUTOR = ThreadPoolExecutor(max_workers=1, thread_name_prefix="ntp")


class HealthService:
    """Tracks liveness of named data feeds and exposes system health snapshots.

    Thread-safe: ``record_tick`` and ``record_order_ack`` are called from the
    asyncio event loop; internal state protected by a threading lock so background
    NTP checks (run in an executor) can also read/write safely.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        # feed_name → epoch-seconds of last tick
        self._last_tick: dict[str, float] = {}
        # most recently measured clock drift in milliseconds (NTP delta)
        self._clock_drift_ms: float = 0.0
        # last order-ack round-trip in milliseconds; None if never measured
        self._order_ack_ms: float | None = None
        # number of connected WebSocket clients (set externally)
        self._ws_clients: int = 0

    # ── Feed liveness ──────────────────────────────────────────────────────────

    def record_tick(self, feed_name: str) -> None:
        """Record that a market-data tick was received for ``feed_name``."""
        with self._lock:
            self._last_tick[feed_name] = time.monotonic()

    def declare_feed(self, feed_name: str) -> None:
        """Register a feed as monitored even before its first tick arrives."""
        with self._lock:
            self._last_tick.setdefault(feed_name, 0.0)

    # ── Order-ack latency ──────────────────────────────────────────────────────

    def record_order_ack(self, latency_ms: float) -> None:
        """Record the round-trip time from order submit to broker ack."""
        with self._lock:
            self._order_ack_ms = latency_ms

    # ── WebSocket client count ─────────────────────────────────────────────────

    def set_ws_clients(self, count: int) -> None:
        with self._lock:
            self._ws_clients = count

    # ── NTP clock drift ────────────────────────────────────────────────────────

    async def refresh_clock_drift(self) -> None:
        """Non-blocking NTP check — runs in thread pool, updates self._clock_drift_ms."""
        import asyncio

        loop = asyncio.get_running_loop()
        try:
            drift_ms = await loop.run_in_executor(_NTP_EXECUTOR, _check_ntp_drift)
            with self._lock:
                self._clock_drift_ms = drift_ms
            if abs(drift_ms) > _CLOCK_DRIFT_WARN_MS:
                log.warning("health.clock_drift_warn drift_ms=%.1f", drift_ms)
        except Exception:  # noqa: BLE001
            log.warning("health.ntp_check_failed — drift reading reset to 0")

    # ── Snapshot ───────────────────────────────────────────────────────────────

    def build_health_snapshot(self) -> HealthOut:
        """Return the current health snapshot.  Called every HEALTH_POLL_SECONDS."""
        now_mono = time.monotonic()
        with self._lock:
            feeds = [
                FeedHealth(
                    name=name,
                    last_tick=None if epoch == 0.0 else datetime.now(timezone.utc),
                    staleness_s=now_mono - epoch if epoch > 0.0 else float("inf"),
                    alive=(now_mono - epoch) < _FEED_STALE_S if epoch > 0.0 else False,
                )
                for name, epoch in self._last_tick.items()
            ]
            drift_ms = self._clock_drift_ms
            ack_ms = self._order_ack_ms
            ws = self._ws_clients

        all_healthy = all(f.alive for f in feeds) and abs(drift_ms) < _CLOCK_DRIFT_WARN_MS
        return HealthOut(
            feeds=feeds,
            clock_drift_ms=drift_ms,
            order_ack_latency_ms=ack_ms,
            all_healthy=all_healthy,
            ws_clients=ws,
            as_of=datetime.now(timezone.utc),
        )


def _check_ntp_drift() -> float:
    """Blocking NTP query — meant to run in a thread pool."""
    c = ntplib.NTPClient()
    resp: Any = c.request(_NTP_SERVER, version=3)
    return resp.offset * 1000.0  # seconds → milliseconds
