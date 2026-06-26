"""RiskManager — the mandatory gate between Strategy and Execution.

CLAUDE.md §3: "Risk Manager sits between Strategy and Execution as a mandatory
gate. No order reaches the broker without passing it. Strategy proposes; Risk
disposes; Execution obeys."

Responsibilities:
  - Pre-trade veto gate (all U1–U15 guardrails that apply before sizing)
  - Sizing engine (risk_formula / flat_block + cushion + conviction + DOW + state)
  - Live monitors: mental stop (U13), give-back (C3), daily loss (U4), EOD (U3)
  - Daily state management (reset_session / record_open / record_close)
  - kill-switch (halt_session)
  - Audit: every decision returned as TradeApproval for risk_events logging

spec §5 (risk), §6 (sizing), §7 (time), §8 (market state), §11 (U1–U15).
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from core.config import ConfigService
from core.risk.models import GiveBackLevel, RiskState, TradeApproval, VetoReason
from core.risk.monitors import (
    evaluate_give_back,
    is_daily_loss_limit,
    is_mental_stop_breached,
    should_flatten_eod,
)
from core.risk.pre_trade import evaluate_pre_trade
from core.risk.sizing import compute_size
from core.strategy.models import EntrySignal, PositionSnapshot
from core.timeutils import et_time, to_et


class RiskManager:
    """Stateful daily risk manager.

    One instance per trading session; reset_session() must be called at market
    open to clear yesterday's state (U3 no-overnight).

    Thread-safety: NOT thread-safe — caller must serialise bar events.
    """

    def __init__(self, config: ConfigService) -> None:
        self._cfg = config
        self._state = RiskState()

    # ── Session lifecycle ─────────────────────────────────────────────────────

    def reset_session(self) -> None:
        """Reset all daily state at market open.

        Clears PnL, strikes, position tracking, and halt flag.
        spec U3 (no overnight) / session boundary.
        """
        self._state = RiskState()

    # ── Position lifecycle (called by Execution layer after fills) ────────────

    def record_open(self, symbol: str, entry_price: Decimal) -> None:
        """Record that a position has been opened.

        Increments trades_today (PDT guard) and tracks entry_price (U2 check).
        """
        self._state.open_positions[symbol] = entry_price
        self._state.trades_today += 1

    def record_close(self, symbol: str, pnl: Decimal) -> None:
        """Record that a position has been fully closed.

        Updates realized_pnl, peak_pnl, consecutive_losses.
        Three-strikes check fires inside here (U5); sets halted=True if triggered.
        Positive pnl = win; negative = loss.
        """
        self._state.open_positions.pop(symbol, None)

        # Update realized PnL (Decimal, never float).
        self._state.realized_pnl += pnl

        # High-watermark of the day.
        if self._state.realized_pnl > self._state.peak_pnl:
            self._state.peak_pnl = self._state.realized_pnl

        # Streak tracking (U5 three-strikes).
        if pnl < Decimal("0"):
            self._state.consecutive_losses += 1
        else:
            self._state.consecutive_losses = 0  # any win resets the streak

        # Three-strikes halt (U5). Halt is sticky for the rest of the session.
        three_strikes = self._cfg.get_int("THREE_STRIKES")
        if not self._state.halted and self._state.consecutive_losses >= three_strikes:
            self._state.halted = True
            self._state.halt_reason = "three_strikes"  # spec U5

    # ── Main pre-trade gate ───────────────────────────────────────────────────

    def evaluate(
        self,
        signal: EntrySignal,
        now_et: datetime,
        account_equity: Decimal,
        liquidity_cap_shares: int | None = None,
        catalyst_skip: bool = False,
    ) -> TradeApproval:
        """The mandatory veto gate.

        Returns TradeApproval(approved=True, shares=N) if all rules pass,
        or TradeApproval(approved=False, vetoes=(...)) if any rule fires.

        EVERY proposed trade MUST pass through here before execution.
        spec §5/§6/§11.
        """
        now_time = et_time(now_et)

        # ── Pre-trade veto checks (pure) ──────────────────────────────────────
        vetoes = evaluate_pre_trade(
            signal=signal,
            state=self._state,
            cfg=self._cfg,
            now_et_time=now_time,
            account_equity=account_equity,
            catalyst_skip=catalyst_skip,
        )

        if vetoes:
            return TradeApproval(approved=False, vetoes=tuple(vetoes))

        # ── Sizing engine (pure) ──────────────────────────────────────────────
        day_of_week = to_et(now_et).weekday()  # 0=Mon, 4=Fri
        shares = compute_size(
            signal=signal,
            state=self._state,
            cfg=self._cfg,
            market_state=signal.market_state,
            day_of_week=day_of_week,
            liquidity_cap_shares=liquidity_cap_shares,
        )

        if shares == 0:
            return TradeApproval(approved=False, vetoes=(VetoReason.SIZING_ZERO,))

        return TradeApproval(approved=True, shares=shares)

    # ── Live monitors ─────────────────────────────────────────────────────────

    def check_mental_stop(
        self,
        current_price: Decimal,
        position: PositionSnapshot,
    ) -> bool:
        """U13: True if the mental stop has been breached.

        Caller MUST fire a marketable-limit sell immediately.
        NEVER route a native STOP order. spec §3 P1 / U13.
        """
        return is_mental_stop_breached(current_price, position.current_stop)

    def check_give_back(self) -> GiveBackLevel:
        """C3: current give-back severity.

        NONE=ok; WARN=reduce size; HALT=shutdown (U4).
        spec §5 C3.
        """
        return evaluate_give_back(
            realized_pnl=self._state.realized_pnl,
            peak_pnl=self._state.peak_pnl,
            cfg=self._cfg,
        )

    def check_daily_loss(self, account_equity: Decimal) -> bool:
        """U4: True if the daily loss limit has been hit → halt and stop trading.

        spec §5 C2 / U4.
        """
        return is_daily_loss_limit(
            realized_pnl=self._state.realized_pnl,
            account_equity=account_equity,
            avg_win_day_pnl=self._cfg.get_decimal("AVG_WIN_DAY_PNL"),
            cfg=self._cfg,
        )

    def should_flatten_eod(self, now_et: datetime) -> bool:
        """U3: True when positions should be flattened before close.

        spec §11 U3 (no overnight).
        """
        return should_flatten_eod(et_time(now_et), self._cfg)

    # ── Kill-switch ───────────────────────────────────────────────────────────

    def halt_session(self, reason: str = "manual") -> None:
        """Externally halt the session (e.g., daily loss hit or kill-switch).

        After this call, evaluate() returns HALTED for all subsequent trades.
        spec U4 / U5.
        """
        self._state.halted = True
        self._state.halt_reason = reason

    # ── State access ──────────────────────────────────────────────────────────

    @property
    def state(self) -> RiskState:
        """Current daily state snapshot (read-only; for audit / logging)."""
        return self._state


__all__ = ["RiskManager"]
