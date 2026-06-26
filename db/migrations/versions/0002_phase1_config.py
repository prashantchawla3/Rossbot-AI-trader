"""phase 1: seed new data-layer config keys (Tier A net, RVOL, feeds, attention)

Revision ID: 0002
Revises: 0001
Create Date: 2026-06-26

Phase 1 added scanner/RVOL/feed config keys to ``core.config.DEFAULTS``. ``seed_config`` is
an idempotent upsert (inserts only missing keys), so re-running it here installs the new
Phase-1 rows without touching any operator-tuned Phase-0 values.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from db.config_seed import seed_config
from sqlalchemy.orm import Session

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Keys introduced in Phase 1 (used for a precise downgrade).
_PHASE1_KEYS = (
    "TIER_A_GAP_MIN",
    "TIER_A_RVOL_MIN",
    "TIER_A_FLOAT_CEILING",
    "TIER_A_PRICE_MIN",
    "TIER_A_PRICE_MAX",
    "ATTENTION_PRIME_RANK",
    "ATTENTION_WATCH_RANK",
    "VOLUME_SWEET_LOW",
    "VOLUME_SWEET_HIGH",
    "RUNNING_UP_PCT",
    "RUNNING_UP_WINDOW_MIN",
    "LOW_FLOAT_SUBSCAN_CEILING",
    "RVOL_BASELINE_DAYS",
    "RVOL_MIN_HISTORY_DAYS",
    "FLOAT_DISAGREE_TOLERANCE",
    "REQUIRE_SIP",
    "FEED_STALENESS_SECONDS",
)


def upgrade() -> None:
    bind = op.get_bind()
    with Session(bind=bind) as session:
        seed_config(session)  # idempotent: inserts only the missing Phase-1 keys
        session.commit()


def downgrade() -> None:
    params = {f"k{i}": key for i, key in enumerate(_PHASE1_KEYS)}
    placeholders = ", ".join(f":{name}" for name in params)
    op.execute(sa.text(f"DELETE FROM config WHERE key IN ({placeholders})").bindparams(**params))
