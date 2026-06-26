"""Halt resumption engine — pure functions. spec §12A / §13.7.

POST_HALT (default, C14):
  - Wait for the LULD halt to end (5-min pause).
  - Enter only if resume_price >= pre_halt_price AND green_prints=True.
  - EX5 hard-block: halt-down resume (resume < pre_halt OR halt_type=LULD_DOWN)
    is BLOCKED unless current_vwap is reclaimed (current_price > vwap AND resume > vwap).

PRE_HALT (aggressive, HALT_MODE=pre_halt, HOT only):
  - Enter as price squeezes toward the LULD Limit-Up band.
  - Requires buyer_on_bid (large visible bid = halting to the upside) AND
    distance_to_band_pct <= PRE_HALT_BAND_ENTRY_PCT config.

All functions are pure (no I/O, no side effects).
spec §12A EX5 / §13.7.
"""

from __future__ import annotations

from decimal import Decimal

from adapters.providers import MarketState
from core.config import ConfigService, HaltMode
from core.halt.models import HaltDecision, HaltEvent, HaltType, PreHaltSignal, ResumeQuote


def evaluate_halt_resumption(
    halt_event: HaltEvent,
    resume: ResumeQuote,
    cfg: ConfigService,
    market_state: MarketState,
) -> HaltDecision:
    """Decide whether to enter on a halt resumption. spec §12A / §13.7.

    POST_HALT (default C14):
      BLOCKED if halt was downward and VWAP not reclaimed (EX5).
      SKIP if resume < pre_halt price (weakness) or no green prints.
      ENTER if resume >= pre_halt price AND green prints confirmed.

    PRE_HALT mode is not evaluated here; use evaluate_pre_halt_entry() instead.
    """
    halt_mode = cfg.get_str("HALT_MODE")

    # ── EX5: hard-block halt-DOWN resumption ─────────────────────────────────
    # Halt-down = price flushed below VWAP before halt, or halt_type=LULD_DOWN.
    # Only exception: price has reclaimed AND held above VWAP at resumption.
    # spec §12A EX5 / §13.7 "Hard-block unless VWAP reclaimed".
    is_halt_down = (
        halt_event.halt_type in (HaltType.LULD_DOWN, HaltType.UNKNOWN)
        or resume.resume_price < halt_event.pre_halt_price
    )
    vwap_reclaimed = (
        resume.resume_price > resume.current_vwap
        and resume.current_vwap > Decimal("0")
    )

    if is_halt_down and not vwap_reclaimed:
        return HaltDecision.BLOCKED  # EX5

    # ── POST_HALT (default C14): resumption entry check ──────────────────────
    if halt_mode == HaltMode.POST_HALT.value:
        # Resumption must be at or above the pre-halt price (bullish).
        if resume.resume_price < halt_event.pre_halt_price:
            return HaltDecision.SKIP

        # Require green prints confirming buying pressure at open. spec §12A CONFIRM.
        if not resume.green_prints:
            return HaltDecision.SKIP

        return HaltDecision.ENTER

    # ── PRE_HALT branch — should not reach here (use evaluate_pre_halt_entry).
    # Treat as SKIP to fail safe.
    return HaltDecision.SKIP


def evaluate_pre_halt_entry(
    signal: PreHaltSignal,
    cfg: ConfigService,
    market_state: MarketState,
) -> HaltDecision:
    """Decide whether to enter BEFORE a halt fires (aggressive mode). spec §12A PRE_HALT.

    Only valid when HALT_MODE=pre_halt AND market_state=HOT.
    Requires the symbol to be squeezing toward the LULD Limit-Up band with a
    large buyer on bid.

    SKIP in all other cases — pre-halt carries gap-through risk (C14 warns).
    spec §12A PRE_HALT / §13.7 C14.
    """
    halt_mode = cfg.get_str("HALT_MODE")

    # Pre-halt entries require explicit config opt-in AND HOT market.
    if halt_mode != HaltMode.PRE_HALT.value:
        return HaltDecision.SKIP

    # Gate to HOT market only — cold tape makes pre-halt gap risk unacceptable. spec §8.
    if market_state != MarketState.HOT:
        return HaltDecision.SKIP

    # Require a visible large buyer on the bid (tape confirmation). spec §12A PRE_HALT trigger.
    if not signal.buyer_on_bid:
        return HaltDecision.SKIP

    # Require price to be within PRE_HALT_BAND_ENTRY_PCT of the LULD Limit-Up band.
    # If the config key is absent fall back to a tight 1% (safe default).
    pre_halt_pct = cfg.get_decimal("PRE_HALT_BAND_ENTRY_PCT") if cfg.has("PRE_HALT_BAND_ENTRY_PCT") else Decimal("1.0")
    if signal.distance_to_band_pct > pre_halt_pct:
        return HaltDecision.SKIP

    # EX5 guard: if price is already below VWAP don't enter pre-halt (downward flush risk).
    if signal.current_price < signal.vwap:
        return HaltDecision.BLOCKED

    return HaltDecision.ENTER


__all__ = ["evaluate_halt_resumption", "evaluate_pre_halt_entry"]
