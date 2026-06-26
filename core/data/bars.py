"""Build OHLCV bars from the tick tape (Phase 1).

We construct our **own** bars from time-&-sales prints rather than consuming vendor bars,
so the inclusion rules are explicit and identical in live + backtest (plan Phase 1
"Build own bars from tape with explicit pre-market/odd-lot rules").

=== Documented bar-construction rules (spec §1/§7/§9) ===
1. **Timeframes:** 10-sec and 1-min. Buckets align to the UTC epoch; because the ET offset
   is a whole number of hours, minute/10-sec boundaries coincide in ET and UTC.
2. **Pre-market INCLUDED.** Ross trades pre-market and treats it as the prime window
   (spec §7 PREMARKET_EDGE). Bars are built continuously across pre-market and RTH; no
   prints are dropped by session. Session labelling is available via
   ``core.timeutils.session_for`` for downstream time-of-day rules, not for bar building.
3. **Odd lots (size < 100) INCLUDED** in both price (OHLC) and volume. For low-float momentum
   names odd-lot prints are real, material executions; excluding them understates activity.
   (Modern consolidated tapes include odd-lot last-sale prints.)
4. **Every tape print is treated as last-sale eligible.** The ``TapeTick`` DTO carries no
   trade-condition flags today; if condition codes are added later, non-last-sale-eligible
   prints should be excluded from OHLC here (documented extension point).
5. A bar is emitted only once it is **complete** (a later print opens the next bucket) so we
   never publish a partial bar as final. ``flush()`` emits the final in-progress bar (e.g. at
   session close / no-overnight flatten).
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from adapters.base import BarTick, TapeTick

ODD_LOT_SIZE = 100  # informational threshold; odd lots are included (rule 3)

_TIMEFRAME_SECONDS = {"10s": 10, "1m": 60}


def timeframe_seconds(timeframe: str) -> int:
    """Resolve a supported timeframe label to seconds. Fail loud on unsupported input."""
    try:
        return _TIMEFRAME_SECONDS[timeframe]
    except KeyError:
        raise ValueError(
            f"unsupported timeframe {timeframe!r}; supported: {sorted(_TIMEFRAME_SECONDS)}"
        ) from None


def bucket_start(ts: datetime, timeframe: str) -> datetime:
    """Floor ``ts`` to the start of its bar bucket (UTC-epoch aligned)."""
    if ts.tzinfo is None:
        raise ValueError("tape timestamps must be tz-aware (UTC)")
    secs = timeframe_seconds(timeframe)
    utc = ts.astimezone(UTC)
    epoch = int(utc.timestamp())
    floored = epoch - (epoch % secs)
    return datetime.fromtimestamp(floored, tz=UTC)


class BarBuilder:
    """Aggregate a single symbol's tape prints into OHLCV bars at one timeframe."""

    def __init__(self, symbol: str, timeframe: str) -> None:
        self.symbol = symbol
        self.timeframe = timeframe
        timeframe_seconds(timeframe)  # validate early
        self._bucket: datetime | None = None
        self._open: Decimal | None = None
        self._high: Decimal | None = None
        self._low: Decimal | None = None
        self._close: Decimal | None = None
        self._volume: int = 0

    def on_print(self, tape: TapeTick) -> BarTick | None:
        """Fold a print into the current bar; return the previous bar if this opens a new one."""
        if tape.symbol != self.symbol:
            raise ValueError(f"print for {tape.symbol!r} fed to {self.symbol!r} builder")
        bucket = bucket_start(tape.ts, self.timeframe)
        emitted: BarTick | None = None

        if self._bucket is None:
            self._bucket = bucket
        elif bucket > self._bucket:
            emitted = self._finalize()
            self._bucket = bucket
        elif bucket < self._bucket:
            # Out-of-order print older than the current bar: ignore (fail-safe, no rewrite).
            return None

        price = tape.price
        if self._open is None:
            self._open = self._high = self._low = self._close = price
        else:
            # Invariant: O/H/L/C are set together, so all four are non-None here.
            assert self._high is not None and self._low is not None
            if price > self._high:
                self._high = price
            if price < self._low:
                self._low = price
            self._close = price
        self._volume += tape.size
        return emitted

    def flush(self) -> BarTick | None:
        """Emit the final in-progress bar (session close / flatten), if any."""
        return self._finalize()

    def _finalize(self) -> BarTick | None:
        if self._bucket is None or self._open is None:
            return None
        assert self._high is not None and self._low is not None and self._close is not None
        bar = BarTick(
            symbol=self.symbol,
            ts=self._bucket,
            timeframe=self.timeframe,
            open=self._open,
            high=self._high,
            low=self._low,
            close=self._close,
            volume=self._volume,
        )
        self._open = self._high = self._low = self._close = None
        self._volume = 0
        return bar


class MultiTimeframeBarBuilder:
    """Fan one symbol's tape into several timeframes (e.g. 10s + 1m) at once."""

    def __init__(self, symbol: str, timeframes: tuple[str, ...] = ("10s", "1m")) -> None:
        self.symbol = symbol
        self._builders = {tf: BarBuilder(symbol, tf) for tf in timeframes}

    def on_print(self, tape: TapeTick) -> list[BarTick]:
        out: list[BarTick] = []
        for builder in self._builders.values():
            bar = builder.on_print(tape)
            if bar is not None:
                out.append(bar)
        return out

    def flush(self) -> list[BarTick]:
        return [bar for b in self._builders.values() if (bar := b.flush()) is not None]


def build_bars(symbol: str, timeframe: str, prints: list[TapeTick]) -> list[BarTick]:
    """Backtest helper: a span of prints → completed bars (including the final one)."""
    builder = BarBuilder(symbol, timeframe)
    bars: list[BarTick] = []
    for tp in prints:
        bar = builder.on_print(tp)
        if bar is not None:
            bars.append(bar)
    final = builder.flush()
    if final is not None:
        bars.append(final)
    return bars


__all__ = [
    "ODD_LOT_SIZE",
    "BarBuilder",
    "MultiTimeframeBarBuilder",
    "bucket_start",
    "build_bars",
    "timeframe_seconds",
]
