"""Feed-integrity tests: SIP/IEX guard + staleness detector trips on a gap (acceptance)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from core.data.feed_integrity import (
    FeedIntegrityError,
    FeedStaleError,
    StalenessDetector,
    require_consolidated_feed,
)


# ---- SIP vs IEX guard ----------------------------------------------------
def test_sip_feed_accepted() -> None:
    require_consolidated_feed("sip", require_sip=True)  # no raise


@pytest.mark.parametrize("feed", ["iex", "otc", "delayed_sip", "overnight"])
def test_non_consolidated_feeds_rejected(feed: str) -> None:
    with pytest.raises(FeedIntegrityError):
        require_consolidated_feed(feed, require_sip=True)


def test_unknown_feed_rejected() -> None:
    with pytest.raises(FeedIntegrityError, match="unknown"):
        require_consolidated_feed("madeup", require_sip=True)


def test_guard_can_be_disabled_explicitly() -> None:
    require_consolidated_feed("iex", require_sip=False)  # explicit override, no raise


# ---- staleness detector --------------------------------------------------
def test_staleness_trips_on_gap() -> None:
    det = StalenessDetector.from_seconds(Decimal("5"))
    t0 = datetime(2026, 6, 26, 13, 30, 0, tzinfo=UTC)
    det.record("tape:AAA", t0)
    assert det.is_stale("tape:AAA", t0 + timedelta(seconds=4)) is False
    assert det.is_stale("tape:AAA", t0 + timedelta(seconds=6)) is True  # gap > threshold
    with pytest.raises(FeedStaleError, match="stale"):
        det.check("tape:AAA", t0 + timedelta(seconds=6))


def test_unseen_key_is_stale_failsafe() -> None:
    det = StalenessDetector(default_threshold=timedelta(seconds=5))
    now = datetime(2026, 6, 26, 13, 30, 0, tzinfo=UTC)
    assert det.is_stale("never", now) is True  # no data ever ⇒ stale ⇒ do not trade


def test_per_key_threshold_override() -> None:
    det = StalenessDetector(default_threshold=timedelta(seconds=3))
    det.set_threshold("bars:10s", timedelta(seconds=15))
    t0 = datetime(2026, 6, 26, 13, 30, 0, tzinfo=UTC)
    det.record("bars:10s", t0)
    assert det.is_stale("bars:10s", t0 + timedelta(seconds=12)) is False


def test_naive_timestamp_rejected() -> None:
    det = StalenessDetector()
    with pytest.raises(ValueError, match="tz-aware"):
        det.record("k", datetime(2026, 6, 26, 13, 30, 0))
