"""Entry AND-gate E1–E7 (spec §2).

Pure functions — no side effects, no I/O.  The gate is deterministic: the
same inputs always produce the same verdict, enabling the §12 regression
fixtures to be replayed bit-for-bit.

Entry = E1 AND E2 AND E3 AND E4 AND E5 AND E6 AND E7.
ANY failing gate vetoes the trade.

spec refs:
  E1 §2 E1 / §1 Five Pillars
  E2 §2 E2 / §4A
  E3 §2 E3
  E4 §2 E4
  E5 §2 E5 / C9
  E6 §2 E6 / §2A / §13.2
  E7 §2 E7 (V2)
"""

from __future__ import annotations

from decimal import Decimal

from adapters.base import BarTick
from adapters.providers import L2Signal, MarketState
from core.config import ConfigService, EntryTrigger
from core.indicators import MacdPoint, macd_positive
from core.scanner.models import ScanResult
from core.strategy.models import EntryGateResult, PullbackContext


# ──────────────────────────────────────────────────────────────────────────────
# Candle-direction helpers
# ──────────────────────────────────────────────────────────────────────────────

def is_red_candle(bar: BarTick) -> bool:
    """Red bar: close < open (bearish body)."""
    return bar.close < bar.open


def is_green_candle(bar: BarTick) -> bool:
    """Green bar: close > open (bullish body).  Doji (==) counts as neither."""
    return bar.close > bar.open


# ──────────────────────────────────────────────────────────────────────────────
# Pullback geometry extractor (shared by E2/E5 and pattern recognisers)
# ──────────────────────────────────────────────────────────────────────────────

def find_pullback_context(
    bars: list[BarTick],
    retrace_max: Decimal,
    *,
    surge_min_candles: int = 2,
    pullback_max_candles: int = 3,
) -> PullbackContext | None:
    """Scan backward from bars[-2] to identify 1–3 red pullback bars then a surge.

    Returns a ``PullbackContext`` if the geometry is valid, else ``None``.
    Returning ``None`` means E2 fails (no pullback → chasing a vertical green).

    spec §2 E2 / §4A micro-pullback / §13.8.
    """
    n = len(bars)
    if n < surge_min_candles + pullback_max_candles + 1:
        return None  # not enough history

    # ── Step 1: count consecutive red bars before the signal bar ──────────────
    pullback_bars: list[BarTick] = []
    i = n - 2  # start at bars[-2] (bar immediately before signal bar)
    while i >= 0 and len(pullback_bars) < pullback_max_candles:
        bar = bars[i]
        if is_red_candle(bar):
            pullback_bars.append(bar)
            i -= 1
        else:
            break

    if not pullback_bars:
        return None  # No red pullback → chasing vertical (E2 fails).

    # ── Step 2: count consecutive green surge bars before the pullback ─────────
    surge_bars: list[BarTick] = []
    while i >= 0:
        bar = bars[i]
        if is_green_candle(bar):
            surge_bars.append(bar)
            i -= 1
        else:
            break  # stop at non-green; prior structure handled by caller

    if len(surge_bars) < surge_min_candles:
        return None  # Surge too short to be real.

    pullback_low = min(b.low for b in pullback_bars)
    surge_high = max(b.high for b in surge_bars)
    surge_start = surge_bars[-1].low  # low of the oldest (earliest) surge bar

    move = surge_high - surge_start
    if move <= Decimal("0"):
        return None

    retrace_ratio = (surge_high - pullback_low) / move

    return PullbackContext(
        pullback_count=len(pullback_bars),
        pullback_low=pullback_low,
        surge_high=surge_high,
        surge_start=surge_start,
        retrace_ratio=retrace_ratio,
    )


# ──────────────────────────────────────────────────────────────────────────────
# Individual gate predicates
# ──────────────────────────────────────────────────────────────────────────────

def _e1_universe(scan_result: ScanResult) -> bool:
    """E1: symbol passed Tier B Five Pillars.  spec §2 E1 / §1."""
    return scan_result.tier_b_pass


def _e2_pullback(ctx: PullbackContext | None, max_pullback_candles: int) -> bool:
    """E2: valid pullback found (1–N red candles).  spec §2 E2."""
    if ctx is None:
        return False
    return 1 <= ctx.pullback_count <= max_pullback_candles


def _e3_crossing(bars: list[BarTick], entry_trigger: EntryTrigger) -> bool:
    """E3: signal bar makes a new high vs the previous (pullback) bar.

    candle_close (default): signal bar must CLOSE above the prior bar's high.
    mid_candle (HOT only):  signal bar only needs to TOUCH the prior bar's high.

    spec §2 E3 / C12 / §4A 'first candle to make a new high'.
    """
    if len(bars) < 2:
        return False
    signal = bars[-1]
    prior = bars[-2]
    if entry_trigger is EntryTrigger.MID_CANDLE:
        return signal.high > prior.high
    # candle_close: confirm that the bar closed above the prior bar's high.
    return signal.close > prior.high


