"""Sizing engine — pure function (no side effects).

Computes the approved share count given an entry signal, daily risk state,
config, and market context.  Returns 0 when:
  - stop_price >= entry_price (degenerate; caller adds VetoReason.SIZING_ZERO)
  - all caps reduce shares to zero

Order of operations (spec §6):
  1. Raw count: risk_formula or flat_block
  2. Cushion / icebreaker: day PnL ≤ 0 → icebreaker cap (spec §6 / §5)
  3. Starter cap: positive PnL but below CUSHION_PNL_THRESHOLD
  4. Conviction multiplier (spec §6)
  5. Day-of-week multiplier (spec §5)
  6. Market-state multiplier / cap (spec §8)
  7. Liquidity cap: never be the whole book (U9)
  8. MAX_SIZE hard ceiling (C11)

All arithmetic uses Decimal; no float for sizes (CLAUDE.md §10).
spec §5 (cushion), §6 (sizing), §8 (market state caps), U9 (liquidity).
"""

from __future__ import annotations

from decimal import Decimal, ROUND_DOWN

from adapters.providers import MarketState
from core.config import ConfigService, SizingMode
from core.risk.models import RiskState
from core.strategy.models import EntrySignal


def compute_size(
    signal: EntrySignal,
    state: RiskState,
    cfg: ConfigService,
    market_state: MarketState,
    day_of_week: int,  # 0 = Monday … 4 = Friday … 6 = Sunday
    liquidity_cap_shares: int | None = None,
) -> int:
    """Return approved share count.  0 means cannot size (caller vetoes SIZING_ZERO).

    spec §6 (sizing logic) / §5 (cushion / give-back) / §8 (market-state caps).
    """
    max_size: int = cfg.get_int("MAX_SIZE")
    icebreaker_frac = cfg.get_decimal("ICEBREAKER_FRACTION")
    icebreaker: int = max(
        1,
        int((Decimal(max_size) * icebreaker_frac).to_integral_value(ROUND_DOWN)),
    )

    # ── 1. Raw share count (risk_formula or flat_block) ───────────────────────
    sizing_mode = cfg.get_str("SIZING_MODE")
    raw: int

    if sizing_mode == SizingMode.RISK_FORMULA.value:
        risk_per_share = signal.entry_price - signal.stop_price
        if risk_per_share <= Decimal("0"):
            return 0  # degenerate stop → SIZING_ZERO
        per_trade_risk = cfg.get_decimal("PER_TRADE_RISK_DOLLARS")
        raw = int((per_trade_risk / risk_per_share).to_integral_value(ROUND_DOWN))
    else:  # flat_block
        starter = cfg.get_int("STARTER_CAP")
        if state.realized_pnl >= cfg.get_decimal("CUSHION_PNL_THRESHOLD"):
            raw = max_size
        else:
            raw = starter

    # ── 2. Cushion / icebreaker: cap while day PnL ≤ 0 (spec §6 / §5) ───────
    if state.realized_pnl <= Decimal("0"):
        raw = min(raw, icebreaker)
    elif state.realized_pnl < cfg.get_decimal("CUSHION_PNL_THRESHOLD"):
        # Positive PnL but cushion not yet built → still use STARTER_CAP.
        raw = min(raw, cfg.get_int("STARTER_CAP"))

    # ── 3. Conviction multiplier (0.25–1.0, spec §6) ─────────────────────────
    conviction = signal.conviction_score  # Decimal in [0.25, 1.0]
    raw = int((Decimal(raw) * conviction).to_integral_value(ROUND_DOWN))

    # ── 4. Day-of-week multiplier (spec §5) ──────────────────────────────────
    if day_of_week == 0:  # Monday: most conservative, worst day (spec §5)
        mult = cfg.get_decimal("DOW_MONDAY_MULT")  # default 0.50
        raw = int((Decimal(raw) * mult).to_integral_value(ROUND_DOWN))
    elif day_of_week == 4:  # Friday: conservative (slow / holiday)
        mult = cfg.get_decimal("DOW_FRIDAY_MULT")  # default 0.75
        raw = int((Decimal(raw) * mult).to_integral_value(ROUND_DOWN))

    # ── 5. Market-state multiplier / cap (spec §8) ────────────────────────────
    if market_state == MarketState.REHAB:
        # REHAB: micro size — up to MARKET_STATE_REHAB_CAP (spec §8).
        raw = min(raw, cfg.get_int("MARKET_STATE_REHAB_CAP"))
    elif market_state == MarketState.COLD:
        # COLD: reduce by MARKET_STATE_COLD_MULT (default 0.50, spec §8).
        mult = cfg.get_decimal("MARKET_STATE_COLD_MULT")
        raw = int((Decimal(raw) * mult).to_integral_value(ROUND_DOWN))

    # ── 6. Liquidity cap: never be the whole book (U9) ───────────────────────
    if liquidity_cap_shares is not None and liquidity_cap_shares > 0:
        raw = min(raw, liquidity_cap_shares)

    # ── 7. MAX_SIZE hard ceiling (C11) ───────────────────────────────────────
    raw = min(raw, max_size)

    return max(0, raw)


__all__ = ["compute_size"]
