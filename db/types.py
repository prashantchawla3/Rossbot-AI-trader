"""Custom SQLAlchemy column types.

``Money`` is the schema-level enforcement of the Decimal-only rule (STANDING RULES B):
a ``float`` bound to any money column raises before it can reach the database. This is the
"a float-into-ledger test fails as designed" guarantee at the storage boundary, complementing
``core.money`` at the application boundary.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from core.money import FloatMoneyError
from sqlalchemy import Numeric
from sqlalchemy.engine import Dialect
from sqlalchemy.types import TypeDecorator

# NUMERIC(18, 4): up to 99,999,999,999,999.9999 — ample for prices, PnL, and account equity.
MONEY_PRECISION = 18
MONEY_SCALE = 4


class Money(TypeDecorator[Decimal]):
    """NUMERIC money column that rejects ``float`` at bind time."""

    impl = Numeric(MONEY_PRECISION, MONEY_SCALE, asdecimal=True)
    cache_ok = True

    def process_bind_param(self, value: Any, dialect: Dialect) -> Decimal | None:
        if value is None:
            return None
        if isinstance(value, bool):
            raise FloatMoneyError(f"bool is not valid money: {value!r}")
        if isinstance(value, float):
            raise FloatMoneyError(
                f"float is forbidden for money columns ({value!r}); use Decimal/int/str."
            )
        if isinstance(value, Decimal):
            return value
        if isinstance(value, (int, str)):
            return Decimal(value)
        raise FloatMoneyError(f"unsupported money type {type(value).__name__}: {value!r}")

    def process_result_value(self, value: Any, dialect: Dialect) -> Decimal | None:
        if value is None:
            return None
        return Decimal(value)
