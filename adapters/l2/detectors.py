"""Pure detector functions for L2 microstructure signals (spec §2A / §13.2).

All functions are stateless and deterministic — they take snapshot lists and
tape aggregates as plain values, making them fully unit-testable without any
provider or adapter.

Priority order when multiple detectors fire (highest priority first):
  SPOOF / ICEBERG > ABSORB_BREAK > REAL_FLOOR

spec refs:
  detect_spoof       → EX4/EX6 (CADL bid-pull, fake orders → avoid)
  detect_iceberg     → §2A GMBL/NIXX (hidden seller → do NOT buy, if long → exit)
  detect_real_floor  → §2A real floor (stacked bids + prints → SUPPORT)
  detect_absorb_break→ §2A absorbed-then-break (block ticks down → pop) → E6
"""

from __future__ import annotations

from decimal import Decimal

from adapters.l2.models import DepthSnapshot, TapeAggregate

_ZERO = Decimal("0")


# ─────────────────────────────────────────────────────────────────────────────
# SPOOF — vanishing bid, no confirming prints (EX4/EX6/CADL, spec §2A)
# ─────────────────────────────────────────────────────────────────────────────

def detect_spoof(
    snaps: list[DepthSnapshot],
    agg: TapeAggregate,
    *,
    spoof_bid_min_shares: int,
    spoof_decay_secs: int,
    spoof_min_prints: int,
) -> bool:
    """Return True when a large bid appeared then vanished without tape proof.

    A bid is "vanished" when the current best-bid size has dropped to < 20% of
    the peak size seen over the snapshot history.  The bid-pull must have
    happened within spoof_decay_secs of the first appearance (approximated by
    comparing earliest vs latest snapshot timestamps).

    No prints at the level → confirms no real buying pressure → SPOOF.

    spec §2A EX4 (spoofing on L2: fake orders → avoid) / EX6 (CADL bid-pull).
    """
    if len(snaps) < 2:
        return False

    peak_bid_size = max(s.best_bid_size for s in snaps)
    if peak_bid_size < spoof_bid_min_shares:
        return False  # bid was never large enough to be suspicious

    current_bid_size = snaps[-1].best_bid_size
    # "Vanished" = current bid is less than 20% of peak
    if current_bid_size > peak_bid_size * 0.20:
        return False  # bid is still substantially there → not pulled

    # Check decay speed: compare first time we saw a large bid to last snapshot
    first_large_snap = next(
        (s for s in snaps if s.best_bid_size >= spoof_bid_min_shares), None
    )
    if first_large_snap is None:
        return False
    elapsed = (snaps[-1].ts - first_large_snap.ts).total_seconds()
    if elapsed > spoof_decay_secs:
        return False  # bid was present too long to be a fast pull (might be real)

    # Require absence of tape confirmation: not enough prints = no real buying
    # We use the tape aggregate (total_shares is a proxy for activity at the level)
    return agg.total_shares < spoof_min_prints


# ─────────────────────────────────────────────────────────────────────────────
# ICEBERG — executed >> displayed, price not advancing (GMBL/NIXX, spec §2A)
# ─────────────────────────────────────────────────────────────────────────────

def detect_iceberg(
    agg: TapeAggregate,
    snap: DepthSnapshot,
    *,
    absorbed_min: int,
    display_max: int,
    advance_max_cents: int,
) -> bool:
    """Return True when massive tape volume fails to move price — hidden seller.

    Iceberg pattern (spec §2A / U14):
      - Large volume executed (buyers keep buying at the offer)
      - Displayed ask stays small (seller continuously refills from hidden qty)
      - Price does NOT advance despite heavy buying

    This is the GMBL/NIXX pattern: "10k bought, ask shows 100–600, price flat".
    On detection: do NOT enter; if long → exit (P3 L2/tape reversal).
    spec §2A iceberg / U14 "never anticipate $0.50/$1.00 break with hidden seller".
    """
    if agg.is_empty:
        return False
    if agg.total_shares < absorbed_min:
        return False  # not enough volume to trigger suspicion
    if snap.best_ask_size > display_max:
        return False  # displayed size is large — not an iceberg-style hidden seller
    # Price hasn't meaningfully advanced despite heavy buying
    advance = abs(agg.price_advance_cents)
    return advance <= Decimal(str(advance_max_cents))


