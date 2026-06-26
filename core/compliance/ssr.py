"""SSR (Short Sale Restriction) and LULD band utilities. spec §13.11.

SEC Rule 201 (Short Sale Restriction):
  SSR activates when a stock drops ≥10% from its prior day close.
  It restricts short sales to uptick prices (above current NBB) for the
  rest of the current trading day PLUS the next full trading session.

Effect on RossBot (long-only, no short selling):
  SSR does NOT affect long entries. It is tracked here because:
  1. It reflects underlying selling pressure (catalyst for gap-fills).
  2. It is wired into the halt engine for context on resumed stocks.
  3. The audit trail records it for review.

LULD bands (Reg SCI / FINRA Rule 7100A):
  Tier 1 (S&P 500 / Russell 1000 / select ETPs): ±5% band
  Tier 2 other NMS (stocks typically ≥$3): ±5% normal, ±20% for $0.75–$3
  Below $0.75: ±75% or $0.15 (lesser)
  Last 25 min of RTH: bands double for all ≤$3 stocks.
  Halt pause = 5 minutes after 15-second Limit State.
"""

from __future__ import annotations

from decimal import Decimal


# SSR trigger threshold (SEC Rule 201).
SSR_TRIGGER_PCT = Decimal("10")


def is_ssr_active(current_price: Decimal, prior_close: Decimal) -> bool:
    """True when SEC Rule 201 SSR is triggered (price down ≥10% from prior close).

    RossBot is long-only; SSR does not block entries — log only. spec §13.11.
    """
    if prior_close <= Decimal("0"):
        return False
    change_pct = (current_price - prior_close) / prior_close * Decimal("100")
    return change_pct <= -SSR_TRIGGER_PCT


def luld_band_pct(price: Decimal, *, near_close: bool = False) -> Decimal:
    """Return the LULD percentage band for a given price tier (one-sided).

    ``near_close=True`` doubles the band for stocks ≤$3 (last 25-min rule).
    Caller uses: band_low = price * (1 - band_pct/100); band_high = price * (1 + band_pct/100).
    Source: FINRA Rule 7100A / Reg SCI.
    """
    if price < Decimal("0.75"):
        # Below $0.75: 75% or $0.15 (lesser). Return 75% pct here; caller checks $0.15 floor.
        return Decimal("75")
    if price < Decimal("3.00"):
        base = Decimal("20")
        return base * Decimal("2") if near_close else base
    # Tier 1 and most Tier 2 NMS ≥$3: 5% band.
    return Decimal("5")


def luld_bands(price: Decimal, *, near_close: bool = False) -> tuple[Decimal, Decimal]:
    """Return (lower_band_price, upper_band_price) for the given price.

    Uses luld_band_pct(); minimum absolute band of $0.15 for stocks below $0.75.
    spec §13.11 / FINRA Rule 7100A.
    """
    pct = luld_band_pct(price, near_close=near_close)
    half = price * pct / Decimal("100")
    if price < Decimal("0.75"):
        half = max(half, Decimal("0.15"))
    return price - half, price + half


__all__ = ["is_ssr_active", "luld_band_pct", "luld_bands"]
