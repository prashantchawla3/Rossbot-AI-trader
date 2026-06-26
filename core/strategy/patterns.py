"""Label-agnostic pattern recognisers (spec §4 / §4A).

All functions are pure: (bars, context, config-params) → PatternMatch | None.
No I/O, no side effects.  Geometry is the judge — label names are for
reporting only, not for decision logic.

Universal failed-pattern / reversal set (spec §4A):
  - doji/shooting-star/gravestone after up-move + next candle makes new low
  - false breakout (1–5c breach then flush)
  - candle-under-candle (breaks low of previous)
  - drop below 9 EMA or VWAP
  - MACD negative cross
  - retrace > 50%
  - breakout on suspiciously light volume after earlier spike (RKDA fixture)
"""

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP

from adapters.base import BarTick
from core.indicators import MacdPoint, macd_positive
from core.strategy.models import PATTERN_RANK, PatternMatch, PatternType


# ──────────────────────────────────────────────────────────────────────────────
# Candle-shape helpers
# ──────────────────────────────────────────────────────────────────────────────

def is_topping_candle(bar: BarTick) -> bool:
    """Detect doji / shooting-star / gravestone-doji / tweezer-top shape.

    Criteria: upper shadow ≥ 2× body (or zero body = doji).
    spec §3 P4 / §4A failed-pattern.
    """
    body = abs(bar.close - bar.open)
    upper_shadow = bar.high - max(bar.open, bar.close)
    if upper_shadow <= Decimal("0.005"):  # trivial wick — not a topping tail
        return False
    if body == Decimal("0"):
        return True  # pure doji
    return upper_shadow >= body * Decimal("2")


# ──────────────────────────────────────────────────────────────────────────────
# Individual pattern detectors
# ──────────────────────────────────────────────────────────────────────────────

def is_micro_pullback(
    bars: list[BarTick],
    ctx: "PullbackContext",  # noqa: F821
    ema9: Decimal | None,
) -> PatternMatch | None:
    """R1 — Micro Pullback (highest conviction, 'bread & butter').

    3–4 green surge candles → 1–2 (max 3) pullback bars on LIGHT volume →
    first candle to new high.  Bonus: pullback ≤ 25% or touches 9 EMA.
    spec §4A micro_pullback.
    """
    if len(bars) < 4:
        return None

    # Require 1–3 pullback candles (already enforced by ctx.pullback_count).
    # Confirm pullback bars have lighter average volume than the surge bars.
    n = len(bars)
    pb_start = n - 2  # index of first (most recent) pullback bar
    pb_end = n - 2 - ctx.pullback_count  # exclusive lower bound

    pb_vols = [bars[i].volume for i in range(pb_end, pb_start + 1) if i >= 0]
    # Surge bars are immediately before the pullback
    surge_start_idx = pb_end - 1
    surge_bars_vols = [
        bars[i].volume
        for i in range(max(0, surge_start_idx - 4), surge_start_idx + 1)
        if i >= 0 and bars[i].close > bars[i].open
    ]

    avg_pb_vol = sum(pb_vols) / max(1, len(pb_vols)) if pb_vols else 0.0
    avg_surge_vol = sum(surge_bars_vols) / max(1, len(surge_bars_vols)) if surge_bars_vols else 0.0

    light_volume = avg_pb_vol <= avg_surge_vol * 0.8 if avg_surge_vol > 0 else True

    if not light_volume:
        # Pullback on heavy volume is not a clean micro-pullback (more like a reversal risk).
        return None

    # Prefer tight retraces; allow but note shallow vs deep.
    confidence = Decimal("0.90") if ctx.retrace_ratio <= Decimal("0.25") else Decimal("0.75")

    # Bonus: pullback touched 9 EMA.
    if ema9 is not None:
        pb_low = ctx.pullback_low
        if ema9 >= pb_low * Decimal("0.99") and ema9 <= ctx.surge_high:
            confidence = min(Decimal("1.0"), confidence + Decimal("0.05"))

    return PatternMatch(pattern=PatternType.MICRO_PULLBACK, confidence=confidence)


def _find_abcd_structure(
    bars: list[BarTick],
    pre_p2_idx: int,
) -> tuple[Decimal, Decimal] | None:
    """Find H1 (bounce high) and P1 (prior pullback low) going back from pre_p2_idx.

    Returns (H1_high, P1_low) if ABCD structure found, else None.
    """
    i = pre_p2_idx

    # Green bars = H1 bounce
    h1_bars: list[BarTick] = []
    while i >= 0 and bars[i].close > bars[i].open:
        h1_bars.append(bars[i])
        i -= 1

    if not h1_bars:
        return None
    h1_high = max(b.high for b in h1_bars)

    # Red bars = P1 pullback
    p1_bars: list[BarTick] = []
    while i >= 0 and bars[i].close < bars[i].open:
        p1_bars.append(bars[i])
        i -= 1

    if not p1_bars:
        return None
    p1_low = min(b.low for b in p1_bars)

    return h1_high, p1_low


