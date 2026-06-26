"""Strategy-engine domain models — signals, gate results, position snapshots.

All price/money fields use ``core.money.Money`` (Annotated Decimal) so a
float can never enter the strategy path (CLAUDE.md §10).  Every model is
frozen (immutable) to keep pure-function guarantees.

spec §2 (entry gate), §3 (exit rules), §4/§4A (patterns), §6 (conviction).
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import IntEnum, StrEnum

from pydantic import BaseModel, ConfigDict

from adapters.providers import L2Signal, MarketState
from core.config import EntryTrigger
from core.indicators import MacdPoint
from core.money import Money


# ──────────────────────────────────────────────────────────────────────────────
# Pattern taxonomy (spec §4)
# ──────────────────────────────────────────────────────────────────────────────

class PatternType(StrEnum):
    MICRO_PULLBACK = "micro_pullback"          # R1 — bread & butter
    ABCD = "abcd"                              # R2 — geometric W
    BULL_FLAG = "bull_flag"                    # R3
    FLAT_TOP = "flat_top"                      # R3 variant
    GAP_AND_GO = "gap_and_go"                 # R5
    VWAP_BREAK = "vwap_break"                 # R6
    HALT_RESUMPTION = "halt_resumption"        # R7 — dip & rip
    RED_TO_GREEN = "red_to_green"              # R10
    REVERSE_SPLIT_SQUEEZE = "reverse_split_squeeze"  # R11
    NONE = "none"                              # no recognised pattern


# Lower number = higher conviction (spec §4 ranking).
PATTERN_RANK: dict[PatternType, int] = {
    PatternType.MICRO_PULLBACK: 1,
    PatternType.ABCD: 2,
    PatternType.BULL_FLAG: 3,
    PatternType.FLAT_TOP: 3,
    PatternType.GAP_AND_GO: 5,
    PatternType.VWAP_BREAK: 6,
    PatternType.HALT_RESUMPTION: 7,
    PatternType.RED_TO_GREEN: 10,
    PatternType.REVERSE_SPLIT_SQUEEZE: 11,
    PatternType.NONE: 99,
}


# ──────────────────────────────────────────────────────────────────────────────
# Exit taxonomy (spec §3 P1–P8)
# ──────────────────────────────────────────────────────────────────────────────

class ExitReason(StrEnum):
    HARD_STOP = "hard_stop"              # P1 — mental stop breached
    TIME_STOP = "time_stop"              # P2 — breakout-or-bailout (+10¢/60s)
    L2_REVERSAL = "l2_reversal"          # P3 — spoof/iceberg/red-tape
    TOPPING_TAIL = "topping_tail"        # P4 — confirmed doji/gravestone
    SCALE_STRENGTH = "scale_strength"    # P5 — HOD break / psych level
    FIRST_RED_CLOSE = "first_red_close"  # P6 — first red 1-min close
    VWAP_GUARD = "vwap_guard"            # P7 — trailing to VWAP
    LOST_POPULARITY = "lost_popularity"  # P8 — attention rotated away


class ScaleAction(StrEnum):
    FULL_EXIT = "full_exit"
    PARTIAL_SCALE = "partial_scale"  # sell a fraction, optionally move stop


# ──────────────────────────────────────────────────────────────────────────────
# Shared base
# ──────────────────────────────────────────────────────────────────────────────

class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True)


# ──────────────────────────────────────────────────────────────────────────────
# Pullback geometry (extracted from bar history for E2/E5/patterns)
# ──────────────────────────────────────────────────────────────────────────────

class PullbackContext(_Frozen):
    """Surge → pullback geometry used by E2, E5, and pattern recognisers."""

    pullback_count: int       # 1–3 red bars
    pullback_low: Money       # min low across pullback bars
    surge_high: Money         # max high across surge bars
    surge_start: Money        # low of the oldest surge bar (before the move)
    retrace_ratio: Decimal    # (surge_high − pullback_low) / (surge_high − surge_start)


# ──────────────────────────────────────────────────────────────────────────────
# Entry gate result (E1–E7)
# ──────────────────────────────────────────────────────────────────────────────

class EntryGateResult(_Frozen):
    """Full per-gate verdicts for the E1–E7 AND-gate (spec §2)."""

    passes: bool
    e1_universe: bool
    e2_pullback: bool
    e3_crossing: bool
    e4_macd: bool
    e5_retrace: bool
    e6_l2: bool
    e7_spread: bool

    pullback_ctx: PullbackContext | None = None
    entry_trigger: EntryTrigger = EntryTrigger.CANDLE_CLOSE
    spread: Money = Decimal("0")
    reasons: tuple[str, ...] = ()


# ──────────────────────────────────────────────────────────────────────────────
# Pattern match
# ──────────────────────────────────────────────────────────────────────────────

class PatternMatch(_Frozen):
    """Result from the pattern recogniser (spec §4/§4A)."""

    pattern: PatternType
    confidence: Decimal  # 0.0–1.0 internal pattern-level score


# ──────────────────────────────────────────────────────────────────────────────
# Entry signal (output of the strategy engine — NO execution)
# ──────────────────────────────────────────────────────────────────────────────

class EntrySignal(_Frozen):
    """A fully-formed entry signal. Passes to the Risk Manager; never to a broker directly.

    spec §2 (entry gate) / §6 (conviction feeds sizing).
    """

    symbol: str
    ts: datetime
    pattern: PatternType
    conviction_score: Money      # 0.0–1.0 composite; Money to avoid float
    entry_price: Money           # close of signal bar (ask+offset applied by execution)
    stop_price: Money            # mental stop basis (C5: pullback_low default)
    target_price: Money          # min 2:1 RR target (spec §5 RR_RATIO)

    gate: EntryGateResult
    market_state: MarketState
    vwap: Money | None = None
    ema9: Money | None = None

    spec_ref: str = "§2"

    @property
    def risk_per_share(self) -> Decimal:
        return self.entry_price - self.stop_price

    @property
    def rr_ratio(self) -> Decimal:
        risk = self.risk_per_share
        if risk <= Decimal("0"):
            return Decimal("0")
        return (self.target_price - self.entry_price) / risk


# ──────────────────────────────────────────────────────────────────────────────
# Position snapshot (fed into the exit engine)
# ──────────────────────────────────────────────────────────────────────────────

class PositionSnapshot(_Frozen):
    """Current open position state.  Updated after each scale-out or stop move."""

    symbol: str
    entry_price: Money
    current_stop: Money          # may have moved to BE after MOVE_BE_TRIGGER
    target_price: Money
    shares: int
    entry_ts: datetime
    high_watermark: Money        # highest price seen since entry (for P5/P7)


# ──────────────────────────────────────────────────────────────────────────────
# Exit signal
# ──────────────────────────────────────────────────────────────────────────────

class ExitSignal(_Frozen):
    """Exit / scale-out signal from the exit engine (spec §3).

    ``action=FULL_EXIT`` → sell all remaining shares.
    ``action=PARTIAL_SCALE`` → sell ``scale_fraction`` and optionally move stop.
    """

    symbol: str
    ts: datetime
    reason: ExitReason
    action: ScaleAction
    scale_fraction: Decimal = Decimal("1.0")
    new_stop: Money | None = None   # set on PARTIAL_SCALE to signal move-to-BE
    spec_ref: str = "§3"


# ──────────────────────────────────────────────────────────────────────────────
# Failed-pattern / reversal invalidation signal
# ──────────────────────────────────────────────────────────────────────────────

class FailedPatternSignal(_Frozen):
    """Universal failed-pattern / invalidation signal (spec §4A)."""

    symbol: str
    ts: datetime
    reason: str
    spec_ref: str = "§4A"


__all__ = [
    "EntryGateResult",
    "EntrySignal",
    "ExitReason",
    "ExitSignal",
    "FailedPatternSignal",
    "PATTERN_RANK",
    "PatternMatch",
    "PatternType",
    "PositionSnapshot",
    "PullbackContext",
    "ScaleAction",
]
