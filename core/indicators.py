"""Streaming + batch technical indicators — pure ``Decimal``, no float (spec §2, §3).

Phase 1 indicators on the 1-min and 10-sec streams: **9 EMA**, **VWAP**, **MACD**
(line / signal / histogram). Implemented by hand on ``Decimal`` rather than via numpy /
pandas / a TA library so the math is exact, reproducible, and seedable for the §12
regression fixtures (CLAUDE.md §9 "deterministic where possible"; §10 "never float").

Two shapes per indicator:
- a **batch** function over a full series (used to verify against known fixtures); and
- an incremental **state** object updated one bar at a time (used on the live stream).
Both share the same recurrence so batch and streaming agree bit-for-bit.

Conventions (documented so fixtures are unambiguous):
- **EMA** smoothing ``k = 2 / (period + 1)``. The series is **seeded with the SMA of the
  first ``period`` samples** (Wilder/most-charting convention); values before the seed are
  ``None``. ``EMA[i] = (price[i] - EMA[i-1]) * k + EMA[i-1]`` thereafter.
- **MACD** = ``EMA(fast) - EMA(slow)`` on close; **signal** = ``EMA(signal)`` of the MACD
  line; **histogram** = ``macd - signal``. Defaults 12 / 26 / 9.
- **VWAP** is **session-cumulative** over typical price ``(H+L+C)/3``:
  ``Σ(tp·vol) / Σ(vol)``. Reset at each session boundary by constructing a new state.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from decimal import Decimal

# Default indicator periods (spec §2/§3: "9 EMA", MACD standard 12/26/9).
EMA_PERIOD_DEFAULT = 9
MACD_FAST = 12
MACD_SLOW = 26
MACD_SIGNAL = 9

# Output rounding for comparison/storage. Internal recurrence keeps full Decimal context
# precision; we only quantize on the way out.
_OUT_QUANT = Decimal("0.000001")  # 6 dp — finer than price scale, exact for fixtures
_THREE = Decimal("3")


def _q(value: Decimal) -> Decimal:
    return value.quantize(_OUT_QUANT)


def _ensure_decimal(value: Decimal) -> Decimal:
    # Hard guard: a float must never enter the indicator math (CLAUDE.md §10).
    if isinstance(value, float):
        raise TypeError("float is forbidden in indicators; pass Decimal")
    return value


# --------------------------------------------------------------------------------------
# EMA
# --------------------------------------------------------------------------------------
class EmaState:
    """Incremental EMA. Returns the EMA after each ``update`` once seeded, else ``None``."""

    __slots__ = ("_buf", "_ema", "_k", "period")

    def __init__(self, period: int) -> None:
        if period < 1:
            raise ValueError("EMA period must be >= 1")
        self.period = period
        self._k = Decimal(2) / Decimal(period + 1)
        self._buf: list[Decimal] = []
        self._ema: Decimal | None = None

    @property
    def value(self) -> Decimal | None:
        return None if self._ema is None else _q(self._ema)

    def update(self, price: Decimal) -> Decimal | None:
        _ensure_decimal(price)
        if self._ema is None:
            self._buf.append(price)
            if len(self._buf) < self.period:
                return None
            self._ema = sum(self._buf, Decimal(0)) / Decimal(self.period)  # SMA seed
            return _q(self._ema)
        self._ema = (price - self._ema) * self._k + self._ema
        return _q(self._ema)


def ema(values: Sequence[Decimal], period: int = EMA_PERIOD_DEFAULT) -> list[Decimal | None]:
    """Batch EMA aligned to ``values`` (``None`` until the SMA seed is available)."""
    state = EmaState(period)
    return [state.update(v) for v in values]


# --------------------------------------------------------------------------------------
# MACD
# --------------------------------------------------------------------------------------
@dataclass(frozen=True)
class MacdPoint:
    macd: Decimal
    signal: Decimal | None
    histogram: Decimal | None


class MacdState:
    """Incremental MACD(fast, slow, signal). Emits a point once the slow EMA is seeded."""

    __slots__ = ("_fast", "_signal", "_slow")

    def __init__(
        self, fast: int = MACD_FAST, slow: int = MACD_SLOW, signal: int = MACD_SIGNAL
    ) -> None:
        if not fast < slow:
            raise ValueError("MACD requires fast < slow")
        self._fast = EmaState(fast)
        self._slow = EmaState(slow)
        self._signal = EmaState(signal)

    def update(self, close: Decimal) -> MacdPoint | None:
        _ensure_decimal(close)
        fast_v = self._fast.update(close)
        slow_v = self._slow.update(close)
        if fast_v is None or slow_v is None:
            return None
        macd_line = fast_v - slow_v
        signal_v = self._signal.update(macd_line)
        hist = None if signal_v is None else _q(macd_line - signal_v)
        return MacdPoint(macd=_q(macd_line), signal=signal_v, histogram=hist)


def macd(
    closes: Sequence[Decimal],
    fast: int = MACD_FAST,
    slow: int = MACD_SLOW,
    signal: int = MACD_SIGNAL,
) -> list[MacdPoint | None]:
    """Batch MACD aligned to ``closes``."""
    state = MacdState(fast, slow, signal)
    return [state.update(c) for c in closes]


def macd_positive(point: MacdPoint | None) -> bool:
    """E4 helper: MACD is positive / crossing up (line > signal AND histogram >= 0).

    Fail-safe: an un-seeded (``None``) point is NOT positive — E4 hard-blocks (spec §2 E4).
    """
    if point is None or point.signal is None or point.histogram is None:
        return False
    return point.macd > point.signal and point.histogram >= Decimal(0)


# --------------------------------------------------------------------------------------
# VWAP (session-cumulative)
# --------------------------------------------------------------------------------------
@dataclass
class VwapState:
    """Session-cumulative VWAP over typical price ``(H+L+C)/3``. New session → new state."""

    _pv: Decimal = field(default_factory=lambda: Decimal(0))
    _vol: Decimal = field(default_factory=lambda: Decimal(0))

    @property
    def value(self) -> Decimal | None:
        if self._vol == 0:
            return None
        return _q(self._pv / self._vol)

    def update(self, high: Decimal, low: Decimal, close: Decimal, volume: int) -> Decimal | None:
        for v in (high, low, close):
            _ensure_decimal(v)
        if isinstance(volume, bool) or not isinstance(volume, int):
            raise TypeError("VWAP volume must be a plain int")
        if volume < 0:
            raise ValueError("VWAP volume must be >= 0")
        typical = (high + low + close) / _THREE
        self._pv += typical * Decimal(volume)
        self._vol += Decimal(volume)
        return self.value


def vwap(bars: Sequence[tuple[Decimal, Decimal, Decimal, int]]) -> Decimal | None:
    """Batch session VWAP from ``(high, low, close, volume)`` bars. ``None`` if no volume."""
    state = VwapState()
    result: Decimal | None = None
    for high, low, close, volume in bars:
        result = state.update(high, low, close, volume)
    return result