def _e4_macd(point: MacdPoint | None) -> bool:
    """E4: MACD positive/crossing-up.  HARD BLOCK if red or None.  spec §2 E4."""
    return macd_positive(point)  # fail-closed on None per spec §2 + §13.2


def _e5_retrace(ctx: PullbackContext, retrace_max: Decimal) -> bool:
    """E5: pullback held the move (retrace ≤ RETRACE_MAX).  spec §2 E5 / C9."""
    return ctx.retrace_ratio <= retrace_max


def _e6_l2(l2_signal: L2Signal) -> bool:
    """E6: real floor or absorbed seller confirmed by L2/tape.

    SUPPORT or ABSORB_BREAK → pass.
    UNKNOWN (stub default) → FAIL CLOSED (spec §13.2 / CLAUDE.md Rule C).
    SPOOF / ICEBERG → fail (EX4, GMBL fixture).
    spec §2 E6 / §2A.
    """
    return l2_signal in (L2Signal.SUPPORT, L2Signal.ABSORB_BREAK)


def _e7_spread(spread: Decimal, spread_min: Decimal, spread_max: Decimal) -> bool:
    """E7: spread ∈ [SPREAD_MIN, SPREAD_MAX].

    ≤ 0.01 = too thick (HFT-dominated, skip).  > 0.10 = too wide (hard veto).
    spec §2 E7 (V2).
    """
    return spread_min <= spread <= spread_max


# ──────────────────────────────────────────────────────────────────────────────
# Main gate evaluator
# ──────────────────────────────────────────────────────────────────────────────

def evaluate_entry_gate(
    *,
    scan_result: ScanResult,
    bars_1m: list[BarTick],
    macd_point: MacdPoint | None,
    l2_signal: L2Signal,
    spread: Decimal,
    vwap: Decimal | None,
    ema9: Decimal | None,
    market_state: MarketState,
    config: ConfigService,
) -> EntryGateResult:
    """Evaluate the full E1–E7 AND-gate.

    Returns ``EntryGateResult.passes = True`` only when ALL seven gates pass.
    Caller should check ``.passes`` before acting on any signal.

    spec §2 ENTRY = E1 AND E2 AND E3 AND E4 AND E5 AND E6 AND E7.
    """
    retrace_max = config.get_decimal("RETRACE_MAX")
    spread_min = config.get_decimal("SPREAD_MIN")
    spread_max = config.get_decimal("SPREAD_MAX")
    max_pullback_candles = config.get_int("PULLBACK_MAX_CANDLES")
    surge_min_candles = config.get_int("SURGE_MIN_CANDLES")

    # C12: mid-candle only when market is HOT.  Force candle_close otherwise.
    entry_trigger_str = config.get_str("ENTRY_TRIGGER")
    if entry_trigger_str == EntryTrigger.MID_CANDLE.value and market_state is not MarketState.HOT:
        entry_trigger = EntryTrigger.CANDLE_CLOSE
    else:
        entry_trigger = EntryTrigger(entry_trigger_str)

    ctx = find_pullback_context(
        bars_1m,
        retrace_max,
        surge_min_candles=surge_min_candles,
        pullback_max_candles=max_pullback_candles,
    )

    e1 = _e1_universe(scan_result)
    e2 = _e2_pullback(ctx, max_pullback_candles)
    e3 = _e3_crossing(bars_1m, entry_trigger) if len(bars_1m) >= 2 else False
    e4 = _e4_macd(macd_point)
    e5 = _e5_retrace(ctx, retrace_max) if ctx is not None else False
    e6 = _e6_l2(l2_signal)
    e7 = _e7_spread(spread, spread_min, spread_max)

    passes = e1 and e2 and e3 and e4 and e5 and e6 and e7

    reasons: list[str] = []
    if not e1:
        reasons.append("E1:five_pillars_fail")
    if not e2:
        if ctx is None:
            reasons.append("E2:no_pullback_or_surge")
        else:
            reasons.append(f"E2:pullback_count_{ctx.pullback_count}_exceeds_{max_pullback_candles}")
    if not e3:
        reasons.append("E3:no_candle_over_candle")
    if not e4:
        reasons.append("E4:macd_red_or_missing")
    if ctx is not None and not e5:
        reasons.append(f"E5:retrace_too_deep_{ctx.retrace_ratio:.3f}_gt_{retrace_max}")
    if not e6:
        reasons.append(f"E6:l2_{l2_signal.value}")
    if not e7:
        reasons.append(f"E7:spread_{spread:.3f}_outside_band")

    return EntryGateResult(
        passes=passes,
        e1_universe=e1,
        e2_pullback=e2,
        e3_crossing=e3,
        e4_macd=e4,
        e5_retrace=e5,
        e6_l2=e6,
        e7_spread=e7,
        pullback_ctx=ctx,
        entry_trigger=entry_trigger,
        spread=spread,
        reasons=tuple(reasons),
    )


__all__ = [
    "evaluate_entry_gate",
    "find_pullback_context",
    "is_green_candle",
    "is_red_candle",
]