# ─────────────────────────────────────────────────────────────────────────────
# REAL FLOOR — stable resting bid + confirming prints (spec §2A E6)
# ─────────────────────────────────────────────────────────────────────────────

def detect_real_floor(
    snaps: list[DepthSnapshot],
    agg: TapeAggregate,
    *,
    floor_bid_min_shares: int,
    floor_min_prints: int,
    floor_min_stable_snaps: int,
) -> bool:
    """Return True when a large, stable bid absorbs selling with print confirmation.

    Real floor (spec §2A):
      "multiple MMs stacked at SAME price on bid (e.g. 4 MMs @ $2.25, 3-4 rows),
       esp. at $0.50/$1.00; sits, absorbs selling, prints execute"

    Three conditions must all hold:
      1. Current best bid is large (≥ floor_bid_min_shares)
      2. Bid has been present for ≥ floor_min_stable_snaps consecutive recent snapshots
         (not a flash bid — proves it isn't being pulled)
      3. Tape confirms: ≥ floor_min_prints shares executed in the window
         (sellers are hitting the bid and it's holding → real absorption)

    spec §2A real-floor / E6 prints-confirmation requirement (§13.2).
    """
    if not snaps:
        return False
    current = snaps[-1]
    if current.best_bid_size < floor_bid_min_shares:
        return False  # current bid too small

    # Condition 2: bid must have been stable (present in recent snapshots)
    lookback = snaps[-floor_min_stable_snaps:] if len(snaps) >= floor_min_stable_snaps else snaps
    half_threshold = floor_bid_min_shares // 2
    stable_count = sum(1 for s in lookback if s.best_bid_size >= half_threshold)
    if stable_count < min(floor_min_stable_snaps, len(snaps)):
        return False  # bid appeared then partially disappeared → not stable

    # Condition 3: prints must confirm real activity (sellers hitting the floor)
    return agg.total_shares >= floor_min_prints


# ─────────────────────────────────────────────────────────────────────────────
# ABSORB → BREAK — visible ask absorbed, price then breaks through (spec §2A)
# ─────────────────────────────────────────────────────────────────────────────

def detect_absorb_break(
    snaps: list[DepthSnapshot],
    agg: TapeAggregate,
    *,
    absorb_ask_min_shares: int,
    absorb_tape_min_shares: int,
    absorb_break_min_cents: int,
) -> bool:
    """Return True when a visible large seller is absorbed and price breaks through.

    Absorbed-then-break pattern (spec §2A / E6):
      "visible block ticks down ('20k,19k,18k...boom') then breaks → shorts squeeze, pop"
      OR "price taps a level repeatedly, dips, later tap pushes THROUGH"

    Three conditions must all hold:
      1. Early snapshots show a large ask (visible seller — absorb_ask_min_shares)
      2. Tape confirms: enough shares executed against that seller (absorb_tape_min_shares)
      3. Price has since advanced (best ask NOW > best ask THEN by absorb_break_min_cents)
         proving the seller was absorbed and the break occurred

    spec §2A "ABSORBED (bullish trigger)" / E6 entry condition.
    Requires prints-confirmation before E6 fires (spec §13.2).
    """
    if len(snaps) < 3:
        return False  # need history to identify "early" vs "current"

    # Step 1: find peak ask size in early history (first half of snapshot buffer)
    mid = len(snaps) // 2
    early_snaps = snaps[:mid]
    peak_ask_size = max(s.best_ask_size for s in early_snaps)
    if peak_ask_size < absorb_ask_min_shares:
        return False  # no meaningful visible seller in early history

    # Step 2: tape must show heavy execution (the seller was hit repeatedly)
    if agg.total_shares < absorb_tape_min_shares:
        return False

    # Step 3: current ask price > early ask price by the break threshold
    early_ask_price = min(s.best_ask for s in early_snaps)  # lowest ask in early period
    current_ask_price = snaps[-1].best_ask
    advance_cents = (current_ask_price - early_ask_price) * Decimal("100")
    return advance_cents >= Decimal(str(absorb_break_min_cents))
