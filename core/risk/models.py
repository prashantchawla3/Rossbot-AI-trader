"""Risk Manager domain models — vetoes, approvals, daily state.

All money fields use Decimal. No float anywhere in this module (CLAUDE.md §10).
spec §5 (risk rules), §6 (sizing), §11 (U1–U15).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, ConfigDict


class VetoReason(StrEnum):
    """Why a trade was blocked by the Risk Manager. spec §5/§11."""

    NO_FIVE_PILLAR = "no_five_pillar"      # U1: Tier-B / E1 not satisfied
    RR_BELOW_MIN = "rr_below_min"          # §5: reward:risk < RR_MIN (2:1)
    DAILY_LOSS_LIMIT = "daily_loss_limit"  # U4: day PnL hit MAX_DAILY_LOSS
    GIVE_BACK_HARD = "give_back_hard"      # U4: 50% peak give-back
    THREE_STRIKES = "three_strikes"         # U5: 3 consecutive losses → halt
    AVERAGE_DOWN = "average_down"          # U2: adding to a red position
    PDT_LIMIT = "pdt_limit"               # §13.11: max trades-per-day reached
    SKIP_CATALYST = "skip_catalyst"        # U15: buyout/secondary/recycled-PR/pump
    HARD_STOP_TIME = "hard_stop_time"      # §7: past HARD_STOP_TIME
    HALTED = "halted"                      # session halted (U4/U5 already fired)
    SIZING_ZERO = "sizing_zero"            # stop too wide → 0 shares from formula


class GiveBackLevel(StrEnum):
    """Give-back severity.  spec §5 C3."""

    NONE = "none"
    WARN = "warn"   # > GIVE_BACK_WARN of peak → log + reduce size
    HALT = "halt"   # > GIVE_BACK_HARD of peak → shutdown (U4)


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True)


class TradeApproval(_Frozen):
    """Result of the Risk Manager pre-trade gate.

    ``approved=True`` → ``shares`` is the approved lot (≥ 1).
    ``approved=False`` → ``vetoes`` documents every triggered rule.
    spec §5/§6/§11.
    """

    approved: bool
    shares: int = 0
    vetoes: tuple[VetoReason, ...] = ()
    spec_ref: str = "§5/§6/§11"


@dataclass
class RiskState:
    """Mutable daily state.  Reset once per trading day via RiskManager.reset_session().

    Money fields are Decimal — float is forbidden (CLAUDE.md §10).
    """

    realized_pnl: Decimal = field(default_factory=lambda: Decimal("0"))
    peak_pnl: Decimal = field(default_factory=lambda: Decimal("0"))

    consecutive_losses: int = 0
    trades_today: int = 0  # incremented on open (PDT guard)

    halted: bool = False
    halt_reason: str | None = None

    # symbol → fill_price for open positions (U2 average-down check).
    open_positions: dict[str, Decimal] = field(default_factory=dict)


__all__ = [
    "GiveBackLevel",
    "RiskState",
    "TradeApproval",
    "VetoReason",
]
