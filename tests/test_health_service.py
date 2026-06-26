"""Unit tests for the health monitoring service.  spec Phase 5."""

from __future__ import annotations

import time
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from api.services.health_service import HealthService, _FEED_STALE_S


class TestHealthService:
    def test_no_feeds_initially(self) -> None:
        svc = HealthService()
        snap = svc.build_health_snapshot()
        assert snap.feeds == []
        assert snap.all_healthy is True

    def test_declared_feed_is_stale_before_first_tick(self) -> None:
        svc = HealthService()
        svc.declare_feed("quote_feed")
        snap = svc.build_health_snapshot()
        assert len(snap.feeds) == 1
        assert snap.feeds[0].name == "quote_feed"
        assert snap.feeds[0].alive is False

    def test_live_tick_makes_feed_alive(self) -> None:
        svc = HealthService()
        svc.declare_feed("tape_feed")
        svc.record_tick("tape_feed")
        snap = svc.build_health_snapshot()
        assert snap.feeds[0].alive is True
        assert snap.feeds[0].staleness_s < 1.0

    def test_stale_feed_not_alive(self) -> None:
        svc = HealthService()
        svc.declare_feed("depth_feed")
        # Manually set last_tick to a very old value
        svc._last_tick["depth_feed"] = time.monotonic() - (_FEED_STALE_S + 5)
        snap = svc.build_health_snapshot()
        assert snap.feeds[0].alive is False
        assert snap.feeds[0].staleness_s > _FEED_STALE_S

    def test_all_healthy_false_when_any_feed_stale(self) -> None:
        svc = HealthService()
        svc.declare_feed("live_feed")
        svc.record_tick("live_feed")
        svc.declare_feed("stale_feed")  # never ticked
        snap = svc.build_health_snapshot()
        assert snap.all_healthy is False

    def test_all_healthy_true_when_all_feeds_alive(self) -> None:
        svc = HealthService()
        svc.declare_feed("feed_a")
        svc.record_tick("feed_a")
        svc.declare_feed("feed_b")
        svc.record_tick("feed_b")
        snap = svc.build_health_snapshot()
        assert snap.all_healthy is True

    def test_order_ack_latency_recorded(self) -> None:
        svc = HealthService()
        svc.record_order_ack(42.5)
        snap = svc.build_health_snapshot()
        assert snap.order_ack_latency_ms == pytest.approx(42.5)

    def test_ws_client_count_reflected_in_snapshot(self) -> None:
        svc = HealthService()
        svc.set_ws_clients(3)
        snap = svc.build_health_snapshot()
        assert snap.ws_clients == 3

    def test_clock_drift_defaults_to_zero(self) -> None:
        svc = HealthService()
        snap = svc.build_health_snapshot()
        assert snap.clock_drift_ms == 0.0

    def test_snapshot_has_utc_timestamp(self) -> None:
        svc = HealthService()
        snap = svc.build_health_snapshot()
        assert snap.as_of.tzinfo is not None
