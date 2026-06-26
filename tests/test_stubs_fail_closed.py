"""Acceptance: "stubs fail closed" (Rule C). Most conservative value, always."""

from __future__ import annotations

import asyncio

from adapters.providers import CatalystVerdict, L2Signal, MarketState
from adapters.stubs import (
    StubCatalystProvider,
    StubL2SignalProvider,
    StubMarketStateProvider,
)


def test_catalyst_stub_unverified() -> None:
    verdict = asyncio.run(StubCatalystProvider().classify("AAPL"))
    assert verdict is CatalystVerdict.UNVERIFIED  # Pillar 5 fails -> no trade


def test_l2_stub_unknown() -> None:
    signal = asyncio.run(StubL2SignalProvider().evaluate("AAPL"))
    assert signal is L2Signal.UNKNOWN  # E6 fails -> no trade


def test_market_state_stub_cold() -> None:
    state = asyncio.run(StubMarketStateProvider().classify())
    assert state is MarketState.COLD  # blocks EX1/EX2/mid-candle/oversize


def test_no_stub_returns_permissive_value() -> None:
    # Defensive: ensure none of the stubs accidentally returns a tradeable signal.
    assert asyncio.run(StubCatalystProvider().classify("X")) is not CatalystVerdict.VERIFIED
    assert asyncio.run(StubL2SignalProvider().evaluate("X")) is not L2Signal.SUPPORT
    assert asyncio.run(StubMarketStateProvider().classify()) is not MarketState.HOT
