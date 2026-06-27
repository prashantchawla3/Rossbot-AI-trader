"""SQLAlchemy declarative base, metadata naming convention, and engine/session factory."""

from __future__ import annotations

import os

from dotenv import load_dotenv
from sqlalchemy import MetaData, create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

# Load .env so ROSSBOT_DATABASE_URL is available for local dev (no Docker) and CLI use.
# In CI/prod the vars are already exported; load_dotenv() is a no-op when no .env exists.
load_dotenv()

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


def ssl_connect_args(url: str) -> dict[str, str]:
    """SSL connect-args for hosted Postgres (Supabase requires TLS).

    Supabase hostnames are ``db.<ref>.supabase.co`` (direct) and
    ``*.pooler.supabase.com`` (pooler). Add ``sslmode=require`` for either, unless the URL
    already carries an explicit ``sslmode`` (avoids passing it twice). Works for both the
    psycopg 3 (``postgresql+psycopg://``) and psycopg2 (``postgresql://``) drivers.
    """
    if "supabase" in url and "sslmode" not in url:
        return {"sslmode": "require"}
    return {}


def make_engine(url: str | None = None, *, echo: bool = False) -> Engine:
    """Create a SQLAlchemy engine (psycopg 3 driver for Postgres; SSL for Supabase)."""
    resolved = url or database_url()
    return create_engine(
        resolved, echo=echo, future=True, connect_args=ssl_connect_args(resolved)
    )


def make_session_factory(engine: Engine) -> sessionmaker[Session]:
    """Create a configured ``sessionmaker`` bound to ``engine``."""
    return sessionmaker(bind=engine, expire_on_commit=False, future=True)
