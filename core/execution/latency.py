"""Loop latency recorder for the mental-stop monitor (spec §13.4, Phase 10).

Measures the wall-clock time of each mental-stop loop iteration and logs a
WARNING when it exceeds LATENCY_WARN_MS (default 200 ms).

Spec §13.4: "Risk: latency → worse fill than a resting stop."
Measurement lets the operator quantify the gap and tune BACKSTOP_OFFSET or
LIVE_POLL_MS accordingly.

Usage (context-manager)::

    recorder = LoopLatencyRecorder(cfg)
    with recorder.measure():
        # one iteration of the mental-stop loop
        ...
    print(recorder.stats)

spec §13.4 / Phase 10.
"""

from __future__ import annotations

import time
from collections.abc import Generator
from contextlib import contextmanager

import structlog

from core.config import ConfigService

log = structlog.get_logger(__name__)


class LoopLatencyRecorder:
    """Records mental-stop loop iteration latency (ms).

    Keeps a simple ring-buffer of the last MAX_SAMPLES measurements.
    Logs WARN when a single iteration exceeds LATENCY_WARN_MS.

    spec §13.4 / Phase 10.
    """

    MAX_SAMPLES = 1000

    def __init__(self, cfg: ConfigService) -> None:
        self._warn_ms: int = cfg.get_int("LATENCY_WARN_MS")
        self._samples: list[float] = []

    @contextmanager
    def measure(self) -> Generator[None, None, None]:
        """Context manager that times one loop iteration and records the sample.

        Logs WARN when latency exceeds LATENCY_WARN_MS (spec §13.4).
        """
        t0 = time.monotonic()
        try:
            yield
        finally:
            elapsed_ms = (time.monotonic() - t0) * 1000.0
            self._samples.append(elapsed_ms)
            if len(self._samples) > self.MAX_SAMPLES:
                self._samples.pop(0)
            if elapsed_ms > self._warn_ms:
                log.warning(
                    "mental_stop_loop.latency_exceeded",
                    ms=round(elapsed_ms, 2),
                    warn_ms=self._warn_ms,
                    spec="§13.4",
                )

    @property
    def stats(self) -> dict[str, float]:
        """Return min/max/avg latency stats and sample count.

        All values in milliseconds.  Empty → all zeros.
        """
        if not self._samples:
            return {"min_ms": 0.0, "max_ms": 0.0, "avg_ms": 0.0, "samples": 0.0}
        return {
            "min_ms": min(self._samples),
            "max_ms": max(self._samples),
            "avg_ms": sum(self._samples) / len(self._samples),
            "samples": float(len(self._samples)),
        }

    @property
    def sample_count(self) -> int:
        return len(self._samples)

    def clear(self) -> None:
        """Reset the sample buffer (call between sessions)."""
        self._samples.clear()
