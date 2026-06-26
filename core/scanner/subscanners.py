"""Sub-scanners (spec §9). Each is a pure filter/sort over a candidate list.

These mirror Ross's named scans. They surface *surveillance* subsets — none of them is a trade
trigger on its own; only the Tier-B Five-Pillars gate (``TwoTierScanner``) authorizes a trade.
Audio-alert sounds in the source platforms are UI artifacts and intentionally omitted.
"""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal

from core.scanner.models import ScanCandidate

TOP_GAINER_MIN_PRICE = Decimal("0.50")  # §9 TOP_GAINERS_SCAN: price > $0.50


def _by_change_desc(cands: Sequence[ScanCandidate]) -> list[ScanCandidate]:
    return sorted(cands, key=lambda c: c.change_pct, reverse=True)


def top_gainers(cands: Sequence[ScanCandidate]) -> list[ScanCandidate]:
    """§9 TOP_GAINERS_SCAN: %-change leaders priced above $0.50."""
    return _by_change_desc([c for c in cands if c.price > TOP_GAINER_MIN_PRICE])


def low_float_top_gainer(
    cands: Sequence[ScanCandidate], *, float_ceiling: int, price_max: Decimal
) -> list[ScanCandidate]:
    """§9 LOW_FLOAT_TOP_GAINER: top gainers with a KNOWN float < ceiling and price < max."""
    out = [
        c
        for c in cands
        if c.float_shares is not None and c.float_shares < float_ceiling and c.price < price_max
    ]
    return _by_change_desc(out)


def hod_momentum(cands: Sequence[ScanCandidate]) -> list[ScanCandidate]:
    """§9 HOD_MOMENTUM_SCAN: names printing a new intraday high."""
    return _by_change_desc([c for c in cands if c.at_hod])


def running_up(cands: Sequence[ScanCandidate], *, surge_pct: Decimal) -> list[ScanCandidate]:
    """§9 RUNNING_UP_SCAN: surging ≥ surge_pct over the window but still BELOW the HOD."""
    out = [
        c
        for c in cands
        if not c.at_hod and c.surge_pct_window is not None and c.surge_pct_window >= surge_pct
    ]
    return sorted(
        out,
        key=lambda c: c.surge_pct_window if c.surge_pct_window is not None else Decimal(0),
        reverse=True,
    )


def halt_scan(cands: Sequence[ScanCandidate]) -> list[ScanCandidate]:
    """§9 HALT_SCAN: names entering/exiting an LULD halt."""
    return [c for c in cands if c.is_halted]


def reverse_split_ipo(cands: Sequence[ScanCandidate]) -> list[ScanCandidate]:
    """§9 REVERSE_SPLIT_IPO_SCAN: recent reverse splits and IPOs."""
    return [c for c in cands if c.recent_reverse_split or c.recent_ipo]


def continuation(cands: Sequence[ScanCandidate]) -> list[ScanCandidate]:
    """§9 CONTINUATION_SCAN / LOW_FLOAT_FORMER_MOMO: big movers from the prior ~2 weeks."""
    return _by_change_desc([c for c in cands if c.was_prior_mover])


__all__ = [
    "TOP_GAINER_MIN_PRICE",
    "continuation",
    "halt_scan",
    "hod_momentum",
    "low_float_top_gainer",
    "reverse_split_ipo",
    "running_up",
    "top_gainers",
]
