"""Exit rule engine P1–P8 (spec §3).

Pure function: (position, current bar, context) → ExitSignal | None.
Priority order is the spec's: P1 fires before P2, P2 before P3, etc.
The first matching rule wins; lower-priority rules are never checked once
a higher-priority trigger fires.

No I/O, no side effects.

spec refs:
  P1 §3 P1  mental hard stop
  P2 §3 P2  breakout-or-bailout (+10¢/60s time stop)
  P3 §3 P3  L2/tape reversal
  P4 §3 P4  topping tail (confirmed by next candle new low)
  P5 §3 P5  scale into strength (HOD break / psych level)
  P6 §3 P6  first red candle close
  P7 §3 P7  profit stop / VWAP guard
  P8 §3 P8  lost popularity / attention rotation
"""

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP

from adapters.base import BarTick
from adapters.providers import L2Signal
from core.config import ConfigService
from core.strategy.models import ExitReason, ExitSignal, PositionSnapshot, ScaleAction
from core.strategy.patterns import is_topping_candle


def _at_psych_level(price: Decimal, step: Decimal, tolerance: Decimal) -> bool:
    """True if price is within ±tolerance of any n × step boundary ($0.50, $1.00, …)."""
    if step <= Decimal("0"):
        return False
    nearest = (price / step).quantize(Decimal("1"), rounding=ROUND_HALF_UP) * step
    return abs(price - nearest) <= tolerance


