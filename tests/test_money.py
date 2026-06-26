"""Decimal-only money kernel (STANDING RULES B). Floats must never enter the money path."""

from __future__ import annotations

from decimal import Decimal

import pytest
from core.money import FloatMoneyError, Money, cents, from_cents, to_money
from pydantic import BaseModel


def test_to_money_rejects_float() -> None:
    with pytest.raises(FloatMoneyError):
        to_money(1.23)


def test_to_money_rejects_bool() -> None:
    with pytest.raises(FloatMoneyError):
        to_money(True)


def test_to_money_accepts_decimal_int_str() -> None:
    assert to_money(Decimal("2.5")) == Decimal("2.5000")
    assert to_money(7) == Decimal("7.0000")
    assert to_money("3.14") == Decimal("3.1400")


def test_cents_roundtrip() -> None:
    assert cents(Decimal("2.50")) == 250
    assert from_cents(250) == Decimal("2.5000")


def test_cents_rejects_float() -> None:
    with pytest.raises(FloatMoneyError):
        cents(2.50)  # type: ignore[arg-type]


def test_money_annotated_type_rejects_float_in_model() -> None:
    class Trade(BaseModel):
        price: Money

    # A float bound to a Money field is a hard type error: our BeforeValidator raises
    # FloatMoneyError (a TypeError), which pydantic propagates rather than wrapping.
    with pytest.raises(FloatMoneyError):
        Trade(price=1.5)

    assert Trade(price="1.50").price == Decimal("1.5000")
