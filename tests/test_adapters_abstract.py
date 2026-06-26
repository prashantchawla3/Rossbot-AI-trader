"""Acceptance: "adapter ABCs can't be instantiated" + no native STOP/MARKET order type."""

from __future__ import annotations

import pytest
from adapters.base import BrokerAdapter, MarketDataAdapter, OrderType
from adapters.providers import CatalystProvider, L2SignalProvider, MarketStateProvider


@pytest.mark.parametrize(
    "abc",
    [
        BrokerAdapter,
        MarketDataAdapter,
        CatalystProvider,
        L2SignalProvider,
        MarketStateProvider,
    ],
)
def test_abcs_cannot_be_instantiated(abc: type) -> None:
    with pytest.raises(TypeError):
        abc()


def test_order_type_has_no_stop_or_market() -> None:
    # U7/U13 by construction: only limit-style orders are representable.
    values = {ot.value for ot in OrderType}
    assert values == {"limit", "marketable_limit"}
    assert "stop" not in values
    assert "market" not in values


def test_broker_adapter_exposes_no_stop_method() -> None:
    # The broker contract must not offer a native-stop write path (§13.4).
    forbidden = {"submit_stop", "submit_market", "place_stop", "stop_order"}
    assert forbidden.isdisjoint(dir(BrokerAdapter))
