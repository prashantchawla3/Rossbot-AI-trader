"""Pre-trade veto gate — pure function (no side effects).

Evaluates every rule that can block a trade BEFORE position sizing:
  U1  (Tier-B / E1)
  §5  (2:1 RR minimum)
  U4  (daily-loss limit and give-back hard stop)
  U5  (three-strikes / session halt)
  U2  (never average down)
  §13.11 (PDT / trade-count guard)
  U15 (SKIP-list catalyst)
  §7  (past HARD_STOP_TIME)

Returns a list of VetoReason; empty list → gate passes.
spec §5, §11 (U1–U15).
"""

from __future__ import annotations

from datetime import time as Time
from decimal import Decimal

from core.config import ConfigService
from core.risk.models import RiskState, VetoReason
from core.strategy.models import EntrySignal


def evaluate_pre_trade(
    signal: EntrySignal,
    state: RiskState,
    cfg: ConfigService,
    now_et_time: Time,
    account_equity: Decimal,
    catalyst_skip: bool = False,
) -> list[VetoReason]:
    """Check all pre-trade veto rules.

    Returns a (possibly empty) list of triggered VetoReasons.
    Empty → gate passes; caller proceeds to sizing.
    Multiple vetoes may be present when the session is in a degraded state.
    """
    vetoes: list[VetoReason] = []

    # ── Fast-path: session already halted (U4/U5 fired earlier today) ────────
    if state.halted:
        vetoes.append(VetoReason.HALTED)
        return vetoes  # further checks are moot

    # ── U1: Tier-B / Five-Pillar confirm (spec §11 U1) ───────────────────────
    # E1 already gated this in the strategy layer; Risk Manager is the second wall.
    if not signal.gate.e1_universe:
        vetoes.append(VetoReason.NO_FIVE_PILLAR)

    # ── 2:1 minimum reward:risk (spec §5 RR_RATIO) ───────────────────────────
    rr_min = cfg.get_decimal("RR_MIN")
    if signal.rr_ratio < rr_min:
        vetoes.append(VetoReason.RR_BELOW_MIN)

    # ── U4: max daily loss (spec §5 C2) ──────────────────────────────────────
    # Effective limit = min(equity × pct, avg_win_day_pnl, broker_hard_lockout).
    max_loss_pct = account_equity * cfg.get_decimal("MAX_DAILY_LOSS_PCT")
    avg_win_day = cfg.get_decimal("AVG_WIN_DAY_PNL")
    broker_lockout = cfg.get_decimal("BROKER_HARD_LOCKOUT")
    effective_limit = min(max_loss_pct, avg_win_day, broker_lockout)
    if state.realized_pnl <= -effective_limit:
        vetoes.append(VetoReason.DAILY_LOSS_LIMIT)

    # ── U4: give-back hard stop (spec §5 C3) ─────────────────────────────────
    # Only applies when peak_pnl is positive (can't give back what was never made).
    if state.peak_pnl > Decimal("0"):
        give_back_hard = cfg.get_decimal("GIVE_BACK_HARD")
        give_back_threshold = state.peak_pnl * (Decimal("1") - give_back_hard)
        if state.realized_pnl <= give_back_threshold:
            vetoes.append(VetoReason.GIVE_BACK_HARD)

    # ── U5: three-strikes consecutive-loss halt (spec §11 U5) ────────────────
    three_strikes = cfg.get_int("THREE_STRIKES")
    if state.consecutive_losses >= three_strikes:
        vetoes.append(VetoReason.THREE_STRIKES)

    # ── U2: never average down (adding to a red position) (spec §11 U2) ──────
    # Block any new buy on a symbol whose current position is already in loss.
    if signal.symbol in state.open_positions:
        open_entry = state.open_positions[signal.symbol]
        if signal.entry_price < open_entry:
            vetoes.append(VetoReason.AVERAGE_DOWN)

    # ── §13.11: PDT / cash-settlement max trades per day ─────────────────────
    max_trades = cfg.get_int("MAX_TRADES_PER_DAY")
    if state.trades_today >= max_trades:
        vetoes.append(VetoReason.PDT_LIMIT)

    # ── U15: SKIP-list catalyst (spec §11 U15 / §1 SKIP_1–SKIP_7) ───────────
    if catalyst_skip:
        vetoes.append(VetoReason.SKIP_CATALYST)

    # ── §7: no new entries past HARD_STOP_TIME ────────────────────────────────
    hard_stop = cfg.get_time("HARD_STOP_TIME")
    if now_et_time > hard_stop:
        vetoes.append(VetoReason.HARD_STOP_TIME)

    return vetoes


__all__ = ["evaluate_pre_trade"]
