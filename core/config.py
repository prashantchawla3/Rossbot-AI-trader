"""Config domain: the typed registry of every tunable, seeded with cautious defaults.

CLAUDE.md §6 / STANDING RULES B: every spec ``⚠️ CONFLICT`` (C1–C16) is a config key with
the spec's *cautious* default — NEVER a hardcoded pick in strategy code. Hard-rule operational
numbers (Five Pillars, spread band, offsets, guard thresholds) also live here so PLR2004
(magic-value) lint keeps them out of code bodies.

This module is pure (no DB import) so ``core`` stays dependency-free:
- ``DEFAULTS``       : the canonical seed rows (key, raw value, type, category, spec ref).
- ``parse_value``    : raw string -> typed Python value, by ``ValueType``.
- ``ConfigService``  : holds a {key: raw_str} map; typed getters + validation.

The DB-facing seed/loader live in ``db/config_seed.py`` and ``db/config_loader.py``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import time
from decimal import Decimal
from enum import StrEnum
from typing import Any

# --------------------------------------------------------------------------------------
# Enumerations for the conflict options (Appendix A). Strategy code switches on these,
# never on raw strings.
# --------------------------------------------------------------------------------------


class SizingMode(StrEnum):
    RISK_FORMULA = "risk_formula"  # C10 default
    FLAT_BLOCK = "flat_block"


class EntryTrigger(StrEnum):
    CANDLE_CLOSE = "candle_close"  # C12 default
    MID_CANDLE = "mid_candle"  # HOT only


class CatalystVerifyMode(StrEnum):
    BEFORE = "before"  # C13 default
    AFTER = "after"  # HOT only


class HaltMode(StrEnum):
    PRE_HALT = "pre_halt"
    POST_HALT = "post_halt"  # C14 default


class StopBasis(StrEnum):
    PULLBACK_LOW = "pullback_low"  # C5 default
    PREV_CANDLE_LOW = "prev_candle_low"


class ValueType(StrEnum):
    STR = "str"
    INT = "int"
    DECIMAL = "decimal"
    BOOL = "bool"
    TIME = "time"  # "HH:MM" ET


@dataclass(frozen=True)
class ConfigDefault:
    """One seed row for the ``config`` table."""

    key: str
    value: str  # stored as text; typed via ``value_type``
    value_type: ValueType
    category: str
    spec_ref: str
    description: str


# --------------------------------------------------------------------------------------
# Canonical defaults. Defaults bias toward CAUTION (CLAUDE.md §6). Conflicts cite C#.
# --------------------------------------------------------------------------------------
DEFAULTS: list[ConfigDefault] = [
    # ---- C1: price sweet spot (spec §1) ----
    ConfigDefault(
        "SWEET_SPOT_LOW",
        "5.00",
        ValueType.DECIMAL,
        "scanner",
        "C1/§1",
        "Preferred price floor (ranking, not a gate).",
    ),
    ConfigDefault(
        "SWEET_SPOT_HIGH",
        "10.00",
        ValueType.DECIMAL,
        "scanner",
        "C1/§1",
        "Preferred price ceiling (ranking, not a gate).",
    ),
    # ---- Pillar 1 hard price gate (spec §1) ----
    ConfigDefault(
        "PRICE_MIN",
        "2.00",
        ValueType.DECIMAL,
        "scanner",
        "§1 PILLAR_1",
        "Five-Pillars hard price floor.",
    ),
    ConfigDefault(
        "PRICE_MAX",
        "20.00",
        ValueType.DECIMAL,
        "scanner",
        "§1 PILLAR_1",
        "Five-Pillars hard price ceiling.",
    ),
    ConfigDefault(
        "HARD_AVOID_BELOW",
        "2.00",
        ValueType.DECIMAL,
        "scanner",
        "§1",
        "Block entries below this for funded accounts (default ON).",
    ),
    # ---- Pillars 2-4 hard gates (spec §1) ----
    ConfigDefault(
        "FLOAT_HARD_CEILING",
        "20000000",
        ValueType.INT,
        "scanner",
        "§1 PILLAR_2",
        "Tier-B float hard ceiling (shares).",
    ),
    ConfigDefault(
        "RVOL_MIN",
        "5.0",
        ValueType.DECIMAL,
        "scanner",
        "§1 PILLAR_3",
        "Tier-B relative-volume minimum (>= inclusive).",
    ),
    ConfigDefault(
        "ROC_MIN",
        "10.0",
        ValueType.DECIMAL,
        "scanner",
        "§1 PILLAR_4",
        "Tier-B rate-of-change %% from prev close (>= inclusive).",
    ),
    # ---- C2: max daily loss / hard lockout (spec §5) ----
    ConfigDefault(
        "MAX_DAILY_LOSS_MODE",
        "min_pct_acct_or_avg_win",
        ValueType.STR,
        "risk",
        "C2/§5",
        "How MAX_DAILY_LOSS is computed.",
    ),
    ConfigDefault(
        "MAX_DAILY_LOSS_PCT",
        "0.10",
        ValueType.DECIMAL,
        "risk",
        "C2/§5",
        "Account fraction component of the daily-loss stop.",
    ),
    ConfigDefault(
        "BROKER_HARD_LOCKOUT",
        "5000.00",
        ValueType.DECIMAL,
        "risk",
        "C2/§5",
        "Physical broker cutoff (USD).",
    ),
    # ---- C3: give-back stop (spec §5) ----
    ConfigDefault(
        "GIVE_BACK_WARN",
        "0.25",
        ValueType.DECIMAL,
        "risk",
        "C3/§5",
        "Warn + reduce size at this give-back of peak day PnL.",
    ),
    ConfigDefault(
        "GIVE_BACK_HARD",
        "0.50",
        ValueType.DECIMAL,
        "risk",
        "C3/§5",
        "Shut down at this give-back of peak day PnL (U4).",
    ),
    # ---- U5 three strikes (spec §5) ----
    ConfigDefault(
        "THREE_STRIKES",
        "3",
        ValueType.INT,
        "risk",
        "U5/§5",
        "Consecutive losing trades that halt the day.",
    ),
    ConfigDefault(
        "RR_MIN",
        "2.0",
        ValueType.DECIMAL,
        "risk",
        "§5 RR_RATIO",
        "Minimum reward:risk before a trade qualifies.",
    ),
    ConfigDefault(
        "DOW_MONDAY_MULT",
        "0.50",
        ValueType.DECIMAL,
        "risk",
        "§5",
        "Monday size multiplier (worst day, most conservative).",
    ),
    # ---- C4: first scale fraction (spec §3) ----
    ConfigDefault(
        "FIRST_SCALE_FRACTION",
        "0.50",
        ValueType.DECIMAL,
        "execution",
        "C4/§3",
        "Fraction sold at first target (0.75 hot variant).",
    ),
    # ---- C5: stop basis (spec §3) ----
    ConfigDefault(
        "STOP_BASIS",
        StopBasis.PULLBACK_LOW.value,
        ValueType.STR,
        "execution",
        "C5/§3",
        "Mental-stop reference price basis.",
    ),
    # ---- C15: move-to-breakeven trigger (spec §3) ----
    ConfigDefault(
        "MOVE_BE_TRIGGER",
        "0.10",
        ValueType.DECIMAL,
        "execution",
        "C15/§3",
        "Unrealized gain ($/sh) that moves the stop to entry.",
    ),
    # ---- C6/C7: time-of-day (spec §7) ----
    ConfigDefault(
        "SCAN_START", "07:00", ValueType.TIME, "timing", "C6/§7", "Primary scan start (ET)."
    ),
    ConfigDefault(
        "HARD_STOP_TIME",
        "11:00",
        ValueType.TIME,
        "timing",
        "C7/§7",
        "No new entries after this (ET); tighten when COLD.",
    ),
    ConfigDefault(
        "STALE_NO_TRADE_MIN",
        "60",
        ValueType.INT,
        "timing",
        "§7",
        "Stop for the day if no trade within this many minutes.",
    ),
    # ---- C8: HTB-only filter (spec §2) ----
    ConfigDefault(
        "HTB_ONLY_FILTER",
        "false",
        ValueType.BOOL,
        "entry",
        "C8/§2",
        "Hard-to-borrow preference filter (optional, default OFF).",
    ),
    # ---- C9: pullback retrace depth (spec §2) ----
    ConfigDefault(
        "RETRACE_MAX",
        "0.50",
        ValueType.DECIMAL,
        "entry",
        "C9/§2",
        "Invalidate entry beyond this retrace of the surge.",
    ),
    ConfigDefault(
        "RETRACE_PREFERRED",
        "0.25",
        ValueType.DECIMAL,
        "entry",
        "C9/§2",
        "Full-conviction retrace ceiling.",
    ),
    # ---- E7 spread gate (spec §2) ----
    ConfigDefault(
        "SPREAD_MIN",
        "0.03",
        ValueType.DECIMAL,
        "entry",
        "§2 E7",
        "Lower edge of healthy spread band.",
    ),
    ConfigDefault(
        "SPREAD_MAX",
        "0.10",
        ValueType.DECIMAL,
        "entry",
        "§2 E7",
        "Upper edge of healthy spread band (size down / caution beyond).",
    ),
    # ---- C12: entry trigger timing (spec §2) ----
    ConfigDefault(
        "ENTRY_TRIGGER",
        EntryTrigger.CANDLE_CLOSE.value,
        ValueType.STR,
        "entry",
        "C12/§2",
        "Candle-close default; mid_candle only when HOT.",
    ),
    # ---- C13: catalyst verify mode (spec §1) ----
    ConfigDefault(
        "CATALYST_VERIFY_MODE",
        CatalystVerifyMode.BEFORE.value,
        ValueType.STR,
        "entry",
        "C13/§1",
        "Verify catalyst before buying; after only when HOT.",
    ),
    # ---- C10/C11: sizing (spec §6) ----
    ConfigDefault(
        "SIZING_MODE",
        SizingMode.RISK_FORMULA.value,
        ValueType.STR,
        "sizing",
        "C10/§6",
        "risk_formula default ($1k/stop) vs flat_block.",
    ),
    ConfigDefault(
        "PER_TRADE_RISK_DOLLARS",
        "1000.00",
        ValueType.DECIMAL,
        "sizing",
        "§6",
        "Risk budget per trade for risk_formula sizing.",
    ),
    ConfigDefault(
        "MAX_SIZE",
        "10000",
        ValueType.INT,
        "sizing",
        "C11/§6",
        "Absolute max shares; liquidity-capped, NEVER hardcode 100k.",
    ),
    ConfigDefault(
        "STARTER_CAP",
        "5000",
        ValueType.INT,
        "sizing",
        "§5/§6",
        "Share cap until cushion (>$1k realized) secured.",
    ),
    ConfigDefault(
        "ICEBREAKER_FRACTION",
        "0.25",
        ValueType.DECIMAL,
        "sizing",
        "§6",
        "Icebreaker size = this fraction of MAX_SIZE while day PnL <= 0.",
    ),
    ConfigDefault(
        "CUSHION_PNL_THRESHOLD",
        "1000.00",
        ValueType.DECIMAL,
        "sizing",
        "§5",
        "Realized day PnL above which size may scale past STARTER_CAP.",
    ),
    # ---- C14: halt entry mode (spec §12A) ----
    ConfigDefault(
        "HALT_MODE",
        HaltMode.POST_HALT.value,
        ValueType.STR,
        "halt",
        "C14/§12A",
        "post_halt default (resumption) vs pre_halt (gap-through risk).",
    ),
    # ---- Execution offsets (spec §10) ----
    ConfigDefault(
        "BUY_OFFSET",
        "0.05",
        ValueType.DECIMAL,
        "execution",
        "§10",
        "Buy limit = ask + offset ({0.05, 0.10}); cautious default 0.05.",
    ),
    # ---- Time stop / breakout-or-bailout (spec §3 P2, 13.5) ----
    ConfigDefault(
        "BAILOUT_SECONDS",
        "60",
        ValueType.INT,
        "execution",
        "§3 P2",
        "Bailout window: must advance within this many seconds.",
    ),
    ConfigDefault(
        "BAILOUT_MOVE",
        "0.10",
        ValueType.DECIMAL,
        "execution",
        "§3 P2",
        "Required favorable move ($/sh) within the bailout window.",
    ),
    # ---- U6 simulator gate (spec §11) ----
    ConfigDefault(
        "SIM_GATE_DAYS",
        "10",
        ValueType.INT,
        "sim",
        "U6/§11",
        "Consecutive sim days required before live.",
    ),
    ConfigDefault(
        "SIM_GATE_ACCURACY",
        "0.60",
        ValueType.DECIMAL,
        "sim",
        "U6/§11",
        "Minimum accuracy across the sim-gate window.",
    ),
    ConfigDefault(
        "LIVE_ENABLED",
        "false",
        ValueType.BOOL,
        "sim",
        "U6/§11",
        "Hard gate: live trading stays OFF until U6 satisfied + sign-off.",
    ),
    # ---- Account / regulatory (spec §13.11) — cautious until account confirmed ----
    ConfigDefault(
        "MAX_TRADES_PER_DAY",
        "1",
        ValueType.INT,
        "account",
        "§13.11",
        "Cautious cash/small-account default (one trade/day) until confirmed.",
    ),
    # ---- C16: platform (spec §9) ----
    ConfigDefault(
        "PLATFORM",
        "vendor_agnostic",
        ValueType.STR,
        "platform",
        "C16/§9",
        "Native reimplementation; no third-party scanner platform.",
    ),
    # ---- Fail-safe market-state default (spec §8 / 13.9) ----
    ConfigDefault(
        "MARKET_STATE_DEFAULT",
        "COLD",
        ValueType.STR,
        "risk",
        "§8/13.9",
        "Most conservative state; blocks EX1/EX2/mid-candle/oversize.",
    ),
    # ======================================================================
    # PHASE 1 — Data layer (scanner / RVOL / feeds). Hard-rule operational
    # numbers from spec §1 (two-tier model), §9 (scanner defs), §2A. Not
    # ⚠️CONFLICT keys; live here so PLR2004 keeps them out of code bodies.
    # ======================================================================
    # ---- Tier A wide net (spec §1 TIER_A_WIDE_NET / §9 GAP_SCAN) ----
    ConfigDefault(
        "TIER_A_GAP_MIN",
        "4.0",
        ValueType.DECIMAL,
        "scanner",
        "§1 TIER_A/§9",
        "Tier-A wide-net gap/change %% floor (>= inclusive).",
    ),
    ConfigDefault(
        "TIER_A_RVOL_MIN",
        "2.0",
        ValueType.DECIMAL,
        "scanner",
        "§1 TIER_A/§9",
        "Tier-A wide-net relative-volume floor (>= inclusive).",
    ),
    ConfigDefault(
        "TIER_A_FLOAT_CEILING",
        "50000000",
        ValueType.INT,
        "scanner",
        "§1 TIER_A/§9",
        "Tier-A surveillance float ceiling (shares); Tier-B stays <=20M.",
    ),
    ConfigDefault(
        "TIER_A_PRICE_MIN",
        "1.00",
        ValueType.DECIMAL,
        "scanner",
        "§1 TIER_A/§9",
        "Tier-A wide-net price floor (surveillance only).",
    ),
    ConfigDefault(
        "TIER_A_PRICE_MAX",
        "20.00",
        ValueType.DECIMAL,
        "scanner",
        "§1 TIER_A/§9",
        "Tier-A wide-net price ceiling (surveillance only).",
    ),
    # ---- Attention ranking (spec §1) ----
    ConfigDefault(
        "ATTENTION_PRIME_RANK",
        "3",
        ValueType.INT,
        "scanner",
        "§1",
        "Top-N by %%gain → PRIME attention.",
    ),
    ConfigDefault(
        "ATTENTION_WATCH_RANK",
        "10",
        ValueType.INT,
        "scanner",
        "§1",
        "Top-N by %%gain → WATCH attention (else IGNORE).",
    ),
    # ---- Volume sweet spot (ranking, not a gate) (spec §1 V2) ----
    ConfigDefault(
        "VOLUME_SWEET_LOW",
        "5000000",
        ValueType.INT,
        "scanner",
        "§1",
        "Preferred EOD volume floor (shares); below = illiquid.",
    ),
    ConfigDefault(
        "VOLUME_SWEET_HIGH",
        "25000000",
        ValueType.INT,
        "scanner",
        "§1",
        "Preferred EOD volume ceiling (shares); above = HFT-dominated.",
    ),
    # ---- Sub-scanner thresholds (spec §9) ----
    ConfigDefault(
        "RUNNING_UP_PCT",
        "5.0",
        ValueType.DECIMAL,
        "scanner",
        "§9 RUNNING_UP_SCAN",
        "Surge %% within RUNNING_UP_WINDOW_MIN, below HOD ('5%% in 5min').",
    ),
    ConfigDefault(
        "RUNNING_UP_WINDOW_MIN",
        "5",
        ValueType.INT,
        "scanner",
        "§9 RUNNING_UP_SCAN",
        "Lookback window (minutes) for the running-up surge.",
    ),
    ConfigDefault(
        "LOW_FLOAT_SUBSCAN_CEILING",
        "5000000",
        ValueType.INT,
        "scanner",
        "§9 LOW_FLOAT_TOP_GAINER",
        "Float ceiling (shares) for the low-float-top-gainer sub-scan.",
    ),
    # ---- RVOL engine (spec §1 PILLAR_3 / §13) ----
    ConfigDefault(
        "RVOL_BASELINE_DAYS",
        "50",
        ValueType.INT,
        "scanner",
        "§1/§9",
        "Rolling baseline window (trading days) for the RVOL average.",
    ),
    ConfigDefault(
        "RVOL_MIN_HISTORY_DAYS",
        "20",
        ValueType.INT,
        "scanner",
        "§1",
        "Below this many baseline days, RVOL is flagged low-confidence.",
    ),
    # ---- Float resolver (spec §13.1 Pillar-2 dependency) ----
    ConfigDefault(
        "FLOAT_DISAGREE_TOLERANCE",
        "0.05",
        ValueType.DECIMAL,
        "scanner",
        "§13.1",
        "Vendor-vs-EDGAR share-count mismatch beyond this fraction → low confidence.",
    ),
    # ---- Feed integrity (spec §10 fail-safe; CLAUDE.md §7.2) ----
    ConfigDefault(
        "REQUIRE_SIP",
        "true",
        ValueType.BOOL,
        "feed",
        "§9/CLAUDE§7.2",
        "Reject IEX-only / single-venue feeds for scanning (consolidated/SIP required).",
    ),
    ConfigDefault(
        "FEED_STALENESS_SECONDS",
        "5",
        ValueType.DECIMAL,
        "feed",
        "§10",
        "Default feed-gap threshold; exceeding it trips staleness → do not trade.",
    ),
]

# Conflict keys (C1–C16) for validation/audit — every one must be present in the table.
CONFLICT_KEYS: frozenset[str] = frozenset(d.key for d in DEFAULTS if d.spec_ref.startswith("C"))


def parse_value(raw: str, value_type: ValueType) -> Any:
    """Parse a stored text value into its typed Python form. Fail loud on bad data."""
    if value_type is ValueType.STR:
        return raw
    if value_type is ValueType.INT:
        return int(raw)
    if value_type is ValueType.DECIMAL:
        return Decimal(raw)
    if value_type is ValueType.BOOL:
        lowered = raw.strip().lower()
        if lowered in {"true", "1", "yes", "on"}:
            return True
        if lowered in {"false", "0", "no", "off"}:
            return False
        raise ValueError(f"invalid bool config value: {raw!r}")
    if value_type is ValueType.TIME:
        hh, mm = raw.split(":")
        return time(int(hh), int(mm))
    raise ValueError(f"unhandled value type: {value_type}")


class ConfigService:
    """Typed access over a {key: (raw_value, value_type)} map loaded from the DB.

    Strategy/risk code reads config ONLY through this, never via literals.
    """

    def __init__(self, rows: dict[str, tuple[str, ValueType]]) -> None:
        self._rows = dict(rows)

    @classmethod
    def from_defaults(cls) -> ConfigService:
        """Build a service straight from ``DEFAULTS`` (handy for tests / dry runs)."""
        return cls({d.key: (d.value, d.value_type) for d in DEFAULTS})

    def has(self, key: str) -> bool:
        return key in self._rows

    def get(self, key: str) -> Any:
        if key not in self._rows:
            raise KeyError(f"unknown config key: {key!r}")
        raw, vt = self._rows[key]
        return parse_value(raw, vt)

    def get_decimal(self, key: str) -> Decimal:
        value = self.get(key)
        if not isinstance(value, Decimal):
            raise TypeError(f"{key} is not a Decimal config value")
        return value

    def get_int(self, key: str) -> int:
        value = self.get(key)
        if not isinstance(value, int) or isinstance(value, bool):
            raise TypeError(f"{key} is not an int config value")
        return value

    def get_bool(self, key: str) -> bool:
        value = self.get(key)
        if not isinstance(value, bool):
            raise TypeError(f"{key} is not a bool config value")
        return value

    def get_str(self, key: str) -> str:
        value = self.get(key)
        if not isinstance(value, str):
            raise TypeError(f"{key} is not a str config value")
        return value

    def get_time(self, key: str) -> time:
        value = self.get(key)
        if not isinstance(value, time):
            raise TypeError(f"{key} is not a time config value")
        return value

    def validate_conflicts_present(self) -> None:
        """Fail-safe: ensure every C1–C16 conflict key is configured."""
        missing = CONFLICT_KEYS - self._rows.keys()
        if missing:
            raise ValueError(f"missing required conflict config keys: {sorted(missing)}")

    def keys(self) -> frozenset[str]:
        return frozenset(self._rows)
