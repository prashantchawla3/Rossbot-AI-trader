"""Shared pytest fixtures.

Unit tests run against an in-memory SQLite DB (fast, no infra). Postgres-specific behavior
(append-only triggers, hypertables, full migration) is exercised by the ``integration``-marked
tests in test_schema_migration.py, which require ROSSBOT_TEST_DATABASE_URL.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from db.models import Base
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker


@pytest.fixture
def sqlite_engine() -> Iterator[Engine]:
    engine = create_engine("sqlite://", future=True)
    Base.metadata.create_all(engine)
    try:
        yield engine
    finally:
        Base.metadata.drop_all(engine)
        engine.dispose()


@pytest.fixture
def session(sqlite_engine: Engine) -> Iterator[Session]:
    factory = sessionmaker(bind=sqlite_engine, expire_on_commit=False, future=True)
    with factory() as s:
        yield s
