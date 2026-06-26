"""NTP clock-drift guard.

CLAUDE.md §10 / plan Phase 0: "time sync (NTP)". A drifting clock corrupts bar
alignment, the +10¢/60s time-stop, and halt/session logic. Fail-safe: if drift exceeds
the configured budget OR cannot be measured, the caller must treat the system as
NOT-OK-to-trade. This module only *measures*; the trade decision lives in the risk gate.

verified: pypi.org/project/ntplib 0.4.0 — NTPClient().request(server, version=3) ->
response.offset (seconds, local minus server) (2026-06).
"""

from __future__ import annotations

from dataclasses import dataclass

import ntplib


@dataclass(frozen=True)
class ClockDriftResult:
    """Outcome of a clock-drift check."""

    ok: bool
    drift_ms: float | None
    server: str
    error: str | None = None


def check_clock_drift(
    *,
    server: str = "pool.ntp.org",
    max_drift_ms: float = 250.0,
    timeout_s: float = 5.0,
) -> ClockDriftResult:
    """Measure local-vs-NTP offset. Returns ``ok=False`` on excess drift OR any failure.

    Fail-closed: a network/timeout error yields ``ok=False`` with the error recorded,
    never a silent pass.
    """
    client = ntplib.NTPClient()
    try:
        response = client.request(server, version=3, timeout=timeout_s)
    except Exception as exc:
        return ClockDriftResult(ok=False, drift_ms=None, server=server, error=str(exc))

    drift_ms = abs(response.offset) * 1000.0
    return ClockDriftResult(ok=drift_ms <= max_drift_ms, drift_ms=drift_ms, server=server)
