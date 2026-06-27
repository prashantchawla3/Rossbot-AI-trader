"""Alembic environment. URL from ROSSBOT_DATABASE_URL; target metadata from db.models."""

from __future__ import annotations

import os
from logging.config import fileConfig

from alembic import context
from db.base import ssl_connect_args  # Supabase SSL connect-args helper
from db.models import Base  # registers all 12 tables on Base.metadata
from dotenv import load_dotenv
from sqlalchemy import engine_from_config, pool

# Load .env so `python scripts/run_migrations.py` / `alembic upgrade head` pick up
# ROSSBOT_DATABASE_URL locally (no Docker). No-op in CI/prod where vars are exported.
load_dotenv()

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Inject the URL from env (never store secrets in alembic.ini).
_url = os.environ.get("ROSSBOT_DATABASE_URL")
if _url:
    config.set_main_option("sqlalchemy.url", _url)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode (emit SQL, no DBAPI connection)."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode (live connection)."""
    url = config.get_main_option("sqlalchemy.url") or ""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
        connect_args=ssl_connect_args(url),  # sslmode=require for Supabase
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
