"""UTC/ET helpers: DST correctness, session classification, naive-datetime rejection."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from core.timeutils import Session, session_for, to_et, to_utc


def test_naive_datetime_rejected() -> None:
    with pytest.raises(ValueError, match="naive"):
        to_utc(datetime(2026, 6, 26, 12, 0))
    with pytest.raises(ValueError, match="naive"):
        to_et(datetime(2026, 6, 26, 12, 0))


def test_dst_offsets_differ() -> None:
    # Winter (EST, UTC-5): 17:00Z -> 12:00 ET.
    winter = datetime(2026, 1, 15, 17, 0, tzinfo=UTC)
    assert to_et(winter).hour == 12
    # Summer (EDT, UTC-4): 16:00Z -> 12:00 ET.
    summer = datetime(2026, 7, 15, 16, 0, tzinfo=UTC)
    assert to_et(summer).hour == 12


def test_session_classification() -> None:
    # Thursday 2026-06-25, 14:00 ET (18:00Z) -> RTH.
    rth = datetime(2026, 6, 25, 18, 0, tzinfo=UTC)
    assert session_for(rth) is Session.RTH
    # Thursday 08:00 ET (12:00Z) -> PREMARKET.
    pre = datetime(2026, 6, 25, 12, 0, tzinfo=UTC)
    assert session_for(pre) is Session.PREMARKET
    # Saturday -> CLOSED.
    weekend = datetime(2026, 6, 27, 18, 0, tzinfo=UTC)
    assert session_for(weekend) is Session.CLOSED
