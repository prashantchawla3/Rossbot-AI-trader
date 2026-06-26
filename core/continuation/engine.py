"""Multi-day continuation engine — pure functions. spec §12B / §13.10.

Day-2 continuation eligibility and done-condition checks.

Eligibility (ELIGIBLE_DAY2, spec §12B):
  - Day-1 move ≥ 100% (day1_high / day1_open - 1 ≥ 1.0)
  - Held gains into close: close ≥ CONTINUATION_HOLD_PCT * day1_high

Done-conditions (DONE_IF, spec §12B):
  - today_rvol < 25% of prev_day_volume        (RVOL_FADED)
  - retrace > 50% of Day-1 move                (RETRACE_EXCEEDED)
  - MACD histogram turns negative              (MACD_NEGATIVE_CROSS)
  - breaks AND holds below session VWAP        (VWAP_BROKEN)

All functions are pure (no I/O, no side effects).
spec §12B / §13.10.
"""

from __future__ import annotations

from decimal import Decimal

from core.config import ConfigService
from core.continuation.models import (
    ContinuationContext,
    Day2Settings,
    DoneReason,
    EligibilityResult,
)


# Minimum hold fraction of Day-1 high at close for continuation eligibility.
# Configurable via CONTINUATION_HOLD_PCT; default 0.70 (held 70% of Day-1 high).
_DEFAULT_HOLD_PCT = Decimal("0.70")


def evaluate_day2_eligibility(
    ctx: ContinuationContext,
    cfg: ConfigService,
) -> EligibilityResult:
    """Determine if a symbol qualifies for Day-2 continuation. spec §12B ELIGIBLE_DAY2.

    Returns EligibilityResult with eligible=True/False and diagnostic fields.
    """
    # ── Day-1 move ≥ 100% ────────────────────────────────────────────────────
    if ctx.day1_open <= Decimal("0"):
        return EligibilityResult(
            eligible=False,
            day1_move_pct=Decimal("0"),
            held_close_pct=Decimal("0"),
            reason="day1_open is zero or negative",
        )

    day1_move_pct = (ctx.day1_high - ctx.day1_open) / ctx.day1_open * Decimal("100")

    min_move_pct = (
        cfg.get_decimal("CONTINUATION_MIN_DAY1_PCT")
        if cfg.has("CONTINUATION_MIN_DAY1_PCT")
        else Decimal("100")
    )
    if day1_move_pct < min_move_pct:
        return EligibilityResult(
            eligible=False,
            day1_move_pct=day1_move_pct,
            held_close_pct=Decimal("0"),
            reason=f"Day-1 move {day1_move_pct:.1f}% < required {min_move_pct}%",
        )

    # ── Held gains into close ─────────────────────────────────────────────────
    hold_pct = (
        cfg.get_decimal("CONTINUATION_HOLD_PCT")
        if cfg.has("CONTINUATION_HOLD_PCT")
        else _DEFAULT_HOLD_PCT
    )
    held_close_pct = ctx.day1_close / ctx.day1_high if ctx.day1_high > Decimal("0") else Decimal("0")

    if held_close_pct < hold_pct:
        return EligibilityResult(
            eligible=False,
            day1_move_pct=day1_move_pct,
            held_close_pct=held_close_pct,
            reason=(
                f"Day-1 close held only {held_close_pct * 100:.1f}% of high "
                f"(need ≥{hold_pct * 100:.0f}%)"
            ),
        )

    return EligibilityResult(
        eligible=True,
        day1_move_pct=day1_move_pct,
        held_close_pct=held_close_pct,
        reason="eligible",
    )


def check_continuation_done(
    ctx: ContinuationContext,
    cfg: ConfigService,
) -> DoneReason:
    """Check whether Day-2 continuation conditions have been exhausted. spec §12B DONE_IF.

    Returns the first triggered DoneReason, or DoneReason.NOT_DONE.
    """
    # ── RVOL_FADED: today volume < 25% of Day-1 volume ───────────────────────
    rvol_threshold = (
        cfg.get_decimal("CONTINUATION_RVOL_DONE_PCT")
        if cfg.has("CONTINUATION_RVOL_DONE_PCT")
        else Decimal("0.25")
    )
    if ctx.prev_day_volume > 0:
        today_rvol_frac = Decimal(ctx.today_volume) / Decimal(ctx.prev_day_volume)
        if today_rvol_frac < rvol_threshold:
            return DoneReason.RVOL_FADED

    # ── RETRACE_EXCEEDED: today retrace > 50% of Day-1 move ──────────────────
    day1_move = ctx.day1_high - ctx.day1_open
    retrace_done_pct = (
        cfg.get_decimal("CONTINUATION_RETRACE_DONE_PCT")
        if cfg.has("CONTINUATION_RETRACE_DONE_PCT")
        else Decimal("0.50")
    )
    if day1_move > Decimal("0"):
        today_retrace = ctx.day1_high - ctx.today_low
        retrace_frac = today_retrace / day1_move
        if retrace_frac > retrace_done_pct:
            return DoneReason.RETRACE_EXCEEDED

    # ── MACD_NEGATIVE_CROSS: histogram turns negative ─────────────────────────
    if ctx.macd_histogram < Decimal("0"):
        return DoneReason.MACD_NEGATIVE_CROSS

    # ── VWAP_BROKEN: current price below session VWAP ─────────────────────────
    if ctx.current_price < ctx.current_vwap and ctx.current_vwap > Decimal("0"):
        return DoneReason.VWAP_BROKEN

    return DoneReason.NOT_DONE


def get_day2_settings(cfg: ConfigService) -> Day2Settings:
    """Return the adjusted Day-2 parameters. spec §12B ADJUSTMENTS.

    Forces 5-min timeframe and a reduced size fraction (default 50%).
    """
    size_fraction = (
        cfg.get_decimal("CONTINUATION_SIZE_FRACTION")
        if cfg.has("CONTINUATION_SIZE_FRACTION")
        else Decimal("0.50")
    )
    return Day2Settings(
        timeframe="5m",
        size_fraction=size_fraction,
        avoid_gap_and_go=True,
        avoid_aggressive_hod=True,
    )


__all__ = ["check_continuation_done", "evaluate_day2_eligibility", "get_day2_settings"]
