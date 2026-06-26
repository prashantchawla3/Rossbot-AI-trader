"""Seed the ``config`` table from ``core.config.DEFAULTS`` (cautious C1–C16 + operational).

Idempotent upsert: inserts missing keys, leaves existing rows untouched (operators may have
tuned them out-of-session — STANDING RULES never edit config mid-session). The Alembic
migration calls ``seed_config`` on upgrade.
"""

from __future__ import annotations

from core.config import DEFAULTS
from sqlalchemy import select
from sqlalchemy.orm import Session

from db.models import ConfigRow


def seed_config(session: Session) -> int:
    """Insert any missing default config rows. Returns the number inserted."""
    existing = set(session.scalars(select(ConfigRow.key)).all())
    inserted = 0
    for d in DEFAULTS:
        if d.key in existing:
            continue
        session.add(
            ConfigRow(
                key=d.key,
                value=d.value,
                value_type=d.value_type.value,
                category=d.category,
                spec_ref=d.spec_ref,
                description=d.description,
            )
        )
        inserted += 1
    session.flush()
    return inserted