def evaluate_exit(
    *,
    position: PositionSnapshot,
    current_bar: BarTick,
    prev_bars: list[BarTick],
    current_price: Decimal,
    l2_signal: L2Signal,
    vwap: Decimal | None,
    market_rank: int | None,
    intraday_high: Decimal,
    config: ConfigService,
) -> ExitSignal | None:
    """Evaluate exit conditions in priority order P1–P8.

    Returns the first firing ExitSignal, or None if no exit condition met.
    spec §3 priority order.
    """
    ts = current_bar.ts
    symbol = position.symbol
    first_scale_fraction = config.get_decimal("FIRST_SCALE_FRACTION")
    bailout_seconds = config.get_int("BAILOUT_SECONDS")
    bailout_move = config.get_decimal("BAILOUT_MOVE")
    move_be_trigger = config.get_decimal("MOVE_BE_TRIGGER")
    attention_watch_rank = config.get_int("ATTENTION_WATCH_RANK")
    psych_step = config.get_decimal("PSYCH_LEVEL_STEP")
    psych_tol = config.get_decimal("PSYCH_LEVEL_TOLERANCE")

    unrealized = current_price - position.entry_price

    # ── P1 — HARD STOP (MENTAL) ───────────────────────────────────────────────
    # IF price <= current_stop THEN sell_full() via marketable-limit.
    # This is the highest priority — checked first, unconditionally.
    # spec §3 P1 / U13 (no native STOP; monitor fires marketable-limit).
    if current_price <= position.current_stop:
        return ExitSignal(
            symbol=symbol,
            ts=ts,
            reason=ExitReason.HARD_STOP,
            action=ScaleAction.FULL_EXIT,
            scale_fraction=Decimal("1.0"),
            spec_ref="§3 P1",
        )

    # ── P2 — BREAKOUT-OR-BAILOUT (TIME STOP) ─────────────────────────────────
    # IF price NOT advanced ≥ BAILOUT_MOVE within BAILOUT_SECONDS → sell_full().
    # Proxy for "pulling away" / "hesitates" judgment (spec §3 P2 / §13.5).
    elapsed = (ts - position.entry_ts).total_seconds()
    if elapsed >= bailout_seconds and unrealized < bailout_move:
        return ExitSignal(
            symbol=symbol,
            ts=ts,
            reason=ExitReason.TIME_STOP,
            action=ScaleAction.FULL_EXIT,
            scale_fraction=Decimal("1.0"),
            spec_ref="§3 P2",
        )

    # ── P3 — L2/TAPE REVERSAL ─────────────────────────────────────────────────
    # Large ask-seller / spoof / iceberg / red-tape burst → sell_full().
    # SPOOF or ICEBERG: do not rely on vanishing bids (EX4/EX6, GMBL/NIXX).
    # spec §3 P3 / §2A.
    if l2_signal in (L2Signal.SPOOF, L2Signal.ICEBERG):
        return ExitSignal(
            symbol=symbol,
            ts=ts,
            reason=ExitReason.L2_REVERSAL,
            action=ScaleAction.FULL_EXIT,
            scale_fraction=Decimal("1.0"),
            spec_ref="§3 P3",
        )

    # ── P4 — TOPPING TAIL (confirmed by next candle making new low) ───────────
    # Check if the PREVIOUS bar was a topping candle AND the current bar
    # confirms by printing a new low below the previous bar's low.
    # spec §3 P4 [V2] "confirmed when NEXT candle makes new low".
    if len(prev_bars) >= 1:
        topping_bar = prev_bars[-1]
        if is_topping_candle(topping_bar) and current_bar.low < topping_bar.low:
            return ExitSignal(
                symbol=symbol,
                ts=ts,
                reason=ExitReason.TOPPING_TAIL,
                action=ScaleAction.FULL_EXIT,
                scale_fraction=Decimal("1.0"),
                spec_ref="§3 P4",
            )

    # ── P5 — SCALE INTO STRENGTH (partial exit + move stop to BE) ────────────
    # Trigger: retest/break HOD  OR  hit $0.50/$1.00 psyche level.
    # Action: sell FIRST_SCALE_FRACTION; move stop to entry (breakeven).
    # spec §3 P5 / C4 / C15.
    hod_break = current_price > intraday_high and position.high_watermark < intraday_high
    psych_hit = _at_psych_level(current_price, psych_step, psych_tol)
    if (hod_break or psych_hit) and unrealized >= move_be_trigger:
        return ExitSignal(
            symbol=symbol,
            ts=ts,
            reason=ExitReason.SCALE_STRENGTH,
            action=ScaleAction.PARTIAL_SCALE,
            scale_fraction=first_scale_fraction,
            new_stop=position.entry_price,  # move to BE
            spec_ref="§3 P5",
        )

    # ── P6 — FIRST RED CANDLE CLOSE ───────────────────────────────────────────
    # The first 1-min candle to close red → sell remaining.
    # spec §3 P6.
    if current_bar.close < current_bar.open:
        return ExitSignal(
            symbol=symbol,
            ts=ts,
            reason=ExitReason.FIRST_RED_CLOSE,
            action=ScaleAction.FULL_EXIT,
            scale_fraction=Decimal("1.0"),
            spec_ref="§3 P6",
        )

    # ── P7 — PROFIT STOP / VWAP GUARD ────────────────────────────────────────
    # Significantly green → trail stop slightly below VWAP.
    # Signal fires when price dips BELOW VWAP while in meaningful profit.
    # spec §3 P7.
    if vwap is not None and unrealized >= move_be_trigger:
        if current_price < vwap:
            return ExitSignal(
                symbol=symbol,
                ts=ts,
                reason=ExitReason.VWAP_GUARD,
                action=ScaleAction.FULL_EXIT,
                scale_fraction=Decimal("1.0"),
                spec_ref="§3 P7",
            )

    # ── P8 — LOST POPULARITY (attention rotation) ────────────────────────────
    # Attention has rotated away; stock is no longer in top-N gainers.
    # spec §3 P8 / §13.3.
    if market_rank is not None and market_rank > attention_watch_rank:
        return ExitSignal(
            symbol=symbol,
            ts=ts,
            reason=ExitReason.LOST_POPULARITY,
            action=ScaleAction.FULL_EXIT,
            scale_fraction=Decimal("1.0"),
            spec_ref="§3 P8",
        )

    return None


__all__ = ["evaluate_exit"]
