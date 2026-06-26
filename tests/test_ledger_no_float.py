"""Acceptance: "a float-into-ledger test fails as designed."

Enforced at two boundaries:
1. the SQLAlchemy ``Money`` column rejects a float at bind time (storage boundary);
2. an ORM insert of a float amount into ``ledger`` raises before it can be written.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from core.money import FloatMoneyError
from db.models import LedgerEntry
from db.types import Money
from sqlalchemy.exc import StatementError
from sqlalchemy.orm import Session


def test_money_column_rejects_float_bind() -> None:
    col = Money()
    with pytest.raises(FloatMoneyError):
        col.process_bind_param(1.23, dialect=None)  # type: ignore[arg-type]


def test_money_column_accepts_decimal() -> None:
    col = Money()
    assert col.process_bind_param(Decimal("1.23"), dialect=None) == Decimal("1.23")  # type: ignore[arg-type]


def test_float_into_ledger_raises(session: Session) -> None:
    session.add(LedgerEntry(entry_type="pnl", amount=12.34))  # float — forbidden
    # SQLAlchemy wraps the bind-time rejection; the cause is our FloatMoneyError.
    with pytest.raises(StatementError) as excinfo:
        session.flush()
    assert isinstance(excinfo.value.orig, FloatMoneyError)


def test_decimal_into_ledger_ok(session: Session) -> None:
    session.add(LedgerEntry(entry_type="pnl", amount=Decimal("12.34")))
    session.flush()  # must not raise