def is_abcd(
    bars: list[BarTick],
    ctx: "PullbackContext",  # noqa: F821
) -> PatternMatch | None:
    """R2 — ABCD ('W') pattern, label-agnostic geometry.

    surge → P1 (first pullback low) → H1 (bounce high) → P2 (second pullback,
    P2 ≥ P1) → break of H1.  INVALID if P2 < P1 (stair-stepping down).

    spec §4A ABCD_VALID.
    """
    n = len(bars)
    if n < 8:
        return None  # need room for signal + P2 + H1 bounce + P1 + initial surge

    # The P2 pullback is ctx.pullback_count bars ending at bars[-2].
    # The bar before P2 (last bar of the H1 bounce) is at:
    pre_p2_idx = n - 2 - ctx.pullback_count
    if pre_p2_idx < 3:
        return None

    result = _find_abcd_structure(bars, pre_p2_idx)
    if result is None:
        return None

    h1_high, p1_low = result

    # Core ABCD rule: P2 ≥ P1 (higher low).
    if ctx.pullback_low < p1_low:
        return None  # P2 undercut P1 → void (stair-stepping down, spec §4A)

    # Signal bar should be approaching / breaking H1 (within 5% tolerance).
    signal_bar = bars[-1]
    if signal_bar.high < h1_high * Decimal("0.95"):
        return None  # Not reaching H1 — may be ABCD setup but not the entry bar yet.

    return PatternMatch(pattern=PatternType.ABCD, confidence=Decimal("0.85"))


def is_bull_flag(
    bars: list[BarTick],
    ctx: "PullbackContext",  # noqa: F821
    ema9: Decimal | None,
    flag_consolidation_max: Decimal,
) -> PatternMatch | None:
    """R3 — Bull Flag.

    Strong pole up on increasing volume → 1–3 red flag bars on LIGHT volume
    (tight, top 15–25% of pole) → first green to new high on increasing volume.
    4–6 flag candles = weak (interest lost) — return None.
    spec §4A bull_flag.
    """
    n = len(bars)
    if n < 5:
        return None

    pullback_count = ctx.pullback_count
    if pullback_count > 3:
        return None  # Too many flag bars = interest lost

    # Flag must stay in the top quarter of the pole range (tight consolidation).
    if ctx.retrace_ratio > flag_consolidation_max:
        return None

    # Pole volume vs flag volume: flag bars should be lighter.
    pb_start = n - 2
    pb_end = n - 2 - pullback_count
    flag_vols = [bars[i].volume for i in range(max(0, pb_end), pb_start + 1)]
    surge_vols = [
        bars[i].volume for i in range(max(0, pb_end - 5), max(0, pb_end))
        if bars[i].close > bars[i].open
    ]

    avg_flag_vol = sum(flag_vols) / max(1, len(flag_vols)) if flag_vols else 0.0
    avg_surge_vol = sum(surge_vols) / max(1, len(surge_vols)) if surge_vols else 0.0

    if avg_surge_vol > 0 and avg_flag_vol > avg_surge_vol:
        return None  # Heavy flag volume — not a clean flag

    # Signal bar (breakout) should ideally have volume ≥ flag average.
    signal_vol: int = bars[-1].volume
    signal_increasing = avg_flag_vol == 0 or signal_vol >= avg_flag_vol

    confidence = Decimal("0.80") if signal_increasing else Decimal("0.65")

    # Bonus: flag touched 9 EMA.
    if ema9 is not None and ctx.pullback_low <= ema9 <= ctx.surge_high:
        confidence = min(Decimal("1.0"), confidence + Decimal("0.05"))

    return PatternMatch(pattern=PatternType.BULL_FLAG, confidence=confidence)


