"""Config domain: cautious C1–C16 defaults present and typed correctly (CLAUDE.md §6)."""

from __future__ import annotations

from datetime import time
from decimal import Decimal

import pytest
from core.config import (
    CONFLICT_KEYS,
    DEFAULTS,
    CatalystVerifyMode,
    ConfigService,
    EntryTrigger,
    HaltMode,
    SizingMode,
    StopBasis,
    ValueType,
    parse_value,
)


def test_all_16_conflicts_present() -> None:
    # C1..C16 each contribute >=1 key; every one must be seeded.
    refs = {d.spec_ref.split("/")[0] for d in DEFAULTS if d.spec_ref.startswith("C")}
    assert refs == {f"C{i}" for i in range(1, 17)}
    assert CONFLICT_KEYS  # non-empty


def test_no_duplicate_keys() -> None:
    keys = [d.key for d in DEFAULTS]
    assert len(keys) == len(set(keys))


def test_cautious_defaults() -> None:
    cfg = ConfigService.from_defaults()
    cfg.validate_conflicts_present()
    # Cautious picks per Appendix A.
    assert cfg.get_str("SIZING_MODE") == SizingMode.RISK_FORMULA.value
    assert cfg.get_str("ENTRY_TRIGGER") == EntryTrigger.CANDLE_CLOSE.value
    assert cfg.get_str("CATALYST_VERIFY_MODE") == CatalystVerifyMode.BEFORE.value
    assert cfg.get_str("HALT_MODE") == HaltMode.POST_HALT.value
    assert cfg.get_str("STOP_BASIS") == StopBasis.PULLBACK_LOW.value
    assert cfg.get_decimal("RETRACE_MAX") == Decimal("0.50")
    assert cfg.get_decimal("MOVE_BE_TRIGGER") == Decimal("0.10")
    assert cfg.get_time("HARD_STOP_TIME") == time(11, 0)
    # Fail-safe gates default to the safe side.
    assert cfg.get_bool("LIVE_ENABLED") is False
    assert cfg.get_str("MARKET_STATE_DEFAULT") == "COLD"
    assert cfg.get_int("MAX_TRADES_PER_DAY") == 1


def test_max_size_not_hardcoded_100k() -> None:
    # C11: never hardcode 100k; cautious, liquidity-capped.
    cfg = ConfigService.from_defaults()
    assert cfg.get_int("MAX_SIZE") < 100_000


def test_validate_conflicts_present_raises_when_missing() -> None:
    svc = ConfigService({"SWEET_SPOT_LOW": ("5.00", ValueType.DECIMAL)})
    with pytest.raises(ValueError, match="missing required conflict"):
        svc.validate_conflicts_present()


def test_parse_value_types() -> None:
    assert parse_value("3", ValueType.INT) == 3
    assert parse_value("1.5", ValueType.DECIMAL) == Decimal("1.5")
    assert parse_value("true", ValueType.BOOL) is True
    assert parse_value("off", ValueType.BOOL) is False
    assert parse_value("09:30", ValueType.TIME) == time(9, 30)


def test_parse_bad_bool_raises() -> None:
    with pytest.raises(ValueError, match="invalid bool"):
        parse_value("maybe", ValueType.BOOL)


def test_typed_getter_mismatch_raises() -> None:
    cfg = ConfigService.from_defaults()
    with pytest.raises(TypeError):
        cfg.get_int("SIZING_MODE")  # it's a str
