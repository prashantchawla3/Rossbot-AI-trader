"""Wash-sale tracker (IRC §1091) — advisory only, NOT a hard trade veto. spec §13.11.

A wash sale occurs when a trader sells a security at a loss and repurchases
the same (or substantially identical) security within 30 days before or after
the sale. The disallowed loss is added to the cost basis of the replacement shares.

This tracker flags intraday re-entries where a prior loss was recorded within
the 30-day lookback window. The risk layer LOGS the flag but does NOT block the
trade — wash-sale is a tax consequence, not a trading rule. The flag is included
in the audit trail so the client's tax accountant can review.

Per-instance state is maintained in memory for the current session. Persistence
across sessions should be wired through the ledger/DB (caller's responsibility).

Note: Wash-sale applies even for intraday re-entries on the same day (e.g., sell
at a loss at 10:15, buy again at 11:30 = wash sale). Source: IRS Publication 550.
spec §13.11.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal


_WASH_WINDOW_DAYS = 30


@dataclass
class _LossRecord:
    symbol: str
    trade_date: date
    pnl: Decimal  # negative


@dataclass
class WashSaleTracker:
    """Tracks recent losses for potential wash-sale flagging. spec §13.11.

    Call record_loss() on every losing trade close.
    Call check_wash_sale_risk() before re-entering the same symbol.
    """

    _history: list[_LossRecord] = field(default_factory=list)

    def record_loss(self, symbol: str, trade_date: date, pnl: Decimal) -> None:
        """Record a loss trade. Only stores negative PnL trades. spec §13.11."""
        if pnl >= Decimal("0"):
            return  # winning trade — no wash-sale concern
        self._history.append(_LossRecord(symbol=symbol.upper(), trade_date=trade_date, pnl=pnl))

    def check_wash_sale_risk(self, symbol: str, as_of: date) -> tuple[bool, str]:
        """Return (at_risk, description) for re-entering ``symbol`` on ``as_of`` date.

        ``at_risk=True`` when there is a loss on ``symbol`` within the 30-day window.
        The caller should LOG this; it is NOT a hard block. spec §13.11.
        """
        sym = symbol.upper()
        for rec in self._history:
            if rec.symbol != sym:
                continue
            days_ago = (as_of - rec.trade_date).days
            if 0 <= days_ago <= _WASH_WINDOW_DAYS:
                return (
                    True,
                    (
                        f"WASH_SALE_RISK: re-entering {sym} within {days_ago}d of a "
                        f"${abs(rec.pnl):.2f} loss on {rec.trade_date}. "
                        "Loss may be disallowed (IRC §1091). Flag for tax review."
                    ),
                )
        return False, ""

    def purge_before(self, cutoff: date) -> None:
        """Remove records older than 30 days from ``cutoff`` (memory hygiene)."""
        self._history = [
            r for r in self._history
            if (cutoff - r.trade_date).days <= _WASH_WINDOW_DAYS
        ]


__all__ = ["WashSaleTracker"]