def is_flat_top(bars: list[BarTick]) -> PatternMatch | None:
    """R3 variant — Flat-Top Breakout.

    Multiple prior candles share the same high (horizontal resistance) within
    a 3-cent tolerance.  Signal bar breaks above.
    spec §4A bull_flag flat-top variant.
    """
    if len(bars) < 4:
        return None

    signal = bars[-1]
    tolerance = Decimal("0.03")

    # Need at least 2 prior bars with matching highs.
    prior_highs = [bars[-(k + 2)].high for k in range(min(3, len(bars) - 2))]
    if len(prior_highs) < 2:
        return None

    high_range = max(prior_highs) - min(prior_highs)
    if high_range > tolerance:
        return None  # Highs not flat enough

    resistance = max(prior_highs)
    if signal.high <= resistance:
        return None  # Signal bar didn't break out

    return PatternMatch(pattern=PatternType.FLAT_TOP, confidence=Decimal("0.75"))


def is_gap_and_go(
    bars: list[BarTick],
    gap_pct: Decimal,
    gap_min_pct: Decimal = Decimal("4.0"),
) -> PatternMatch | None:
    """R5 — Gap and Go.

    Significant pre-market gap (≥4%) followed by continuation.
    Entry timing: ENTRY_TRIGGER config (candle_close default; mid_candle in HOT).
    spec §4A gap_and_go / §2 entry-timing conflict C12.
    """
    if len(bars) < 2:
        return None
    if gap_pct < gap_min_pct:
        return None

    # The signal bar should be continuing in the gap direction (still climbing).
    signal = bars[-1]
    if signal.close <= signal.open:
        return None  # Gap-and-go signal bar should be green

    return PatternMatch(pattern=PatternType.GAP_AND_GO, confidence=Decimal("0.70"))


def is_vwap_break(
    bars: list[BarTick],
    vwap: Decimal | None,
) -> PatternMatch | None:
    """R6 — VWAP Break / Snap.

    Signal bar closes above VWAP; prior bar was at or below VWAP.
    spec §4.
    """
    if vwap is None or len(bars) < 2:
        return None

    signal = bars[-1]
    prior = bars[-2]

    crossed = signal.close > vwap and prior.close <= vwap
    if not crossed:
        return None

    return PatternMatch(pattern=PatternType.VWAP_BREAK, confidence=Decimal("0.65"))


def is_halt_resumption(
    bars: list[BarTick],
    is_halted_resume: bool,
) -> PatternMatch | None:
    """R7 — Halt Resumption (Dip and Rip).

    Default post_halt mode: stock resumes from LULD halt at/above prior price.
    Entry on micro-dip then rip with green prints.
    spec §12A / C14 HALT_MODE default post_halt.
    """
    if not is_halted_resume:
        return None
    if len(bars) < 2:
        return None

    signal = bars[-1]
    # Resumption bar should be green (rip).
    if signal.close <= signal.open:
        return None

    return PatternMatch(pattern=PatternType.HALT_RESUMPTION, confidence=Decimal("0.60"))


def is_red_to_green(
    bars: list[BarTick],
    prev_close: Decimal | None,
) -> PatternMatch | None:
    """R10 — Red-to-Green.

    Stock crosses back above its prior closing price on strong volume.
    spec §4 R10.
    """
    if prev_close is None or len(bars) < 2:
        return None

    signal = bars[-1]
    prior = bars[-2]

    # Signal bar closes above prev_close; prior bar was at or below prev_close.
    if signal.close <= prev_close or prior.close > prev_close:
        return None

    # Confirm on positive volume trend.
    vol_increasing = bars[-1].volume >= bars[-2].volume
    confidence = Decimal("0.55") if vol_increasing else Decimal("0.45")

    return PatternMatch(pattern=PatternType.RED_TO_GREEN, confidence=confidence)


def is_reverse_split_squeeze(
    bars: list[BarTick],
    recent_reverse_split: bool,
) -> PatternMatch | None:
    """R11 — Reverse Split Squeeze.

    Recent reverse split dramatically reduces float → tight squeeze → momentum.
    spec §4 R11 / §9 REVERSE_SPLIT_IPO_SCAN.
    """
    if not recent_reverse_split:
        return None
    if len(bars) < 2:
        return None

    signal = bars[-1]
    if signal.close <= signal.open:
        return None

    return PatternMatch(pattern=PatternType.REVERSE_SPLIT_SQUEEZE, confidence=Decimal("0.50"))


# ──────────────────────────────────────────────────────────────────────────────
# Failed-pattern / invalidation detector
# ──────────────────────────────────────────────────────────────────────────────

