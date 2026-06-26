"""schema v0: 12 tables + append-only triggers + TimescaleDB hypertables + config seed

Revision ID: 0001
Revises:
Create Date: 2026-06-26

Baseline migration. Tables are created from the ORM metadata (single source of truth in
db/models.py), then Postgres-specific hardening is layered on:
- append-only triggers on ledger & risk_events (UPDATE/DELETE blocked) — audit integrity;
- TimescaleDB hypertables on the time-series tables (skipped if the extension is absent);
- config seed (cautious C1–C16 + operational defaults).

Postgres-only steps are guarded so the migration still runs on a plain Postgres (CI) without
the TimescaleDB extension.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from db.config_seed import seed_config
from db.models import APPEND_ONLY_TABLES, HYPERTABLE_SPECS, Base
from sqlalchemy.orm import Session

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_FORBID_FN = "rossbot_forbid_mutation"


def _is_postgres(bind: sa.engine.Connection) -> bool:
    return bind.dialect.name == "postgresql"


def _timescale_available(bind: sa.engine.Connection) -> bool:
    """Try to enable TimescaleDB; return whether it is usable.

    Uses a savepoint so a failed CREATE EXTENSION rolls back cleanly without
    aborting the outer transaction (plain postgres:17 has no timescaledb).
    """
    try:
        with bind.begin_nested():  # SAVEPOINT
            bind.execute(sa.text("CREATE EXTENSION IF NOT EXISTS timescaledb CASCADE"))
        return True
    except Exception:
        return False


def upgrade() -> None:
    bind = op.get_bind()

    # 1) Create every table from the ORM metadata (NUMERIC money, tz-aware timestamps, CHECKs).
    Base.metadata.create_all(bind=bind)

    if _is_postgres(bind):
        # 2) Append-only triggers: ledger & risk_events reject UPDATE/DELETE (audit record).
        op.execute(
            sa.text(
                f"""
                CREATE OR REPLACE FUNCTION {_FORBID_FN}() RETURNS trigger AS $$
                BEGIN
                    RAISE EXCEPTION
                        'append-only table %: % is not permitted', TG_TABLE_NAME, TG_OP;
                END;
                $$ LANGUAGE plpgsql;
                """
            )
        )
        for table in APPEND_ONLY_TABLES:
            op.execute(
                sa.text(
                    f"""
                    CREATE TRIGGER {table}_append_only
                    BEFORE UPDATE OR DELETE ON {table}
                    FOR EACH ROW EXECUTE FUNCTION {_FORBID_FN}();
                    """
                )
            )

        # 3) TimescaleDB hypertables for the high-volume time-series tables (optional).
        if _timescale_available(bind):
            for table, time_col in HYPERTABLE_SPECS:
                op.execute(
                    sa.text(
                        f"SELECT create_hypertable('{table}', '{time_col}', "
                        f"if_not_exists => TRUE, migrate_data => TRUE)"
                    )
                )

    # 4) Seed cautious config defaults (idempotent).
    with Session(bind=bind) as session:
        seed_config(session)
        session.commit()


def downgrade() -> None:
    bind = op.get_bind()

    if _is_postgres(bind):
        for table in APPEND_ONLY_TABLES:
            op.execute(sa.text(f"DROP TRIGGER IF EXISTS {table}_append_only ON {table}"))
        op.execute(sa.text(f"DROP FUNCTION IF EXISTS {_FORBID_FN}()"))

    # Hypertables are dropped together with their tables.
    Base.metadata.drop_all(bind=bind)
