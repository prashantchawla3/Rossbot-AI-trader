"""Acceptance: "config loader returns seeded C1–C16."

Seeds the config table (SQLite) and loads it back through the typed loader.
"""

from __future__ import annotations

from decimal import Decimal

from core.config import CONFLICT_KEYS, DEFAULTS
from db.config_loader import load_config
from db.config_seed import seed_config
from sqlalchemy.orm import Session


def test_seed_then_load_roundtrip(session: Session) -> None:
    inserted = seed_config(session)
    assert inserted == len(DEFAULTS)

    cfg = load_config(session)
    # Every conflict key (C1–C16) is present and typed.
    assert cfg.keys() >= CONFLICT_KEYS
    assert cfg.get_decimal("RETRACE_MAX") == Decimal("0.50")
    assert cfg.get_str("SIZING_MODE") == "risk_formula"
    assert cfg.get_bool("LIVE_ENABLED") is False


def test_seed_is_idempotent(session: Session) -> None:
    assert seed_config(session) == len(DEFAULTS)
    assert seed_config(session) == 0  # second run inserts nothing
