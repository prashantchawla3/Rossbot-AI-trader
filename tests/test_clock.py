"""NTP clock-drift guard: fail-closed on excess drift and on any NTP failure."""

from __future__ import annotations

from typing import Any

import core.clock as clock
import ntplib
import pytest


class _FakeResponse:
    def __init__(self, offset_s: float) -> None:
        self.offset = offset_s


def _patch_ntp(monkeypatch: pytest.MonkeyPatch, *, offset_s: float | None, raises: bool) -> None:
    def fake_request(self: Any, *args: Any, **kwargs: Any) -> _FakeResponse:
        if raises:
            raise OSError("ntp unreachable")
        assert offset_s is not None
        return _FakeResponse(offset_s)

    monkeypatch.setattr(ntplib.NTPClient, "request", fake_request)


def test_within_budget_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_ntp(monkeypatch, offset_s=0.05, raises=False)  # 50 ms
    result = clock.check_clock_drift(max_drift_ms=250.0)
    assert result.ok is True
    assert result.drift_ms is not None and result.drift_ms <= 250.0


def test_excess_drift_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_ntp(monkeypatch, offset_s=0.5, raises=False)  # 500 ms
    result = clock.check_clock_drift(max_drift_ms=250.0)
    assert result.ok is False


def test_ntp_failure_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_ntp(monkeypatch, offset_s=None, raises=True)
    result = clock.check_clock_drift()
    assert result.ok is False
    assert result.error is not None
