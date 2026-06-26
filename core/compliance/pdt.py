"""PDT Guard — spec §13.11.

IMPORTANT REGULATORY UPDATE (2026-06-04): FINRA eliminated the Pattern Day
Trader (PDT) rule on June 4, 2026. The old $25,000 minimum equity requirement
and ≤3-day-trades-in-5-rolling-days restriction are NO LONGER ACTIVE for
margin accounts. RossBot enforces MAX_TRADES_PER_DAY from config as the
conservative guard instead (configurable; default 1 for cash, higher for margin).

This module:
- Tracks intraday round-trip count (one round-trip = one open + matching close).
- Enforces MAX_TRADES_PER_DAY from ConfigService.
- Handles cash-account T+1 unsettled-fund restriction (one-trade-per-day default).

All date comparisons use calendar date (ET), not datetime.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from adapters.base import AccountType
from core.config import ConfigService


@dataclass
class PDTGuard:
    """Tracks intraday round-trip count and enforces MAX_TRADES_PER_DAY.

    One instance per trading session; call reset_session() at each day open.
    Thread-safety: NOT thread-safe — serialise calls from the session loop.
    spec §13.11.
    """

    round_trips_today: int = field(default=0)
    open_symbols: dict[str, int] = field(default_factory=dict)  # symbol → open qty

    def reset_session(self) -> None:
        """Clear state at each market open (U3 session boundary)."""
        self.round_trips_today = 0
        self.open_symbols = {}

    def record_open(self, symbol: str, qty: int) -> None:
        """Track position open for round-trip counting."""
        self.open_symbols[symbol] = self.open_symbols.get(symbol, 0) + qty

    def record_close(self, symbol: str, qty: int) -> None:
        """Record position close; increment round_trips_today when fully flat."""
        remaining = self.open_symbols.get(symbol, 0) - qty
        if remaining <= 0:
            self.open_symbols.pop(symbol, None)
            self.round_trips_today += 1
        else:
            self.open_symbols[symbol] = remaining

    def can_trade(
        self,
        cfg: ConfigService,
        account_type: AccountType,
    ) -> tuple[bool, str]:
        """Return (allowed, reason_if_blocked).

        Checks MAX_TRADES_PER_DAY from config; cash accounts default to 1.
        spec §13.11.
        """
        max_trades = cfg.get_int("MAX_TRADES_PER_DAY")

        if account_type == AccountType.CASH and max_trades > 1:
            # Cash account: T+1 unsettled-fund restriction — use 1 unless config raised it explicitly.
            max_trades = 1

        if self.round_trips_today >= max_trades:
            return (
                False,
                (
                    f"MAX_TRADES_PER_DAY reached: {self.round_trips_today}/{max_trades} "
                    f"round-trips today (account_type={account_type.value}). spec §13.11."
                ),
            )
        return True, ""


__all__ = ["PDTGuard"]
