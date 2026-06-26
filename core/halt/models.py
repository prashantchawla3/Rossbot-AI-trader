"""Halt engine domain models — spec §12A / §13.7.

All price fields use Decimal (CLAUDE.md §10).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum


class HaltType(StrEnum):
    """Reason for the trading halt."""

    LULD_UP = "luld_up"       # halted approaching the Limit-Up band
    LULD_DOWN = "luld_down"   # halted approaching the Limit-Down band (EX5 danger)
    NEWS = "news"             # T1/T12 regulatory news halt
    UNKNOWN = "unknown"       # cannot determine direction — treat as LULD_DOWN (safe)


class HaltDecision(StrEnum):
    """Output of the halt-resumption evaluator. spec §12A / §13.7."""

    ENTER = "enter"           # conditions pass — signal HALT_RESUMPTION entry
    SKIP = "skip"             # resumption conditions not met — stay flat
    BLOCKED = "blocked"       # EX5 fired: halt-down resume without VWAP reclaim


@dataclass(frozen=True)
class HaltEvent:
    """State at the moment a halt begins. spec §12A.

    ``pre_halt_price`` is the last trade price before the halt.
    ``vwap`` is the session VWAP at the time of halt.
    ``halt_type`` is inferred from direction.
    """

    symbol: str
    ts: datetime
    halt_type: HaltType
    pre_halt_price: Decimal
    vwap: Decimal


@dataclass(frozen=True)
class ResumeQuote:
    """Data available at halt resumption (reopen auction clearing price). spec §12A.

    ``resume_price`` is the auction/indicative clearing price post-halt.
    ``green_prints`` is True when buy-side tape volume dominates in the first second.
    ``current_vwap`` is the rolling session VWAP at the moment of resume.
    """

    symbol: str
    ts: datetime
    resume_price: Decimal
    green_prints: bool
    current_vwap: Decimal


@dataclass(frozen=True)
class PreHaltSignal:
    """State when approaching LULD band pre-halt (aggressive mode). spec §12A PRE_HALT.

    ``distance_to_band_pct`` is the % gap between current price and the LULD band.
    ``buyer_on_bid`` is True when a large buyer appears on the bid (spec trigger).
    """

    symbol: str
    ts: datetime
    current_price: Decimal
    luld_band: Decimal
    distance_to_band_pct: Decimal
    buyer_on_bid: bool
    vwap: Decimal


__all__ = [
    "HaltDecision",
    "HaltEvent",
    "HaltType",
    "PreHaltSignal",
    "ResumeQuote",
]
