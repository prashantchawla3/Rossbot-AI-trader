"""Acceptance (integration): schema migrates up/down clean; append-only triggers enforce.

Requires a throwaway Postgres via ROSSBOT_TEST_DATABASE_URL (ideally the TimescaleDB image so
hypertables are exercised too). Skipped automatically when that env var is absent, so the
default unit run stays infra-free.
"""

from __future__ import annotations

import os

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

pytestmark = pytest.mark.integration

_TEST_DB = os.environ.get("ROSSBOT_TEST_DATABASE_URL")

_EXPECTED_TABLES = {
    "symbols",
    "bars",
    "quotes",
    "depth_snapshots",
    "tape_prints",
    "signals",
    "orders",
    "fills",
    "positions",
    "ledger",
    "risk_events",
    "config",
}


@pytest.fixture
def alembic_cfg() -> Config:
    if not _TEST_DB:
        pytest.skip("ROSSBOT_TEST_DATABASE_URL not set")
    os.environ["ROSSBOT_DATABASE_URL"] = _TEST_DB
    cfg = Config("alembic.ini")
    # Clean slate.
    command.downgrade(cfg, "base")
    return cfg


def test_upgrade_creates_tables_and_seeds_config(alembic_cfg: Config) -> None:
    command.upgrade(alembic_cfg, "head")
    engine = create_engine(_TEST_DB, future=True)  # type: ignore[arg-type]
    try:
        tables = set(inspect(engine).get_table_names())
        assert tables >= _EXPECTED_TABLES
        with engine.connect() as conn:
            count = conn.execute(text("SELECT count(*) FROM config")).scalar_one()
        assert count >= 16  # all C1–C16 conflict keys at minimum
    finally:
        engine.dispose()


def test_ledger_is_append_only(alembic_cfg: Config) -> None:
    command.upgrade(alembic_cfg, "head")
    engine = create_engine(_TEST_DB, future=True)  # type: ignore[arg-type]
    try:
        with engine.begin() as conn:
            conn.execute(
                text("INSERT INTO ledger (ts, entry_type, amount) VALUES (now(), 'pnl', 100.00)")
            )
        with engine.begin() as conn, pytest.raises(Exception):  # noqa: B017
            conn.execute(text("UPDATE ledger SET amount = 200.00"))
        with engine.begin() as conn, pytest.raises(Exception):  # noqa: B017
            conn.execute(text("DELETE FROM ledger"))
    finally:
        engine.dispose()


def test_downgrade_drops_tables(alembic_cfg: Config) -> None:
    command.upgrade(alembic_cfg, "head")
    command.downgrade(alembic_cfg, "base")
    engine = create_engine(_TEST_DB, future=True)  # type: ignore[arg-type]
    try:
        tables = set(inspect(engine).get_table_names())
        assert not (_EXPECTED_TABLES & tables)
    finally:
        engine.dispose()