def is_failed_pattern(
    bars: list[BarTick],
    vwap: Decimal | None,
    ema9: Decimal | None,
    macd_point: MacdPoint | None,
    retrace_ratio: Decimal,
    *,
    light_volume_ratio: Decimal = Decimal("0.30"),
    volume_spike_lookback: int = 10,
) -> tuple[bool, str]:
    """Check the universal failed-pattern / invalidation set (spec §4A).

    Returns (is_failed, reason_str).  Reason is empty string when not failed.
    """
    if len(bars) < 2:
        return False, ""

    current = bars[-1]
    previous = bars[-2]

    # ── Topping tail CONFIRMED by next candle making new low (P4) ─────────────
    # When processing current bar, check if PREVIOUS bar was a topping candle
    # AND current bar's low is below previous bar's low (confirms the reversal).
    if is_topping_candle(previous) and current.low < previous.low:
        return True, "topping_tail_confirmed"

    # ── False breakout: tiny breach then flush below prior close ───────────────
    if len(bars) >= 2:
        breach = current.high - previous.high
        if Decimal("0") < breach <= Decimal("0.05") and current.close < previous.close:
            return True, "false_breakout_flush"

    # ── Candle under candle: current close < previous low ─────────────────────
    if current.close < previous.low:
        return True, "candle_under_candle"

    # ── Drop below 9 EMA ──────────────────────────────────────────────────────
    if ema9 is not None and current.close < ema9:
        return True, "below_9ema"

    # ── Drop below VWAP ───────────────────────────────────────────────────────
    if vwap is not None and current.close < vwap:
        return True, "below_vwap"

    # ── MACD negative cross ────────────────────────────────────────────────────
    if macd_point is not None and not macd_positive(macd_point):
        return True, "macd_negative_cross"

    # ── Retrace > 50% (should be caught by E5, but double-check here) ─────────
    if retrace_ratio > Decimal("0.50"):
        return True, "retrace_exceeds_50pct"

    # ── Light-volume breakout after an earlier spike (RKDA fixture) ────────────
    # Detect: there was a high-volume spike in the lookback window, but the
    # current breakout bar has suspiciously low volume vs that spike.
    if len(bars) >= 3:
        lookback = bars[-volume_spike_lookback:] if len(bars) >= volume_spike_lookback else bars
        prior_vols = [b.volume for b in lookback[:-1]]  # exclude current bar
        if prior_vols:
            spike_vol = max(prior_vols)
            avg_vol = sum(prior_vols) / len(prior_vols)
            # A prior spike exists if max > 3× average volume.
            if spike_vol > avg_vol * 3 and current.volume < spike_vol * float(light_volume_ratio):
                return True, "light_volume_breakout_after_spike"

    return False, ""


# ──────────────────────────────────────────────────────────────────────────────
# Main pattern recogniser
# ──────────────────────────────────────────────────────────────────────────────

def recognize_pattern(
    bars: list[BarTick],
    ctx: "PullbackContext",  # noqa: F821
    *,
    vwap: Decimal | None,
    ema9: Decimal | None,
    is_halted_resume: bool,
    recent_reverse_split: bool,
    prev_close: Decimal | None,
    gap_pct: Decimal,
    flag_consolidation_max: Decimal,
    gap_min_pct: Decimal = Decimal("4.0"),
) -> PatternMatch:
    """Return the highest-priority recognised pattern (lowest PATTERN_RANK value).

    All patterns are checked; the one with the lowest rank number wins.
    Returns PatternType.NONE if no pattern is recognised.
    spec §4 / §4A / §13.8.
    """
    candidates: list[PatternMatch] = []

    def _add(m: PatternMatch | None) -> None:
        if m is not None:
            candidates.append(m)

    _add(is_micro_pullback(bars, ctx, ema9))
    _add(is_abcd(bars, ctx))
    _add(is_bull_flag(bars, ctx, ema9, flag_consolidation_max))
    _add(is_flat_top(bars))
    _add(is_gap_and_go(bars, gap_pct, gap_min_pct))
    _add(is_vwap_break(bars, vwap))
    _add(is_halt_resumption(bars, is_halted_resume))
    _add(is_red_to_green(bars, prev_close))
    _add(is_reverse_split_squeeze(bars, recent_reverse_split))

    if not candidates:
        return PatternMatch(pattern=PatternType.NONE, confidence=Decimal("0.0"))

    # Return the highest-priority match (lowest rank number).
    return min(candidates, key=lambda m: PATTERN_RANK[m.pattern])


# Re-export PullbackContext type hint (used in function signatures via string).
from core.strategy.models import PullbackContext  # noqa: E402


__all__ = [
    "is_abcd",
    "is_bull_flag",
    "is_failed_pattern",
    "is_flat_top",
    "is_gap_and_go",
    "is_halt_resumption",
    "is_micro_pullback",
    "is_red_to_green",
    "is_reverse_split_squeeze",
    "is_topping_candle",
    "is_vwap_break",
    "recognize_pattern",
]
