"""Conservative fill model for the backtester and paper simulator.

OPTIMISTIC FILLS ARE FORBIDDEN. See ``FILL_MODEL_DOC`` for the full documented model.
All money values: Decimal. Float is forbidden (CLAUDE.md §10).
spec Phase 4 plan / CLAUDE.md §9.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from decimal import Decimal

# ── Public documentation of the fill model ───────────────────────────────────

FILL_MODEL_DOC = """
Conservative Fill Model for Sub-$20 Low-Float Names
=====================================================
RULE: Optimistic fills are FORBIDDEN (plan Phase 4 / CLAUDE.md §9).
      When in doubt, assume the worse fill. This model must under-estimate PnL.

Entry fills (BUY):
  - Base order: limit @ ask + BUY_OFFSET (config, default $0.05).  spec §10
  - Slippage: max(1, min(5, floor(price_in_dollars / 10))) cents
      $2 name → 1¢ | $10 name → 1¢ | $20 name → 2¢ (thin books widen)
  - Partial fill: Alpaca paper has ~10% random probability of 50% partial fill.
    With a deterministic seed: modelled; without seed: assume full fill (conservative
    because partial fills reduce risk but we size down ourselves via LIQUIDITY_CAP).
  - Result: fill_price = ask + offset + slippage (always above mid)

Exit fills — mental stop breach (U13):
  - The bot uses an internal price monitor + marketable-limit (never a native STOP).
    spec §3 P1 / §11 U13 / §13.4
  - Latency cost (documented U13 risk, spec §13.4): the marketable-limit is fired
    AFTER the monitor detects the breach, which incurs ~1 bar of latency on the fill.
  - fill_price = min(stop_price − LATENCY_SLIP, bar_low − 0.01)
      where LATENCY_SLIP = $0.05 (conservative, measured against real resting-stop fills)
  - This is intentionally WORSE than a resting stop, which is forbidden.
  - Optional hidden catastrophic backstop (not modelled here; placed far below).

Exit fills — profit targets / scale-outs (P5, P6, P7):
  - Sell at bid (spec §10 "sell @ bid").
  - Slippage: 1¢ additional (selling into momentum is generally cleaner than stops).

ECN / Regulatory Fees (verified 2026 from SEC/FINRA/NYSE sources):
  - SEC Transaction Fee: $0.00 per share (rate dropped to ~$0 effective May 14, 2025).
  - FINRA TAF: $0.000195 per share on SELLS only (2026 rate), capped at $9.79/txn.
  - Exchange blended taker: $0.0003 per share (conservative; actual range $0.00–$0.002).
  - Buy-side total: ~$0.0003 per share (exchange only).
  - Sell-side total: ~$0.000195 + $0.0003 = ~$0.000495/share (rounded to $0.0005).
  Note: for a 2,000-share trade, total fees ≈ $1.00; negligible vs spread cost but included.
