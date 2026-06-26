"""Tests for CapitalRamp (Phase 6 staged capital ramp).

spec §5/§6/Phase 6 / ROSSBOT_PROJECT_PLAN.md Phase 6.
"""

from __future__ import annotations

import pytest

from core.config import ConfigService, DEFAULTS, ValueType
from core.live.capital_ramp import CapitalRamp
from core.live.models import CapitalTier


def _config(**overrides: str) -> ConfigService:
    rows = {d.key: (d.value, d.value_type) for d in DEFAULTS}
    for key, val in overrides.items():
        # Preserve the declared ValueType for keys that exist in DEFAULTS
        existing_type = next((d.value_type for d in DEFAULTS if d.key == key), ValueType.STR)
        rows[key] = (val, existing_type)
    return ConfigService(rows)


def _micro_config() -> ConfigService:
    return _config(
        CAPITAL_RAMP_TIER="MICRO",
        CAPITAL_RAMP_MICRO_SHARES="100",
        CAPITAL_RAMP_STARTER_SHARES="2000",
    )


def _starter_config() -> ConfigService:
    return _config(
        CAPITAL_RAMP_TIER="STARTER",
        CAPITAL_RAMP_MICRO_SHARES="100",
        CAPITAL_RAMP_STARTER_SHARES="2000",
    )


def _full_config() -> ConfigService:
    return _config(
        CAPITAL_RAMP_TIER="FULL",
        CAPITAL_RAMP_MICRO_SHARES="100",
        CAPITAL_RAMP_STARTER_SHARES="2000",
    )


# ── tier property ─────────────────────────────────────────────────────────────

def test_tier_micro():
    ramp = CapitalRamp(_micro_config())
    assert ramp.tier is CapitalTier.MICRO


def test_tier_starter():
    ramp = CapitalRamp(_starter_config())
    assert ramp.tier is CapitalTier.STARTER


def test_tier_full():
    ramp = CapitalRamp(_full_config())
    assert ramp.tier is CapitalTier.FULL


def test_unknown_tier_defaults_to_micro():
    cfg = _config(CAPITAL_RAMP_TIER="UNKNOWN_TIER")
    ramp = CapitalRamp(cfg)
    assert ramp.tier is CapitalTier.MICRO  # fail-safe


# ── apply() capping ───────────────────────────────────────────────────────────

def test_micro_caps_to_100():
    ramp = CapitalRamp(_micro_config())
    assert ramp.apply(500) == 100
    assert ramp.apply(100) == 100
    assert ramp.apply(50) == 50  # under cap → not inflated


def test_micro_does_not_inflate():
    ramp = CapitalRamp(_micro_config())
    assert ramp.apply(30) == 30  # 30 < 100 → unchanged


def test_starter_caps_to_2000():
    ramp = CapitalRamp(_starter_config())
    assert ramp.apply(5000) == 2000
    assert ramp.apply(2000) == 2000
    assert ramp.apply(1500) == 1500  # under cap → unchanged


def test_full_no_cap():
    ramp = CapitalRamp(_full_config())
    assert ramp.apply(9999) == 9999
    assert ramp.apply(50000) == 50000  # no cap in FULL tier


def test_apply_zero_stays_zero():
    for cfg in [_micro_config(), _starter_config(), _full_config()]:
        ramp = CapitalRamp(cfg)
        assert ramp.apply(0) == 0


# ── max_for_tier() ────────────────────────────────────────────────────────────

def test_max_for_tier_micro():
    ramp = CapitalRamp(_micro_config())
    assert ramp.max_for_tier() == 100


def test_max_for_tier_starter():
    ramp = CapitalRamp(_starter_config())
    assert ramp.max_for_tier() == 2000


def test_max_for_tier_full_returns_none():
    ramp = CapitalRamp(_full_config())
    assert ramp.max_for_tier() is None


# ── apply never returns more than approved ─────────────────────────────────────

def test_apply_never_exceeds_approved():
    for cfg in [_micro_config(), _starter_config(), _full_config()]:
        ramp = CapitalRamp(cfg)
        for n in [0, 1, 50, 100, 500, 2000, 10000]:
            assert ramp.apply(n) <= n
