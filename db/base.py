"""SQLAlchemy declarative base, metadata naming convention, and engine/session factory."""

from __future__ import annotations

import os

from sqlalchemy import MetaData, create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

# Deterministic constraint/index names so Alembic autogenerate + downgrades are stable.
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    """Declarative base for all ORM models."""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)


def database_url() -> str:
    """Resolve the database URL from env (fail-safe: explicit error if unset)."""
    url = os.environ.get("ROSSBOT_DATABASE_URL")
    if not url:
        raise RuntimeError("ROSSBOT_DATABASE_URL is not set (see .env.example)")
    return url


def make_engine(url: str | None = None, *, echo: bool = False) -> Engine:
    """Create a SQLAlchemy engine (psycopg 3 driver for Postgres)."""
    return create_engine(url or database_url(), echo=echo, future=True)


def make_session_factory(engine: Engine) -> sessionmaker[Session]:
    """Create a configured ``sessionmaker`` bound to ``engine``."""
    return sessionmaker(bind=engine, expire_on_commit=False, future=True)