"""

# ── Fee constants (Decimal, NEVER float) ─────────────────────────────────────

_FINRA_TAF_PER_SHARE = Decimal("0.000195")    # sells only (2026 rate)
_FINRA_TAF_CAP = Decimal("9.79")              # per-transaction cap
_EXCHANGE_TAKER_PER_SHARE = Decimal("0.0003") # conservative blended taker
_SEC_FEE_PER_SHARE = Decimal("0")             # ~$0 effective May 2025

# U13 latency cost: documented cost of mental-stop vs resting stop (spec §13.4)
MENTAL_STOP_LATENCY_SLIP = Decimal("0.05")    # 5 cents conservative


@dataclass(frozen=True)
class FillResult:
    """Result of a simulated fill."""

    fill_price: Decimal
    fill_shares: int          # may be < requested on partial fill
    fees: Decimal             # total ECN + regulatory (Decimal, never float)
    is_partial: bool = False
    slippage: Decimal = Decimal("0")  # documented slippage vs ideal price


# ── Entry fill ────────────────────────────────────────────────────────────────

def entry_fill(
    ask_price: Decimal,
    buy_offset: Decimal,
    requested_shares: int,
    *,
    seed: int | None = None,
) -> FillResult:
    """Simulate a BUY entry fill. Conservative: always above mid.

    ``seed`` enables deterministic partial-fill simulation (for replay).
    Without seed, full fill is assumed (optimism guard: partial = less risk).
    spec §10 (limit @ ask+offset) / FILL_MODEL_DOC.
    """
    # Slippage: 1¢ per $10 of price, min 1¢, max 5¢
    price_cents = int(ask_price)
    slip_cents = max(1, min(5, price_cents // 10))
    slippage = Decimal(slip_cents) / Decimal("100")

    fill_price = ask_price + buy_offset + slippage

    # Partial fill: Alpaca paper has ~10% probability of 50% partial
    is_partial = False
    fill_shares = requested_shares
    if seed is not None:
        rng = random.Random(seed)
        if rng.random() < 0.10:
            fill_shares = max(1, requested_shares // 2)
            is_partial = True

    # Buy-side fees: exchange taker only (no SEC, no FINRA TAF on buys)
    fees = Decimal(fill_shares) * _EXCHANGE_TAKER_PER_SHARE

    return FillResult(
        fill_price=fill_price,
        fill_shares=fill_shares,
        fees=fees,
        is_partial=is_partial,
        slippage=slippage,
    )


# ── Stop exit fill (U13 latency cost) ────────────────────────────────────────

def exit_fill_stop(
    stop_price: Decimal,
    bar_low: Decimal,
    shares: int,
) -> FillResult:
    """Simulate a mental-stop exit fill with documented U13 latency cost.

    Fill is INTENTIONALLY WORSE than a resting stop would achieve.
    spec §3 P1 / §11 U13 / §13.4 / FILL_MODEL_DOC.
    """
    # Latency penalty: we fill at worse than the stop price
    latency_adjusted = stop_price - MENTAL_STOP_LATENCY_SLIP
    # Also can't fill above bar_low (we didn't exit before the bar low)
    fill_price = min(latency_adjusted, bar_low - Decimal("0.01"))
    fill_price = max(fill_price, Decimal("0.01"))  # floor at 1¢

    slippage = stop_price - fill_price
    fees = _sell_fees(fill_price, shares)

    return FillResult(
        fill_price=fill_price,
        fill_shares=shares,
        fees=fees,
        slippage=slippage,
    )


# ── Profit-target / scale-out exit fill ──────────────────────────────────────

def exit_fill_target(
    bid_price: Decimal,
    shares: int,
    extra_slippage: Decimal = Decimal("0.01"),
) -> FillResult:
    """Simulate a profit-target or scale-out exit fill.

    Sell at bid with 1¢ slippage (spec §10 'sell @ bid').
    spec §3 P5/P6/P7 / §10 / FILL_MODEL_DOC.
    """
    fill_price = max(bid_price - extra_slippage, Decimal("0.01"))
    fees = _sell_fees(fill_price, shares)

    return FillResult(
        fill_price=fill_price,
        fill_shares=shares,
        fees=fees,
        slippage=extra_slippage,
    )


# ── Internal helpers ──────────────────────────────────────────────────────────

def _sell_fees(fill_price: Decimal, shares: int) -> Decimal:  # noqa: ARG001 (fill_price kept for future SEC calc)
    """FINRA TAF + exchange taker on sells. SEC fee ~$0 as of May 2025."""
    finra = min(
        Decimal(shares) * _FINRA_TAF_PER_SHARE,
        _FINRA_TAF_CAP,
    )
    exchange = Decimal(shares) * _EXCHANGE_TAKER_PER_SHARE
    return finra + exchange


__all__ = [
    "FILL_MODEL_DOC",
    "MENTAL_STOP_LATENCY_SLIP",
    "FillResult",
    "entry_fill",
    "exit_fill_stop",
    "exit_fill_target",
]
