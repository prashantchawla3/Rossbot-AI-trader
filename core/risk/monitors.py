"""Live risk monitors — pure functions (no state mutations).

These fire during a live session to detect risk events requiring action
while a position is open or the session is running.  Callers must act on
True returns; the monitor functions themselves have no side effects.

Functions:
  is_mental_stop_breached  — U13: mental stop emulation (no native STOP ever)
  evaluate_give_back       — C3: give-back severity level
  is_daily_loss_limit      — U4: max daily loss hit
  should_flatten_eod       — U3: time to flatten before close
  is_past_hard_stop_time   — §7: past HARD_STOP_TIME

spec §3 P1 (mental stop), §5 (give-back / daily loss), §7 (time), U3, U13.
"""

from __future__ import annotations

from datetime import time as Time
from decimal import Decimal

from core.config import ConfigService
from core.risk.models import GiveBackLevel


# ── U13: Mental stop emulation (spec §3 P1 / §11 U13) ───────────────────────

def is_mental_stop_breached(current_price: Decimal, stop_price: Decimal) -> bool:
    """Return True when current_price has hit or breached the mental stop.

    Caller MUST fire a marketable-limit sell immediately.
    NEVER route a native STOP or STOP-LIMIT order type (U13).
    spec §3 P1 / §11 U13.
    """
    return current_price <= stop_price


# ── C3: Give-back stop (spec §5) ─────────────────────────────────────────────

def evaluate_give_back(
    realized_pnl: Decimal,
    peak_pnl: Decimal,
    cfg: ConfigService,
) -> GiveBackLevel:
    """Classify how much of today's peak gain has been given back.

    NONE → no issue.
    WARN → > GIVE_BACK_WARN of peak; log and reduce sizing.
    HALT → > GIVE_BACK_HARD of peak; shut down (U4).
    spec §5 C3.
    """
    if peak_pnl <= Decimal("0"):
        return GiveBackLevel.NONE

    give_back_fraction = (peak_pnl - realized_pnl) / peak_pnl
    if give_back_fraction >= cfg.get_decimal("GIVE_BACK_HARD"):
        return GiveBackLevel.HALT
    if give_back_fraction >= cfg.get_decimal("GIVE_BACK_WARN"):
        return GiveBackLevel.WARN
    return GiveBackLevel.NONE


# ── U4: Max daily loss (spec §5 C2) ──────────────────────────────────────────

def is_daily_loss_limit(
    realized_pnl: Decimal,
    account_equity: Decimal,
    avg_win_day_pnl: Decimal,
    cfg: ConfigService,
) -> bool:
    """Return True if the daily loss limit has been hit → halt the session.

    MAX_DAILY_LOSS = min(account_equity × MAX_DAILY_LOSS_PCT,
                         avg_win_day_pnl,
                         BROKER_HARD_LOCKOUT)
    spec §5 C2 / U4.
    """
    max_loss_pct = account_equity * cfg.get_decimal("MAX_DAILY_LOSS_PCT")
    broker_lockout = cfg.get_decimal("BROKER_HARD_LOCKOUT")
    effective = min(max_loss_pct, avg_win_day_pnl, broker_lockout)
    return realized_pnl <= -effective


# ── U3: EOD flatten (spec §11 U3) ────────────────────────────────────────────

def should_flatten_eod(now_et_time: Time, cfg: ConfigService) -> bool:
    """Return True when it is time to flatten all positions before market close.

    Fires at or after EOD_FLATTEN_TIME (default 15:55 ET) so the execution
    layer has time to work orders before 16:00.
    spec §11 U3.
    """
    flatten_time = cfg.get_time("EOD_FLATTEN_TIME")
    return now_et_time >= flatten_time


# ── §7: Time-of-day guard ─────────────────────────────────────────────────────

def is_past_hard_stop_time(now_et_time: Time, cfg: ConfigService) -> bool:
    """Return True when past HARD_STOP_TIME — no new entries allowed.

    spec §7.
    """
    return now_et_time > cfg.get_time("HARD_STOP_TIME")


__all__ = [
    "evaluate_give_back",
    "is_daily_loss_limit",
    "is_mental_stop_breached",
    "is_past_hard_stop_time",
    "should_flatten_eod",
]
