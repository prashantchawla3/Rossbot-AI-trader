"""Fail-closed provider stubs (Rule C). Every default is the most conservative value.

These are the live implementations until Phases 7/8/9 replace them. They never trade by
omission: catalyst is always UNVERIFIED, the book is always UNKNOWN, the market is always
COLD. Replacing a stub means raising its permissiveness deliberately, with the real model.
"""

from __future__ import annotations

from adapters.providers import (
    CatalystProvider,
    CatalystVerdict,
    L2Signal,
    L2SignalProvider,
    MarketState,
    MarketStateProvider,
)


class StubCatalystProvider(CatalystProvider):
    """Always UNVERIFIED → Pillar 5 fails → no trade (§13.1, Rule C)."""

    async def classify(self, symbol: str) -> CatalystVerdict:
        return CatalystVerdict.UNVERIFIED


class StubL2SignalProvider(L2SignalProvider):
    """Always UNKNOWN → E6 fails → no trade (§13.2, Rule C)."""

    async def evaluate(self, symbol: str) -> L2Signal:
        return L2Signal.UNKNOWN


class StubMarketStateProvider(MarketStateProvider):
    """Always COLD → blocks EX1/EX2/mid-candle/oversize (§13.9, Rule C)."""

    async def classify(self) -> MarketState:
        return MarketState.COLD
