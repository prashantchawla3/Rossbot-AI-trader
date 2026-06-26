"""Hard-to-automate signal provider interfaces (STUB-THEN-HARDEN, Rule C).

These three providers wrap the spec's highest-risk dependencies. Phase 0 ships ABCs + the
enums whose MOST CONSERVATIVE member is the fail-closed default:
- Catalyst (Pillar 5, §13.1)  -> UNVERIFIED  (Pillar 5 fails -> no trade)
- L2 signal (E6, §13.2)        -> UNKNOWN     (E6 fails -> no trade)
- Market state (§8, §13.9)     -> COLD        (blocks EX1/EX2/mid-candle/oversize)

The real classifiers replace the stubs in Phases 7/8/9. A stub must NEVER default to a
permissive value (Rule C).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from enum import StrEnum


class CatalystVerdict(StrEnum):
    """Pillar-5 verdict. ``UNVERIFIED`` is the fail-closed default; ``SKIP`` = hard block."""

    VERIFIED = "verified"
    UNVERIFIED = "unverified"  # fail-closed default
    SKIP = "skip"  # SKIP-list catalyst (buyout/secondary/recycled-PR/pump/5c-tick) — U15


class L2Signal(StrEnum):
    """Order-book read for E6 (§2A). ``UNKNOWN`` is the fail-closed default."""

    SUPPORT = "support"  # real floor / absorbed-then-break (bullish, E6 satisfied)
    ABSORB_BREAK = "absorb_break"
    SPOOF = "spoof"  # vanishing bid / fake → avoid (EX4/EX6)
    ICEBERG = "iceberg"  # hidden seller → do not buy (GMBL/NIXX)
    UNKNOWN = "unknown"  # fail-closed default → E6 fails


class MarketState(StrEnum):
    """Market regime (§8). ``COLD`` is the fail-closed default (most conservative)."""

    HOT = "hot"
    COLD = "cold"  # fail-closed default
    REHAB = "rehab"


class CatalystProvider(ABC):
    """Classifies whether a symbol has a real, tradable catalyst (Pillar 5)."""

    @abstractmethod
    async def classify(self, symbol: str) -> CatalystVerdict:
        """Return the catalyst verdict. Bias to UNVERIFIED/SKIP on ambiguity (§13.1)."""


class L2SignalProvider(ABC):
    """Reads depth/tape into an E6 order-book signal (§2A, §13.2)."""

    @abstractmethod
    async def evaluate(self, symbol: str) -> L2Signal:
        """Return the order-book signal. Require prints-confirmation before SUPPORT (§13.2)."""


class MarketStateProvider(ABC):
    """Classifies the market regime that gates risky exceptions (§8, §13.9)."""

    @abstractmethod
    async def classify(self) -> MarketState:
        """Return the current regime. Bias COLD on uncertainty (§13.9)."""
