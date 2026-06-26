"""Load the ``config`` table into a typed ``core.config.ConfigService``."""

from __future__ import annotations

from core.config import ConfigService, ValueType
from sqlalchemy import select
from sqlalchemy.orm import Session

from db.models import ConfigRow


def load_config(session: Session) -> ConfigService:
    """Read all config rows and return a typed ConfigService. Validates C1–C16 present."""
    rows = session.scalars(select(ConfigRow)).all()
    mapping = {row.key: (row.value, ValueType(row.value_type)) for row in rows}
    service = ConfigService(mapping)
    service.validate_conflicts_present()  # fail-safe: refuse to run with missing conflicts
    return service
