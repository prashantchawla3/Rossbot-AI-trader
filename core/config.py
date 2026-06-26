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
    # ==========================================================================
    # PHASE 2 — Strategy Engine (entry gate, patterns, conviction, exit engine).
    # Non-conflict operational numbers from spec §2/§3/§4A.
    # ==========================================================================
    # ---- E2: pullback candle constraints (spec §2 E2 / §4A) ----
    ConfigDefault(
        "PULLBACK_MAX_CANDLES",
        "3",
        ValueType.INT,
        "entry",
        "§2 E2/§4A",
        "Maximum red-candle pullback count; 1–3 per spec (1–2 for micro-pullback).",
    ),
    ConfigDefault(
        "SURGE_MIN_CANDLES",
        "2",
        ValueType.INT,
        "entry",
        "§2 E2/§4A",
        "Minimum green surge bars required before a pullback is recognised.",
    ),
    # ---- P5: psyche-level step (spec §3 P5) ----
    ConfigDefault(
        "PSYCH_LEVEL_STEP",
        "0.50",
        ValueType.DECIMAL,
        "exit",
        "§3 P5",
        "Step size for $0.50/$1.00 psyche-level detection in scale-out trigger.",
    ),
    ConfigDefault(
        "PSYCH_LEVEL_TOLERANCE",
        "0.03",
        ValueType.DECIMAL,
        "exit",
        "§3 P5",
        "Price tolerance (±$) around a psyche level for P5 trigger.",
    ),
    # ---- §4A Bull Flag consolidation range (spec §4A) ----
    ConfigDefault(
        "FLAG_CONSOLIDATION_MAX",
        "0.25",
        ValueType.DECIMAL,
        "entry",
        "§4A bull_flag",
        "Max retrace for a tight bull-flag; should stay in top 15–25%% of pole.",
    ),
    # ---- §4A Light-volume breakout detector (spec §4A RKDA fixture) ----
    ConfigDefault(
        "LIGHT_VOLUME_RATIO",
        "0.30",
        ValueType.DECIMAL,
        "entry",
        "§4A RKDA",
        "Breakout bar volume < this ratio of prior spike → suspicious (RKDA).",
    ),
    ConfigDefault(
        "VOLUME_SPIKE_LOOKBACK",
        "10",
        ValueType.INT,
        "entry",
        "§4A RKDA",
        "Lookback bars to locate the prior high-volume spike for light-vol check.",
    ),
    # ==========================================================================
    # PHASE 3 — Risk Management Layer (pre-trade gate, sizing, live monitors).
    # Non-conflict operational numbers from spec §5/§6/§7/§8/§11/§13.11.
    # ==========================================================================
    # ── C2: average winning day PnL (used in MAX_DAILY_LOSS formula, spec §5) ─
    ConfigDefault(
        "AVG_WIN_DAY_PNL",
        "1000.00",
        ValueType.DECIMAL,
        "risk",
        "C2/§5",
        "Fallback avg winning-day PnL; MAX_DAILY_LOSS = min(equity×pct, this, lockout).",
    ),
    # ── U9/§13.6: liquidity cap — never be the whole book ──────────────────────
    ConfigDefault(
        "LIQUIDITY_CAP_FRACTION",
        "0.10",
        ValueType.DECIMAL,
        "sizing",
        "U9/§13.6",
        "Max fraction of displayed book volume any single order may represent.",
    ),
    # ── §8: market-state size multipliers ──────────────────────────────────────
    ConfigDefault(
        "MARKET_STATE_COLD_MULT",
        "0.50",
        ValueType.DECIMAL,
        "sizing",
        "§8",
        "COLD market size multiplier (cap ~50% of normal; spec §8 COLD caps).",
    ),
    ConfigDefault(
        "MARKET_STATE_REHAB_CAP",
        "1000",
        ValueType.INT,
        "sizing",
        "§8",
        "Absolute share cap in REHAB mode (micro size; spec §8 'as low as 100 sh').",
    ),
    # ── U3: EOD flatten time (spec §11 U3) ─────────────────────────────────────
    ConfigDefault(
        "EOD_FLATTEN_TIME",
        "15:55",
        ValueType.TIME,
        "timing",
        "U3/§11",
        "Flatten all positions at or after this ET time (5 min before close).",
    ),
    # ── §5: day-of-week weighting (Friday multiplier) ──────────────────────────
    ConfigDefault(
        "DOW_FRIDAY_MULT",
        "0.75",
        ValueType.DECIMAL,
        "sizing",
        "§5",
        "Friday size multiplier (slow/holiday days; tighten quality bar per spec §5).",
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
    # ==========================================================================
    # PHASE 6 — Live Trading (hardened execution path, capital ramp, readiness).
    # spec §5/§6/§13.4/ROSSBOT_PROJECT_PLAN.md Phase 6.
    # ==========================================================================
    # ---- Mental-stop monitor poll interval in live mode (§13.4) ----
    ConfigDefault(
        "LIVE_POLL_MS",
        "100",
        ValueType.INT,
        "execution",
        "§13.4/Phase6",
        "Mental-stop monitor poll interval (ms) in live mode; tighter than 500ms paper.",
    ),
    # ---- Broker position reconciliation (Phase 6) ----
    ConfigDefault(
        "RECONCILE_INTERVAL_S",
        "30",
        ValueType.INT,
        "execution",
        "Phase6",
        "Interval (seconds) between broker position reconciliation checks.",
    ),
    # ---- Disconnect / recovery (Phase 6) ----
    ConfigDefault(
        "RECONNECT_MAX_ATTEMPTS",
        "3",
        ValueType.INT,
        "execution",
        "Phase6",
        "Max reconnect attempts on broker/data-feed disconnect before flatten+halt.",
    ),
    ConfigDefault(
        "RECONNECT_DELAY_S",
        "5",
        ValueType.INT,
        "execution",
        "Phase6",
        "Delay (seconds) between reconnection attempts after disconnect.",
    ),
    # ---- Staged capital ramp (spec §5/§6) ----
    ConfigDefault(
        "CAPITAL_RAMP_TIER",
        "MICRO",
        ValueType.STR,
        "sizing",
        "§5/§6/Phase6",
        "Staged ramp tier: MICRO (first live days) | STARTER | FULL. Promoted manually.",
    ),
    ConfigDefault(
        "CAPITAL_RAMP_MICRO_SHARES",
        "100",
        ValueType.INT,
        "sizing",
        "§5/§6/Phase6",
        "Absolute max shares per trade in MICRO tier (first live days, tiny size).",
    ),
    ConfigDefault(
        "CAPITAL_RAMP_STARTER_SHARES",
        "2000",
        ValueType.INT,
        "sizing",
        "§5/§6/Phase6",
        "Absolute max shares per trade in STARTER tier (before full risk_formula).",
    ),
    # ---- Pre-market readiness gates (Phase 6) ----
    ConfigDefault(
        "READINESS_MIN_BUYING_POWER",
        "5000.00",
        ValueType.DECIMAL,
        "account",
        "Phase6",
        "Minimum buying power (USD) required at session start (readiness gate).",
    ),
    ConfigDefault(
        "READINESS_MIN_EQUITY",
        "25000.00",
        ValueType.DECIMAL,
        "account",
        "§13.11/Phase6",
        "Minimum equity for non-PDT margin trading ($25k Pattern Day Trader threshold).",
    ),
    ConfigDefault(
        "CLOCK_DRIFT_MAX_MS",
        "500",
        ValueType.INT,
        "timing",
        "Phase6",
        "Maximum acceptable NTP clock drift (ms) before readiness check fails.",
    ),
    # ==========================================================================
    # PHASE 7 — Catalyst Detection (spec §1/§13.1).
    # NLP news classifier + reaction-proof gate + SEC dilution check.
    # Env vars for secrets: BENZINGA_API_KEY, ANTHROPIC_API_KEY (never in DB).
    # ==========================================================================
    ConfigDefault(
        "CATALYST_LLM_ENABLED",
        "true",
        ValueType.BOOL,
        "catalyst",
        "§1/§13.1/Phase7",
        "Enable Claude LLM for catalyst tag classification; false = keyword+filing only.",
    ),
    ConfigDefault(
        "CATALYST_LLM_MODEL",
        "claude-haiku-4-5-20251001",
        ValueType.STR,
        "catalyst",
        "§1/§13.1/Phase7",
        "Claude model ID for catalyst classification (Haiku 4.5: $1/$5 per MTok I/O).",
    ),
    ConfigDefault(
        "CATALYST_CONFIDENCE_THRESHOLD",
        "0.70",
        ValueType.DECIMAL,
        "catalyst",
        "§1/§13.1/Phase7",
        "Minimum LLM confidence to return VERIFIED; below threshold → UNVERIFIED.",
    ),
    ConfigDefault(
        "CATALYST_FILING_LOOKBACK_DAYS",
        "30",
        ValueType.INT,
        "catalyst",
        "§1/§13.1/Phase7",
        "Days back to check EDGAR submissions for dilution filings (S-1/S-3/424B).",
    ),
    ConfigDefault(
        "CATALYST_MAX_HEADLINES",
        "5",
        ValueType.INT,
        "catalyst",
        "§1/§13.1/Phase7",
        "Max headlines to fetch and pass to the LLM classifier (cost control).",
    ),
    # ==========================================================================
    # PHASE 8 — L2 / Tape Microstructure Engine (spec §2A / §13.2).
    # Real floor-vs-spoof, iceberg, green-tape, absorption/break detectors.
    # Replaces StubL2SignalProvider. Requires Databento XNAS.ITCH subscription.
    # ==========================================================================
    # ---- Rolling windows ----
    ConfigDefault(
        "L2_WINDOW_SECS",
        "30",
        ValueType.INT,
        "l2",
        "§2A/§13.2/Phase8",
        "Rolling tape window (seconds) used by all L2 detectors.",
    ),
    ConfigDefault(
        "L2_DEPTH_SNAPSHOTS",
        "20",
        ValueType.INT,
        "l2",
        "§2A/§13.2/Phase8",
        "Max depth-of-book snapshots retained per symbol (ring buffer).",
    ),
    # ---- Spoof detection (EX4/EX6 CADL bid-pull, spec §2A) ----
    ConfigDefault(
        "SPOOF_BID_MIN_SHARES",
        "20000",
        ValueType.INT,
        "l2",
        "§2A EX4/EX6/Phase8",
        "Min bid size (shares) at a level to flag as a potential spoof bid.",
    ),
    ConfigDefault(
        "SPOOF_DECAY_SECS",
        "5",
        ValueType.INT,
        "l2",
        "§2A EX4/EX6/Phase8",
        "If a flagged bid vanishes within this many seconds without prints → SPOOF.",
    ),
    ConfigDefault(
        "SPOOF_MIN_PRINTS",
        "100",
        ValueType.INT,
        "l2",
        "§2A EX4/EX6/Phase8",
        "Min tape shares at the flagged level to prove the bid is real (not spoof).",
    ),
    # ---- Iceberg detection (GMBL/NIXX, spec §2A, U14) ----
    ConfigDefault(
        "ICEBERG_ABSORBED_MIN",
        "5000",
        ValueType.INT,
        "l2",
        "§2A GMBL/NIXX/U14/Phase8",
        "Min shares executed in window to suspect a hidden iceberg seller.",
    ),
    ConfigDefault(
        "ICEBERG_ADVANCE_MAX_CENTS",
        "2",
        ValueType.INT,
        "l2",
        "§2A GMBL/NIXX/U14/Phase8",
        "Max price advance (cents) while heavy buying occurs → iceberg (price not moving).",
    ),
    ConfigDefault(
        "ICEBERG_DISPLAY_MAX",
        "600",
        ValueType.INT,
        "l2",
        "§2A GMBL/NIXX/U14/Phase8",
        "Max displayed ask size (shares) to suspect iceberg (small display, hidden seller).",
    ),
    # ---- Real floor / Support (spec §2A, E6 prints-confirmation) ----
    ConfigDefault(
        "FLOOR_BID_MIN_SHARES",
        "10000",
        ValueType.INT,
        "l2",
        "§2A E6/Phase8",
        "Min bid size at best bid to qualify as a real resting floor.",
    ),
    ConfigDefault(
        "FLOOR_MIN_PRINTS",
        "200",
        ValueType.INT,
        "l2",
        "§2A E6/Phase8",
        "Min tape shares executed in window confirming the floor before SUPPORT fires.",
    ),
    ConfigDefault(
        "FLOOR_MIN_STABLE_SNAPS",
        "2",
        ValueType.INT,
        "l2",
        "§2A E6/Phase8",
        "Min consecutive depth snapshots where bid >= FLOOR_BID_MIN_SHARES (bid stability).",
    ),
    # ---- Absorption → Break (spec §2A absorbed-then-break trigger, E6) ----
    ConfigDefault(
        "ABSORB_ASK_MIN_SHARES",
        "5000",
        ValueType.INT,
        "l2",
        "§2A E6/Phase8",
        "Min peak displayed ask (shares) to identify a visible large seller for absorb-break.",
    ),
    ConfigDefault(
        "ABSORB_TAPE_MIN_SHARES",
        "3000",
        ValueType.INT,
        "l2",
        "§2A E6/Phase8",
        "Min tape shares executed against the visible ask before break qualifies.",
    ),
    ConfigDefault(
        "ABSORB_BREAK_MIN_CENTS",
        "5",
        ValueType.INT,
        "l2",
        "§2A E6/Phase8",
        "Min price advance (cents) through the ask level to confirm the break.",
    ),
    # ==========================================================================
    # PHASE 9 — Market-State Classifier + Attention (spec §8 / §13.3 / §13.9).
    # Rolling-feature heuristic → HOT/COLD/REHAB.  Bias COLD on uncertainty.
    # Gates EX1/EX2/mid-candle/oversize.
    # ==========================================================================
    # ── Rolling window (how many days of data to use) ─────────────────────────
    ConfigDefault(
        "MS_HOT_WINDOW_DAYS",
        "5",
        ValueType.INT,
        "market_state",
        "§8/§13.9/Phase9",
        "Rolling window (trading days) for market-state feature computation.",
    ),
    ConfigDefault(
        "MS_MIN_WINDOW_DAYS",
        "3",
        ValueType.INT,
        "market_state",
        "§8/§13.9/Phase9",
        "Min days of data required; below this → COLD (insufficient signal).",
    ),
    # ── HOT thresholds (ALL must fire for HOT; bias COLD per spec §13.9) ──────
    ConfigDefault(
        "MS_HOT_BIG_MOVERS_MIN",
        "2",
        ValueType.INT,
        "market_state",
        "§8/§13.9/Phase9",
        "Min count of >100%% moves required for the 'big_movers' HOT signal.",
    ),
    ConfigDefault(
        "MS_HOT_FOLLOW_THROUGH_MIN",
        "0.60",
        ValueType.DECIMAL,
        "market_state",
        "§8/§13.9/Phase9",
        "Min gapper follow-through rate (0–1) for the HOT signal.",
    ),
    ConfigDefault(
        "MS_HOT_AVG_GREEN_MIN",
        "0.25",
        ValueType.DECIMAL,
        "market_state",
        "§8/§13.9/Phase9",
        "Min avg winner %%gain (0–1 fraction) for the HOT signal.",
    ),
    # ── COLD thresholds ───────────────────────────────────────────────────────
    ConfigDefault(
        "MS_COLD_FOLLOW_THROUGH_MAX",
        "0.35",
        ValueType.DECIMAL,
        "market_state",
        "§8/§13.9/Phase9",
        "Max gapper follow-through rate (0–1) that triggers a COLD signal.",
    ),
    ConfigDefault(
        "MS_COLD_AVG_GREEN_MAX",
        "0.10",
        ValueType.DECIMAL,
        "market_state",
        "§8/§13.9/Phase9",
        "Max avg winner %%gain (0–1 fraction) that triggers a COLD signal.",
    ),
    # ── Attention scorer (§1/§13.3) ───────────────────────────────────────────
    ConfigDefault(
        "ATTENTION_RVOL_SCALE",
        "100.0",
        ValueType.DECIMAL,
        "market_state",
        "§1/§13.3/Phase9",
        "RVOL value that maps to a full rvol_score=1.0 in the attention scorer.",
    ),
    # ==========================================================================
    # PHASE 10 — Execution Safety: Mental Stops & Time Stop (spec §13.4/§13.5).
    # Hardened no-native-stop path; quantified breakout-or-bailout;
    # optional hidden catastrophic backstop; loop latency measurement.
    # ==========================================================================
    # ── Optional catastrophic backstop (§13.4) ────────────────────────────────
    ConfigDefault(
        "BACKSTOP_ENABLED",
        "false",
        ValueType.BOOL,
        "execution",
        "§13.4/Phase10",
        "Enable optional hidden catastrophic backstop far below mental stop (U13-compliant).",
    ),
    ConfigDefault(
        "BACKSTOP_OFFSET",
        "0.50",
        ValueType.DECIMAL,
        "execution",
        "§13.4/Phase10",
        "$/sh below entry price for catastrophic backstop level (never a native STOP).",
    ),
    # ── Loop latency monitoring (§13.4) ───────────────────────────────────────
    ConfigDefault(
        "LATENCY_WARN_MS",
        "200",
        ValueType.INT,
        "execution",
        "§13.4/Phase10",
        "Log WARN when mental-stop loop iteration exceeds this latency (ms).",
    ),
    # ==========================================================================
    # PHASE 11 — Halt Resumption & Multi-Day Continuation (spec §12A/§13.7/§12B/§13.10).
    # Halt engine: post_halt default (C14), LULD + reopen auction, EX5 hard-block.
    # Continuation engine: Day-1 ≥100% eligibility, numeric done-conditions, 5-min shift.
    # ==========================================================================
    # ── Halt engine (§12A / §13.7) ────────────────────────────────────────────
    ConfigDefault(
        "PRE_HALT_BAND_ENTRY_PCT",
        "1.0",
        ValueType.DECIMAL,
        "halt",
        "§12A/§13.7/Phase11",
        "Pre-halt mode: enter when price within this %% of LULD Limit-Up band (HOT only).",
    ),
    # ── Continuation engine (§12B / §13.10) ──────────────────────────────────
    ConfigDefault(
        "CONTINUATION_MIN_DAY1_PCT",
        "100.0",
        ValueType.DECIMAL,
        "continuation",
        "§12B/§13.10/Phase11",
        "Minimum Day-1 % move (open→high) for Day-2 continuation eligibility.",
    ),
    ConfigDefault(
        "CONTINUATION_HOLD_PCT",
        "0.70",
        ValueType.DECIMAL,
        "continuation",
        "§12B/§13.10/Phase11",
        "Day-1 close must be ≥ this fraction of Day-1 high for continuation to be eligible.",
    ),
    ConfigDefault(
        "CONTINUATION_RVOL_DONE_PCT",
        "0.25",
        ValueType.DECIMAL,
        "continuation",
        "§12B/§13.10/Phase11",
        "Done if Day-2 RVOL fraction of Day-1 volume falls below this (spec §12B DONE_IF).",
    ),
    ConfigDefault(
        "CONTINUATION_RETRACE_DONE_PCT",
        "0.50",
        ValueType.DECIMAL,
        "continuation",
        "§12B/§13.10/Phase11",
        "Done if Day-2 retrace exceeds this fraction of the Day-1 move (spec §12B DONE_IF).",
    ),
    ConfigDefault(
        "CONTINUATION_SIZE_FRACTION",
        "0.50",
        ValueType.DECIMAL,
        "continuation",
        "§12B/§13.10/Phase11",
        "Day-2 size as fraction of normal max size (auto-reduced per spec §12B ADJUSTMENTS).",
    ),
    # ==========================================================================
    # PHASE 12 — Sizing/Liquidity & Pattern Hardening (spec §13.6 / §13.8).
    # ADV-based cap + depth-level cap; mid-candle already gated to HOT (entry_gate.py).
    # ==========================================================================
    # ── ADV-based order cap (§13.6) ───────────────────────────────────────────
    ConfigDefault(
        "ADV_CAP_FRACTION",
        "0.01",
        ValueType.DECIMAL,
        "sizing",
        "§13.6/Phase12",
        "Max order size as fraction of Average Daily Volume (ADV). Default 1%% of ADV.",
    ),
    # ── Depth-level aggregation for book cap (§13.6 / U9) ────────────────────
    ConfigDefault(
        "DEPTH_CAP_LEVELS",
        "3",
        ValueType.INT,
        "sizing",
        "§13.6/U9/Phase12",
        "Number of top ask-side depth levels to aggregate for the displayed-book cap.",
    ),
    # ==========================================================================
    # PHASE 13 — Regulatory / Account Compliance (spec §13.11).
    # Startup hard-gate, PDT guard (rule eliminated 2026-06-04), T+1 cash, wash-sale, SSR.
    # ==========================================================================
    # ── SSR awareness (§13.11 / Rule 201) ─────────────────────────────────────
    ConfigDefault(
        "SSR_LOG_ONLY",
        "true",
        ValueType.BOOL,
        "compliance",
        "§13.11/Phase13",
        "SSR only restricts short sales (RossBot is long-only); log but never block longs.",
    ),
    # ── Wash-sale tracking (§13.11 / IRC §1091) ───────────────────────────────
    ConfigDefault(
        "WASH_SALE_WARN_ENABLED",
        "true",
        ValueType.BOOL,
        "compliance",
        "§13.11/Phase13",
        "Enable wash-sale risk warnings in audit log (advisory; not a hard trade veto).",
    ),
    # ── Startup compliance (§13.11) ───────────────────────────────────────────
    ConfigDefault(
        "COMPLIANCE_SHORTING_ENABLED",
        "false",
        ValueType.BOOL,
        "compliance",
        "§13.11/Phase13",
        "Short-selling must remain false (locate/HTB out of scope; assert at startup).",
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
