"""Decimal money kernel.

STANDING RULES B / CLAUDE.md §10: money is ``Decimal`` or integer cents, NEVER ``float``.
A ``float`` reaching the money path is a hard error by construction, not a lint nicety —
binary floats cannot represent cents exactly and silently corrupt a ledger.

Public surface:
- ``Money``      : an Annotated Decimal type that REJECTS ``float`` at pydantic validation.
- ``to_money``   : safe constructor (str/int/Decimal -> Decimal, quantized); raises on float.
- ``cents``      : Decimal -> integer cents (banker-safe rounding).
- ``from_cents`` : integer cents -> Decimal dollars.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from typing import Annotated, Any

from pydantic import BeforeValidator

# Prices/PnL stored at 4 dp (sub-penny ECN pricing); matches NUMERIC(18, 4) in db.types.Money.
MONEY_QUANT = Decimal("0.0001")


class FloatMoneyError(TypeError):
    """Raised when a ``float`` is used where exact money is required."""


def to_money(value: Any) -> Decimal:
    """Coerce ``value`` to a quantized ``Decimal``. Reject ``float`` outright.

    Accepts ``Decimal``, ``int``, and numeric ``str``. ``bool`` is rejected (it is an
    ``int`` subclass but never a valid monetary amount).
    """
    if isinstance(value, bool):
        raise FloatMoneyError(f"bool is not a valid money value: {value!r}")
    if isinstance(value, float):
        raise FloatMoneyError(
            f"float is forbidden for money ({value!r}); pass Decimal, int, or a string."
        )
    if isinstance(value, Decimal):
        return value.quantize(MONEY_QUANT, rounding=ROUND_HALF_UP)
    if isinstance(value, (int, str)):
        return Decimal(value).quantize(MONEY_QUANT, rounding=ROUND_HALF_UP)
    raise FloatMoneyError(f"unsupported money type {type(value).__name__}: {value!r}")


def cents(value: Decimal | int | str) -> int:
    """Return the amount as an integer number of cents (rounded half-up)."""
    if isinstance(value, float):
        raise FloatMoneyError("float is forbidden for money; pass Decimal/int/str.")
    dollars = value if isinstance(value, Decimal) else Decimal(value)
    return int((dollars * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def from_cents(value: int) -> Decimal:
    """Return integer cents as a quantized ``Decimal`` dollar amount."""
    if not isinstance(value, int) or isinstance(value, bool):
        raise FloatMoneyError(f"cents must be a plain int, got {type(value).__name__}")
    return (Decimal(value) / 100).quantize(MONEY_QUANT, rounding=ROUND_HALF_UP)


# Use as a pydantic field type: ``price: Money``. A float passed here raises ValidationError.
Money = Annotated[Decimal, BeforeValidator(to_money)]
