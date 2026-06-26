"""Schema v0 — the 12 Phase-0 tables (ROSSBOT_PROJECT_PLAN.md Phase 0).

Design rules enforced here by construction:
- All money columns use ``db.types.Money`` (NUMERIC, rejects float). CLAUDE.md §10.
- All timestamps are tz-aware UTC; ET is derived at read time. CLAUDE.md §10.
- ``orders.order_type`` is CHECK-constrained to limit/marketable_limit only — a native
  STOP or MARKET order is impossible to persist (U7 / U13 by construction).
- Time-series tables (bars/quotes/depth_snapshots/tape_prints) carry the time column in
  their PK so the Alembic migration can promote them to TimescaleDB hypertables.

Append-only enforcement (UPDATE/DELETE blocked) for ``ledger`` and ``risk_events`` is added
as Postgres triggers in the migration, not here (triggers are dialect-specific).
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from core.timeutils import now_utc
from sqlalchemy import (
    JSON,
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column

from db.base import Base
from db.types import Money

# Reusable column annotations.
_TS = DateTime(timezone=True)
# BIGINT in Postgres, but INTEGER on SQLite so autoincrement PKs work in unit tests
# (SQLite only auto-assigns rowids to INTEGER PRIMARY KEY, not BIGINT).
_BIGINT_PK = BigInteger().with_variant(Integer, "sqlite")


class Symbol(Base):
    __tablename__ = "symbols"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    symbol: Mapped[str] = mapped_column(String(16), unique=True, index=True)
    name: Mapped[str | None] = mapped_column(String(128))
    exchange: Mapped[str | None] = mapped_column(String(16))
    float_shares: Mapped[int | None] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(_TS, default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(_TS, default=now_utc, onupdate=now_utc)


class Bar(Base):
    """OHLCV bar. Composite PK (symbol_id, timeframe, ts) → hypertable-ready."""

    __tablename__ = "bars"

    symbol_id: Mapped[int] = mapped_column(ForeignKey("symbols.id"), primary_key=True)
    timeframe: Mapped[str] = mapped_column(String(8), primary_key=True)  # "10s" | "1m"
    ts: Mapped[datetime] = mapped_column(_TS, primary_key=True)
    open: Mapped[Decimal] = mapped_column(Money)
    high: Mapped[Decimal] = mapped_column(Money)
    low: Mapped[Decimal] = mapped_column(Money)
    close: Mapped[Decimal] = mapped_column(Money)
    volume: Mapped[int] = mapped_column(BigInteger, default=0)


class Quote(Base):
    """Top-of-book quote. Composite PK (symbol_id, ts) → hypertable-ready."""

    __tablename__ = "quotes"

    symbol_id: Mapped[int] = mapped_column(ForeignKey("symbols.id"), primary_key=True)
    ts: Mapped[datetime] = mapped_column(_TS, primary_key=True)
    bid: Mapped[Decimal] = mapped_column(Money)
    ask: Mapped[Decimal] = mapped_column(Money)
    bid_size: Mapped[int] = mapped_column(BigInteger, default=0)
    ask_size: Mapped[int] = mapped_column(BigInteger, default=0)


class DepthSnapshot(Base):
    """Full depth-of-book snapshot. Levels stored as JSON arrays of [price, size]."""

    __tablename__ = "depth_snapshots"

    symbol_id: Mapped[int] = mapped_column(ForeignKey("symbols.id"), primary_key=True)
    ts: Mapped[datetime] = mapped_column(_TS, primary_key=True)
    # [[price, size], ...] — prices stored as strings to keep exactness through JSON.
    bids: Mapped[list[Any]] = mapped_column(JSON)
    asks: Mapped[list[Any]] = mapped_column(JSON)


class TapePrint(Base):
    """Time & sales print. Composite PK (symbol_id, ts, seq) → hypertable-ready."""

    __tablename__ = "tape_prints"

    symbol_id: Mapped[int] = mapped_column(ForeignKey("symbols.id"), primary_key=True)
    ts: Mapped[datetime] = mapped_column(_TS, primary_key=True)
    seq: Mapped[int] = mapped_column(BigInteger, primary_key=True)  # disambiguate same-ts prints
    price: Mapped[Decimal] = mapped_column(Money)
    size: Mapped[int] = mapped_column(BigInteger)
    side: Mapped[str] = mapped_column(String(8), default="unknown")  # buy | sell | unknown

    __table_args__ = (CheckConstraint("side in ('buy','sell','unknown')", name="tape_side_valid"),)


class SignalRow(Base):
    """A strategy-proposed trade. Phase 0 = table only; nothing routes to a broker."""

    __tablename__ = "signals"

    id: Mapped[int] = mapped_column(_BIGINT_PK, primary_key=True, autoincrement=True)
    symbol_id: Mapped[int] = mapped_column(ForeignKey("symbols.id"), index=True)
    ts: Mapped[datetime] = mapped_column(_TS, default=now_utc)
    pattern: Mapped[str | None] = mapped_column(String(48))
    conviction: Mapped[Decimal | None] = mapped_column(Money)  # 0..1 score, exact
    entry_trigger: Mapped[str | None] = mapped_column(String(16))
    proposed_entry: Mapped[Decimal | None] = mapped_column(Money)
    proposed_stop: Mapped[Decimal | None] = mapped_column(Money)
    proposed_target: Mapped[Decimal | None] = mapped_column(Money)
    detail: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    spec_ref: Mapped[str | None] = mapped_column(String(48))


class Order(Base):
    """An order. Schema forbids native STOP/MARKET order types (U7/U13)."""

    __tablename__ = "orders"

    id: Mapped[int] = mapped_column(_BIGINT_PK, primary_key=True, autoincrement=True)
    # Idempotency key: a retry with the same client_order_id cannot create a duplicate order.
    client_order_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    broker_order_id: Mapped[str | None] = mapped_column(String(64), index=True)
    symbol_id: Mapped[int] = mapped_column(ForeignKey("symbols.id"), index=True)
    signal_id: Mapped[int | None] = mapped_column(ForeignKey("signals.id"))
    side: Mapped[str] = mapped_column(String(8))  # buy | sell
    order_type: Mapped[str] = mapped_column(String(24))  # limit | marketable_limit ONLY
    limit_price: Mapped[Decimal] = mapped_column(Money)
    qty: Mapped[int] = mapped_column(BigInteger)
    status: Mapped[str] = mapped_column(String(24), default="new")
    reason: Mapped[str | None] = mapped_column(Text)
    spec_ref: Mapped[str | None] = mapped_column(String(48))
    created_at: Mapped[datetime] = mapped_column(_TS, default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(_TS, default=now_utc, onupdate=now_utc)

    __table_args__ = (
        CheckConstraint("side in ('buy','sell')", name="order_side_valid"),
        # U7/U13: only limit-style orders may ever exist. No 'market', no 'stop', no 'stop_limit'.
        CheckConstraint("order_type in ('limit','marketable_limit')", name="order_type_limit_only"),
        CheckConstraint("qty > 0", name="order_qty_positive"),
    )


class Fill(Base):
    __tablename__ = "fills"

    id: Mapped[int] = mapped_column(_BIGINT_PK, primary_key=True, autoincrement=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), index=True)
    ts: Mapped[datetime] = mapped_column(_TS, default=now_utc)
    fill_price: Mapped[Decimal] = mapped_column(Money)
    fill_qty: Mapped[int] = mapped_column(BigInteger)
    fees: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"))
    broker_exec_id: Mapped[str | None] = mapped_column(String(64), unique=True)


class Position(Base):
    __tablename__ = "positions"

    id: Mapped[int] = mapped_column(_BIGINT_PK, primary_key=True, autoincrement=True)
    symbol_id: Mapped[int] = mapped_column(ForeignKey("symbols.id"), index=True)
    qty: Mapped[int] = mapped_column(BigInteger, default=0)  # signed; long only in scope now
    avg_price: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"))
    realized_pnl: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"))
    status: Mapped[str] = mapped_column(String(16), default="open")  # open | closed
    opened_at: Mapped[datetime] = mapped_column(_TS, default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(_TS, default=now_utc, onupdate=now_utc)

    __table_args__ = (CheckConstraint("status in ('open','closed')", name="position_status_valid"),)


class LedgerEntry(Base):
    """Append-only money ledger (the legal record). UPDATE/DELETE blocked by trigger."""

    __tablename__ = "ledger"

    id: Mapped[int] = mapped_column(_BIGINT_PK, primary_key=True, autoincrement=True)
    ts: Mapped[datetime] = mapped_column(_TS, default=now_utc, index=True)
    entry_type: Mapped[str] = mapped_column(String(24))  # pnl | fee | deposit | adjustment
    symbol_id: Mapped[int | None] = mapped_column(ForeignKey("symbols.id"))
    ref_order_id: Mapped[int | None] = mapped_column(ForeignKey("orders.id"))
    amount: Mapped[Decimal] = mapped_column(Money)
    balance_after: Mapped[Decimal | None] = mapped_column(Money)
    description: Mapped[str | None] = mapped_column(Text)
    spec_ref: Mapped[str | None] = mapped_column(String(48))


class RiskEvent(Base):
    """Append-only audit of every risk decision (veto/fire). UPDATE/DELETE blocked by trigger."""

    __tablename__ = "risk_events"

    id: Mapped[int] = mapped_column(_BIGINT_PK, primary_key=True, autoincrement=True)
    ts: Mapped[datetime] = mapped_column(_TS, default=now_utc, index=True)
    event_type: Mapped[str] = mapped_column(String(32))  # VETO | LOCKOUT | FLATTEN | STRIKE ...
    rule: Mapped[str | None] = mapped_column(String(16))  # U2, U4, ...
    decision: Mapped[str | None] = mapped_column(String(16))  # REJECT | ALLOW | HALT
    symbol_id: Mapped[int | None] = mapped_column(ForeignKey("symbols.id"))
    detail: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    spec_ref: Mapped[str | None] = mapped_column(String(48))


class ConfigRow(Base):
    """Tunable config (C1–C16 + operational). Read via ``core.config.ConfigService``."""

    __tablename__ = "config"

    key: Mapped[str] = mapped_column(String(48), primary_key=True)
    value: Mapped[str] = mapped_column(Text)
    value_type: Mapped[str] = mapped_column(String(16))
    category: Mapped[str] = mapped_column(String(24))
    spec_ref: Mapped[str | None] = mapped_column(String(48))
    description: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(_TS, default=now_utc, onupdate=now_utc)


# Helpful secondary indexes for time-series scans.
Index("ix_bars_ts", Bar.ts)
Index("ix_quotes_ts", Quote.ts)
Index("ix_tape_prints_ts", TapePrint.ts)

# Names of the append-only tables (consumed by the migration to attach triggers).
APPEND_ONLY_TABLES = ("ledger", "risk_events")
# Time-series tables eligible for TimescaleDB hypertable promotion (table, time_column).
HYPERTABLE_SPECS = (
    ("bars", "ts"),
    ("quotes", "ts"),
    ("depth_snapshots", "ts"),
    ("tape_prints", "ts"),
)

__all__ = [
    "APPEND_ONLY_TABLES",
    "HYPERTABLE_SPECS",
    "Bar",
    "Base",
    "ConfigRow",
    "DepthSnapshot",
    "Fill",
    "LedgerEntry",
    "Order",
    "Position",
    "Quote",
    "RiskEvent",
    "SignalRow",
    "Symbol",
    "TapePrint",
]
